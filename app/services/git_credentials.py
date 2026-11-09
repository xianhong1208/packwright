"""Manage per-host Git credentials and resolve the right token for a clone URL.

Replaces the single GITLAB_TOKEN env var. Tokens are stored encrypted and chosen
by the URL's host, so GitLab and GitHub (and self-hosted instances) can each have
their own token. `settings.gitlab_token` remains a fallback for GitLab-style
hosts when no stored credential matches.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.git_credential import GitCredential
from app.schemas.git_credential import GitCredentialCreate, GitCredentialUpdate
from app.services.crypto import encrypt_secret, decrypt_secret

# Default host for each provider, used when the caller does not give one.
_PROVIDER_DEFAULT_HOST = {"gitlab": "gitlab.com", "github": "github.com"}


class InvalidHostError(ValueError):
    """The host given for a credential can never match a Git URL."""


# One DNS label; "_" is tolerated because internal names use it and git accepts it.
_LABEL = r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?"
_HOSTNAME = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")

# Shorter tokens get no hint: the last four characters of a short token are
# most of it (a four-character token was shown whole).
_HINT_MIN_TOKEN_LENGTH = 16


def normalize_host(raw: str) -> str:
    """The host name a credential is stored under, or InvalidHostError.

    A credential is found by the clone URL's host name (no scheme, port or
    path), so anything else stored here never matched: "https://x.com/" was
    accepted and the page then said builds clone from https://https://x.com//.
    """
    host = (raw or "").strip().lower().rstrip(".")
    if "://" in host or "/" in host:
        raise InvalidHostError(
            "Enter the host name only, without https:// or a path (for example gitlab.example.com)"
        )
    try:
        return str(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        pass
    if host == "localhost" or host.endswith(".localhost"):
        raise InvalidHostError("localhost cannot be a Git host: Git URLs pointing at it are refused")
    if ":" in host:
        raise InvalidHostError("Enter the host name without a port: a credential applies to every port of its host")
    if len(host) > 253 or not _HOSTNAME.fullmatch(host):
        raise InvalidHostError(f"'{(raw or '').strip()}' is not a valid host name")
    return host


def token_hint(token: str) -> str | None:
    """The last four characters, shown to recognise a token; none for a short one."""
    return token[-4:] if len(token) >= _HINT_MIN_TOKEN_LENGTH else None


def infer_provider(host: str) -> str:
    """Guess the provider from a host name (for injection format + fallbacks)."""
    h = host.lower()
    if "github" in h:
        return "github"
    if "gitlab" in h:
        return "gitlab"
    return "generic"


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


async def list_credentials(db: AsyncSession) -> list[GitCredential]:
    result = await db.execute(select(GitCredential).order_by(GitCredential.host))
    return list(result.scalars().all())


async def get_by_host(db: AsyncSession, host: str) -> GitCredential | None:
    result = await db.execute(select(GitCredential).where(GitCredential.host == host.lower()))
    return result.scalar_one_or_none()


async def create_credential(
    db: AsyncSession, data: GitCredentialCreate, created_by: int | None
) -> GitCredential:
    raw = (data.host or "").strip() or _PROVIDER_DEFAULT_HOST.get(data.provider) or ""
    if not raw:
        raise InvalidHostError("host is required for a generic provider")
    host = normalize_host(raw)
    if await get_by_host(db, host):
        raise ValueError(f"a credential for host '{host}' already exists")
    cred = GitCredential(
        provider=data.provider,
        host=host,
        label=data.label,
        token_encrypted=encrypt_secret(data.token),
        token_hint=token_hint(data.token),
        created_by=created_by,
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return cred


async def update_credential(
    db: AsyncSession, cred: GitCredential, data: GitCredentialUpdate
) -> GitCredential:
    if data.label is not None:
        cred.label = data.label
    if data.token is not None:
        cred.token_encrypted = encrypt_secret(data.token)
        cred.token_hint = token_hint(data.token)
    await db.commit()
    await db.refresh(cred)
    return cred


async def delete_credential(db: AsyncSession, cred: GitCredential) -> None:
    await db.delete(cred)
    await db.commit()


async def resolve_for_url(db: AsyncSession, url: str) -> tuple[str | None, str]:
    """Return (token, provider) for cloning `url`.

    Looks up a stored credential by the URL's host. Falls back to
    settings.gitlab_token only for exactly settings.gitlab_token_host. The
    token may be None (public repo / no credential); provider still guides how a
    token, if any, is injected into the URL.
    """
    host = _host_of(url)
    provider = infer_provider(host)
    cred = await get_by_host(db, host) if host else None
    if cred is not None:
        cred.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        return decrypt_secret(cred.token_encrypted), cred.provider
    # The env fallback is one GitLab token for one GitLab server. Offer it to that
    # host only: matching any host *named* like GitLab handed it to
    # gitlab.attacker.example on its first 401, via /api/git/refs with no build
    # and no history row.
    settings = get_settings()
    if settings.gitlab_token and host == (settings.gitlab_token_host or "").strip().lower():
        return settings.gitlab_token, "gitlab"
    return None, provider

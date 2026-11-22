"""Personal API tokens: format, storage, and what a token may reach.

Format: ``pwt_`` + 43 base62 characters (32 random bytes) + a 6-character base62
CRC32 of everything before it, like GitHub's tokens. The checksum lets a secret
scanner, or this server, tell a real token from a typo or a random string
without a database lookup; it is not a security property (anyone can compute
it). Base62 keeps the whole token one "word", so a double-click selects all of
it and a scanner's regex is simple: ``pwt_[0-9A-Za-z]{49}``.

Only the SHA-256 is stored. A token is looked up by that hash, which is a
constant-time comparison in effect: the secret itself is never compared
character by character (the found row is still checked with compare_digest).

What a token may do is the intersection of two things, both checked on every
request:

* the token's scopes, through :data:`TOKEN_ROUTES`: the one list of endpoints a
  token can call at all, each with the scope it needs. Anything not listed,
  which includes every user, role, credential, settings and token-management
  endpoint, answers 403 to a token whatever its scopes. There is no admin scope;
* the owner's role, as it is now: the route's own permission checks run
  unchanged against the owner's current permissions, and an owner who is
  deactivated (or deleted) makes every token of theirs fail with 401.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_token import ApiToken
from app.models.user import User

TOKEN_PREFIX = "pwt_"
_BODY_LEN = 43  # 32 random bytes in base62
_CHECKSUM_LEN = 6  # CRC32 in base62
TOKEN_LEN = len(TOKEN_PREFIX) + _BODY_LEN + _CHECKSUM_LEN
_TOKEN_RE = re.compile(rf"^{TOKEN_PREFIX}[0-9A-Za-z]{{{_BODY_LEN + _CHECKSUM_LEN}}}$")
# Shown in the console and stored: "pwt_" plus 8 characters of the random part.
DISPLAY_PREFIX_LEN = len(TOKEN_PREFIX) + 8

_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

SCOPES: dict[str, str] = {
    "builds:read": "List and follow builds, read their logs and download their results",
    "builds:write": "Start builds and cancel them",
    "projects:read": "List projects and read their settings",
}

EXPIRY_PRESETS_DAYS = (7, 30, 90, 365)
MAX_EXPIRY_DAYS = 365

# last_used_at is written at most this often per token: a CI job polling a
# build every few seconds must not turn every read into a database write.
LAST_USED_RESOLUTION = timedelta(minutes=1)

# (method, route path template) → the scope a token needs for it. "WS" marks a
# WebSocket route. Default deny: a route missing here is refused to tokens.
TOKEN_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/api/tasks"): "builds:read",
    ("GET", "/api/tasks/{task_id}"): "builds:read",
    ("GET", "/api/tasks/{task_id}/logs"): "builds:read",
    ("GET", "/api/history"): "builds:read",
    ("GET", "/api/history/versions"): "builds:read",
    ("GET", "/api/history/export"): "builds:read",
    ("GET", "/api/history/{task_id}"): "builds:read",
    ("GET", "/api/history/{task_id}/download"): "builds:read",
    ("WS", "/ws/tasks"): "builds:read",
    ("WS", "/ws/tasks/{task_id}"): "builds:read",
    ("POST", "/api/tasks"): "builds:write",
    ("DELETE", "/api/tasks/{task_id}"): "builds:write",
    ("POST", "/api/projects/{project_id}/builds"): "builds:write",
    ("GET", "/api/projects"): "projects:read",
    ("GET", "/api/projects/{project_id}"): "projects:read",
}


def scope_for_route(method: str, path: str) -> str | None:
    """The scope a token needs for this route, or None if tokens may not use it."""
    method = method.upper()
    # HEAD is served by the GET route.
    if method == "HEAD":
        method = "GET"
    return TOKEN_ROUTES.get((method, path))


def _base62(value: int, width: int) -> str:
    out = []
    while value:
        value, rem = divmod(value, 62)
        out.append(_BASE62[rem])
    return "".join(reversed(out)).rjust(width, "0")


def _checksum(head: str) -> str:
    return _base62(zlib.crc32(head.encode("ascii")), _CHECKSUM_LEN)


def generate_token() -> str:
    """A new token. Shown to its owner once, never stored."""
    body = _base62(int.from_bytes(secrets.token_bytes(32), "big"), _BODY_LEN)
    head = TOKEN_PREFIX + body
    return head + _checksum(head)


def looks_like_token(raw: str) -> bool:
    """True for anything a caller meant as an API token rather than a session JWT."""
    return raw.startswith(TOKEN_PREFIX)


def checksum_ok(raw: str) -> bool:
    """Well formed and its checksum matches: worth a database lookup."""
    if not _TOKEN_RE.match(raw):
        return False
    head, check = raw[:-_CHECKSUM_LEN], raw[-_CHECKSUM_LEN:]
    return hmac.compare_digest(_checksum(head), check)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def display_prefix(raw: str) -> str:
    return raw[:DISPLAY_PREFIX_LEN]


def normalize_scopes(scopes: list[str]) -> list[str]:
    """Known scopes only, each once, in a stable order. Raises ValueError otherwise."""
    unknown = sorted(set(scopes) - SCOPES.keys())
    if unknown:
        raise ValueError(f"Unknown scope: {', '.join(unknown)}")
    if not scopes:
        raise ValueError("Choose at least one scope")
    return [s for s in SCOPES if s in scopes]


@dataclass
class TokenRejected(Exception):
    """Why a token was refused. The reason goes to the audit log, never to the caller."""

    reason: str
    token: ApiToken | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_token(
    db: AsyncSession,
    *,
    user_id: int,
    name: str,
    scopes: list[str],
    expires_in_days: int,
) -> tuple[ApiToken, str]:
    """Store a new token and return it with its plaintext (the only time it exists)."""
    if not 1 <= expires_in_days <= MAX_EXPIRY_DAYS:
        raise ValueError(f"A token expires within 1 to {MAX_EXPIRY_DAYS} days")
    raw = generate_token()
    row = ApiToken(
        user_id=user_id,
        name=name,
        token_hash=hash_token(raw),
        token_prefix=display_prefix(raw),
        scopes=" ".join(normalize_scopes(scopes)),
        expires_at=_now() + timedelta(days=expires_in_days),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, raw


async def authenticate(
    db: AsyncSession, raw: str, *, now: datetime | None = None
) -> tuple[User, ApiToken]:
    """The owner and the token row for a presented token, or TokenRejected."""
    now = now or _now()
    if not checksum_ok(raw):
        raise TokenRejected("malformed")

    digest = hash_token(raw)
    token = (
        await db.execute(select(ApiToken).where(ApiToken.token_hash == digest))
    ).scalar_one_or_none()
    if token is None or not hmac.compare_digest(token.token_hash, digest):
        raise TokenRejected("unknown")
    if token.revoked_at is not None:
        raise TokenRejected("revoked", token)
    if token.expired(now):
        raise TokenRejected("expired", token)

    user = await db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise TokenRejected("owner_inactive", token)

    last = token.last_used_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is None or now - last >= LAST_USED_RESOLUTION:
        token.last_used_at = now
        await db.commit()
    return user, token

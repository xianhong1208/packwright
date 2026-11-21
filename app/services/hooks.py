"""Incoming webhooks: who sent a delivery, and what it asks to build.

Everything here is pure (no database), so each guard can be tested on its own:

* ``verify`` — the delivery was made with the hook's secret. GitHub and Gitea sign
  the raw body with HMAC-SHA256 (``X-Hub-Signature-256: sha256=<hex>``; Gitea also
  ``X-Gitea-Signature: <hex>``). GitLab sends its secret token in clear
  (``X-Gitlab-Token``) or, since 19.0, signs ``{webhook-id}.{webhook-timestamp}.{body}``
  with a signing token GitLab generates (Standard Webhooks, ``webhook-signature:
  v1,<base64>``). The generic URL takes the hook's token in a header or ``?token=``.
  A missing or empty signature is refused like a wrong one: Gitea sends the
  headers empty when no secret is set on its side.
* ``parse_forge`` — which branch or tag was pushed, at which commit, or why the
  delivery builds nothing (a ping, another event, a deletion).
* ``ref_allowed`` / ``skip_requested`` / ``same_repository`` — the filters.

Comparisons of secrets are constant-time (``hmac.compare_digest`` on bytes).
Secrets and bodies are never logged.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from urllib.parse import urlsplit

from app.schemas.task import COMMIT_SHA_RE

PROVIDERS = ("github", "gitlab", "gitea", "generic")

# A GitLab signed delivery older (or newer) than this is a replay, not a retry:
# GitLab stamps each attempt afresh.
SIGNATURE_TOLERANCE_SECONDS = 300

ZERO_SHA = re.compile(r"0+")
_SKIP_CI = re.compile(r"\[(?:skip ci|ci skip)\]", re.IGNORECASE)

MAX_PATTERNS = 20
MAX_PATTERN_LENGTH = 200


def new_public_id() -> str:
    """The random part of a hook's URL (128 bits)."""
    return secrets.token_urlsafe(16)


def new_secret() -> str:
    """A hook's secret (256 bits), shown once."""
    return secrets.token_urlsafe(32)


# ---------- verification ----------


class Rejected(Exception):
    """The delivery was not made with this hook's secret. ``reason`` is for the
    deliveries list only; the sender always gets the same 401."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _same(given: str, expected: str) -> bool:
    # Bytes, so a non-ASCII header value is a mismatch rather than a TypeError.
    return hmac.compare_digest(given.encode("utf-8", "surrogateescape"), expected.encode())


def _hmac_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _hub_signature(headers: dict[str, str], secret: str, body: bytes) -> None:
    given = headers.get("x-hub-signature-256", "").strip()
    if not given:
        raise Rejected("no X-Hub-Signature-256 header")
    algo, _, digest = given.partition("=")
    if algo != "sha256" or not digest:
        raise Rejected("X-Hub-Signature-256 is not of the form sha256=<hex>")
    if not _same(digest.lower(), _hmac_hex(secret, body)):
        raise Rejected("signature does not match")


def _gitea_signature(headers: dict[str, str], secret: str, body: bytes) -> None:
    given = headers.get("x-gitea-signature", "").strip()
    if not given:
        # Gitea sends both; a proxy or a Gitea fork may pass on only the GitHub-style one.
        _hub_signature(headers, secret, body)
        return
    if not _same(given.lower(), _hmac_hex(secret, body)):
        raise Rejected("signature does not match")


def _gitlab_signed(headers: dict[str, str], signing_key: str, body: bytes, now: float) -> None:
    msg_id = headers.get("webhook-id", "").strip()
    stamp = headers.get("webhook-timestamp", "").strip()
    given = headers.get("webhook-signature", "").strip()
    if not given:
        raise Rejected("no webhook-signature header (this hook has a GitLab signing token)")
    if not msg_id or not stamp:
        raise Rejected("webhook-id or webhook-timestamp missing")
    try:
        sent_at = int(stamp)
    except ValueError:
        raise Rejected("webhook-timestamp is not a number") from None
    if abs(now - sent_at) > SIGNATURE_TOLERANCE_SECONDS:
        raise Rejected("webhook-timestamp is more than 5 minutes off")
    try:
        key = base64.b64decode(signing_key.removeprefix("whsec_"), validate=True)
    except (binascii.Error, ValueError):
        raise Rejected("the stored signing token is not valid base64") from None
    expected = base64.b64encode(
        hmac.new(key, f"{msg_id}.{stamp}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    # Several signatures may be sent (space-separated) while a token is rotated.
    for candidate in given.split():
        version, _, sig = candidate.partition(",")
        if version == "v1" and sig and _same(sig, expected):
            return
    raise Rejected("signature does not match")


def _generic_token(headers: dict[str, str], query_token: str | None) -> str:
    auth = headers.get("authorization", "").strip()
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return headers.get("x-packwright-token", "").strip() or (query_token or "").strip()


def verify(
    provider: str,
    headers: dict[str, str],
    body: bytes,
    secret: str,
    *,
    signing_key: str | None = None,
    now: float,
    query_token: str | None = None,
) -> None:
    """Raise Rejected unless the delivery was made with this hook's secret.

    ``headers`` has lower-case names. For GitLab, a stored signing token makes
    the signature mandatory: the clear-text token alone would let anyone who saw
    it once (a proxy log) keep sending.
    """
    if provider == "github":
        _hub_signature(headers, secret, body)
    elif provider == "gitea":
        _gitea_signature(headers, secret, body)
    elif provider == "gitlab":
        if signing_key:
            _gitlab_signed(headers, signing_key, body, now)
            return
        given = headers.get("x-gitlab-token", "").strip()
        if not given:
            raise Rejected("no X-Gitlab-Token header")
        if not _same(given, secret):
            raise Rejected("token does not match")
    elif provider == "generic":
        given = _generic_token(headers, query_token)
        if not given:
            raise Rejected("no token")
        if not _same(given, secret):
            raise Rejected("token does not match")
    else:
        raise Rejected(f"unknown provider {provider}")


def valid_signing_key(raw: str) -> str:
    """GitLab's signing token as pasted, checked; ValueError if it cannot be one."""
    key = raw.strip()
    try:
        decoded = base64.b64decode(key.removeprefix("whsec_"), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("A GitLab signing token is whsec_ followed by base64; copy it again from GitLab") from None
    if len(decoded) < 16:
        raise ValueError("That signing token is too short; copy it again from GitLab")
    return key


# ---------- what was pushed ----------


@dataclass
class Push:
    """A branch or tag push that may build."""

    kind: str  # "branch" | "tag"
    name: str
    sha: str
    message: str = ""
    repo_urls: list[str] = field(default_factory=list)


@dataclass
class Parsed:
    """What a delivery says, for the deliveries list, and either a push or why not."""

    event: str
    ref: str | None = None
    sha: str | None = None
    push: Push | None = None
    ignored: str | None = None


def split_ref(ref: str) -> tuple[str, str] | None:
    """``refs/heads/x`` → ("branch", "x"), ``refs/tags/v1`` → ("tag", "v1")."""
    for prefix, kind in (("refs/heads/", "branch"), ("refs/tags/", "tag")):
        if ref.startswith(prefix) and len(ref) > len(prefix):
            return kind, ref[len(prefix):]
    return None


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _urls(*objs: object, keys: tuple[str, ...]) -> list[str]:
    out = []
    for obj in objs:
        if isinstance(obj, dict):
            out.extend(v for k in keys if (v := _str(obj.get(k))))
    return out


def _push_from(event: str, ref: str, after: str, deleted: bool, message: str, urls: list[str]) -> Parsed:
    parsed = Parsed(event=event, ref=ref or None, sha=after or None)
    kind_name = split_ref(ref)
    if kind_name is None:
        parsed.ignored = f"ref {ref or '(none)'} is neither a branch nor a tag"
        return parsed
    kind, name = kind_name
    if deleted or (after and ZERO_SHA.fullmatch(after)):
        parsed.ignored = f"{kind} {name} was deleted"
        return parsed
    if not COMMIT_SHA_RE.fullmatch(after):
        parsed.ignored = "the payload names no commit"
        return parsed
    parsed.push = Push(kind=kind, name=name, sha=after, message=message, repo_urls=urls)
    return parsed


def parse_forge(provider: str, headers: dict[str, str], payload: dict) -> Parsed:
    """Read a GitHub, Gitea or GitLab delivery (already verified)."""
    if provider in ("github", "gitea"):
        if provider == "gitea":
            event = headers.get("x-gitea-event") or headers.get("x-github-event", "")
        else:
            event = headers.get("x-github-event", "")
        event = event.strip()[:64]
        if event == "ping":
            return Parsed(event=event, ignored="ping: the hook is connected")
        if event != "push":
            return Parsed(event=event or "(none)", ignored=f"the {event or 'unnamed'} event does not start builds")
        head = payload.get("head_commit")
        if not isinstance(head, dict):
            commits = payload.get("commits")
            head = commits[-1] if isinstance(commits, list) and commits and isinstance(commits[-1], dict) else {}
        repo = payload.get("repository")
        urls = _urls(repo, keys=("clone_url", "ssh_url", "git_url", "html_url", "url", "svn_url"))
        return _push_from(
            event, _str(payload.get("ref")), _str(payload.get("after")).lower(),
            payload.get("deleted") is True, _str(head.get("message")), urls,
        )
    if provider == "gitlab":
        event = headers.get("x-gitlab-event", "").strip()[:64]
        if event not in ("Push Hook", "Tag Push Hook"):
            return Parsed(event=event or "(none)", ignored=f"the {event or 'unnamed'} event does not start builds")
        after = _str(payload.get("after")).lower()
        checkout = _str(payload.get("checkout_sha")).lower()
        sha = checkout or after
        message = ""
        commits = payload.get("commits")
        if isinstance(commits, list):
            for c in commits:
                if isinstance(c, dict) and _str(c.get("id")).lower() == sha:
                    message = _str(c.get("message"))
        urls = _urls(
            payload.get("project"), payload.get("repository"),
            keys=("git_http_url", "git_ssh_url", "web_url", "http_url", "ssh_url", "url", "homepage"),
        )
        deleted = bool(after) and ZERO_SHA.fullmatch(after) is not None
        return _push_from(event, _str(payload.get("ref")), "" if deleted else sha, deleted, message, urls)
    raise ValueError(f"not a forge provider: {provider}")


def parse_generic(payload: dict, default_ref: str, default_type: str) -> Parsed:
    """Read a generic delivery: ``{"ref": ..., "ref_type": ..., "commit": ...}``, all optional.

    Without ``ref`` the project's own branch or tag builds. ``ref`` may be a full
    ``refs/heads/…`` / ``refs/tags/…`` or a bare name (a branch unless
    ``ref_type`` is "tag"). Without ``commit`` the build takes where the ref
    points when it starts.
    """
    raw_ref = _str(payload.get("ref")).strip()
    commit = _str(payload.get("commit")).strip().lower()
    if raw_ref:
        kind_name = split_ref(raw_ref) if raw_ref.startswith("refs/") else None
        if kind_name is None and raw_ref.startswith("refs/"):
            return Parsed(event="generic", ref=raw_ref, ignored=f"ref {raw_ref} is neither a branch nor a tag")
        if kind_name is None:
            ref_type = _str(payload.get("ref_type")) or "branch"
            if ref_type not in ("branch", "tag"):
                return Parsed(event="generic", ref=raw_ref, ignored="ref_type must be branch or tag")
            kind_name = (ref_type, raw_ref)
    else:
        kind_name = (default_type if default_type in ("branch", "tag") else "branch", default_ref)
    kind, name = kind_name
    full_ref = f"refs/{'heads' if kind == 'branch' else 'tags'}/{name}"
    if commit and not COMMIT_SHA_RE.fullmatch(commit):
        return Parsed(event="generic", ref=full_ref, ignored="commit must be a full commit id (40 or 64 hex characters)")
    return Parsed(event="generic", ref=full_ref, sha=commit or None, push=Push(kind=kind, name=name, sha=commit))


# ---------- filters ----------


def normalise_patterns(raw: str) -> str:
    """Glob patterns as stored: one per line, trimmed, de-duplicated. ValueError if unusable."""
    seen: list[str] = []
    for part in re.split(r"[\s,]+", raw or ""):
        if not part:
            continue
        if len(part) > MAX_PATTERN_LENGTH:
            raise ValueError(f"A pattern may be at most {MAX_PATTERN_LENGTH} characters")
        if part not in seen:
            seen.append(part)
    if len(seen) > MAX_PATTERNS:
        raise ValueError(f"At most {MAX_PATTERNS} patterns")
    return "\n".join(seen)


def ref_allowed(patterns: str, name: str) -> bool:
    """Whether a branch or tag name matches one of the hook's glob patterns.

    ``*`` also matches ``/`` (``release/*`` and ``*`` both match
    ``release/1.2``); matching is case-sensitive, as Git refs are.
    """
    return any(fnmatchcase(name, p) for p in patterns.split("\n") if p)


def skip_requested(message: str) -> bool:
    """``[skip ci]`` or ``[ci skip]`` in the pushed commit's message (any case)."""
    return bool(_SKIP_CI.search(message or ""))


_SCP_LIKE = re.compile(r"^(?:[^@/]+@)?([^:/]+):(?!//)(.+)$")


def normalise_repo(url: str) -> str | None:
    """``host/owner/repo`` for any spelling of a repository URL, or None.

    https, http, ssh://, git:// and scp-like ``git@host:owner/repo`` all
    become the same string: lower case, no user, port, ``.git`` or slash at
    the end. A self-hosted forge often clones over SSH on another port, so the
    port says nothing about which repository it is.
    """
    url = (url or "").strip()
    if not url:
        return None
    if "://" in url:
        parts = urlsplit(url)
        host, path = (parts.hostname or ""), parts.path
    else:
        m = _SCP_LIKE.match(url)
        if not m:
            return None
        host, path = m.group(1), m.group(2)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    path = path.strip("/")
    if not host or not path:
        return None
    return f"{host.lower()}/{path.lower()}"


def same_repository(project_url: str, payload_urls: list[str]) -> bool:
    """Whether any URL the delivery names is the project's repository."""
    want = normalise_repo(project_url)
    return want is not None and any(normalise_repo(u) == want for u in payload_urls)

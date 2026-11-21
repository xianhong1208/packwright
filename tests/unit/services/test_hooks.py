"""
Unit tests for incoming webhooks: signatures, payloads and filters.
Source: app/services/hooks.py
"""

import base64
import hashlib
import hmac
import time

import pytest

from app.services import hooks
from app.services.hooks import Rejected, verify

SECRET = "hook-secret-for-tests"
BODY = b'{"ref":"refs/heads/main"}'
SHA = "a" * 40
SIGNING_RAW = b"0123456789abcdef0123456789abcdef"
SIGNING_KEY = "whsec_" + base64.b64encode(SIGNING_RAW).decode()


def _hex(body: bytes = BODY, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _std_sig(msg_id: str, stamp: int, body: bytes = BODY, key: bytes = SIGNING_RAW) -> str:
    digest = hmac.new(key, f"{msg_id}.{stamp}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def _rejected(provider, headers, body=BODY, **kw) -> str:
    with pytest.raises(Rejected) as e:
        verify(provider, headers, body, SECRET, now=kw.pop("now", time.time()), **kw)
    return e.value.reason


@pytest.mark.unit
def test_tc_hook_001_github_signature_over_the_raw_body():
    """TC-HOOK-001: sha256=<hex> of the raw body with the secret passes; upper-case hex too."""
    verify("github", {"x-hub-signature-256": f"sha256={_hex()}"}, BODY, SECRET, now=0)
    verify("github", {"x-hub-signature-256": f"sha256={_hex().upper()}"}, BODY, SECRET, now=0)


@pytest.mark.unit
def test_tc_hook_002_github_wrong_missing_or_empty_signature_is_refused():
    """TC-HOOK-002: another body, another secret, no header, an empty header, a bare
    'sha256=', the legacy sha1 form, and a non-ASCII value are all refused."""
    assert _rejected("github", {"x-hub-signature-256": f"sha256={_hex(b'other')}"}) == "signature does not match"
    assert _rejected("github", {"x-hub-signature-256": f"sha256={_hex(secret='x')}"}) == "signature does not match"
    assert "no X-Hub-Signature-256" in _rejected("github", {})
    assert "no X-Hub-Signature-256" in _rejected("github", {"x-hub-signature-256": "  "})
    assert "not of the form" in _rejected("github", {"x-hub-signature-256": "sha256="})
    assert "not of the form" in _rejected("github", {"x-hub-signature-256": f"sha1={_hex()}"})
    assert _rejected("github", {"x-hub-signature-256": "sha256=é" + _hex()[1:]}) == "signature does not match"


@pytest.mark.unit
def test_tc_hook_003_signature_compare_is_constant_time(mocker):
    """TC-HOOK-003: the digest is compared with hmac.compare_digest, never ==."""
    spy = mocker.spy(hooks.hmac, "compare_digest")
    verify("github", {"x-hub-signature-256": f"sha256={_hex()}"}, BODY, SECRET, now=0)
    verify("gitlab", {"x-gitlab-token": SECRET}, BODY, SECRET, now=0)
    verify("generic", {"x-packwright-token": SECRET}, BODY, SECRET, now=0)
    assert spy.call_count == 3


@pytest.mark.unit
def test_tc_hook_004_gitea_signature_or_its_github_style_copy():
    """TC-HOOK-004: X-Gitea-Signature (hex, no prefix) passes; without it the
    X-Hub-Signature-256 copy is checked; empty headers (no secret set in Gitea) are refused."""
    verify("gitea", {"x-gitea-signature": _hex()}, BODY, SECRET, now=0)
    verify("gitea", {"x-hub-signature-256": f"sha256={_hex()}"}, BODY, SECRET, now=0)
    assert _rejected("gitea", {"x-gitea-signature": _hex(b"x")}) == "signature does not match"
    assert "no X-Hub-Signature-256" in _rejected("gitea", {"x-gitea-signature": "", "x-hub-signature-256": ""})


@pytest.mark.unit
def test_tc_hook_005_gitlab_secret_token():
    """TC-HOOK-005: X-Gitlab-Token equal to the secret passes; another, empty or none is refused."""
    verify("gitlab", {"x-gitlab-token": SECRET}, BODY, SECRET, now=0)
    assert _rejected("gitlab", {"x-gitlab-token": SECRET + "x"}) == "token does not match"
    assert "no X-Gitlab-Token" in _rejected("gitlab", {"x-gitlab-token": ""})
    assert "no X-Gitlab-Token" in _rejected("gitlab", {})


@pytest.mark.unit
def test_tc_hook_006_gitlab_signed_delivery():
    """TC-HOOK-006: with a signing token stored, v1,<base64 HMAC of id.timestamp.body> passes,
    also as one of several signatures; the clear token alone no longer does."""
    now = 1_800_000_000
    h = {"webhook-id": "msg-1", "webhook-timestamp": str(now), "webhook-signature": _std_sig("msg-1", now)}
    verify("gitlab", h, BODY, SECRET, signing_key=SIGNING_KEY, now=now)
    h2 = {**h, "webhook-signature": f"v1,AAAA {_std_sig('msg-1', now)}"}
    verify("gitlab", h2, BODY, SECRET, signing_key=SIGNING_KEY, now=now + 10)
    assert "no webhook-signature" in _rejected("gitlab", {"x-gitlab-token": SECRET}, signing_key=SIGNING_KEY, now=now)


@pytest.mark.unit
def test_tc_hook_007_gitlab_signed_delivery_refusals():
    """TC-HOOK-007: another body, another message id, a stamp more than 5 minutes off
    (either way), a non-numeric stamp, a missing id and a v2 label are refused."""
    now = 1_800_000_000
    good = {"webhook-id": "m", "webhook-timestamp": str(now), "webhook-signature": _std_sig("m", now)}
    kw = {"signing_key": SIGNING_KEY}
    assert _rejected("gitlab", good, body=b"{}", now=now, **kw) == "signature does not match"
    assert _rejected("gitlab", {**good, "webhook-id": "n"}, now=now, **kw) == "signature does not match"
    assert "5 minutes" in _rejected("gitlab", good, now=now + 301, **kw)
    assert "5 minutes" in _rejected("gitlab", good, now=now - 301, **kw)
    verify("gitlab", good, BODY, SECRET, now=now + 300, **kw)
    assert "not a number" in _rejected("gitlab", {**good, "webhook-timestamp": "soon"}, now=now, **kw)
    assert "missing" in _rejected("gitlab", {**good, "webhook-id": ""}, now=now, **kw)
    v2 = {**good, "webhook-signature": good["webhook-signature"].replace("v1,", "v2,")}
    assert _rejected("gitlab", v2, now=now, **kw) == "signature does not match"


@pytest.mark.unit
def test_tc_hook_008_generic_token_in_header_bearer_or_query():
    """TC-HOOK-008: the generic token is read from Authorization: Bearer, X-Packwright-Token,
    or ?token=; a wrong or missing one is refused."""
    verify("generic", {"authorization": f"Bearer {SECRET}"}, b"", SECRET, now=0)
    verify("generic", {"x-packwright-token": SECRET}, b"", SECRET, now=0)
    verify("generic", {}, b"", SECRET, now=0, query_token=SECRET)
    assert _rejected("generic", {"authorization": "Bearer nope"}) == "token does not match"
    assert _rejected("generic", {"authorization": "Basic " + SECRET}) == "no token"
    assert _rejected("generic", {}) == "no token"


@pytest.mark.unit
def test_tc_hook_009_signing_key_validation():
    """TC-HOOK-009: a pasted signing token must be whsec_ + base64 of at least 16 bytes."""
    assert hooks.valid_signing_key(f"  {SIGNING_KEY} ") == SIGNING_KEY
    for bad in ("whsec_not base64!", "whsec_" + base64.b64encode(b"short").decode()):
        with pytest.raises(ValueError):
            hooks.valid_signing_key(bad)


def _gh(ref="refs/heads/main", after=SHA, message="fix things", **extra) -> dict:
    return {
        "ref": ref, "after": after, "deleted": False, "head_commit": {"message": message},
        "repository": {"clone_url": "https://github.com/acme/app.git", "ssh_url": "git@github.com:acme/app.git"},
        **extra,
    }


@pytest.mark.unit
def test_tc_hook_010_github_push_and_tag_push():
    """TC-HOOK-010: a branch push and a tag push name the kind, the name, the pushed commit,
    the head commit's message and the repository URLs."""
    p = hooks.parse_forge("github", {"x-github-event": "push"}, _gh())
    assert p.push.kind == "branch" and p.push.name == "main" and p.push.sha == SHA
    assert p.push.message == "fix things" and "git@github.com:acme/app.git" in p.push.repo_urls
    t = hooks.parse_forge("github", {"x-github-event": "push"}, _gh(ref="refs/tags/v1.2.0", after=SHA.upper()))
    assert (t.push.kind, t.push.name, t.push.sha) == ("tag", "v1.2.0", SHA)


@pytest.mark.unit
def test_tc_hook_011_github_ping_other_events_deletions_are_ignored():
    """TC-HOOK-011: ping, another event, a deleted branch (zero SHA or deleted: true), a ref
    that is neither branch nor tag and a payload without a commit build nothing, with a reason."""
    ev = {"x-github-event": "push"}
    assert "ping" in hooks.parse_forge("github", {"x-github-event": "ping"}, {"zen": "x"}).ignored
    assert "pull_request" in hooks.parse_forge("github", {"x-github-event": "pull_request"}, _gh()).ignored
    assert hooks.parse_forge("github", ev, _gh(after="0" * 40)).ignored == "branch main was deleted"
    assert hooks.parse_forge("github", ev, _gh(deleted=True)).ignored == "branch main was deleted"
    assert hooks.parse_forge("github", ev, _gh(ref="refs/tags/v1", after="0" * 40)).ignored == "tag v1 was deleted"
    assert "neither" in hooks.parse_forge("github", ev, _gh(ref="refs/pull/1/head")).ignored
    assert hooks.parse_forge("github", ev, _gh(after="abc")).ignored == "the payload names no commit"
    for p in (hooks.parse_forge("github", ev, _gh(after="0" * 40)),):
        assert p.push is None


@pytest.mark.unit
def test_tc_hook_012_gitea_push_uses_the_last_commit_without_head_commit():
    """TC-HOOK-012: Gitea's X-Gitea-Event is read; without head_commit the last commit's message is used."""
    payload = _gh(message="")
    del payload["head_commit"]
    payload["commits"] = [{"message": "a"}, {"message": "b [skip ci]"}]
    p = hooks.parse_forge("gitea", {"x-gitea-event": "push"}, payload)
    assert p.push.message == "b [skip ci]"
    assert "delete" in hooks.parse_forge("gitea", {"x-gitea-event": "delete"}, payload).ignored


@pytest.mark.unit
def test_tc_hook_013_gitlab_push_tag_push_and_deletion():
    """TC-HOOK-013: Push Hook / Tag Push Hook build checkout_sha with its commit's message;
    a deletion (after = zeros, checkout_sha null) and other events are ignored."""
    payload = {
        "object_kind": "push", "ref": "refs/heads/dev", "after": SHA, "checkout_sha": SHA,
        "commits": [{"id": "b" * 40, "message": "older"}, {"id": SHA, "message": "head"}],
        "project": {"git_http_url": "https://gitlab.com/acme/app.git", "git_ssh_url": "git@gitlab.com:acme/app.git"},
    }
    p = hooks.parse_forge("gitlab", {"x-gitlab-event": "Push Hook"}, payload)
    assert (p.push.kind, p.push.name, p.push.sha, p.push.message) == ("branch", "dev", SHA, "head")
    tag = {**payload, "ref": "refs/tags/v2", "object_kind": "tag_push"}
    assert hooks.parse_forge("gitlab", {"x-gitlab-event": "Tag Push Hook"}, tag).push.kind == "tag"
    gone = {**tag, "after": "0" * 40, "checkout_sha": None}
    assert hooks.parse_forge("gitlab", {"x-gitlab-event": "Tag Push Hook"}, gone).ignored == "tag v2 was deleted"
    assert "Merge Request Hook" in hooks.parse_forge("gitlab", {"x-gitlab-event": "Merge Request Hook"}, payload).ignored


@pytest.mark.unit
def test_tc_hook_014_generic_body():
    """TC-HOOK-014: no body builds the project's own ref; a full or bare ref and a commit are
    read; a short commit or an unknown ref_type is ignored with a reason."""
    p = hooks.parse_generic({}, "main", "branch")
    assert (p.push.kind, p.push.name, p.push.sha, p.ref) == ("branch", "main", "", "refs/heads/main")
    p = hooks.parse_generic({"ref": "refs/tags/v3", "commit": SHA}, "main", "branch")
    assert (p.push.kind, p.push.name, p.push.sha) == ("tag", "v3", SHA)
    assert hooks.parse_generic({"ref": "v3", "ref_type": "tag"}, "main", "branch").push.kind == "tag"
    assert "full commit" in hooks.parse_generic({"commit": "abc123"}, "main", "branch").ignored
    assert "ref_type" in hooks.parse_generic({"ref": "x", "ref_type": "pr"}, "main", "branch").ignored


@pytest.mark.unit
def test_tc_hook_015_glob_filters():
    """TC-HOOK-015: patterns are split on lines, spaces or commas; '*' matches across '/';
    matching is case-sensitive; no pattern matches nothing."""
    pats = hooks.normalise_patterns("main, release/*\n v*  main")
    assert pats == "main\nrelease/*\nv*"
    assert hooks.ref_allowed(pats, "main") and hooks.ref_allowed(pats, "release/1.2")
    assert hooks.ref_allowed(pats, "v1.0.0") and not hooks.ref_allowed(pats, "Main")
    assert not hooks.ref_allowed(pats, "feature/x")
    assert not hooks.ref_allowed("", "main")
    assert hooks.ref_allowed("*", "feature/deep/x")
    with pytest.raises(ValueError):
        hooks.normalise_patterns(" ".join(f"p{i}" for i in range(21)))
    with pytest.raises(ValueError):
        hooks.normalise_patterns("x" * 201)


@pytest.mark.unit
def test_tc_hook_016_skip_ci_markers():
    """TC-HOOK-016: [skip ci] and [ci skip] anywhere, in any case, ask to skip; similar text does not."""
    assert hooks.skip_requested("Docs only [skip ci]")
    assert hooks.skip_requested("[CI SKIP] typo")
    assert not hooks.skip_requested("skip ci")
    assert not hooks.skip_requested("[skip-ci]")
    assert not hooks.skip_requested("")


@pytest.mark.unit
def test_tc_hook_017_repository_urls_are_compared_normalised():
    """TC-HOOK-017: https, ssh://, scp-like and .git/no .git spellings of one repository match;
    user names, ports and case do not matter; another repository or host does not match."""
    same = [
        "https://github.com/Acme/App.git", "https://user:tok@github.com/acme/app/",
        "git@github.com:acme/app.git", "ssh://git@github.com:22/acme/app", "http://github.com/acme/app",
    ]
    assert all(hooks.normalise_repo(u) == "github.com/acme/app" for u in same)
    assert hooks.same_repository("https://github.com/acme/app.git", ["git@github.com:acme/app.git"])
    assert not hooks.same_repository("https://github.com/acme/app.git", ["https://github.com/acme/app2.git"])
    assert not hooks.same_repository("https://github.com/acme/app.git", ["https://gitlab.com/acme/app.git"])
    assert not hooks.same_repository("https://github.com/acme/app.git", [])
    assert hooks.normalise_repo("") is None and hooks.normalise_repo("not a url") is None


@pytest.mark.unit
def test_tc_hook_018_public_ids_and_secrets_are_random_and_long():
    """TC-HOOK-018: hook ids carry 128 bits, secrets 256 bits, and never repeat."""
    ids = {hooks.new_public_id() for _ in range(500)}
    secrets_ = {hooks.new_secret() for _ in range(500)}
    assert len(ids) == len(secrets_) == 500
    assert all(len(i) >= 22 for i in ids) and all(len(s) >= 43 for s in secrets_)


class _FakeRequest:
    """Just enough of a Starlette request for _read_body."""

    def __init__(self, declared: str | None, chunks: list[bytes]):
        self.headers = {} if declared is None else {"content-length": declared}
        self._chunks = chunks
        self.read = 0

    async def stream(self):
        for c in self._chunks:
            self.read += 1
            yield c


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_hook_019_body_cap_refuses_a_declared_size_before_reading():
    """TC-HOOK-019: a Content-Length over the cap (or not a number) is refused without reading
    a byte; a body without one is read only until it passes the cap; one at the cap is read."""
    from app.api.routes.hooks import _read_body, _TooLarge

    for declared in ("1025", "lots"):
        req = _FakeRequest(declared, [b"x"])
        with pytest.raises(_TooLarge):
            await _read_body(req, 1024)
        assert req.read == 0
    req = _FakeRequest(None, [b"x" * 600, b"x" * 600, b"x" * 600])
    with pytest.raises(_TooLarge):
        await _read_body(req, 1024)
    assert req.read == 2
    assert await _read_body(_FakeRequest("1024", [b"x" * 1024]), 1024) == b"x" * 1024


@pytest.mark.unit
def test_tc_hook_020_access_log_masks_a_query_token():
    """TC-HOOK-020: uvicorn's access line for /api/hooks/generic/<id>?token=<secret> shows
    [redacted] in place of the token, and leaves other query values alone."""
    import logging

    from app.main import _RedactQueryTokens

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "POST", "/api/hooks/generic/abc?ref=main&token=s3cret-value&x=1", "1.1", 202), None,
    )
    assert _RedactQueryTokens().filter(record)
    line = record.getMessage()
    assert "s3cret-value" not in line and "token=[redacted]" in line and "ref=main" in line and "x=1" in line
    assert _RedactQueryTokens in {type(f) for f in logging.getLogger("uvicorn.access").filters}

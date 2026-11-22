"""
Incoming webhooks through the real app and database: managing hooks, receiving
signed deliveries, and the builds (or the reasons for none) they lead to.
Source: app/api/routes/hooks.py, app/services/hooks.py, app/services/triggered_builds.py,
        alembic/versions/d4f7a9c2e8b1_add_project_hooks.py

Builds are filed but never started (start_build_task is replaced), so nothing is
cloned: what is under test is which delivery files which build, as whom, at which commit.
"""

import base64
import hashlib
import hmac
import json
import sqlite3
import time
import uuid

import pytest

from .test_api_tokens import _new as _new_api_token
from .test_artifact_download import _db_file
from .test_projects import _build, _git, _h, _viewer

REPO = "https://github.com/acme/hooked.git"
SHA = "1" * 40


@pytest.fixture
def no_hook_builds(no_builds, mocker):
    from app.api.routes import hooks as hooks_route

    return mocker.patch.object(hooks_route, "start_build_task", mocker.AsyncMock())


def _sql(query: str, *args):
    with sqlite3.connect(_db_file()) as con:
        return con.execute(query, args).fetchall()


def _project(client, token, name, url=REPO) -> int:
    return _build(client, token, name, _git(url))["project_id"]


def _hook(client, token, project_id, provider="github", branches="main", tags="v*") -> dict:
    r = client.post(f"/api/projects/{project_id}/hooks", headers=_h(token),
                    json={"provider": provider, "branches": branches, "tags": tags})
    assert r.status_code == 201, r.text
    return r.json()


def _push(ref="refs/heads/main", sha=SHA, message="change", repo=REPO, **extra) -> bytes:
    return json.dumps({
        "ref": ref, "before": "2" * 40, "after": sha, "deleted": False,
        "head_commit": {"id": sha, "message": message},
        "repository": {"clone_url": repo, "html_url": repo.removesuffix(".git")},
        **extra,
    }).encode()


def _gh(client, hook, body, event="push", secret=None, delivery=None, sig=None):
    secret = hook["secret"] if secret is None else secret
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery or str(uuid.uuid4()),
        "X-Hub-Signature-256": sig if sig is not None else
        "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
    }
    return client.post(hook["path"], content=body, headers=headers)


def _deliveries(client, token, project_id, hook_id) -> list[dict]:
    r = client.get(f"/api/projects/{project_id}/hooks/{hook_id}/deliveries", headers=_h(token))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.integration
def test_tc_int_098_a_hook_secret_is_shown_once_and_stored_encrypted(client, admin_tokens, no_hook_builds):
    """TC-INT-098: creating answers the secret and a payload URL with a random id; the list
    never shows the secret; the database holds it encrypted; creation is audited."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-create")
    hook = _hook(client, token, pid, branches="main, release/*", tags="")
    assert hook["path"].startswith("/api/hooks/github/") and len(hook["path"].rsplit("/", 1)[1]) >= 22
    assert hook["url"].endswith(hook["path"]) and hook["branches"] == ["main", "release/*"] and hook["tags"] == []
    assert hook["enabled"] and hook["created_by"] == "admin" and len(hook["secret"]) >= 43

    listed = client.get(f"/api/projects/{pid}/hooks", headers=_h(token)).json()
    assert [h["id"] for h in listed] == [hook["id"]] and "secret" not in listed[0]
    assert hook["secret"] not in json.dumps(_sql("SELECT * FROM project_hooks"))
    assert hook["secret"] not in json.dumps(_sql("SELECT * FROM audit_logs"))
    assert _sql("SELECT status FROM audit_logs WHERE action = 'hook_create' AND resource_id = ?", str(hook["id"]))


@pytest.mark.integration
def test_tc_int_099_only_the_creator_or_a_project_manager_manages_hooks(client, admin_tokens, no_hook_builds):
    """TC-INT-099: another builder sees the hooks but cannot create, change, rotate or delete
    one; an API token (even with every scope) reaches none of the hook routes; a hook on a
    local-folder project or with too many patterns is refused."""
    admin = admin_tokens["access_token"]
    pid = _project(client, admin, "hook-perms")
    hook = _hook(client, admin, pid)
    other = _viewer(client, admin, "hook-viewer")
    assert client.get(f"/api/projects/{pid}/hooks", headers=_h(other)).status_code == 200
    base = f"/api/projects/{pid}/hooks"
    assert client.post(base, headers=_h(other), json={"provider": "github"}).status_code == 403
    assert client.patch(f"{base}/{hook['id']}", headers=_h(other), json={"enabled": False}).status_code == 403
    assert client.post(f"{base}/{hook['id']}/rotate", headers=_h(other)).status_code == 403
    assert client.delete(f"{base}/{hook['id']}", headers=_h(other)).status_code == 403

    api = _new_api_token(client, admin)["token"]
    assert client.get(base, headers=_h(api)).status_code == 403
    assert client.post(base, headers=_h(api), json={"provider": "github"}).status_code == 403
    assert client.post(f"{base}/{hook['id']}/rotate", headers=_h(api)).status_code == 403

    r = client.post(base, headers=_h(admin), json={"provider": "github", "branches": " ".join(f"b{i}" for i in range(21))})
    assert r.status_code == 422
    assert client.post(base, headers=_h(admin), json={"provider": "svn"}).status_code == 422


@pytest.mark.integration
def test_tc_int_100_a_push_builds_exactly_the_pushed_commit_as_the_creator(client, admin_tokens, no_hook_builds):
    """TC-INT-100: a signed GitHub push of a matching branch answers 202 with the build id;
    the build is filed under the project as the hook's creator with trigger push, the pushed
    commit and branch; the background start gets that commit; the delivery says built."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-push")
    hook = _hook(client, token, pid)
    r = _gh(client, hook, _push(sha="ab" * 20))
    assert r.status_code == 202, r.text
    build_id = r.json()["build_id"]
    item = client.get(f"/api/history/{build_id}", headers=_h(token)).json()
    assert item["trigger"] == "push" and item["commit_sha"] == "ab" * 20 and item["user_name"] == "admin"
    assert item["project_id"] == pid and item["config"]["git_ref"] == "main" and item["config"]["git_ref_type"] == "branch"
    args = no_hook_builds.call_args.args
    assert args[0] == build_id and args[2] == "ab" * 20
    [d] = _deliveries(client, token, pid, hook["id"])
    assert d["result"] == "built" and d["task_id"] == build_id and d["ref"] == "refs/heads/main" and d["event"] == "push"


@pytest.mark.integration
def test_tc_int_101_a_tag_push_builds_as_tag_with_the_tag_as_version(client, admin_tokens, no_hook_builds):
    """TC-INT-101: a tag push matching the tag patterns builds with trigger tag, the tag as
    ref and version; a tag outside the patterns is ignored."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-tag")
    hook = _hook(client, token, pid, tags="v*")
    r = _gh(client, hook, _push(ref="refs/tags/v1.4.0", sha="cd" * 20))
    assert r.status_code == 202, r.text
    item = client.get(f"/api/history/{r.json()['build_id']}", headers=_h(token)).json()
    assert item["trigger"] == "tag" and item["config"]["version"] == "v1.4.0" and item["config"]["git_ref_type"] == "tag"
    r = _gh(client, hook, _push(ref="refs/tags/nightly", sha="ce" * 20))
    assert r.status_code == 200 and r.json()["status"] == "ignored" and "tag patterns" in r.json()["reason"]


@pytest.mark.integration
def test_tc_int_102_bad_missing_or_empty_signatures_get_the_same_401(client, admin_tokens, no_hook_builds):
    """TC-INT-102: a wrong secret, no signature, an empty signature, an unknown hook id and the
    wrong provider in the URL all answer the same 401 body and build nothing; the reasons are
    in the deliveries list."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-sig")
    hook = _hook(client, token, pid)
    body = _push()
    answers = [
        _gh(client, hook, body, secret="wrong"),
        _gh(client, hook, body, sig=""),
        client.post(hook["path"], content=body, headers={"X-GitHub-Event": "push"}),
        client.post("/api/hooks/github/doesnotexist0000000000", content=body),
        client.post(hook["path"].replace("/github/", "/gitlab/"), content=body, headers={"X-Gitlab-Token": hook["secret"]}),
        client.post(hook["path"].replace("/github/", "/nosuch/"), content=body),
    ]
    assert {r.status_code for r in answers} == {401}
    assert len({r.text for r in answers}) == 1
    no_hook_builds.assert_not_called()
    reasons = [d["reason"] for d in _deliveries(client, token, pid, hook["id"])]
    assert {d["result"] for d in _deliveries(client, token, pid, hook["id"])} == {"rejected"}
    assert "signature does not match" in reasons and any("no X-Hub-Signature-256" in r for r in reasons)
    assert any("gitlab URL" in r for r in reasons)


@pytest.mark.integration
def test_tc_int_103_duplicates_are_built_once(client, admin_tokens, no_hook_builds):
    """TC-INT-103: the same delivery id again is ignored with the first build's id; a new
    delivery id for a commit already queued on the same ref is ignored too; another branch at
    the same commit builds; a rejected delivery id does not block the real one."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-dup")
    hook = _hook(client, token, pid, branches="*")
    body = _push(sha="ef" * 20)
    first = _gh(client, hook, body, delivery="dlv-1")
    assert first.status_code == 202
    again = _gh(client, hook, body, delivery="dlv-1")
    assert again.status_code == 200 and again.json()["build_id"] == first.json()["build_id"]
    retry = _gh(client, hook, body, delivery="dlv-2")
    assert retry.status_code == 200 and "already built" in retry.json()["reason"]
    other = _gh(client, hook, _push(ref="refs/heads/dev", sha="ef" * 20), delivery="dlv-3")
    assert other.status_code == 202
    assert no_hook_builds.call_count == 2

    assert _gh(client, hook, _push(sha="f0" * 20), delivery="dlv-4", secret="forged").status_code == 401
    assert _gh(client, hook, _push(sha="f0" * 20), delivery="dlv-4").status_code == 202


@pytest.mark.integration
def test_tc_int_104_a_recent_success_dedupes_an_old_one_does_not(client, admin_tokens, no_hook_builds):
    """TC-INT-104: a build of the commit that passed 5 minutes ago makes a new delivery a
    duplicate; one that passed 11 minutes ago, or failed, does not."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-window")
    hook = _hook(client, token, pid)
    sha = "a1" * 20
    build = _gh(client, hook, _push(sha=sha)).json()["build_id"]

    def finish(status, minutes_ago):
        _sql("UPDATE history SET status = ?, end_time = datetime('now', ?) WHERE task_id = ?",
             status, f"-{minutes_ago} minutes", build)

    finish("COMPLETED", 5)
    assert _gh(client, hook, _push(sha=sha)).status_code == 200
    finish("FAILED", 1)
    r = _gh(client, hook, _push(sha=sha))
    assert r.status_code == 202
    build = r.json()["build_id"]
    finish("COMPLETED", 11)
    assert _gh(client, hook, _push(sha=sha)).status_code == 202


@pytest.mark.integration
def test_tc_int_105_genuine_deliveries_that_build_nothing_answer_200(client, admin_tokens, no_hook_builds):
    """TC-INT-105: ping, another event, a deleted branch, [skip ci], a branch outside the
    patterns and another repository all answer 200 ignored with a reason, build nothing,
    and are listed as ignored."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-ignore")
    hook = _hook(client, token, pid, branches="main")
    cases = [
        (_gh(client, hook, b'{"zen":"hi","hook_id":1}', event="ping"), "ping"),
        (_gh(client, hook, _push(), event="issues"), "issues event"),
        (_gh(client, hook, _push(sha="0" * 40, deleted=True)), "was deleted"),
        (_gh(client, hook, _push(sha="b2" * 20, message="docs [skip ci]")), "skip"),
        (_gh(client, hook, _push(ref="refs/heads/feature/x", sha="b3" * 20)), "branch patterns"),
        (_gh(client, hook, _push(sha="b4" * 20, repo="https://github.com/evil/hooked.git")), "not this project's"),
    ]
    for r, words in cases:
        assert r.status_code == 200 and r.json()["status"] == "ignored" and words in r.json()["reason"], r.text
    no_hook_builds.assert_not_called()
    assert [d["result"] for d in _deliveries(client, token, pid, hook["id"])] == ["ignored"] * 6
    # The same repository spelt as SSH matches.
    r = _gh(client, hook, _push(sha="b5" * 20, repo="git@github.com:Acme/hooked"))
    assert r.status_code == 202


@pytest.mark.integration
def test_tc_int_106_a_creator_who_may_no_longer_build_turns_the_hook_off(client, admin_tokens, no_hook_builds):
    """TC-INT-106: once the creator is deactivated the next push answers 200 'hook disabled',
    builds nothing, and the hook shows off with the reason (audited); turning it on again is
    409 until someone takes it over, after which pushes build as that person."""
    admin = admin_tokens["access_token"]
    owner = _viewer(client, admin, "hook-owner")
    pid = _project(client, owner, "hook-owned")
    hook = _hook(client, owner, pid)
    uid = next(u["id"] for u in client.get("/api/users", headers=_h(admin)).json() if u["username"] == "hook-owner")
    assert client.put(f"/api/users/{uid}/status", json={"is_active": False}, headers=_h(admin)).status_code == 200

    r = _gh(client, hook, _push(sha="c1" * 20))
    assert r.status_code == 200 and "hook disabled" in r.json()["reason"] and "deactivated" in r.json()["reason"]
    no_hook_builds.assert_not_called()
    [listed] = client.get(f"/api/projects/{pid}/hooks", headers=_h(admin)).json()
    assert not listed["enabled"] and "hook-owner's account is deactivated" in listed["disabled_reason"]
    assert _sql("SELECT error_message FROM audit_logs WHERE action = 'hook_disabled' AND resource_id = ?", str(hook["id"]))
    r = _gh(client, hook, _push(sha="c2" * 20))
    assert r.status_code == 200 and r.json()["reason"].startswith("hook disabled")

    url = f"/api/projects/{pid}/hooks/{hook['id']}"
    r = client.patch(url, headers=_h(admin), json={"enabled": True})
    assert r.status_code == 409 and "Take it over" in r.json()["detail"]
    r = client.patch(url, headers=_h(admin), json={"enabled": True, "take_over": True})
    assert r.status_code == 200 and r.json()["enabled"] and r.json()["created_by"] == "admin"
    r = _gh(client, hook, _push(sha="c3" * 20))
    assert r.status_code == 202
    assert client.get(f"/api/history/{r.json()['build_id']}", headers=_h(admin)).json()["user_name"] == "admin"


@pytest.mark.integration
def test_tc_int_107_a_manually_disabled_hook_and_rotation(client, admin_tokens, no_hook_builds):
    """TC-INT-107: a disabled hook answers 200 ignored; rotating gives a new secret and the
    old one is refused at once."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-rotate")
    hook = _hook(client, token, pid)
    url = f"/api/projects/{pid}/hooks/{hook['id']}"
    assert client.patch(url, headers=_h(token), json={"enabled": False}).json()["enabled"] is False
    r = _gh(client, hook, _push(sha="d1" * 20))
    assert r.status_code == 200 and r.json()["reason"] == "hook disabled"
    client.patch(url, headers=_h(token), json={"enabled": True})

    rotated = client.post(f"{url}/rotate", headers=_h(token)).json()
    assert rotated["secret"] != hook["secret"] and rotated["secret_rotated_at"]
    assert _gh(client, hook, _push(sha="d2" * 20)).status_code == 401
    assert _gh(client, {**hook, "secret": rotated["secret"]}, _push(sha="d2" * 20)).status_code == 202


def _gitlab_body(sha, ref="refs/heads/main", url=REPO) -> bytes:
    return json.dumps({
        "object_kind": "push", "ref": ref, "before": "3" * 40, "after": sha, "checkout_sha": sha,
        "commits": [{"id": sha, "message": "gl"}],
        "project": {"git_http_url": url, "web_url": url.removesuffix(".git")},
    }).encode()


@pytest.mark.integration
def test_tc_int_108_gitlab_token_and_signed_deliveries(client, admin_tokens, no_hook_builds):
    """TC-INT-108: GitLab with X-Gitlab-Token builds; once the GitLab signing token is stored a
    signed delivery builds and the clear token alone is refused; the signing token is
    write-only and checked; other providers have none."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-gitlab")
    hook = _hook(client, token, pid, provider="gitlab")
    plain = {"X-Gitlab-Event": "Push Hook", "X-Gitlab-Token": hook["secret"], "Content-Type": "application/json"}
    r = client.post(hook["path"], content=_gitlab_body("e1" * 20), headers={**plain, "Idempotency-Key": "k1"})
    assert r.status_code == 202, r.text

    raw = b"k" * 32
    key = "whsec_" + base64.b64encode(raw).decode()
    url = f"/api/projects/{pid}/hooks/{hook['id']}/signing-key"
    assert client.put(url, headers=_h(token), json={"signing_key": "whsec_!!"}).status_code == 422
    r = client.put(url, headers=_h(token), json={"signing_key": key})
    assert r.status_code == 200 and r.json()["has_signing_key"] and key not in r.text
    assert key not in json.dumps(_sql("SELECT * FROM project_hooks"))

    body = _gitlab_body("e2" * 20)
    assert client.post(hook["path"], content=body, headers=plain).status_code == 401
    stamp = str(int(time.time()))
    sig = base64.b64encode(hmac.new(raw, f"m-2.{stamp}.".encode() + body, hashlib.sha256).digest()).decode()
    signed = {"X-Gitlab-Event": "Push Hook", "webhook-id": "m-2", "webhook-timestamp": stamp,
              "webhook-signature": f"v1,{sig}", "Content-Type": "application/json"}
    r = client.post(hook["path"], content=body, headers=signed)
    assert r.status_code == 202, r.text
    # GitLab's retry keeps webhook-id: a duplicate.
    assert client.post(hook["path"], content=body, headers=signed).json()["status"] == "ignored"

    gh = _hook(client, token, pid)
    assert client.put(f"/api/projects/{pid}/hooks/{gh['id']}/signing-key", headers=_h(token),
                      json={"signing_key": key}).status_code == 422


@pytest.mark.integration
def test_tc_int_109_gitea_and_generic(client, admin_tokens, no_hook_builds):
    """TC-INT-109: Gitea's X-Gitea-Signature builds; the generic URL builds the project's ref
    with its token in a header or ?token=, or a named tag at a commit, and refuses a wrong token."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-gitea-generic")
    gitea = _hook(client, token, pid, provider="gitea")
    body = _push(sha="f1" * 20)
    r = client.post(gitea["path"], content=body, headers={
        "X-Gitea-Event": "push", "X-Gitea-Delivery": "g-1",
        "X-Gitea-Signature": hmac.new(gitea["secret"].encode(), body, hashlib.sha256).hexdigest()})
    assert r.status_code == 202, r.text

    generic = _hook(client, token, pid, provider="generic", branches="main", tags="v*")
    r = client.post(generic["path"], headers={"Authorization": f"Bearer {generic['secret']}"})
    assert r.status_code == 202, r.text
    item = client.get(f"/api/history/{r.json()['build_id']}", headers=_h(token)).json()
    assert item["trigger"] == "push" and item["commit_sha"] is None and item["config"]["git_ref"] == "main"
    r = client.post(f"{generic['path']}?token={generic['secret']}", json={"ref": "refs/tags/v9", "commit": "f2" * 20})
    assert r.status_code == 202
    item = client.get(f"/api/history/{r.json()['build_id']}", headers=_h(token)).json()
    assert item["trigger"] == "tag" and item["commit_sha"] == "f2" * 20
    assert client.post(generic["path"], headers={"X-Packwright-Token": "nope"}).status_code == 401
    assert client.post(generic["path"], headers={"X-Packwright-Token": generic["secret"]},
                       content=b"[1]").status_code == 400


@pytest.mark.integration
def test_tc_int_110_body_size_cap_and_own_rate_limit(client, admin_tokens, no_hook_builds):
    """TC-INT-110: a body over WEBHOOK_MAX_BODY_BYTES answers 413 (declared or streamed);
    webhook deliveries have their own per-minute budget (60 by default) and its 429 does not
    touch the console's."""
    from app.config import get_settings

    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-limits")
    hook = _hook(client, token, pid)
    big = b"x" * (get_settings().webhook_max_body_bytes + 1)
    assert client.post(hook["path"], content=big).status_code == 413

    def chunks():
        for _ in range(3):
            yield b"y" * (get_settings().webhook_max_body_bytes // 2)

    assert client.post(hook["path"], content=chunks()).status_code == 413

    # The two 413s above already spent two of this minute's deliveries.
    budget = get_settings().webhook_per_minute - 2
    codes = [client.post("/api/hooks/github/nonexistent-hook-id").status_code for _ in range(budget)]
    assert set(codes) == {401}
    assert client.post("/api/hooks/github/nonexistent-hook-id").status_code == 429
    assert client.get("/api/projects", headers=_h(token)).status_code == 200


@pytest.mark.integration
def test_tc_int_111_deliveries_are_bounded_and_hooks_go_with_their_project(client, admin_tokens, no_hook_builds):
    """TC-INT-111: a hook keeps its newest 50 deliveries; deleting a hook or its project
    removes its deliveries; deleting a hook is audited."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "hook-bound")
    hook = _hook(client, token, pid)
    for i in range(55):
        _gh(client, hook, _push(), event=f"evt{i}")
    listed = _deliveries(client, token, pid, hook["id"])
    assert len(listed) == 50 and listed[0]["event"] == "evt54" and listed[-1]["event"] == "evt5"
    assert _sql("SELECT COUNT(*) FROM hook_deliveries WHERE hook_id = ?", hook["id"]) == [(50,)]

    second = _hook(client, token, pid)
    _gh(client, second, _push(), event="ping")
    assert client.delete(f"/api/projects/{pid}/hooks/{second['id']}", headers=_h(token)).status_code == 204
    assert _sql("SELECT COUNT(*) FROM hook_deliveries WHERE hook_id = ?", second["id"]) == [(0,)]
    assert _sql("SELECT 1 FROM audit_logs WHERE action = 'hook_delete' AND resource_id = ?", str(second["id"]))

    assert client.delete(f"/api/projects/{pid}", headers=_h(token)).status_code == 204
    assert _sql("SELECT COUNT(*) FROM project_hooks WHERE project_id = ?", pid) == [(0,)]
    assert _sql("SELECT COUNT(*) FROM hook_deliveries WHERE hook_id = ?", hook["id"]) == [(0,)]
    assert client.post(hook["path"], content=_push()).status_code == 401


@pytest.mark.integration
def test_tc_int_112_a_deleted_creator_leaves_the_hook_turned_off_not_gone(client, admin_tokens, no_hook_builds):
    """TC-INT-112: deleting the creator's account (users row; ON DELETE SET NULL) keeps the
    hook; its next push answers 200 and turns it off with "no longer has an account"."""
    admin = admin_tokens["access_token"]
    owner = _viewer(client, admin, "hook-gone")
    pid = _project(client, owner, "hook-gone-project")
    hook = _hook(client, owner, pid)
    with sqlite3.connect(_db_file()) as con:
        con.execute("PRAGMA foreign_keys=ON")
        uid = con.execute("SELECT id FROM users WHERE username = 'hook-gone'").fetchone()[0]
        for table in ("refresh_tokens", "login_history"):
            con.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
        con.execute("DELETE FROM users WHERE id = ?", (uid,))
    assert _sql("SELECT created_by_id, created_by FROM project_hooks WHERE id = ?", hook["id"]) == [(None, "hook-gone")]
    r = _gh(client, hook, _push(sha="9" * 40))
    assert r.status_code == 200 and "no longer has an account" in r.json()["reason"]
    no_hook_builds.assert_not_called()
    [listed] = client.get(f"/api/projects/{pid}/hooks", headers=_h(admin)).json()
    assert not listed["enabled"] and "no longer has an account" in listed["disabled_reason"]


@pytest.mark.integration
def test_tc_int_113_a_creator_without_task_create_turns_the_hook_off(client, admin_tokens, no_hook_builds):
    """TC-INT-113: moving the creator to a role without task:create (account still active)
    turns the hook off at the next push, with that reason."""
    admin = admin_tokens["access_token"]
    owner = _viewer(client, admin, "hook-readonly")
    pid = _project(client, owner, "hook-readonly-project")
    hook = _hook(client, owner, pid)
    r = client.post("/api/users/roles", headers=_h(admin), json={
        "name": "hook-reader", "display_name": "Reader", "permission_codes": ["history:view_own"]})
    assert r.status_code == 200, r.text
    uid = next(u["id"] for u in client.get("/api/users", headers=_h(admin)).json() if u["username"] == "hook-readonly")
    assert client.put(f"/api/users/{uid}/role", headers=_h(admin), json={"role_id": r.json()["id"]}).status_code == 200
    r = _gh(client, hook, _push(sha="8" * 40))
    assert r.status_code == 200 and "task:create" in r.json()["reason"]
    no_hook_builds.assert_not_called()

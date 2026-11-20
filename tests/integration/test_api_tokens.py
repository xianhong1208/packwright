"""
API tokens through the real app and database: creating, using, refusing, revoking.
Source: app/api/routes/api_tokens.py, app/services/api_tokens.py,
        app/services/permission.py (get_current_user), app/api/websocket.py,
        alembic/versions/c9d4e1f7a2b6_add_api_tokens.py
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect
from starlette.websockets import WebSocketDisconnect

from app.services.api_tokens import _checksum, generate_token, hash_token

from .test_artifact_download import _completed_task, _db_file
from .test_projects import _git, _h, _viewer
from .test_schema_drift import _migrate

ALL = ["builds:read", "builds:write", "projects:read"]


def _new(client, session: str, name="ci", scopes=ALL, days=30) -> dict:
    r = client.post("/api/tokens", json={"name": name, "scopes": scopes, "expires_in_days": days}, headers=_h(session))
    assert r.status_code == 201, r.text
    return r.json()


def _sql(query: str, *args):
    with sqlite3.connect(_db_file()) as con:
        return con.execute(query, args).fetchall()


def _audit(action: str, resource_id) -> list[tuple]:
    return _sql("SELECT status, error_message, details, actor_id FROM audit_logs"
                " WHERE action = ? AND resource_id = ? ORDER BY id", action, str(resource_id))


@pytest.mark.integration
def test_tc_int_087_a_token_is_shown_once_and_stored_as_a_hash(client, admin_tokens):
    """TC-INT-087: creating answers 201 with the token; the list shows only its prefix;
    the database holds its SHA-256 and never the token; creation is audited."""
    session = admin_tokens["access_token"]
    created = _new(client, session, name="  release script  ", scopes=["projects:read", "builds:read"], days=7)
    token = created["token"]
    assert token.startswith("pwt_") and len(token) == 53
    assert created["name"] == "release script" and created["scopes"] == ["builds:read", "projects:read"]
    assert created["prefix"] == token[:12] and created["status"] == "active"
    expires = datetime.fromisoformat(created["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    assert timedelta(days=6, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=7)

    listed = client.get("/api/tokens", headers=_h(session)).json()
    row = next(t for t in listed if t["id"] == created["id"])
    assert "token" not in row and token not in json.dumps(listed)

    stored = _sql("SELECT token_hash, token_prefix FROM api_tokens WHERE id = ?", created["id"])
    assert stored == [(hash_token(token), token[:12])]
    assert token not in json.dumps(_sql("SELECT * FROM api_tokens")) + json.dumps(_sql("SELECT * FROM audit_logs"))
    [(status, _err, details, _actor)] = _audit("api_token_create", created["id"])
    assert status == "success" and json.loads(details)["prefix"] == token[:12]


@pytest.mark.integration
def test_tc_int_088_creation_is_validated(client, admin_tokens):
    """TC-INT-088: a name, at least one known scope and an expiry of 1 to 365 days are required."""
    session = admin_tokens["access_token"]
    for body in (
        {"name": "x", "scopes": ALL, "expires_in_days": 0},
        {"name": "x", "scopes": ALL, "expires_in_days": 366},
        {"name": "x", "scopes": ALL},
        {"name": "   ", "scopes": ALL, "expires_in_days": 30},
        {"name": "x", "scopes": [], "expires_in_days": 30},
        {"name": "x", "scopes": ["builds:read", "admin"], "expires_in_days": 30},
        {"name": "x" * 101, "scopes": ALL, "expires_in_days": 30},
    ):
        assert client.post("/api/tokens", json=body, headers=_h(session)).status_code == 422, body


@pytest.mark.integration
def test_tc_int_089_builds_started_with_a_token_say_api(client, admin_tokens, no_builds):
    """TC-INT-089: a build from /api/tasks and a project's new version, started with a token,
    are recorded as trigger "api" whatever the body says; the same with a session is "console"."""
    session = admin_tokens["access_token"]
    token = _new(client, session)["token"]
    r = client.post("/api/tasks", headers=_h(token), json={
        "project_name": "tok-build", "config": _git("https://git.example.com/tok.git"), "trigger": "console"})
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["trigger"] == "api" and task["user_name"] == "admin"
    assert client.get(f"/api/history/{task['id']}", headers=_h(token)).json()["trigger"] == "api"

    r = client.post(f"/api/projects/{task['project_id']}/builds", json={"version": "2.0.0"}, headers=_h(token))
    assert r.status_code == 201 and r.json()["trigger"] == "api"
    r = client.post(f"/api/projects/{task['project_id']}/builds", json={"version": "2.0.1"}, headers=_h(session))
    assert r.status_code == 201 and r.json()["trigger"] == "console"

    # Reading back: active builds, one build, its logs, the project list, cancelling.
    assert client.get("/api/tasks", headers=_h(token)).status_code == 200
    assert client.get(f"/api/tasks/{task['id']}/logs", headers=_h(token)).status_code == 200
    assert any(p["id"] == task["project_id"] for p in client.get("/api/projects", headers=_h(token)).json())
    assert client.get(f"/api/projects/{task['project_id']}", headers=_h(token)).status_code == 200
    assert client.delete(f"/api/tasks/{task['id']}", headers=_h(token)).status_code in (200, 400)


@pytest.mark.integration
def test_tc_int_090_a_missing_scope_is_403_and_audited(client, admin_tokens, no_builds):
    """TC-INT-090: each scope opens only its own routes: a read-only token cannot start or
    cancel, a projects-only token cannot read builds, a builds-only token cannot list projects."""
    session = admin_tokens["access_token"]
    read = _new(client, session, scopes=["builds:read"])
    projects = _new(client, session, scopes=["projects:read"])
    write = _new(client, session, scopes=["builds:write"])
    body = {"project_name": "tok-scope", "config": _git("https://git.example.com/scope.git")}

    r = client.post("/api/tasks", headers=_h(read["token"]), json=body)
    assert r.status_code == 403 and "builds:write" in r.json()["detail"]
    assert client.get("/api/history", headers=_h(projects["token"])).status_code == 403
    assert client.get("/api/projects", headers=_h(read["token"])).status_code == 403
    assert client.get("/api/tasks", headers=_h(write["token"])).status_code == 403
    assert client.get("/api/projects", headers=_h(projects["token"])).status_code == 200
    assert client.get("/api/history", headers=_h(read["token"])).status_code == 200
    assert client.post("/api/tasks", headers=_h(write["token"]), json=body).status_code == 201

    denied = _audit("api_token_denied", read["id"])
    assert [d[0] for d in denied] == ["denied", "denied"]
    assert json.loads(denied[0][2])["endpoint"] == "POST /api/tasks"


@pytest.mark.integration
def test_tc_int_091_management_routes_refuse_every_token(client, admin_tokens):
    """TC-INT-091: an admin's token with every scope still gets 403 from user, role,
    credential, notification, token and account routes: there is no admin scope."""
    session = admin_tokens["access_token"]
    token = _new(client, session)
    h = _h(token["token"])
    calls = [
        ("get", "/api/users"), ("get", "/api/users/roles/list"), ("post", "/api/users/roles"),
        ("get", "/api/settings/git-credentials"), ("post", "/api/settings/git-credentials"),
        ("get", "/api/tokens"), ("post", "/api/tokens"), ("delete", f"/api/tokens/{token['id']}"),
        ("get", "/auth/me"), ("post", "/auth/change-password"), ("post", "/auth/logout-all"),
        ("get", "/api/projects/1/notifications"), ("put", "/api/projects/1"), ("delete", "/api/projects/1"),
        ("get", "/api/monitoring/stats"), ("post", "/api/git/refs"),
    ]
    for method, path in calls:
        r = getattr(client, method)(path, headers=h) if method in ("get", "delete") else \
            getattr(client, method)(path, headers=h, json={})
        assert r.status_code == 403, (method, path, r.status_code)
        assert r.json()["detail"] == "API tokens cannot be used for this endpoint"
    # The token was not revoked by its own attempt.
    assert client.get("/api/history", headers=h).status_code == 200


@pytest.mark.integration
def test_tc_int_092_revoked_expired_and_forged_tokens_get_the_same_401(client, admin_tokens):
    """TC-INT-092: revoked, expired, unknown, bad-checksum and wrong-prefix tokens all get
    401 "Invalid or expired token"; the audit log records which it was."""
    session = admin_tokens["access_token"]
    revoked = _new(client, session, name="revoked")
    expired = _new(client, session, name="expired")
    assert client.get("/api/history", headers=_h(revoked["token"])).status_code == 200

    assert client.delete(f"/api/tokens/{revoked['id']}", headers=_h(session)).status_code == 204
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S.%f")
    _sql("UPDATE api_tokens SET expires_at = ? WHERE id = ?", past, expired["id"])
    # Same display prefix and a valid checksum, but not a token that was ever issued.
    head = expired["token"][:12] + generate_token()[12:-6]
    forged = head + _checksum(head)
    typo = revoked["token"][:-7] + ("A" if revoked["token"][-7] != "A" else "B") + revoked["token"][-6:]

    for bad in (revoked["token"], expired["token"], generate_token(), forged, typo, "pwt_short"):
        r = client.get("/api/history", headers=_h(bad))
        assert r.status_code == 401, bad
        assert r.json() == {"detail": "Invalid or expired token"}

    assert [a[1] for a in _audit("api_token_rejected", revoked["id"])] == ["revoked"]
    assert [a[1] for a in _audit("api_token_rejected", expired["id"])] == ["expired"]
    reasons = [r[0] for r in _sql("SELECT error_message FROM audit_logs WHERE action = 'api_token_rejected'"
                                  " AND resource_id IS NULL")]
    assert {"unknown", "malformed"} <= set(reasons)
    listed = {t["id"]: t["status"] for t in client.get("/api/tokens", headers=_h(session)).json()}
    assert (listed[revoked["id"]], listed[expired["id"]]) == ("revoked", "expired")


@pytest.mark.integration
def test_tc_int_093_the_owners_role_and_status_apply_on_every_request(client, admin_tokens, no_builds):
    """TC-INT-093: a token can never do more than its owner can now: a user's token with
    builds:write cannot start a build once the role loses task:create, sees only the
    user's own builds, and stops working (401) when the account is deactivated."""
    admin = admin_tokens["access_token"]
    session = _viewer(client, admin, "tok-owner")
    token = _new(client, session)["token"]
    body = {"project_name": "tok-owner", "config": _git("https://git.example.com/owner.git")}
    mine = client.post("/api/tasks", headers=_h(token), json=body)
    assert mine.status_code == 201
    other = client.post("/api/tasks", headers=_h(admin), json={**body, "project_name": "tok-admin-only"}).json()

    visible = {t["task_id"] for t in client.get("/api/history", headers=_h(token)).json()}
    assert mine.json()["id"] in visible and other["id"] not in visible
    assert client.get(f"/api/history/{other['id']}", headers=_h(token)).status_code == 403

    uid = next(u["id"] for u in client.get("/api/users", headers=_h(admin)).json() if u["username"] == "tok-owner")
    viewer_role = client.post("/api/users/roles", headers=_h(admin), json={
        "name": "tok-view-only", "display_name": "View only", "permission_codes": ["task:view_own", "history:view_own"]})
    assert viewer_role.status_code == 200, viewer_role.text
    assert client.put(f"/api/users/{uid}/role", json={"role_id": viewer_role.json()["id"]},
                      headers=_h(admin)).status_code == 200
    r = client.post("/api/tasks", headers=_h(token), json=body)
    assert r.status_code == 403 and "task:create" in r.json()["detail"]
    assert client.get("/api/history", headers=_h(token)).status_code == 200

    assert client.put(f"/api/users/{uid}/status", json={"is_active": False}, headers=_h(admin)).status_code == 200
    assert client.get("/api/history", headers=_h(token)).status_code == 401
    assert client.put(f"/api/users/{uid}/status", json={"is_active": True}, headers=_h(admin)).status_code == 200
    assert client.get("/api/history", headers=_h(token)).status_code == 200


@pytest.mark.integration
def test_tc_int_094_owners_and_admins_revoke_others_cannot(client, admin_tokens):
    """TC-INT-094: people list their own tokens; everyone's needs user:manage; someone
    else's token is 404 to revoke unless you may manage it; an admin's revocation is audited."""
    admin = admin_tokens["access_token"]
    alice = _viewer(client, admin, "tok-alice")
    bob = _viewer(client, admin, "tok-bob")
    a = _new(client, alice, name="alice-ci")
    b = _new(client, bob, name="bob-ci")

    assert [t["name"] for t in client.get("/api/tokens", headers=_h(alice)).json()] == ["alice-ci"]
    assert client.get("/api/tokens?everyone=true", headers=_h(alice)).status_code == 403
    everyone = client.get("/api/tokens?everyone=true", headers=_h(admin)).json()
    assert {(t["name"], t["owner"]) for t in everyone} >= {("alice-ci", "tok-alice"), ("bob-ci", "tok-bob")}
    assert all("token" not in t for t in everyone)

    assert client.delete(f"/api/tokens/{b['id']}", headers=_h(alice)).status_code == 404
    assert client.get("/api/history", headers=_h(b["token"])).status_code == 200
    assert client.delete(f"/api/tokens/{b['id']}", headers=_h(admin)).status_code == 204
    assert client.get("/api/history", headers=_h(b["token"])).status_code == 401
    assert client.delete(f"/api/tokens/{a['id']}", headers=_h(alice)).status_code == 204
    assert client.delete(f"/api/tokens/{a['id']}", headers=_h(alice)).status_code == 204
    [(status, _err, details, actor)] = _audit("api_token_revoke", b["id"])
    admin_id = client.get("/auth/me", headers=_h(admin)).json()["id"]
    assert status == "success" and json.loads(details)["owner"] == "tok-bob" and actor == admin_id
    assert len(_audit("api_token_revoke", a["id"])) == 1


@pytest.mark.integration
def test_tc_int_095_last_used_is_written_at_most_once_a_minute(client, admin_tokens):
    """TC-INT-095: the first use sets last_used_at; uses within a minute leave it; a use a
    minute later moves it."""
    session = admin_tokens["access_token"]
    t = _new(client, session)
    assert _sql("SELECT last_used_at FROM api_tokens WHERE id = ?", t["id"]) == [(None,)]
    client.get("/api/history", headers=_h(t["token"]))
    [(first,)] = _sql("SELECT last_used_at FROM api_tokens WHERE id = ?", t["id"])
    assert first is not None
    client.get("/api/history", headers=_h(t["token"]))
    assert _sql("SELECT last_used_at FROM api_tokens WHERE id = ?", t["id"]) == [(first,)]

    old = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S.%f")
    _sql("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", old, t["id"])
    client.get("/api/history", headers=_h(t["token"]))
    [(moved,)] = _sql("SELECT last_used_at FROM api_tokens WHERE id = ?", t["id"])
    assert moved > old


@pytest.mark.integration
def test_tc_int_096_a_token_downloads_artifacts_and_follows_logs(client, admin_tokens):
    """TC-INT-096: builds:read downloads a finished build's archive and opens the live log
    WebSocket with an Authorization header; without builds:read both are refused, and a
    token in the WebSocket URL is not accepted at all."""
    from app.services.paths import git_workspace

    session = admin_tokens["access_token"]
    read = _new(client, session, scopes=["builds:read"])
    other = _new(client, session, scopes=["projects:read"])
    task_id = _completed_task({"source_type": "git", "project_path": "", "output_dir": "dist"})
    out = git_workspace(task_id) / "dist"
    out.mkdir(parents=True)
    (out / "app.bin").write_bytes(b"built")

    r = client.get(f"/api/history/{task_id}/download", headers=_h(read["token"]))
    assert r.status_code == 200 and r.headers["content-type"] == "application/gzip"
    assert client.get(f"/api/history/{task_id}/download", headers=_h(other["token"])).status_code == 403
    # The browser's ticket route stays a console-session thing.
    assert client.post(f"/api/history/{task_id}/download-ticket", headers=_h(read["token"])).status_code == 403

    with client.websocket_connect("/ws/tasks", headers=_h(read["token"])) as ws:
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong"}
    for url, headers, code in (
        ("/ws/tasks", _h(other["token"]), 4403),
        ("/ws/tasks", _h(generate_token()), 4401),
        (f"/ws/tasks?token={read['token']}", {}, 4401),
    ):
        # A wrongly accepted socket answers the ping instead of hanging the test.
        try:
            with client.websocket_connect(url, headers=headers) as ws:
                ws.send_text("ping")
                ws.receive_json()
            outcome = "accepted"
        except WebSocketDisconnect as closed:
            outcome = closed.code
        assert outcome == code, url


@pytest.mark.integration
def test_tc_int_097_the_migration_adds_and_drops_the_table(tmp_path):
    """TC-INT-097: c9d4e1f7a2b6 creates api_tokens with its unique hash and owner index,
    and its downgrade removes them again."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'tok.db'}"
    _migrate(url)
    engine = create_engine(f"sqlite:///{tmp_path / 'tok.db'}")
    try:
        insp = inspect(engine)
        assert {c["name"] for c in insp.get_columns("api_tokens")} == {
            "id", "user_id", "name", "token_hash", "token_prefix", "scopes",
            "created_at", "expires_at", "last_used_at", "revoked_at"}
        assert [u["column_names"] for u in insp.get_unique_constraints("api_tokens")] == [["token_hash"]]
        assert [i["column_names"] for i in insp.get_indexes("api_tokens")] == [["user_id"]]
        assert insp.get_foreign_keys("api_tokens")[0]["options"].get("ondelete") == "CASCADE"
    finally:
        engine.dispose()
    _migrate(url, "b4e8d2f6a9c1", down=True)
    engine = create_engine(f"sqlite:///{tmp_path / 'tok.db'}")
    try:
        assert "api_tokens" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

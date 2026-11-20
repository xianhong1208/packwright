"""
What started a build and which commit it built, through the real app and database.
Source: app/api/routes/tasks (create_task, history), app/api/routes/projects (build_project),
        app/services/task_manager (create_task, set_commit), app/services/notifications,
        alembic/versions/b4e8d2f6a9c1_add_history_commit_and_trigger.py
"""

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text

from .test_notifications import SLACK, _add, _finish, _run, sent  # noqa: F401  (fixture)
from .test_projects import _build, _git, _h
from .test_schema_drift import _migrate

SHA = "3f2a9c1d4b5e6f708192a3b4c5d6e7f809a1b2c3"


def _history(client, token, task_id) -> dict:
    r = client.get(f"/api/history/{task_id}", headers=_h(token))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.integration
def test_tc_int_082_console_builds_say_console_whatever_the_body_says(client, admin_tokens, no_builds):
    """TC-INT-082: a trigger in the request body is ignored: a build from /api/tasks and
    a project's new version are both "console"; the commit is unknown until cloned."""
    token = admin_tokens["access_token"]
    r = client.post("/api/tasks", headers=_h(token), json={
        "project_name": "trig-body", "config": _git("https://git.example.com/trig.git"), "trigger": "push"})
    assert r.status_code == 201, r.text
    task = r.json()
    assert (task["trigger"], task["commit_sha"]) == ("console", None)
    assert _history(client, token, task["id"])["trigger"] == "console"

    r = client.post(f"/api/projects/{task['project_id']}/builds", json={"version": "1.0.0"}, headers=_h(token))
    assert r.status_code == 201 and r.json()["trigger"] == "console"

    listed = client.get("/api/history", headers=_h(token)).json()
    assert next(row for row in listed if row["task_id"] == task["id"])["trigger"] == "console"
    csv = client.get("/api/history/export", headers=_h(token)).text
    assert csv.splitlines()[0].endswith(",commit_sha,trigger")


@pytest.mark.integration
def test_tc_int_083_a_given_commit_is_stored_and_handed_to_the_build(client, admin_tokens, no_builds):
    """TC-INT-083: git_commit is kept on the build at once and passed to the build task;
    a malformed one or one for a Local source is 422 and builds nothing."""
    from app.api.routes import tasks as tasks_route

    token = admin_tokens["access_token"]
    task = client.post("/api/tasks", headers=_h(token), json={
        "project_name": "trig-sha", "config": _git("https://git.example.com/sha.git"), "git_commit": SHA}).json()
    assert task["commit_sha"] == SHA and _history(client, token, task["id"])["commit_sha"] == SHA
    assert tasks_route.start_build_task.await_args.args[2] == SHA

    calls = tasks_route.start_build_task.await_count
    for bad in ("3f2a9c1", SHA.upper(), "--upload-pack=x", "main"):
        r = client.post("/api/tasks", headers=_h(token), json={
            "project_name": "trig-sha", "config": _git("https://git.example.com/sha.git"), "git_commit": bad})
        assert r.status_code == 422, bad
    local = {"source_type": "local", "project_path": "/srv/x", "project_type": "backend_only"}
    r = client.post("/api/tasks", headers=_h(token), json={"project_name": "x", "config": local, "git_commit": SHA})
    assert r.status_code == 422
    assert tasks_route.start_build_task.await_count == calls


@pytest.mark.integration
def test_tc_int_084_set_commit_records_the_checkout(client, admin_tokens, no_builds):
    """TC-INT-084: the commit a build resolved is written to its row and its live state."""
    from app.services.task_manager import task_manager

    token = admin_tokens["access_token"]
    task = _build(client, token, "trig-set", _git("https://git.example.com/set.git"))
    _run(client, task_manager.set_commit, task["id"], SHA)

    assert _history(client, token, task["id"])["commit_sha"] == SHA
    assert client.get(f"/api/tasks/{task['id']}", headers=_h(token)).json()["commit_sha"] == SHA


@pytest.mark.integration
def test_tc_int_085_notifications_carry_trigger_and_commit(client, admin_tokens, no_builds, sent):  # noqa: F811
    """TC-INT-085: a finished build's message says how it started and which commit."""
    from app.services.notifications import notify_build
    from app.services.task_manager import task_manager

    token = admin_tokens["access_token"]
    task = _build(client, token, "trig-notify", _git("https://git.example.com/trig-notify.git"))
    _add(client, token, task["project_id"], "slack", SLACK)
    _add(client, token, task["project_id"], "webhook", "https://ci.example.com/hook")
    _run(client, task_manager.set_commit, task["id"], SHA)
    _run(client, _finish, task["id"], "completed", {"duration_seconds": 8})
    _run(client, notify_build, task["id"])

    by_url = dict(sent)
    assert "Started by admin (console), commit 3f2a9c1d4b5e" in by_url[SLACK]["text"]
    hook = by_url["https://ci.example.com/hook"]
    assert (hook["trigger"], hook["commit"]) == ("console", SHA)


@pytest.mark.integration
def test_tc_int_086_migration_keeps_existing_builds_as_console(tmp_path):
    """TC-INT-086: upgrading a database with builds gives them trigger "console" and no
    commit; a new row without a trigger also gets "console"; downgrade removes both
    columns and keeps the rows."""
    db = tmp_path / "m.db"
    url = f"sqlite+aiosqlite:///{db}"
    _migrate(url, "a7c3e9d1f2b8")
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO history (task_id, user_name, project_name, python_version, start_time, status)"
                    " VALUES ('old-1', 'mei', 'shop', '3.13', '2026-11-01 00:00:00', 'COMPLETED')")

    _migrate(url)
    engine = create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            assert conn.execute(text("SELECT trigger, commit_sha FROM history WHERE task_id='old-1'")).one() == ("console", None)
            conn.execute(text("INSERT INTO history (task_id, user_name, project_name, python_version, start_time, status)"
                              " VALUES ('new-1', 'mei', 'shop', '3.13', '2026-11-20 00:00:00', 'PENDING')"))
            assert conn.execute(text("SELECT trigger FROM history WHERE task_id='new-1'")).scalar() == "console"
    finally:
        engine.dispose()

    _migrate(url, "a7c3e9d1f2b8", down=True)
    engine = create_engine(f"sqlite:///{db}")
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("history")}
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM history")).scalar() == 2
    finally:
        engine.dispose()
    assert "trigger" not in columns and "commit_sha" not in columns

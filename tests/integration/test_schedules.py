"""
Scheduled builds through the real app and database: managing schedules, and what the
scheduler does when a run is due (build, skip as unchanged, skip an overlap, not make up
missed runs, fire once, turn off when the creator may no longer build).
Source: app/api/routes/schedules.py, app/services/schedules.py,
        alembic/versions/e6b2c8d4f1a3_add_project_schedules.py

The scheduler is driven by hand (``run_due(now)`` on the app's own event loop; the
loop itself is off in tests). ``git ls-remote`` is replaced and builds are filed but
never started, so nothing is cloned.
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from .test_api_tokens import _new as _new_api_token
from .test_artifact_download import _db_file
from .test_projects import _build, _git, _h, _viewer

REPO = "https://github.com/acme/scheduled.git"
SHA1 = "a1" * 20
SHA2 = "b2" * 20
UTC = timezone.utc


def _sql(query: str, *args):
    with sqlite3.connect(_db_file()) as con:
        return con.execute(query, args).fetchall()


def _stamp(dt: datetime) -> str:
    """How SQLAlchemy stores a UTC datetime in SQLite."""
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


@pytest.fixture(autouse=True)
def quiet_schedules():
    """Schedules other tests left on would also come due in this test's run_due."""
    _sql("UPDATE project_schedules SET enabled = 0, next_run_at = NULL")


@pytest.fixture
def sched_env(no_builds, mocker):
    """ls-remote answers ``env.sha``; started builds are recorded, not run."""
    from app.services import git_service, schedules

    class Env:
        sha = SHA1
        calls: list = []
        during_resolve = None

    env = Env()

    async def resolve(url, ref, ref_type, token, **kw):
        env.calls.append((url, ref, ref_type))
        if env.during_resolve is not None:
            await env.during_resolve()
        return env.sha

    mocker.patch.object(git_service, "resolve_ref", side_effect=resolve)
    env.start = mocker.patch.object(schedules, "start_build_task", mocker.AsyncMock())
    return env


def _project(client, token, name, url=REPO) -> int:
    pid = _build(client, token, name, _git(url))["project_id"]
    _settle(pid)
    return pid


def _settle(pid: int, status: str = "FAILED") -> None:
    """The builds no_builds filed never run; give them an end."""
    _sql("UPDATE history SET status = ?, end_time = start_time WHERE project_id = ? AND status IN ('PENDING','RUNNING')",
         status, pid)


def _schedule(client, token, pid, cron="* * * * *", **extra) -> dict:
    r = client.post(f"/api/projects/{pid}/schedules", headers=_h(token), json={"cron": cron, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _due(sid: int, ago: timedelta = timedelta(seconds=5)) -> datetime:
    """Make the schedule due ``ago`` before now; returns now."""
    now = datetime.now(UTC).replace(microsecond=0)
    _sql("UPDATE project_schedules SET next_run_at = ? WHERE id = ?", _stamp(now - ago), sid)
    return now


def _tick(client, now: datetime):
    from app.services import schedules

    return client.portal.call(schedules.run_due, now)


def _runs(client, token, pid, sid) -> list[dict]:
    r = client.get(f"/api/projects/{pid}/schedules/{sid}/runs", headers=_h(token))
    assert r.status_code == 200, r.text
    return r.json()


def _get(client, token, pid, sid) -> dict:
    return next(s for s in client.get(f"/api/projects/{pid}/schedules", headers=_h(token)).json() if s["id"] == sid)


@pytest.mark.integration
def test_tc_int_114_creating_a_schedule_validates_and_shows_the_next_run(client, admin_tokens, sched_env):
    """TC-INT-114: a schedule takes the project's branch and the server's zone by default and
    has a next run in the future; a preview lists the next 5 times; a bad expression, an
    unknown zone, a bad ref and a local-folder project are refused with 422; creating is audited."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "sched-create")
    before = datetime.now(UTC)
    s = _schedule(client, token, pid, cron="0 2 * * *", timezone="Asia/Taipei")
    assert s["ref"] == "main" and s["ref_type"] == "branch" and s["timezone"] == "Asia/Taipei"
    assert s["enabled"] and s["skip_unchanged"] and s["created_by"] == "admin" and s["description"]
    nxt = datetime.fromisoformat(s["next_run_at"].replace("Z", "+00:00"))
    assert nxt.tzinfo and before < nxt <= before + timedelta(days=1) and (nxt.hour, nxt.minute) == (18, 0)
    assert _sql("SELECT 1 FROM audit_logs WHERE action = 'schedule_create' AND resource_id = ?", str(s["id"]))

    d = _schedule(client, token, pid, cron="@hourly", ref="v1.0", ref_type="tag")
    assert d["timezone"] and d["ref"] == "v1.0" and d["ref_type"] == "tag"

    r = client.post(f"/api/projects/{pid}/schedules/preview", headers=_h(token),
                    json={"cron": "30 2 * * *", "timezone": "Europe/Berlin"})
    assert r.status_code == 200, r.text
    times = r.json()["next_runs"]
    assert len(times) == 5 and times == sorted(times) and r.json()["timezone"] == "Europe/Berlin"

    base = f"/api/projects/{pid}/schedules"
    for body, fragment in (
        ({"cron": "61 * * * *"}, "Invalid cron"),
        ({"cron": "0 0 * * * *"}, "5 fields"),
        ({"cron": "0 2 * * *", "timezone": "Mars/Base"}, "Unknown time zone"),
        ({"cron": "0 2 * * *", "ref": "--upload-pack=x"}, ""),
    ):
        r = client.post(base, headers=_h(token), json=body)
        assert r.status_code == 422 and fragment in r.text, (body, r.text)
        r = client.post(f"{base}/preview", headers=_h(token), json={"cron": body["cron"], "timezone": body.get("timezone")})
        assert r.status_code == (200 if "ref" in body else 422)

    # A project that builds from a folder cannot have one; one that stops building from
    # Git turns its schedules off at the next run.
    _sql("UPDATE projects SET source_type = 'local' WHERE id = ?", pid)
    r = client.post(base, headers=_h(token), json={"cron": "0 2 * * *"})
    assert r.status_code == 422 and "Git URL" in r.text
    [run] = _tick(client, _due(s["id"]))
    assert run.result == "failed" and "no longer builds from a Git URL" in run.reason
    assert not _get(client, token, pid, s["id"])["enabled"] and not sched_env.start.called


@pytest.mark.integration
def test_tc_int_115_only_the_creator_or_a_project_manager_manages_schedules(client, admin_tokens, sched_env):
    """TC-INT-115: another builder sees the schedules and their runs but cannot create,
    change or delete one; an API token (every scope) reaches none of the schedule routes."""
    admin = admin_tokens["access_token"]
    pid = _project(client, admin, "sched-perms")
    s = _schedule(client, admin, pid)
    other = _viewer(client, admin, "sched-viewer")
    base = f"/api/projects/{pid}/schedules"
    listed = client.get(base, headers=_h(other))
    assert listed.status_code == 200 and listed.json()[0]["can_edit"] is False
    assert client.get(f"{base}/{s['id']}/runs", headers=_h(other)).status_code == 200
    assert client.post(base, headers=_h(other), json={"cron": "* * * * *"}).status_code == 403
    assert client.patch(f"{base}/{s['id']}", headers=_h(other), json={"enabled": False}).status_code == 403
    assert client.delete(f"{base}/{s['id']}", headers=_h(other)).status_code == 403

    api = _new_api_token(client, admin)["token"]
    assert client.get(base, headers=_h(api)).status_code == 403
    assert client.post(base, headers=_h(api), json={"cron": "* * * * *"}).status_code == 403
    assert client.patch(f"{base}/{s['id']}", headers=_h(api), json={"enabled": False}).status_code == 403
    assert client.post(f"{base}/preview", headers=_h(api), json={"cron": "* * * * *"}).status_code == 403
    assert client.delete(f"{base}/{s['id']}", headers=_h(api)).status_code == 403
    assert client.get(base, headers=_h(admin)).json()[0]["enabled"]


@pytest.mark.integration
def test_tc_int_116_a_due_run_builds_the_resolved_commit_as_the_creator(client, admin_tokens, sched_env):
    """TC-INT-116: a due run resolves the branch, files a build of exactly that commit with
    trigger schedule as the schedule's creator, starts it with that commit, records "built",
    and counts the next run from now."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "sched-build")
    s = _schedule(client, token, pid, cron="*/5 * * * *", timezone="UTC")
    now = _due(s["id"])
    [run] = _tick(client, now)
    assert run.result == "built" and run.commit_sha == SHA1
    item = client.get(f"/api/history/{run.task_id}", headers=_h(token)).json()
    assert item["trigger"] == "schedule" and item["commit_sha"] == SHA1 and item["user_name"] == "admin"
    assert item["project_id"] == pid and item["config"]["git_ref"] == "main"
    assert sched_env.calls[-1] == (REPO, "main", "branch")
    args = sched_env.start.call_args.args
    assert args[0] == run.task_id and args[2] == SHA1
    listed = _get(client, token, pid, s["id"])
    nxt = datetime.fromisoformat(listed["next_run_at"].replace("Z", "+00:00"))
    assert now < nxt <= now + timedelta(minutes=5) and nxt.minute % 5 == 0
    assert listed["last_run"]["result"] == "built" and listed["last_run"]["task_id"] == run.task_id
    [r] = _runs(client, token, pid, s["id"])
    assert r["result"] == "built" and r["commit_sha"] == SHA1
    # Not due yet: nothing happens.
    assert _tick(client, now + timedelta(seconds=1)) == []


@pytest.mark.integration
def test_tc_int_117_skip_unchanged_compares_commit_and_settings(client, admin_tokens, sched_env):
    """TC-INT-117: after a successful build, a run at the same commit with the same settings
    is skipped as unchanged (naming that build); a new commit builds; changed settings build;
    with skip_unchanged off the same commit builds again; a failed build never counts."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "sched-unchanged")
    s = _schedule(client, token, pid)
    [first] = _tick(client, _due(s["id"]))
    assert first.result == "built"
    _settle(pid, "COMPLETED")

    [same] = _tick(client, _due(s["id"]))
    assert same.result == "skipped" and same.reason.startswith("unchanged") and same.task_id == first.task_id

    sched_env.sha = SHA2
    [moved] = _tick(client, _due(s["id"]))
    assert moved.result == "built" and moved.commit_sha == SHA2
    _settle(pid, "COMPLETED")
    [again] = _tick(client, _due(s["id"]))
    assert again.result == "skipped" and "unchanged" in again.reason

    r = client.put(f"/api/projects/{pid}", headers=_h(token), json={"config": _git(REPO, generate_report=True)})
    assert r.status_code == 200, r.text
    [changed] = _tick(client, _due(s["id"]))
    assert changed.result == "built"
    _settle(pid, "FAILED")
    [after_fail] = _tick(client, _due(s["id"]))
    # The last *successful* build has the old settings: the failed one does not count.
    assert after_fail.result == "built"
    _settle(pid, "COMPLETED")

    assert client.patch(f"/api/projects/{pid}/schedules/{s['id']}", headers=_h(token),
                        json={"skip_unchanged": False}).status_code == 200
    [forced] = _tick(client, _due(s["id"]))
    assert forced.result == "built"


@pytest.mark.integration
def test_tc_int_118_a_run_never_overlaps_a_build_of_the_project(client, admin_tokens, sched_env):
    """TC-INT-118: while a build of the project is queued or running, a due run is skipped as
    overlap naming that build, and nothing is resolved or filed; once it ends the next run builds;
    a build filed while the branch is being read also makes the run skip."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "sched-overlap")
    busy = _build(client, token, "sched-overlap", _git(REPO))["id"]
    _sql("UPDATE history SET status = 'RUNNING' WHERE task_id = ?", busy)
    s = _schedule(client, token, pid)
    calls = len(sched_env.calls)
    [run] = _tick(client, _due(s["id"]))
    assert run.result == "skipped" and run.reason.startswith("overlap") and run.task_id == busy
    assert len(sched_env.calls) == calls and not sched_env.start.called
    _settle(pid, "COMPLETED")
    [run] = _tick(client, _due(s["id"]))
    assert run.result == "built"

    # A build filed while the branch was being read (a console build, a push) also wins.
    _settle(pid, "COMPLETED")
    sched_env.start.reset_mock()

    async def someone_builds():
        from sqlalchemy import text

        from app.database import async_session

        async with async_session() as db:
            await db.execute(text("UPDATE history SET status = 'RUNNING' WHERE task_id = :t"), {"t": busy})
            await db.commit()

    sched_env.during_resolve = someone_builds
    sched_env.sha = SHA2
    [run] = _tick(client, _due(s["id"]))
    assert run.result == "skipped" and run.reason.startswith("overlap") and run.task_id == busy
    assert not sched_env.start.called


@pytest.mark.integration
def test_tc_int_119_missed_runs_are_not_made_up(client, admin_tokens, sched_env):
    """TC-INT-119: a run found long overdue (Packwright was down for many slots) is recorded
    once as missed, builds nothing, and the next run is the next slot after now; the run
    after that builds normally."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "sched-missed")
    s = _schedule(client, token, pid)
    now = _due(s["id"], ago=timedelta(minutes=10))
    runs = _tick(client, now)
    assert [r.result for r in runs] == ["skipped"] and runs[0].reason.startswith("missed")
    assert not sched_env.start.called
    nxt = datetime.fromisoformat(_get(client, token, pid, s["id"])["next_run_at"].replace("Z", "+00:00"))
    assert now < nxt <= now + timedelta(minutes=1)
    assert _tick(client, now + timedelta(seconds=1)) == []
    [run] = _tick(client, nxt + timedelta(seconds=3))
    assert run.result == "built"
    assert len(_runs(client, token, pid, s["id"])) == 2


@pytest.mark.integration
def test_tc_int_120_a_run_fires_once_when_two_loops_tick_together(client, admin_tokens, sched_env):
    """TC-INT-120: two scheduler passes at the same moment file one build; a claim made with
    a stale next-run time, or for a schedule turned off since it was read, is refused."""
    from app.database import async_session
    from app.models.schedule import ProjectSchedule
    from app.services import schedules

    token = admin_tokens["access_token"]
    pid = _project(client, token, "sched-once")
    s = _schedule(client, token, pid)
    now = _due(s["id"])

    async def both():
        return await asyncio.gather(schedules.run_due(now), schedules.run_due(now))

    a, b = client.portal.call(both)
    assert sorted(len(x) for x in (a, b)) == [0, 1]
    assert _sql("SELECT COUNT(*) FROM history WHERE project_id = ? AND \"trigger\" = 'schedule'", pid) == [(1,)]
    assert len(_runs(client, token, pid, s["id"])) == 1

    async def stale():
        async with async_session() as db:
            row = await db.get(ProjectSchedule, s["id"])
            row.next_run_at = now - timedelta(minutes=1)  # what a slower loop read earlier
            db.expunge(row)
            return await schedules.claim(db, row, now)

    assert client.portal.call(stale) is False

    # Read as on, turned off by a person before the claim: not run either.
    now = _due(s["id"])

    async def turned_off_meanwhile():
        async with async_session() as db:
            row = await db.get(ProjectSchedule, s["id"])
            db.expunge(row)
        _sql("UPDATE project_schedules SET enabled = 0 WHERE id = ?", s["id"])
        async with async_session() as db:
            return await schedules.claim(db, row, now)

    assert client.portal.call(turned_off_meanwhile) is False


@pytest.mark.integration
def test_tc_int_121_a_creator_who_may_no_longer_build_turns_the_schedule_off(client, admin_tokens, sched_env):
    """TC-INT-121: once the creator is deactivated the next run builds nothing, turns the
    schedule off with the reason (audited) and has no next run; turning it on is 409 until
    someone takes it over, after which runs build as that person."""
    admin = admin_tokens["access_token"]
    owner = _viewer(client, admin, "sched-owner")
    pid = _project(client, owner, "sched-owned")
    s = _schedule(client, owner, pid)
    uid = next(u["id"] for u in client.get("/api/users", headers=_h(admin)).json() if u["username"] == "sched-owner")
    assert client.put(f"/api/users/{uid}/status", json={"is_active": False}, headers=_h(admin)).status_code == 200

    [run] = _tick(client, _due(s["id"]))
    assert run.result == "failed" and "deactivated" in run.reason and not sched_env.start.called
    listed = _get(client, admin, pid, s["id"])
    assert not listed["enabled"] and "sched-owner's account is deactivated" in listed["disabled_reason"]
    assert listed["next_run_at"] is None
    assert _sql("SELECT 1 FROM audit_logs WHERE action = 'schedule_disabled' AND resource_id = ?", str(s["id"]))

    url = f"/api/projects/{pid}/schedules/{s['id']}"
    r = client.patch(url, headers=_h(admin), json={"enabled": True})
    assert r.status_code == 409 and "Take it over" in r.json()["detail"]
    r = client.patch(url, headers=_h(admin), json={"enabled": True, "take_over": True})
    assert r.status_code == 200 and r.json()["enabled"] and r.json()["created_by"] == "admin"
    assert r.json()["next_run_at"] and r.json()["disabled_reason"] is None
    [run] = _tick(client, _due(s["id"]))
    assert run.result == "built"
    assert client.get(f"/api/history/{run.task_id}", headers=_h(admin)).json()["user_name"] == "admin"


@pytest.mark.integration
def test_tc_int_122_a_deleted_creator_and_a_role_without_task_create(client, admin_tokens, sched_env):
    """TC-INT-122: deleting the creator's account keeps the schedule (created_by_id NULL) and
    its next run turns it off with "no longer has an account"; a creator moved to a role
    without task:create turns it off with that reason."""
    admin = admin_tokens["access_token"]
    owner = _viewer(client, admin, "sched-gone")
    pid = _project(client, owner, "sched-gone-project")
    s = _schedule(client, owner, pid)
    with sqlite3.connect(_db_file()) as con:
        con.execute("PRAGMA foreign_keys=ON")
        uid = con.execute("SELECT id FROM users WHERE username = 'sched-gone'").fetchone()[0]
        for table in ("refresh_tokens", "login_history"):
            con.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
        con.execute("DELETE FROM users WHERE id = ?", (uid,))
    assert _sql("SELECT created_by_id, created_by FROM project_schedules WHERE id = ?", s["id"]) == [(None, "sched-gone")]
    [run] = _tick(client, _due(s["id"]))
    assert run.result == "failed" and "no longer has an account" in run.reason
    assert not _get(client, admin, pid, s["id"])["enabled"]

    reader = _viewer(client, admin, "sched-reader")
    pid2 = _project(client, reader, "sched-reader-project")
    s2 = _schedule(client, reader, pid2)
    r = client.post("/api/users/roles", headers=_h(admin), json={
        "name": "sched-readonly", "display_name": "Reader", "permission_codes": ["history:view_own"]})
    assert r.status_code == 200, r.text
    uid = next(u["id"] for u in client.get("/api/users", headers=_h(admin)).json() if u["username"] == "sched-reader")
    assert client.put(f"/api/users/{uid}/role", headers=_h(admin), json={"role_id": r.json()["id"]}).status_code == 200
    [run] = _tick(client, _due(s2["id"]))
    assert run.result == "failed" and "task:create" in run.reason
    assert not sched_env.start.called


@pytest.mark.integration
def test_tc_int_123_editing_turning_off_bounded_runs_and_project_delete(client, admin_tokens, sched_env):
    """TC-INT-123: changing the expression recomputes the next run; turning a schedule off
    clears it and a due-looking off schedule never runs; a schedule keeps its newest 50
    runs; deleting a schedule or its project removes its runs; changes are audited."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "sched-edit")
    s = _schedule(client, token, pid, cron="0 2 * * *", timezone="UTC")
    url = f"/api/projects/{pid}/schedules/{s['id']}"
    r = client.patch(url, headers=_h(token), json={"cron": "0 3 * * *"})
    assert r.status_code == 200 and r.json()["cron"] == "0 3 * * *" and "T03:00:00" in r.json()["next_run_at"]
    assert client.patch(url, headers=_h(token), json={"cron": "nope"}).status_code == 422
    assert _sql("SELECT 1 FROM audit_logs WHERE action = 'schedule_update' AND resource_id = ?", str(s["id"]))

    r = client.patch(url, headers=_h(token), json={"enabled": False})
    assert r.status_code == 200 and not r.json()["enabled"] and r.json()["next_run_at"] is None
    assert r.json()["disabled_reason"] is None
    now = _due(s["id"])
    _sql("UPDATE project_schedules SET enabled = 0 WHERE id = ?", s["id"])
    assert _tick(client, now) == []
    assert client.patch(url, headers=_h(token), json={"enabled": True}).json()["next_run_at"]

    # 55 runs, each found by a busy project: only the newest 50 are kept.
    busy = _build(client, token, "sched-edit", _git(REPO))["id"]
    for _ in range(55):
        _tick(client, _due(s["id"]))
    runs = _runs(client, token, pid, s["id"])
    assert len(runs) == 50 and all(r["task_id"] == busy for r in runs)
    assert _sql("SELECT COUNT(*) FROM schedule_runs WHERE schedule_id = ?", s["id"]) == [(50,)]

    other = _schedule(client, token, pid)
    _tick(client, _due(other["id"]))
    assert client.delete(f"/api/projects/{pid}/schedules/{other['id']}", headers=_h(token)).status_code == 204
    assert _sql("SELECT COUNT(*) FROM schedule_runs WHERE schedule_id = ?", other["id"]) == [(0,)]
    assert _sql("SELECT 1 FROM audit_logs WHERE action = 'schedule_delete' AND resource_id = ?", str(other["id"]))

    _settle(pid)
    assert client.delete(f"/api/projects/{pid}", headers=_h(token)).status_code == 204
    assert _sql("SELECT COUNT(*) FROM project_schedules WHERE project_id = ?", pid) == [(0,)]
    assert _sql("SELECT COUNT(*) FROM schedule_runs WHERE schedule_id = ?", s["id"]) == [(0,)]

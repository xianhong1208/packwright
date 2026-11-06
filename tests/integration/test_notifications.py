"""
Project notifications through the real application and database.
Source: app/api/routes/notifications.py, app/services/notifications.notify_build

Nothing leaves the machine: delivery is replaced, and what is under test is who
may change a project's destinations, that a URL is stored encrypted and never
returned, and which destinations a finished build reaches with what.
"""

import pytest
from sqlalchemy import select, update

from .test_projects import _build, _git, _h, _viewer

SLACK = "https://hooks.slack.com/services/T000/B000/secretTAIL"
DISCORD = "https://discord.com/api/webhooks/1/discordTAIL"


@pytest.fixture
def sent(mocker):
    """Every delivery: (url, body). All succeed."""
    from app.services import notifications

    calls: list[tuple[str, dict]] = []

    async def fake(url, body, **_):
        calls.append((url, body))
        return True, None

    mocker.patch.object(notifications, "deliver", side_effect=fake)
    return calls


def _project(client, token, name) -> int:
    return _build(client, token, name, _git(f"https://git.example.com/{name}.git"))["project_id"]


def _add(client, token, project_id, kind, url, **flags):
    return client.post(f"/api/projects/{project_id}/notifications", json={"kind": kind, "url": url, **flags}, headers=_h(token))


def _run(client, fn, *args):
    """Run app code on the application's own event loop (its DB engine lives there)."""
    return client.portal.call(fn, *args)


async def _finish(task_id: str, status: str, result: dict) -> None:
    from app.database import async_session
    from app.models.task import Task

    async with async_session() as db:
        await db.execute(update(Task).where(Task.task_id == task_id).values(status=status, result=result))
        await db.commit()


async def _stored(project_id: int) -> list:
    from app.database import async_session
    from app.models.notification import ProjectNotification

    async with async_session() as db:
        rows = await db.execute(select(ProjectNotification).where(ProjectNotification.project_id == project_id))
        return list(rows.scalars().all())


@pytest.mark.integration
def test_tc_int_056_url_is_stored_encrypted_and_never_returned(client, admin_tokens, no_builds):
    """TC-INT-056: the response and the list carry a hint only; the row holds ciphertext."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "notify-secret")

    r = _add(client, token, pid, "slack", SLACK)
    assert r.status_code == 201, r.text
    assert "secretTAIL" not in r.text and "T000" not in r.text
    assert r.json()["url_hint"] == "hooks.slack.com …TAIL"
    assert (r.json()["on_failed"], r.json()["on_passed"]) == (True, True)
    listed = client.get(f"/api/projects/{pid}/notifications", headers=_h(token))
    assert "T000" not in listed.text and len(listed.json()) == 1

    row = _run(client, _stored, pid)[0]
    assert "T000" not in row.url_encrypted
    from app.services.crypto import decrypt_secret
    assert decrypt_secret(row.url_encrypted) == SLACK


@pytest.mark.integration
def test_tc_int_057_everyone_sees_only_owners_change(client, admin_tokens, no_builds):
    """TC-INT-057: a builder who did not create the project sees the list but may not
    add, change, test or delete; a bad URL is refused with the reason."""
    admin = admin_tokens["access_token"]
    pid = _project(client, admin, "notify-owner")
    nid = _add(client, admin, pid, "discord", DISCORD).json()["id"]
    viewer = _viewer(client, admin, "notify-viewer")

    assert client.get(f"/api/projects/{pid}/notifications", headers=_h(viewer)).status_code == 200
    assert _add(client, viewer, pid, "webhook", "https://example.com/x").status_code == 403
    base = f"/api/projects/{pid}/notifications/{nid}"
    assert client.patch(base, json={"on_passed": False}, headers=_h(viewer)).status_code == 403
    assert client.post(f"{base}/test", headers=_h(viewer)).status_code == 403
    assert client.delete(base, headers=_h(viewer)).status_code == 403

    bad = _add(client, admin, pid, "discord", "https://discord.com/channels/1/2")
    assert bad.status_code == 422 and "not a Discord incoming webhook" in bad.json()["detail"]


@pytest.mark.integration
def test_tc_int_058_change_test_and_delete(client, admin_tokens, no_builds, sent):
    """TC-INT-058: switches change alone; a new URL replaces the old and clears its
    last delivery; a test is sent to the stored URL and recorded; delete removes it.
    Another project's id in the path finds nothing."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "notify-edit")
    other = _project(client, token, "notify-edit-other")
    nid = _add(client, token, pid, "slack", SLACK).json()["id"]
    base = f"/api/projects/{pid}/notifications/{nid}"

    r = client.post(f"{base}/test", headers=_h(token))
    assert r.json() == {"ok": True, "error": None}
    assert sent[-1][0] == SLACK and "Test message from Packwright for notify-edit" in sent[-1][1]["text"]
    assert client.get(f"/api/projects/{pid}/notifications", headers=_h(token)).json()[0]["last_ok"] is True

    r = client.patch(base, json={"on_passed": False}, headers=_h(token))
    assert (r.json()["on_passed"], r.json()["on_failed"], r.json()["url_hint"]) == (False, True, "hooks.slack.com …TAIL")
    r = client.patch(base, json={"url": "https://hooks.slack.com/services/T9/B9/newURL"}, headers=_h(token))
    assert r.json()["url_hint"] == "hooks.slack.com …wURL" and r.json()["last_ok"] is None

    assert client.patch(f"/api/projects/{other}/notifications/{nid}", json={"on_failed": False}, headers=_h(token)).status_code == 404
    assert client.delete(base, headers=_h(token)).status_code == 204
    assert client.get(f"/api/projects/{pid}/notifications", headers=_h(token)).json() == []


@pytest.mark.integration
def test_tc_int_059_a_finished_build_reaches_the_destinations_that_want_it(client, admin_tokens, no_builds, sent):
    """TC-INT-059: a failed build goes to destinations with on_failed, with its
    diagnosis; a passed one to those with on_passed; a cancelled one nowhere."""
    from app.services.notifications import notify_build

    token = admin_tokens["access_token"]
    task = _build(client, token, "notify-run", _git("https://git.example.com/notify-run.git", version="3.1.0"))
    pid = task["project_id"]
    _add(client, token, pid, "slack", SLACK, on_passed=False)
    _add(client, token, pid, "webhook", "https://ci.example.com/hook", on_failed=False)

    diagnosis = [{"problem": "Nuitka is not installed", "suggestion": "Run setup_nuitka_venvs.sh"}]
    _run(client, _finish, task["id"], "failed", {"diagnosis": diagnosis, "duration_seconds": 61})
    _run(client, notify_build, task["id"])
    assert [url for url, _ in sent] == [SLACK]
    assert sent[0][1]["text"].splitlines()[:3] == [
        "*notify-run 3.1.0 failed*", "Nuitka is not installed", "Run setup_nuitka_venvs.sh",
    ]

    sent.clear()
    _run(client, _finish, task["id"], "completed", {"duration_seconds": 61})
    _run(client, notify_build, task["id"])
    assert [url for url, _ in sent] == ["https://ci.example.com/hook"]
    assert sent[0][1]["event"] == "passed" and sent[0][1]["version"] == "3.1.0"

    sent.clear()
    _run(client, _finish, task["id"], "cancelled", {})
    _run(client, notify_build, task["id"])
    assert sent == []


@pytest.mark.integration
def test_tc_int_060_a_dead_webhook_is_recorded_not_raised(client, admin_tokens, no_builds, mocker):
    """TC-INT-060: a delivery that fails is kept on the destination for the page to
    show; nothing is raised into the build."""
    from app.services import notifications

    mocker.patch.object(notifications, "deliver", mocker.AsyncMock(return_value=(False, "hooks.slack.com answered HTTP 404")))
    token = admin_tokens["access_token"]
    task = _build(client, token, "notify-dead", _git("https://git.example.com/notify-dead.git"))
    _add(client, token, task["project_id"], "slack", SLACK)

    _run(client, _finish, task["id"], "failed", {})
    _run(client, notifications.notify_build, task["id"])
    row = client.get(f"/api/projects/{task['project_id']}/notifications", headers=_h(token)).json()[0]
    assert (row["last_ok"], row["last_error"]) == (False, "hooks.slack.com answered HTTP 404")
    assert row["last_sent_at"] is not None


@pytest.mark.integration
def test_tc_int_061_deleting_a_project_deletes_its_destinations(client, admin_tokens, no_builds):
    """TC-INT-061: no orphaned webhook URLs are left behind a deleted project."""
    token = admin_tokens["access_token"]
    pid = _project(client, token, "notify-gone")
    _add(client, token, pid, "slack", SLACK)

    assert client.delete(f"/api/projects/{pid}", headers=_h(token)).status_code == 204
    assert _run(client, _stored, pid) == []

"""
Projects: filing builds, building new versions, and who may change what.
Source: app/api/routes/projects.py, app/api/routes/tasks.py (create_task), app/services/projects.py

Builds are started in the background; here that is replaced, so nothing is cloned
or compiled — what is under test is which project a build lands in and with what.
"""

import pytest

from .conftest import login


def _git(url: str, **extra) -> dict:
    return {"source_type": "git", "git_url": url, "git_ref": "main", "project_type": "backend_only", **extra}


@pytest.fixture
def no_builds(mocker):
    from app.api.routes import projects as projects_route
    from app.api.routes import tasks as tasks_route

    mocker.patch.object(tasks_route, "start_build_task", mocker.AsyncMock())
    mocker.patch.object(projects_route, "start_build_task", mocker.AsyncMock())


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _build(client, token, name, config) -> dict:
    r = client.post("/api/tasks", json={"project_name": name, "config": config}, headers=_h(token))
    assert r.status_code == 201, r.text
    return r.json()


def _viewer(client, admin_token: str, name: str) -> str:
    """A newly registered, activated account with the default 'user' role."""
    assert client.post("/auth/register", json={"username": name, "password": "viewer-pass-123"}).status_code == 201
    uid = next(u["id"] for u in client.get("/api/users", headers=_h(admin_token)).json() if u["username"] == name)
    client.put(f"/api/users/{uid}/status", json={"is_active": True}, headers=_h(admin_token))
    return login(client, name, "viewer-pass-123")["access_token"]


@pytest.mark.integration
def test_tc_int_052_builds_are_filed_by_name_and_source(client, admin_tokens, no_builds):
    """TC-INT-052: the same name and source is one project; the same name from another
    source becomes its own, numbered, project."""
    token = admin_tokens["access_token"]
    a = _build(client, token, "filing", _git("https://git.example.com/filing.git"))
    b = _build(client, token, "filing", _git("https://git.example.com/filing.git"))
    c = _build(client, token, "filing", _git("https://git.example.com/other.git"))

    assert a["project_id"] == b["project_id"] != c["project_id"]
    assert c["project_name"] == "filing (2)"
    listed = {p["name"]: p for p in client.get("/api/projects", headers=_h(token)).json()}
    assert listed["filing"]["builds"] == 2 and listed["filing (2)"]["builds"] == 1


@pytest.mark.integration
def test_tc_int_053_a_new_version_starts_from_the_project_defaults(client, admin_tokens, no_builds):
    """TC-INT-053: building a version uses the project's settings, this build's changes
    on top, and records the version."""
    token = admin_tokens["access_token"]
    first = _build(client, token, "defaults", _git("https://git.example.com/defaults.git", pack_mode="full", onefile=False))

    r = client.post(f"/api/projects/{first['project_id']}/builds",
                    json={"version": "2.0.0", "overrides": {"git_ref": "v2.0.0", "git_ref_type": "tag", "docker_enabled": True}},
                    headers=_h(token))
    assert r.status_code == 201, r.text
    config = r.json()["config"]

    assert (config["pack_mode"], config["onefile"]) == ("full", False)  # from the project
    assert (config["git_ref"], config["docker_enabled"], config["version"]) == ("v2.0.0", True, "2.0.0")
    detail = client.get(f"/api/projects/{first['project_id']}", headers=_h(token)).json()
    assert [b["version"] for b in detail["history"]] == ["2.0.0", None]


@pytest.mark.integration
def test_tc_int_054_everyone_may_build_only_owners_change(client, admin_tokens, no_builds):
    """TC-INT-054: anyone who may build sees a project and builds a version of it;
    changing or deleting it is for its creator and project managers. Deleting keeps
    the builds, unfiled."""
    admin = admin_tokens["access_token"]
    viewer = _viewer(client, admin, "proj-viewer")
    pid = _build(client, admin, "shared", _git("https://git.example.com/shared.git"))["project_id"]

    assert any(p["id"] == pid and not p["can_edit"] for p in client.get("/api/projects", headers=_h(viewer)).json())
    built = client.post(f"/api/projects/{pid}/builds", json={"version": "1.0.1"}, headers=_h(viewer))
    assert built.status_code == 201
    assert client.put(f"/api/projects/{pid}", json={"name": "taken-over"}, headers=_h(viewer)).status_code == 403
    assert client.delete(f"/api/projects/{pid}", headers=_h(viewer)).status_code == 403

    assert client.delete(f"/api/projects/{pid}", headers=_h(admin)).status_code == 204
    kept = client.get(f"/api/history/{built.json()['id']}", headers=_h(admin))
    assert kept.status_code == 200 and kept.json()["project_id"] is None


@pytest.mark.integration
def test_tc_int_055_renaming_keeps_builds_findable(client, admin_tokens, no_builds):
    """TC-INT-055: a renamed project's builds carry the new name; a name another
    project has is refused."""
    token = admin_tokens["access_token"]
    one = _build(client, token, "rename-me", _git("https://git.example.com/rename.git"))
    _build(client, token, "already-here", _git("https://git.example.com/here.git"))

    assert client.put(f"/api/projects/{one['project_id']}", json={"name": "already-here"}, headers=_h(token)).status_code == 409
    assert client.put(f"/api/projects/{one['project_id']}", json={"name": "renamed"}, headers=_h(token)).status_code == 200
    assert client.get(f"/api/history/{one['id']}", headers=_h(token)).json()["project_name"] == "renamed"

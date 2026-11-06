"""
Finding earlier builds of the version about to be built.
Source: app/api/routes/tasks (builds_of_version), app/models/task (history.version)

New build asks before building a version that already passed; the lookup must
match project and version exactly and respect who may see whose builds.
"""

import os
import sqlite3
import uuid

import pytest

from .conftest import login


def _insert(project: str, version: str | None, status: str, user: str = "admin", start: str = "2026-11-05 00:00:00") -> str:
    task_id = str(uuid.uuid4())
    db = os.environ["DATABASE_URL"].split(":///", 1)[1]
    with sqlite3.connect(db) as con:
        con.execute(
            "INSERT INTO history (task_id, user_name, project_name, python_version, start_time, status, config, version)"
            " VALUES (?, ?, ?, '3.13', ?, ?, '{}', ?)",
            (task_id, user, project, start, status, version),
        )
    return task_id


def _lookup(client, token: str, project: str, version: str) -> list[dict]:
    r = client.get("/api/history/versions", params={"project_name": project, "version": version},
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.integration
def test_tc_int_046_same_project_and_version_newest_first(client, admin_tokens):
    """TC-INT-046: only builds of this project at this version, newest first."""
    older = _insert("shop", "1.2.0", "COMPLETED", start="2026-11-01 00:00:00")
    newer = _insert("shop", "1.2.0", "FAILED", start="2026-11-04 00:00:00")
    _insert("shop", "1.3.0", "COMPLETED")
    _insert("shop-web", "1.2.0", "COMPLETED")
    _insert("shop", None, "COMPLETED")

    found = _lookup(client, admin_tokens["access_token"], "shop", "1.2.0")

    assert [b["task_id"] for b in found] == [newer, older]
    assert [b["status"] for b in found] == ["failed", "completed"]


@pytest.mark.integration
def test_tc_int_047_view_own_sees_only_their_builds(client, admin_tokens):
    """TC-INT-047: someone limited to their own history is not told about others' builds."""
    r = client.post("/auth/register", json={"username": "ver-viewer", "password": "viewer-pass-123"})
    assert r.status_code == 201, r.text
    users = client.get("/api/users", headers={"Authorization": f"Bearer {admin_tokens['access_token']}"}).json()
    viewer_id = next(u["id"] for u in users if u["username"] == "ver-viewer")
    client.put(f"/api/users/{viewer_id}/status", json={"is_active": True},
               headers={"Authorization": f"Bearer {admin_tokens['access_token']}"})
    viewer = login(client, "ver-viewer", "viewer-pass-123")["access_token"]

    _insert("report", "3.0.0", "COMPLETED", user="admin")
    mine = _insert("report", "3.0.0", "COMPLETED", user="ver-viewer")

    assert [b["task_id"] for b in _lookup(client, viewer, "report", "3.0.0")] == [mine]
    assert len(_lookup(client, admin_tokens["access_token"], "report", "3.0.0")) == 2

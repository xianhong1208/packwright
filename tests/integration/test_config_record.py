"""
A setting a build decides is saved for the next build.
Source: app/services/task_manager.py (record_config_value)

Docker volumes found by the smoke run prefill the Volumes field: they are saved in
the build's settings, and in the project's while the project has none.
"""

import pytest

from .test_projects import _build, _git, _h


def _record(client, task_id: str, value: str) -> None:
    from app.database import async_session
    from app.services.task_manager import task_manager

    async def run():
        async with async_session() as db:
            await task_manager.record_config_value(task_id, "docker_volumes", value, db)

    client.portal.call(run)


@pytest.mark.integration
def test_tc_int_077_detected_volumes_prefill_the_next_build(client, admin_tokens, no_builds):
    """TC-INT-077: the value lands in the build and in the project, but never replaces the project's own."""
    token = admin_tokens["access_token"]
    task = _build(client, token, "vols", _git("https://git.example.com/vols.git", docker_enabled=True))
    _record(client, task["id"], "data, secrets")

    project = client.get(f"/api/projects/{task['project_id']}", headers=_h(token)).json()
    assert project["config"]["docker_volumes"] == "data, secrets"
    assert client.get(f"/api/tasks/{task['id']}", headers=_h(token)).json()["config"]["docker_volumes"] == "data, secrets"

    second = _build(client, token, "vols", _git("https://git.example.com/vols.git", docker_enabled=True))
    _record(client, second["id"], "logs")
    project = client.get(f"/api/projects/{task['project_id']}", headers=_h(token)).json()
    assert project["config"]["docker_volumes"] == "data, secrets"

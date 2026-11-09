"""
Rate limits as the real application applies them.
Source: app/main.py (rate_limit_config), app/middleware/rate_limiter.py

Two QA findings: one person reached the global 60 a minute in about 20 page
loads and a 429 on the session check signed them out; and building a project's
new version was not limited at all while POST /api/tasks was.
"""

import pytest

from .conftest import login


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _limiter(client):
    from app.middleware.rate_limiter import RateLimitMiddleware

    layer = client.app.middleware_stack
    while layer is not None and not isinstance(layer, RateLimitMiddleware):
        layer = getattr(layer, "app", None)
    return layer


@pytest.mark.integration
def test_tc_int_071_project_builds_spend_the_build_submit_allowance(client, admin_tokens, no_builds, monkeypatch):
    """TC-INT-071: building a project's version counts against the same per-minute
    allowance as POST /api/tasks, and is refused with 429 once it is spent."""
    token = admin_tokens["access_token"]
    first = client.post("/api/tasks", headers=_h(token), json={"project_name": "limited", "config": {
        "source_type": "git", "git_url": "https://git.example.com/limited.git", "git_ref": "main",
        "project_type": "backend_only"}})
    assert first.status_code == 201, first.text
    pid = first.json()["project_id"]
    monkeypatch.setitem(_limiter(client).config.path_limits, "POST /api/tasks", 3)

    statuses = [client.post(f"/api/projects/{pid}/builds", json={"version": f"1.0.{i}"}, headers=_h(token)).status_code
                for i in range(3)]

    assert statuses == [201, 201, 429]  # the submission above already spent one
    assert client.post("/api/tasks", headers=_h(token), json={"project_name": "limited", "config": {
        "source_type": "git", "git_url": "https://git.example.com/limited.git", "git_ref": "main",
        "project_type": "backend_only"}}).status_code == 429


@pytest.mark.integration
def test_tc_int_072_a_busy_minute_of_ordinary_use_is_not_refused(client, admin_tokens):
    """TC-INT-072: the default allowance covers far more than the old 60 calls a minute
    of ordinary pages (session checks, lists)."""
    token = login(client, "admin", "integration-admin-pass")["access_token"]

    statuses = {client.get(path, headers=_h(token)).status_code
                for _ in range(40) for path in ("/auth/me", "/api/projects", "/api/users/roles/list")}

    assert statuses == {200}

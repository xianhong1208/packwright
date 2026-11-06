"""Fixtures that run the real application: FastAPI TestClient against a temporary
SQLite database (see tests/conftest.py), with the real lifespan (schema, RBAC
seed, bootstrap admin). These catch what mocks hide: which token types a
dependency accepts, which helper a route actually calls, what reaches the wire."""

import pytest
from fastapi.testclient import TestClient

ADMIN = ("admin", "integration-admin-pass")


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fresh_rate_limits(request):
    """Every test that talks to the app starts with empty rate-limit windows.

    The whole suite runs from one address within a minute, so it outgrew the
    global 60 requests a minute and later tests got 429 for what earlier ones
    sent. The limits themselves stay as configured; the limiter has its own
    tests in tests/unit/middleware.
    """
    if "client" not in request.fixturenames:
        return
    from app.middleware.rate_limiter import RateLimitMiddleware

    layer = request.getfixturevalue("client").app.middleware_stack
    while layer is not None and not isinstance(layer, RateLimitMiddleware):
        layer = getattr(layer, "app", None)
    if layer is not None:
        for counts in (layer._minute_counts, layer._hour_counts, layer._path_counts):
            counts.clear()


@pytest.fixture
def no_builds(mocker):
    """Builds are accepted and filed but never started: nothing is cloned or compiled."""
    from app.api.routes import projects as projects_route
    from app.api.routes import tasks as tasks_route

    mocker.patch.object(tasks_route, "start_build_task", mocker.AsyncMock())
    mocker.patch.object(projects_route, "start_build_task", mocker.AsyncMock())


def login(client, username: str, password: str) -> dict:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="session")
def admin_tokens(client) -> dict:
    return login(client, *ADMIN)

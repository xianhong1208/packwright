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


def login(client, username: str, password: str) -> dict:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="session")
def admin_tokens(client) -> dict:
    return login(client, *ADMIN)

"""
Unit tests for API token format and the routes a token may reach.
Source: app/services/api_tokens.py
"""

import re

import pytest

from app.services import api_tokens
from app.services.api_tokens import (
    SCOPES,
    TOKEN_LEN,
    TOKEN_ROUTES,
    checksum_ok,
    display_prefix,
    generate_token,
    hash_token,
    normalize_scopes,
    scope_for_route,
)


@pytest.mark.unit
def test_tc_tok_001_generated_tokens_have_the_documented_shape():
    """TC-TOK-001: pwt_ + 49 base62 characters, distinct every time, checksum valid."""
    tokens = {generate_token() for _ in range(200)}
    assert len(tokens) == 200
    for t in tokens:
        assert len(t) == TOKEN_LEN == 53
        assert re.fullmatch(r"pwt_[0-9A-Za-z]{49}", t)
        assert checksum_ok(t)


@pytest.mark.unit
def test_tc_tok_002_a_typo_fails_the_checksum():
    """TC-TOK-002: changing any one character after the prefix, dropping one, or adding one
    is caught by the checksum or the shape, without a database."""
    t = generate_token()
    for i in range(4, len(t)):
        swapped = "A" if t[i] != "A" else "B"
        assert not checksum_ok(t[:i] + swapped + t[i + 1:]), i
    assert not checksum_ok(t[:-1])
    assert not checksum_ok(t + "0")
    assert not checksum_ok("pwt_" + "-" * 49)
    assert not checksum_ok("ghp_" + t[4:])


@pytest.mark.unit
def test_tc_tok_003_hash_and_display_prefix():
    """TC-TOK-003: the stored hash is the hex SHA-256 of the whole token; the display
    prefix is pwt_ plus eight characters and does not contain the rest."""
    t = generate_token()
    assert re.fullmatch(r"[0-9a-f]{64}", hash_token(t))
    assert hash_token(t) != hash_token(generate_token())
    assert display_prefix(t) == t[:12] and display_prefix(t).startswith("pwt_")


@pytest.mark.unit
def test_tc_tok_004_scopes_are_known_unique_and_ordered():
    """TC-TOK-004: unknown or empty scope lists are refused; duplicates collapse; the
    order is the documented one whatever order they were asked in."""
    assert normalize_scopes(["projects:read", "builds:read", "builds:read"]) == ["builds:read", "projects:read"]
    with pytest.raises(ValueError):
        normalize_scopes([])
    with pytest.raises(ValueError):
        normalize_scopes(["builds:read", "admin"])
    assert set(SCOPES) == {"builds:read", "builds:write", "projects:read"}


@pytest.mark.unit
def test_tc_tok_005_route_scopes():
    """TC-TOK-005: reading builds needs builds:read, starting or cancelling needs
    builds:write, HEAD counts as GET, and an unlisted route has no scope at all."""
    assert scope_for_route("GET", "/api/tasks/{task_id}") == "builds:read"
    assert scope_for_route("head", "/api/history/{task_id}/download") == "builds:read"
    assert scope_for_route("POST", "/api/tasks") == "builds:write"
    assert scope_for_route("DELETE", "/api/tasks/{task_id}") == "builds:write"
    assert scope_for_route("GET", "/api/projects") == "projects:read"
    assert scope_for_route("PUT", "/api/projects/{project_id}") is None
    assert scope_for_route("POST", "/api/tokens") is None


@pytest.mark.unit
def test_tc_tok_006_no_management_route_is_reachable_by_a_token():
    """TC-TOK-006: every route a token may use exists in the app, and none of them is a
    user, role, credential, settings, notification, token or sign-in route (no admin
    scope in 1.4)."""
    from fastapi import APIRouter

    import app.main as main

    # Every router main.py includes (none is included under an extra prefix).
    routers = [v for k, v in vars(main).items() if k.endswith("_router") and isinstance(v, APIRouter)]
    assert len(routers) >= 9
    real = set()
    for router in routers:
        for route in router.routes:
            methods = getattr(route, "methods", None)
            if methods:
                real |= {(m, route.path) for m in methods}
            else:
                real.add(("WS", route.path))
    assert set(TOKEN_ROUTES) <= real, set(TOKEN_ROUTES) - real

    forbidden = ("/api/users", "/auth", "/api/settings", "/api/tokens",
                 "/api/monitoring", "/api/git", "/api/directories", "/api/env-file")
    for method, path in TOKEN_ROUTES:
        assert not path.startswith(forbidden), path
        assert "/notifications" not in path, path
        # Project settings are changed by PUT; tokens only read them.
        assert not (path.startswith("/api/projects") and method in {"PUT", "PATCH", "DELETE"}), path
    assert set(TOKEN_ROUTES.values()) <= set(SCOPES)


@pytest.mark.unit
def test_tc_tok_007_route_list_matches_the_scope_names():
    """TC-TOK-007: reads are GET/WS under builds:read or projects:read; writes are the
    three build-starting or cancelling routes under builds:write."""
    writes = {k for k, v in TOKEN_ROUTES.items() if v == "builds:write"}
    assert writes == {("POST", "/api/tasks"), ("DELETE", "/api/tasks/{task_id}"),
                      ("POST", "/api/projects/{project_id}/builds")}
    for (method, _path), scope in TOKEN_ROUTES.items():
        if scope != "builds:write":
            assert method in {"GET", "WS"}
    assert api_tokens.MAX_EXPIRY_DAYS == 365

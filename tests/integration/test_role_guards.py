"""
Role changes that would break access control are refused.
Source: app/api/routes/users.py (create_role, update_role)

One PUT with an empty permission list emptied the built-in admin role and with
it the only way to grant anything back; parent links could form a loop; and
unknown permission codes were dropped without a word.
"""

import pytest

from .conftest import login


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _role(client, token: str, name: str) -> dict:
    return next(r for r in client.get("/api/users/roles/list", headers=_h(token)).json() if r["name"] == name)


def _codes(role: dict) -> list[str]:
    return sorted(p["code"] for p in role["permissions"])


def _create(client, token: str, name: str, **extra) -> dict:
    r = client.post("/api/users/roles", json={"name": name, "display_name": name, **extra}, headers=_h(token))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.integration
def test_tc_int_062_the_last_role_manager_cannot_be_emptied(client, admin_tokens):
    """TC-INT-062: emptying the admin role while it is the only one holding role:manage
    is refused and changes nothing; the admin can still manage roles afterwards."""
    token = admin_tokens["access_token"]
    admin = _role(client, token, "admin")

    r = client.put(f"/api/users/roles/{admin['id']}", json={"permission_codes": []}, headers=_h(token))

    assert r.status_code == 400, r.text
    assert "manage roles" in r.json()["detail"]
    assert _codes(_role(client, token, "admin")) == _codes(admin) == ["*:*"]
    # A display-name edit that keeps the permissions still goes through.
    ok = client.put(f"/api/users/roles/{admin['id']}",
                    json={"display_name": "Administrator", "permission_codes": ["*:*"]}, headers=_h(token))
    assert ok.status_code == 200, ok.text


@pytest.mark.integration
def test_tc_int_063_another_role_manager_makes_the_change_allowed(client, admin_tokens):
    """TC-INT-063: the guard counts active accounts, not role names: with a second active
    account holding role:manage through a custom role, narrowing the admin role is allowed."""
    token = admin_tokens["access_token"]
    keeper = _create(client, token, "role-keeper", permission_codes=["role:manage", "role:view", "user:view"])
    assert client.post("/auth/register", json={"username": "keeper", "password": "keeper-pass-123"}).status_code == 201
    uid = next(u["id"] for u in client.get("/api/users", headers=_h(token)).json() if u["username"] == "keeper")
    assert client.put(f"/api/users/{uid}/role", json={"role_id": keeper["id"]}, headers=_h(token)).status_code == 200
    # Inactive, the account does not count yet.
    assert client.put(f"/api/users/roles/{_role(client, token, 'admin')['id']}",
                      json={"permission_codes": ["task:create"]}, headers=_h(token)).status_code == 400
    assert client.put(f"/api/users/{uid}/status", json={"is_active": True}, headers=_h(token)).status_code == 200

    admin = _role(client, token, "admin")
    narrowed = client.put(f"/api/users/roles/{admin['id']}", json={"permission_codes": ["task:create"]}, headers=_h(token))
    assert narrowed.status_code == 200, narrowed.text

    # The keeper can undo it, which is the point of the rule.
    keeper_token = login(client, "keeper", "keeper-pass-123")["access_token"]
    restored = client.put(f"/api/users/roles/{admin['id']}", json={"permission_codes": ["*:*"]}, headers=_h(keeper_token))
    assert restored.status_code == 200, restored.text
    # With the keeper's own role deactivated, the admin role is the only manager again.
    assert client.put(f"/api/users/roles/{keeper['id']}", json={"is_active": False}, headers=_h(token)).status_code == 200
    assert client.put(f"/api/users/roles/{admin['id']}", json={"permission_codes": []}, headers=_h(token)).status_code == 400


@pytest.mark.integration
def test_tc_int_064_parent_links_cannot_form_a_loop(client, admin_tokens):
    """TC-INT-064: a parent whose ancestry already contains the role is refused, at any depth."""
    token = admin_tokens["access_token"]
    a = _create(client, token, "loop-a")
    b = _create(client, token, "loop-b", parent_role_id=a["id"])
    c = _create(client, token, "loop-c", parent_role_id=b["id"])

    direct = client.put(f"/api/users/roles/{a['id']}", json={"parent_role_id": b["id"]}, headers=_h(token))
    deep = client.put(f"/api/users/roles/{a['id']}", json={"parent_role_id": c["id"]}, headers=_h(token))

    assert direct.status_code == deep.status_code == 400
    assert "loop" in deep.json()["detail"]
    assert _role(client, token, "loop-a")["parent_role_id"] is None
    # A chain that does not come back is still fine.
    d = _create(client, token, "loop-d")
    assert client.put(f"/api/users/roles/{d['id']}", json={"parent_role_id": c["id"]}, headers=_h(token)).status_code == 200


@pytest.mark.integration
def test_tc_int_065_unknown_permission_codes_are_refused(client, admin_tokens):
    """TC-INT-065: creating or updating a role with a code that does not exist is a 400
    naming it, not a role silently missing that permission."""
    token = admin_tokens["access_token"]

    created = client.post("/api/users/roles", headers=_h(token),
                          json={"name": "typo", "display_name": "typo", "permission_codes": ["task:create", "task:craete"]})
    assert created.status_code == 400
    assert "task:craete" in created.json()["detail"]
    assert all(r["name"] != "typo" for r in client.get("/api/users/roles/list", headers=_h(token)).json())

    role = _create(client, token, "typo-ok", permission_codes=["task:create"])
    updated = client.put(f"/api/users/roles/{role['id']}", json={"permission_codes": ["bogus:x"]}, headers=_h(token))
    assert updated.status_code == 400
    assert _codes(_role(client, token, "typo-ok")) == ["task:create"]

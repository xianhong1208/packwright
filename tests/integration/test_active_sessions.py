"""
Integration tests for telling the caller's own sign-in apart in the sessions list.
Source: app/services/auth (create_tokens, refresh_access_token — the ``sid`` claim),
app/services/permission (CurrentUser.session_id), app/api/routes/auth (/auth/active-sessions)
"""

import pytest

from .conftest import ADMIN, login


def _current_ids(client, access_token: str) -> list[int]:
    r = client.get("/auth/active-sessions", headers={"Authorization": f"Bearer {access_token}"})
    assert r.status_code == 200, r.text
    return [s["id"] for s in r.json()["sessions"] if s["is_current"]]


@pytest.mark.integration
def test_tc_int_041_only_the_callers_own_sign_in_is_current(client):
    """TC-INT-041: two sign-ins from the same address — each sees only itself as current.

    Matching on IP marked both, so neither could tell which one to keep when
    signing the other out.
    """
    first = login(client, *ADMIN)
    second = login(client, *ADMIN)

    mine_first = _current_ids(client, first["access_token"])
    mine_second = _current_ids(client, second["access_token"])

    assert len(mine_first) == 1 and len(mine_second) == 1
    assert mine_first != mine_second


@pytest.mark.integration
def test_tc_int_042_a_refreshed_token_points_at_the_new_session(client):
    """TC-INT-042: after rotation the new access token marks the new row, not the revoked one."""
    tokens = login(client, *ADMIN)
    before = _current_ids(client, tokens["access_token"])

    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200, r.text
    after = _current_ids(client, r.json()["access_token"])

    assert len(after) == 1
    assert after != before

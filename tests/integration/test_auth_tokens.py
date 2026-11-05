"""
Integration tests for which credentials authenticate.
Source: app/services/auth (decode_access_token), app/services/permission
(get_current_user), app/api/websocket, app/api/routes/auth (SSO handoff)
"""

import pytest
from starlette.websockets import WebSocketDisconnect

from app.services import mcp_oauth
from app.services.auth import create_download_ticket, decode_token


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
def test_tc_int_001_access_token_authenticates(client, admin_tokens):
    """TC-INT-001: the control case — a login access token reaches /auth/me."""
    r = client.get("/auth/me", headers=_bearer(admin_tokens["access_token"]))
    assert r.status_code == 200
    assert r.json()["username"] == "admin"


@pytest.mark.integration
def test_tc_int_002_download_ticket_is_not_a_bearer_token(client, admin_tokens):
    """TC-INT-002: a download ticket must not work as an access token.

    Tickets are signed with the same key and carry a ``sub``; before the type
    check one acted as a full bearer token for 30 minutes — and tickets travel
    in URLs, so they land in proxy and access logs.
    """
    user_id = int(decode_token(admin_tokens["access_token"])["sub"])
    ticket = create_download_ticket(user_id, "some-task")

    assert client.get("/auth/me", headers=_bearer(ticket)).status_code == 401
    assert client.get("/api/users", headers=_bearer(ticket)).status_code == 401


@pytest.mark.integration
def test_tc_int_003_download_ticket_cannot_open_a_websocket(client, admin_tokens):
    """TC-INT-003: the WebSocket handshake applies the same token-type rule."""
    user_id = int(decode_token(admin_tokens["access_token"])["sub"])
    ticket = create_download_ticket(user_id, "some-task")

    # Fail on accept rather than waiting for a message: a regression must turn the
    # test red, not hang it.
    try:
        with client.websocket_connect("/ws/tasks", subprotocols=["bearer", ticket]):
            pytest.fail("a download ticket opened the task WebSocket")
    except WebSocketDisconnect as exc:
        assert exc.code == 4401


@pytest.mark.integration
def test_tc_int_004_refresh_token_value_is_not_a_bearer_token(client, admin_tokens):
    """TC-INT-004: the opaque refresh token is not a JWT and is refused as one."""
    assert client.get("/auth/me", headers=_bearer(admin_tokens["refresh_token"])).status_code == 401


class TestSsoHandoff:
    @pytest.mark.integration
    def test_tc_int_010_code_redeems_once_in_the_binding_browser(self, client, admin_tokens):
        """TC-INT-010: the code plus the binding cookie yields the tokens, exactly once."""
        code, binding = mcp_oauth.issue_handoff(dict(admin_tokens))

        client.cookies.set("mcp_sso_handoff", binding)
        r = client.post("/auth/oauth/mcp/exchange", json={"code": code})
        assert r.status_code == 200
        assert r.json()["access_token"] == admin_tokens["access_token"]

        client.cookies.set("mcp_sso_handoff", binding)
        again = client.post("/auth/oauth/mcp/exchange", json={"code": code})
        assert again.status_code == 400

    @pytest.mark.integration
    def test_tc_int_011_code_without_the_binding_cookie_is_refused(self, client, admin_tokens):
        """TC-INT-011: a code lifted from a URL is useless in another browser (login CSRF)."""
        code, _binding = mcp_oauth.issue_handoff(dict(admin_tokens))
        client.cookies.clear()

        r = client.post("/auth/oauth/mcp/exchange", json={"code": code})
        assert r.status_code == 400
        assert "access_token" not in r.text

    @pytest.mark.integration
    def test_tc_int_012_callback_issues_a_code_not_tokens(self, client, mocker):
        """TC-INT-012: an approved user's callback succeeds (it used to 500 on a
        resolve_client_ip() call missing an argument) and puts only a one-time
        code in the redirect, with the binding in an HttpOnly cookie."""
        from sqlalchemy import select

        from app.api.routes import auth as auth_route
        from app.models.user import User

        async def _admin(db, _identity):
            return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

        mocker.patch.object(mcp_oauth, "read_flow_state", return_value="verifier")
        mocker.patch.object(mcp_oauth, "exchange_code", mocker.AsyncMock(return_value={"access_token": "x"}))
        mocker.patch.object(mcp_oauth, "identity_from_token", return_value={"sub": "s"})
        mocker.patch.object(auth_route, "_find_or_create_sso_user", side_effect=_admin)

        r = client.get("/auth/oauth/mcp/callback?code=c&state=s", follow_redirects=False)

        assert r.status_code == 302
        location = r.headers["location"]
        assert "#sso_code=" in location
        assert "access_token" not in location and "refresh_token" not in location
        cookie = r.headers.get("set-cookie", "")
        assert "mcp_sso_handoff=" in cookie and "HttpOnly" in cookie

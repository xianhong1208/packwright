"""
Unit tests for the outranking guard on user administration.
Source: app/api/routes/users (_ensure_not_outranked)

user:reset_password and user:manage used to reach any account. A role granted
only "reset passwords" could reset the admin's password and sign in as the
admin; user:manage could deactivate or demote every admin. The guard refuses to
act on an account holding permissions the actor lacks, unless the actor holds
role:manage (who can rewrite roles anyway).
"""

import pytest
from fastapi import HTTPException
from pytest_mock import MockerFixture

from app.api.routes import users as users_route
from app.schemas.user import AdminPasswordReset, UserStatusUpdate
from app.services.permission import CurrentUser


def _actor(*permissions: str) -> CurrentUser:
    return CurrentUser(id=1, username="helpdesk", permissions=list(permissions), role="custom")


@pytest.fixture
def target_perms(mocker: MockerFixture):
    return mocker.patch.object(users_route, "get_user_permissions", autospec=True)


@pytest.fixture
def reset(mocker: MockerFixture):
    mocker.patch.object(users_route, "log_action", autospec=True)
    return mocker.patch.object(users_route, "admin_reset_password", autospec=True, return_value=True)


class TestOutrankingGuard:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_out_001_reset_password_cannot_reach_an_admin(self, target_perms, reset):
        """TC-OUT-001: reset of an admin by a reset-password-only role is refused."""
        target_perms.return_value = {"*:*"}

        with pytest.raises(HTTPException) as exc:
            await users_route.reset_user_password(
                2, AdminPasswordReset(new_password="new-pass-123"),
                current_user=_actor("user:reset_password"), db=object(),
            )

        assert exc.value.status_code == 403
        reset.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_out_002_peers_and_below_are_reachable(self, target_perms, reset):
        """TC-OUT-002: a target whose permissions the actor covers can be reset."""
        target_perms.return_value = {"task:create", "history:view_own"}

        await users_route.reset_user_password(
            2, AdminPasswordReset(new_password="new-pass-123"),
            current_user=_actor("user:reset_password", "task:*", "history:view_own"), db=object(),
        )

        reset.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_out_003_role_manage_is_exempt(self, target_perms, reset):
        """TC-OUT-003: role:manage holders may act on anyone (they can rewrite roles)."""
        target_perms.return_value = {"*:*"}

        await users_route.reset_user_password(
            2, AdminPasswordReset(new_password="new-pass-123"),
            current_user=_actor("user:reset_password", "role:manage"), db=object(),
        )

        reset.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_out_004_user_manage_cannot_deactivate_an_admin(self, target_perms, mocker):
        """TC-OUT-004: deactivating an account that outranks you is refused, before any write."""
        target_perms.return_value = {"*:*"}
        admin = mocker.Mock(is_active=True, username="admin")
        result = mocker.Mock(scalar_one_or_none=mocker.Mock(return_value=admin))
        db = mocker.AsyncMock()
        db.execute.return_value = result

        with pytest.raises(HTTPException) as exc:
            await users_route.update_user_status(
                2, UserStatusUpdate(is_active=False), current_user=_actor("user:manage"), db=db,
            )

        assert exc.value.status_code == 403
        assert admin.is_active is True
        db.commit.assert_not_awaited()

"""
Unit tests for the bootstrap admin and the permissions claim.
Source: app/services/seed (_seed_bootstrap_admin), app/services/auth (get_user_permissions)
"""

import logging
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture

from app.services import auth as auth_service
from app.services import seed


class _Result:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    """Replays queued results, one per execute(); records added objects."""

    def __init__(self, *results):
        self._results = list(results)
        self.added: list = []

    async def execute(self, *_a, **_k):
        return _Result(self._results.pop(0))

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None


def _settings(mocker: MockerFixture, password):
    mocker.patch.object(seed, "get_settings", return_value=SimpleNamespace(
        bootstrap_admin_username="admin", bootstrap_admin_password=password))


class TestBootstrapAdmin:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_bsa_001_unset_password_is_random_and_logged_once(self, mocker, caplog):
        """TC-BSA-001: no BOOTSTRAP_ADMIN_PASSWORD -> a random password, shown in the log.

        A fixed default ("password123") was a published credential on a service
        that listens on 0.0.0.0.
        """
        _settings(mocker, None)
        db = FakeSession(None, SimpleNamespace(id=1))
        caplog.set_level(logging.WARNING)

        await seed._seed_bootstrap_admin(db)

        (admin,) = db.added
        logged = caplog.text.split("generated password: ")[1].split()[0]
        assert len(logged) >= 16 and logged != "password123"
        assert auth_service.verify_password(logged, admin.password_hash)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_bsa_002_two_installs_get_different_passwords(self, mocker, caplog):
        """TC-BSA-002: the generated password is not a constant."""
        _settings(mocker, None)
        caplog.set_level(logging.WARNING)
        await seed._seed_bootstrap_admin(FakeSession(None, SimpleNamespace(id=1)))
        await seed._seed_bootstrap_admin(FakeSession(None, SimpleNamespace(id=1)))

        first, second = [t.split("generated password: ")[1].split()[0]
                         for t in caplog.text.splitlines() if "generated password" in t]
        assert first != second

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_bsa_003_configured_password_is_used_and_not_logged(self, mocker, caplog):
        """TC-BSA-003: an explicit password is honoured and never written to the log."""
        _settings(mocker, "chosen-by-operator")
        db = FakeSession(None, SimpleNamespace(id=1))
        caplog.set_level(logging.WARNING)

        await seed._seed_bootstrap_admin(db)

        assert auth_service.verify_password("chosen-by-operator", db.added[0].password_hash)
        assert "chosen-by-operator" not in caplog.text

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_bsa_004_empty_password_disables_the_account(self, mocker):
        """TC-BSA-004: BOOTSTRAP_ADMIN_PASSWORD="" keeps the self-registration flow."""
        _settings(mocker, "")
        db = FakeSession()
        await seed._seed_bootstrap_admin(db)
        assert db.added == []


class TestPermissionsClaim:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_bsa_010_claim_uses_the_inheriting_resolver(self, mocker: MockerFixture):
        """TC-BSA-010: the JWT permissions claim includes inherited permissions.

        It used to read only the user's own role, so the console hid menus for
        permissions the API would actually grant through a parent role.
        """
        resolver = mocker.patch("app.services.permission.get_user_permissions",
                                autospec=True, return_value={"task:create", "history:view_all"})

        assert await auth_service.get_user_permissions(object(), 7) == ["history:view_all", "task:create"]
        resolver.assert_awaited_once()

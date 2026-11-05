"""
Unit tests for where settings and generated secrets are read from and written to.
Source: app/config (APP_ENV_FILE, Settings.model_config, append_generated_setting)

Generated secrets are appended to the .env next to main.py, but settings used to
be read only from ".env" in the launch directory — so a service started from any
other directory minted a new JWT and encryption key on every start: everyone was
logged out and stored Git credentials could no longer be decrypted.
"""

import logging
import os
import stat

import pytest
from pydantic_settings import SettingsConfigDict

from app import config
from app.config import APP_ENV_FILE, Settings, append_generated_setting


class TestWhereSettingsAreRead:
    @pytest.mark.unit
    def test_tc_envf_001_app_env_file_is_read_first_and_launch_dir_last(self):
        """TC-ENVF-001: the .env beside main.py is always read; the launch directory's wins."""
        files = Settings.model_config["env_file"]
        assert files[0] == APP_ENV_FILE
        assert files[-1] == ".env"
        assert APP_ENV_FILE.parent == config.Path(config.__file__).resolve().parent.parent

    @pytest.mark.unit
    def test_tc_envf_002_generated_secret_is_found_from_another_directory(self, tmp_path, monkeypatch):
        """TC-ENVF-002: launched elsewhere, a value in the app's .env is still read,
        and a .env in the launch directory overrides it."""
        app_dir, launch_dir = tmp_path / "app", tmp_path / "elsewhere"
        app_dir.mkdir()
        launch_dir.mkdir()
        (app_dir / ".env").write_text("MAX_LOG_LINES=111\nLOG_LEVEL=DEBUG\n")
        monkeypatch.delenv("MAX_LOG_LINES", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.chdir(launch_dir)

        class AppSettings(Settings):
            model_config = SettingsConfigDict(
                env_file=(app_dir / ".env", ".env"), env_file_encoding="utf-8", case_sensitive=False
            )

        assert AppSettings().max_log_lines == 111

        (launch_dir / ".env").write_text("MAX_LOG_LINES=222\n")
        loaded = AppSettings()
        assert loaded.max_log_lines == 222
        assert loaded.log_level == "DEBUG"  # keys only in the app's .env still apply


class TestAppendGeneratedSetting:
    @pytest.mark.unit
    def test_tc_envf_010_appends_owner_only(self, tmp_path, monkeypatch):
        """TC-ENVF-010: the secret is appended (existing lines kept) and the file is 0600."""
        target = tmp_path / ".env"
        target.write_text("EXISTING=1\n")
        target.chmod(0o644)
        monkeypatch.setattr(config, "APP_ENV_FILE", target)

        assert append_generated_setting("JWT_SECRET_KEY", "abc", "generated") is True

        text = target.read_text()
        assert text.startswith("EXISTING=1\n") and "\nJWT_SECRET_KEY=abc\n" in text
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o600

    @pytest.mark.unit
    def test_tc_envf_011_failure_is_reported_not_silent(self, tmp_path, monkeypatch, caplog):
        """TC-ENVF-011: an unwritable location returns False and logs a warning naming
        the setting, instead of quietly regenerating the key on every start."""
        monkeypatch.setattr(config, "APP_ENV_FILE", tmp_path / "missing-dir" / ".env")

        with caplog.at_level(logging.WARNING, logger="app.config"):
            assert append_generated_setting("SETTINGS_ENCRYPTION_KEY", "k", "generated") is False

        assert "SETTINGS_ENCRYPTION_KEY" in caplog.text

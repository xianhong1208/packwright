"""
Unit tests for BuildConfig defaults that API callers rely on.
Source: app/schemas/task.BuildConfig
"""

import pytest

from app.schemas.task import BuildConfig, PackMode


class TestPackModeDefault:
    @pytest.mark.unit
    def test_tc_bcd_001_api_default_matches_the_console(self):
        """TC-BCD-001: leaving pack_mode out gives External, as the console preselects —
        it used to give Full, which compiles every dependency and takes hours."""
        assert BuildConfig(project_path="/srv/projects/x").pack_mode is PackMode.EXTERNAL

    @pytest.mark.unit
    def test_tc_bcd_002_stored_full_config_still_reads_as_full(self):
        """TC-BCD-002: a stored config that asked for Full keeps it (rebuilds are faithful)."""
        assert BuildConfig.model_validate({"project_path": "/srv/projects/x", "pack_mode": "full"}).pack_mode is PackMode.FULL

"""
Unit tests for the single version source.
Source: app/version, frontend/scripts/sync-version.mjs

pyproject.toml is the only place a version is written by hand. These tests
fail when anything that should derive from it drifts.
"""

import json
import tomllib
from pathlib import Path

import pytest

from app.version import __version__

ROOT = Path(__file__).resolve().parents[2]


def _pyproject_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


@pytest.mark.unit
def test_tc_ver_001_app_reports_the_pyproject_version():
    """TC-VER-001: app.version reads pyproject.toml (not stale package metadata)."""
    assert __version__ == _pyproject_version()


@pytest.mark.unit
def test_tc_ver_002_frontend_package_matches():
    """TC-VER-002: frontend/package.json and its lock carry the same version.

    `npm run sync-version` (run by `npm run build`) writes them; a release that
    bumps pyproject.toml and skips it fails here.
    """
    version = _pyproject_version()
    package = json.loads((ROOT / "frontend" / "package.json").read_text())
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text())
    assert package["version"] == version
    assert lock["version"] == version
    assert lock["packages"][""]["version"] == version


@pytest.mark.unit
def test_tc_ver_003_no_hard_coded_version_strings_remain():
    """TC-VER-003: the API title/version and the banner derive from app.version."""
    for rel in ("app/main.py", "main.py"):
        text = (ROOT / rel).read_text()
        assert f'"{_pyproject_version()}"' not in text, f"{rel} hard-codes the version"

"""
Tests for reading the version being built from the project.
Source: app/services/project_version.py
"""

import pytest

from app.services.project_version import detect_version, version_from_package_json, version_from_pyproject

PYPROJECT = '[project]\nname = "shop"\nversion = "1.4.0"\n'
PACKAGE = '{"name": "shop-web", "version": "0.9.2"}'


@pytest.mark.unit
def test_tc_ver_001_precedence():
    """TC-VER-001: a tag beats pyproject.toml, which beats package.json."""
    assert detect_version(PYPROJECT, PACKAGE, "v2.0.0", "tag") == {"value": "v2.0.0", "source": "Git tag"}
    assert detect_version(PYPROJECT, PACKAGE, "main", "branch") == {"value": "1.4.0", "source": "pyproject.toml"}
    assert detect_version(None, PACKAGE) == {"value": "0.9.2", "source": "package.json"}
    assert detect_version(None, None) is None


@pytest.mark.unit
def test_tc_ver_002_dynamic_and_unreadable_versions_are_left_to_the_person():
    """TC-VER-002: a dynamic version, broken files and unusable values give nothing."""
    assert version_from_pyproject('[project]\nname = "x"\ndynamic = ["version"]\nversion = "9"\n') is None
    assert version_from_pyproject("[project\nbroken") is None
    assert version_from_pyproject('[tool.poetry]\nversion = "1.0"\n') is None
    assert version_from_package_json("{not json") is None
    assert version_from_package_json('["a list"]') is None
    assert version_from_package_json('{"version": "1.0 beta"}') is None  # a space cannot go in a file name or tag
    assert version_from_package_json('{"version": 3}') is None


@pytest.mark.unit
def test_tc_ver_003_a_branch_is_not_a_version():
    """TC-VER-003: only a tag counts; a branch falls through to the files."""
    assert detect_version(None, None, "release/2.0", "branch") is None
    assert detect_version(None, None, "bad tag!", "tag") is None


@pytest.mark.unit
@pytest.mark.parametrize("value", ["1.2.0", "v2.0.0-rc.1", "2026.11.06", "1.0.0+build.7", "  1.4.0  "])
def test_tc_ver_004_build_config_accepts_versions(value):
    """TC-VER-004: the usual version shapes are accepted (and trimmed)."""
    from app.schemas.task import BuildConfig

    assert BuildConfig(version=value).version == value.strip()


@pytest.mark.unit
@pytest.mark.parametrize("value", ["1.0 beta", "-1.0", "../etc", "v1;rm", "x" * 65])
def test_tc_ver_005_build_config_refuses_what_cannot_be_stamped(value):
    """TC-VER-005: a version goes into a file name, a Docker tag and a file; spaces,
    path parts and shell characters are refused before the build starts."""
    from pydantic import ValidationError

    from app.schemas.task import BuildConfig

    with pytest.raises(ValidationError):
        BuildConfig(version=value)

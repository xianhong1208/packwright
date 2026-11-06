"""
Tests for stamping the version into a Docker image.
Source: app/services/docker_worker.py (docker_tag, image_reference, _generate_dockerfile)
"""

import pytest

from app.schemas.task import BuildConfig
from app.services.docker_worker import _generate_dockerfile, docker_tag, image_reference


@pytest.mark.unit
@pytest.mark.parametrize(
    ("configured", "folder", "version", "expected"),
    [
        ("", "shop", "1.2.0", "shop:1.2.0"),
        ("", "shop", "", "shop:latest"),
        ("", "MCP_Center", "", "mcp_center:latest"),  # Docker refuses upper case
        ("registry.local/team/shop", "x", "1.2.0", "registry.local/team/shop:1.2.0"),
        ("registry.local:5000/shop", "x", "1.2.0", "registry.local:5000/shop:1.2.0"),  # a port is not a tag
        ("shop:stable", "x", "1.2.0", "shop:stable"),  # a chosen tag wins
        ("shop@sha256:abc", "x", "1.2.0", "shop@sha256:abc"),
        ("shop", "x", "", "shop"),
    ],
)
def test_tc_dver_001_image_reference(configured, folder, version, expected):
    """TC-DVER-001: the image is tagged with the version unless a tag was chosen."""
    assert image_reference(configured, folder, version) == expected


@pytest.mark.unit
def test_tc_dver_002_a_version_becomes_a_valid_tag():
    """TC-DVER-002: '+' is not allowed in a tag, nor a leading '.' or '-'."""
    assert docker_tag("1.0.0+build.7") == "1.0.0_build.7"
    assert docker_tag("v2.0.0-rc.1") == "v2.0.0-rc.1"


@pytest.mark.unit
@pytest.mark.parametrize("project_type", ["backend_only", "frontend_only"])
def test_tc_dver_003_the_dockerfile_carries_the_version(project_type, tmp_path):
    """TC-DVER-003: the last lines label the image with its version and expose it to
    the program; a build without a version adds neither."""
    base = {"project_type": project_type, "project_path": str(tmp_path), "docker_enabled": True}
    with_version = _generate_dockerfile(BuildConfig(**base, version="1.2.0"), precompiled=project_type != "frontend_only")
    without = _generate_dockerfile(BuildConfig(**base), precompiled=project_type != "frontend_only")

    assert with_version.rstrip().endswith('LABEL org.opencontainers.image.version="1.2.0"\nENV PACKWRIGHT_BUILD_VERSION=1.2.0')
    assert "image.version" not in without and "PACKWRIGHT_BUILD_VERSION" not in without


@pytest.mark.unit
@pytest.mark.parametrize(
    ("base", "version", "expected"),
    [
        ("shop", "1.2.0", "shop-1.2.0"),
        ("shop", None, "shop"),
        ("shop:1.2.0", "1.2.0", "shop_1.2.0"),  # an image tagged with it already says it
        ("My Shop", "1.0+b7", "My_Shop-1.0_b7"),
    ],
)
def test_tc_dver_004_download_names_carry_the_version(base, version, expected):
    """TC-DVER-004: the archive is named after the output and its version."""
    from app.api.routes.tasks import _download_name

    assert _download_name(base, version) == expected

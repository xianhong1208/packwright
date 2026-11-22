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


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ({"source_type": "git", "git_url": "https://github.com/xianhong1208/MCP_Gate.git", "git_ref": "dev"}, "MCP_Gate"),
        ({"source_type": "git", "git_url": "https://gitlab.example.com/team/shop/", "git_ref": "main"}, "shop"),
        ({"source_type": "git", "git_url": "git@github.com:team/Shop.GIT", "git_ref": "main"}, "Shop"),
        ({"source_type": "local", "project_path": "/srv/projects/shop"}, "shop"),
    ],
)
def test_tc_dver_005_an_unnamed_git_image_is_named_after_the_repository(source, expected):
    """TC-DVER-005: a Git build is cloned into a folder named after the task, so the
    image is named after the repository instead; a local build keeps its folder's name."""
    from app.services.docker_worker import default_image_repo

    config = BuildConfig(project_type="backend_only", docker_enabled=True, **source)
    assert default_image_repo(config) == expected
    assert image_reference("", default_image_repo(config), "1.4.0") == f"{expected.lower()}:1.4.0"


@pytest.mark.unit
def test_tc_dver_006_the_command_preview_uses_the_same_name():
    """TC-DVER-006: the Commands tab shows the name the build will use, not <checkout>."""
    from app.services.command_preview import preview_commands

    config = BuildConfig(
        project_type="backend_only", source_type="git", docker_enabled=True, version="1.4.0",
        git_url="https://github.com/xianhong1208/MCP_Gate.git", git_ref="dev",
    )
    docker = [s for s in preview_commands(config)["steps"] if s["stage"] == "Build the Docker image"]
    assert docker[0]["command"] == "docker build -t mcp_gate:1.4.0 ."

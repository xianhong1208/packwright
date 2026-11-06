"""
Tests for previewing a build's commands.
Source: app/services/command_preview.py (preview_commands)
"""

import pytest

from app.schemas.task import BuildConfig
from app.services.command_preview import preview_commands


def _stages(p: dict) -> list[str]:
    return [s["stage"] for s in p["steps"]]


@pytest.mark.unit
def test_tc_prv_001_backend(tmp_path):
    """TC-PRV-001: a backend is one Nuitka command on its entry point, with VERSION when
    it has a version, and notes on what only the build adds."""
    p = preview_commands(BuildConfig(project_path=str(tmp_path), entry_point="app/main.py", version="1.2.0", nuitka_jobs=6))
    assert _stages(p) == ["Compile with Nuitka"]
    cmd = p["steps"][0]["command"]
    assert "-m nuitka --standalone" in cmd and cmd.endswith(str(tmp_path / "app" / "main.py"))
    assert "--include-data-files=VERSION=VERSION" in cmd and "--jobs=6" in cmd
    assert any("libs/" in n for n in p["notes"])


@pytest.mark.unit
def test_tc_prv_002_fullstack_builds_the_frontend_first(tmp_path):
    """TC-PRV-002: a full stack installs and builds the frontend before compiling; a
    package-lock.json makes it `npm ci`."""
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package-lock.json").write_text("{}")
    p = preview_commands(BuildConfig(project_type="fullstack", project_path=str(tmp_path), frontend_dir="web",
                                     frontend_build_command="build:prod"))
    assert _stages(p) == ["Install frontend dependencies", "Build the frontend", "Compile with Nuitka"]
    assert p["steps"][0]["command"].endswith("npm ci --legacy-peer-deps")
    assert p["steps"][1]["command"] == "npm run build:prod"


@pytest.mark.unit
def test_tc_prv_003_git_and_docker():
    """TC-PRV-003: a Git source shows its checkout as a placeholder; a Docker image is
    tagged with the version."""
    p = preview_commands(BuildConfig(project_type="frontend_only", source_type="git", git_url="https://git.example.com/shop.git",
                                     git_ref="main", docker_enabled=True, docker_image_name="registry.local/shop", version="2.0.0",
                                     frontend_build_tool="pnpm", frontend_dir="."))
    assert p["steps"][0]["command"] == "cd '<checkout>' && pnpm install --frozen-lockfile"
    assert p["steps"][-1]["command"] == "docker build -t registry.local/shop:2.0.0 ."


@pytest.mark.unit
def test_tc_prv_004_auto_jobs_is_explained(tmp_path):
    """TC-PRV-004: on Auto CPU jobs the preview says the number shrinks when builds share."""
    p = preview_commands(BuildConfig(project_path=str(tmp_path)))
    assert any("Auto" in n for n in p["notes"])

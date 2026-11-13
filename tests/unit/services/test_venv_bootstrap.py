"""
Tests for the git-mode .venv bootstrap.
Source: app/services/build_dispatcher.py (_prepare_venv)

What uv installs here is what External mode copies into libs/ and ships in the
program and its Docker image, so a development group must never end up in it
unless the build asked for it.
"""

from pathlib import Path

import pytest

from app.schemas.task import BuildConfig
from app.services import build_dispatcher


class _Proc:
    returncode = 0

    async def communicate(self):
        return b"", b""


@pytest.fixture
def uv_calls(mocker, tmp_path):
    """Record every argv the bootstrap would run, without running uv."""
    calls: list[list[str]] = []

    async def fake_spawn(*cmd, **_kw):
        calls.append(list(cmd))
        return _Proc()

    uv = tmp_path / "uv"
    uv.write_text("")
    mocker.patch.object(build_dispatcher, "_spawn", fake_spawn)
    mocker.patch.object(build_dispatcher.task_manager, "append_log", mocker.AsyncMock())
    settings = mocker.MagicMock(
        git_auto_venv=True, uv_binary=str(uv), bootstrap_uv_cache_dir="",
        subprocess_path="/usr/bin", venv_bootstrap_timeout=60,
    )
    mocker.patch("app.config.get_settings", return_value=settings)
    return calls


def _project(tmp_path: Path, lock: bool) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "p"\nversion = "1.0"\n[dependency-groups]\ndev = ["pytest"]\nrocm = ["torch"]\n'
    )
    if lock:
        (project / "uv.lock").write_text("version = 1\n")
    return project


def _config(**kw) -> BuildConfig:
    return BuildConfig(project_type="backend_only", source_type="local", project_path="/x", **kw)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("lock", [True, False])
async def test_tc_vnv_001_default_groups_are_left_out(uv_calls, tmp_path, lock):
    """TC-VNV-001: with no group chosen, uv sync gets --no-default-groups, so `dev` is not installed."""
    await build_dispatcher._prepare_venv("t1", _project(tmp_path, lock), _config())
    (cmd,) = uv_calls
    assert cmd[1] == "sync"
    assert "--no-default-groups" in cmd
    assert "--group" not in cmd


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_vnv_002_a_chosen_group_is_still_installed(uv_calls, tmp_path):
    """TC-VNV-002: a group picked for the build is added on top with --group."""
    await build_dispatcher._prepare_venv("t1", _project(tmp_path, True), _config(dependency_groups=["rocm"]))
    (cmd,) = uv_calls
    assert "--no-default-groups" in cmd
    assert cmd[cmd.index("--group") + 1] == "rocm"

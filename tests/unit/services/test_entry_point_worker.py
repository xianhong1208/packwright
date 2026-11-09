"""
Unit test for the Nuitka worker's own entry-point check.
Source: app/services/nuitka_worker.py (run_nuitka_build)

The routes check the entry point's name, but a Git clone can hold a main.py
that is a symlink to a host file, and stored configs (rebuilds, project
defaults) reach the worker too. The worker writes the libs loader into the
entry point, so it joins it with safe_join() before touching it.
"""

import sys
from types import SimpleNamespace

import pytest

from app.schemas.task import BuildConfig
from app.services import nuitka_worker


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_pth_027_the_worker_refuses_an_entry_point_outside_the_project(tmp_path, mocker):
    """TC-PTH-027: run_nuitka_build fails before injecting anything when the entry
    point resolves outside the project, and the file it points at is untouched."""
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "host.py"
    outside.write_text("print('host file')\n")
    (project / "main.py").symlink_to(outside)

    logs: list[str] = []
    tm = nuitka_worker.task_manager
    mocker.patch.object(tm, "append_log", mocker.AsyncMock(side_effect=lambda _id, line: logs.append(line)))
    for name in ("set_stage", "set_result", "update_task", "set_process"):
        mocker.patch.object(tm, name, mocker.AsyncMock())
    mocker.patch.object(nuitka_worker, "detect_project_python_version", return_value=(None, "pure Python"))
    mocker.patch.object(nuitka_worker, "find_nuitka_python", return_value=(sys.executable, True))
    mocker.patch.object(nuitka_worker, "find_target_python", return_value=None)

    async def communicate():
        return b"2.8\n", b""

    spawn = mocker.patch.object(
        nuitka_worker.asyncio, "create_subprocess_exec",
        mocker.AsyncMock(return_value=SimpleNamespace(returncode=0, communicate=communicate)),
    )
    config = BuildConfig(project_path=str(project), source_type="local", entry_point="main.py")

    ok = await nuitka_worker.run_nuitka_build("task-entry", config, db=None)

    assert ok is False
    assert any("Entry point refused" in line for line in logs)
    assert not any("Injecting libs loader" in line for line in logs)
    assert outside.read_text() == "print('host file')\n"
    assert spawn.await_count == 1  # only the Nuitka version check ran

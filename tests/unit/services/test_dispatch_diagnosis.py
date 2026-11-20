"""
Tests that a failed build's diagnosis sees the build's preflight checks.
Source: app/services/build_dispatcher.start_build_task (the diagnosis step)

#21: the log is a ring of the last lines, so "No .venv found" from the start of
a long build may be gone by the time the failure is explained; the preflight
record is not.
"""

import contextlib

import pytest

from app.schemas.task import BuildConfig, BuildResult, ProjectType, TaskStatus
from app.services import build_dispatcher


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_fail_037_the_stored_preflight_reaches_the_diagnosis(mocker, tmp_path):
    """TC-FAIL-037: start_build_task — a failed build whose preflight says no .venv is
    diagnosed as such even though its log no longer mentions it."""
    tm = build_dispatcher.task_manager
    result = BuildResult(preflight=[{"label": "Project .venv present", "passed": False}])
    failed = mocker.Mock(status=TaskStatus.FAILED, stage="verify", result=result)
    mocker.patch.object(tm, "get_task", mocker.AsyncMock(return_value=failed))
    for name in ("update_task", "append_log"):
        mocker.patch.object(tm, name, mocker.AsyncMock())
    mocker.patch.object(tm, "get_logs", mocker.AsyncMock(return_value=["ModuleNotFoundError: No module named 'httpx'"]))
    merge = mocker.patch.object(tm, "merge_result", mocker.AsyncMock())

    @contextlib.asynccontextmanager
    async def session():
        yield mocker.MagicMock()

    mocker.patch("app.database.async_session", session)
    mocker.patch.object(build_dispatcher, "dispatch_build", mocker.AsyncMock())
    mocker.patch.object(build_dispatcher, "_record_duration", mocker.AsyncMock())
    mocker.patch.object(build_dispatcher.notifications, "notify_build_soon")

    @contextlib.asynccontextmanager
    async def turn(*_a):
        yield

    mocker.patch.object(build_dispatcher, "_project_turn", turn)
    config = BuildConfig(project_type=ProjectType.BACKEND_ONLY, project_path=str(tmp_path))
    await build_dispatcher.start_build_task("t-21", config)

    report = merge.await_args.args[1]
    assert report["diagnosis"][0]["problem"] == "The project has no .venv, so its packages were not bundled"

"""
Tests that a finished build hands its outcome to the notifications.
Source: app/services/build_dispatcher.start_build_task

Both ways a build can end after taking a slot are covered: the normal path
(after the failure diagnosis, so a message can include it) and a Git clone
that fails before anything is built.
"""

import contextlib

import pytest

from app.schemas.task import BuildConfig, ProjectType, SourceType, TaskStatus
from app.services import build_dispatcher


@pytest.fixture
def dispatcher(mocker):
    """start_build_task with its database, task store and workers replaced."""
    tm = build_dispatcher.task_manager
    for name in ("update_task", "append_log", "merge_result", "get_logs"):
        mocker.patch.object(tm, name, mocker.AsyncMock(return_value=[]))
    mocker.patch.object(tm, "get_task", mocker.AsyncMock(return_value=mocker.Mock(status=TaskStatus.COMPLETED)))

    @contextlib.asynccontextmanager
    async def session():
        yield mocker.MagicMock()

    mocker.patch("app.database.async_session", session)
    mocker.patch.object(build_dispatcher, "dispatch_build", mocker.AsyncMock())
    mocker.patch.object(build_dispatcher, "_record_duration", mocker.AsyncMock())
    mocker.patch.object(build_dispatcher, "_post_build_cleanup", mocker.AsyncMock())
    return mocker.patch.object(build_dispatcher.notifications, "notify_build_soon")


def _config(tmp_path, source=SourceType.LOCAL) -> BuildConfig:
    extra = {"git_url": "https://git.example.com/a.git", "git_ref": "main"} if source == SourceType.GIT else {}
    return BuildConfig(project_name="a", project_type=ProjectType.BACKEND_ONLY, source_type=source,
                       project_path=str(tmp_path), **extra)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_bnh_001_a_finished_build_is_announced(dispatcher, tmp_path):
    """TC-BNH-001: after the build, notifications are started for it, once."""
    await build_dispatcher.start_build_task("t-1", _config(tmp_path))
    dispatcher.assert_called_once_with("t-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_bnh_002_a_failed_clone_is_announced(dispatcher, tmp_path, mocker):
    """TC-BNH-002: a Git clone that fails ends the build as failed, and says so."""
    mocker.patch.object(build_dispatcher, "_prepare_git_workspace", mocker.AsyncMock(side_effect=RuntimeError("no such repo")))
    await build_dispatcher.start_build_task("t-2", _config(tmp_path, SourceType.GIT))
    dispatcher.assert_called_once_with("t-2")
    build_dispatcher.dispatch_build.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_bnh_003_a_build_cancelled_in_the_queue_is_not(dispatcher, tmp_path):
    """TC-BNH-003: cancelled before it started: nothing was built, nothing to announce."""
    build_dispatcher.task_manager.get_task.return_value.status = TaskStatus.CANCELLED
    await build_dispatcher.start_build_task("t-3", _config(tmp_path))
    dispatcher.assert_not_called()

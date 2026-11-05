"""
Unit tests for what the dispatcher records on a finished build's result.
Source: app/services/build_dispatcher (_build_frontend_only, _record_duration)

The detail page shows a build's duration and artifact from `result`. Only the
Nuitka worker used to fill it, so frontend builds showed neither.
"""

import pytest

from app.schemas.task import BuildConfig, ProjectType, TaskStatus
from app.services import build_dispatcher


@pytest.fixture
def tm(mocker):
    """The dispatcher's task_manager, with every call it makes recorded."""
    for name in ("update_task", "append_log", "merge_result"):
        mocker.patch.object(build_dispatcher.task_manager, name, mocker.AsyncMock())
    return build_dispatcher.task_manager


def _frontend_config(tmp_path, **overrides):
    return BuildConfig(
        project_name="web", project_type=ProjectType.FRONTEND_ONLY,
        project_path=str(tmp_path), frontend_dir=".", **overrides,
    )


class TestFrontendArtifact:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_brs_001_successful_frontend_build_records_its_output(self, tmp_path, mocker, tm):
        """TC-BRS-001: the output directory's size and file count land on the result."""
        (tmp_path / "dist" / "assets").mkdir(parents=True)
        (tmp_path / "dist" / "index.html").write_text("<html></html>")
        (tmp_path / "dist" / "assets" / "app.js").write_text("x" * 100)
        mocker.patch("app.services.frontend_worker.run_frontend_build", mocker.AsyncMock(return_value=True))

        await build_dispatcher._build_frontend_only("t1", _frontend_config(tmp_path), mocker.MagicMock())

        tm.merge_result.assert_awaited_once()
        artifact = tm.merge_result.await_args.args[1]["artifact"]
        assert artifact["file_count"] == 2
        assert artifact["size_bytes"] == len("<html></html>") + 100
        assert artifact["sha256"] is None  # a directory has no single digest
        tm.update_task.assert_any_await("t1", "status", TaskStatus.COMPLETED, mocker.ANY)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_brs_002_failed_frontend_build_records_no_artifact(self, tmp_path, mocker, tm):
        """TC-BRS-002: a failed build does not claim an artifact."""
        mocker.patch("app.services.frontend_worker.run_frontend_build", mocker.AsyncMock(return_value=False))

        await build_dispatcher._build_frontend_only("t1", _frontend_config(tmp_path), mocker.MagicMock())

        tm.merge_result.assert_not_awaited()


class TestRecordDuration:
    @staticmethod
    def _task(mocker, status):
        mocker.patch.object(
            build_dispatcher.task_manager, "get_task",
            mocker.AsyncMock(return_value=mocker.MagicMock(status=status) if status else None),
        )
        mocker.patch("app.database.async_session", mocker.MagicMock())

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [TaskStatus.COMPLETED, TaskStatus.FAILED])
    async def test_tc_brs_010_finished_builds_get_their_wall_time(self, mocker, tm, status):
        """TC-BRS-010: passed and failed builds both record a rounded duration."""
        self._task(mocker, status)
        await build_dispatcher._record_duration("t1", 12.345)
        tm.merge_result.assert_awaited_once_with("t1", {"duration_seconds": 12.3}, mocker.ANY)

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [TaskStatus.CANCELLED, None])
    async def test_tc_brs_011_cancelled_or_evicted_tasks_are_left_alone(self, mocker, tm, status):
        """TC-BRS-011: no duration for a cancelled build or one no longer in memory."""
        self._task(mocker, status)
        await build_dispatcher._record_duration("t1", 5.0)
        tm.merge_result.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_brs_012_bookkeeping_error_does_not_fail_the_build(self, mocker, tm):
        """TC-BRS-012: a DB error while recording is logged, not raised."""
        self._task(mocker, TaskStatus.COMPLETED)
        tm.merge_result.side_effect = RuntimeError("db gone")
        await build_dispatcher._record_duration("t1", 5.0)
        tm.append_log.assert_awaited_once()


class TestFailureStage:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_brs_020_frontend_step_names_its_stage(self, tmp_path, mocker, tm):
        """TC-BRS-020: a failing frontend build is explained as a frontend failure.

        Only the Nuitka worker set a stage, so a frontend failure kept 'queued' and its
        report said the build "ended while it was still queued"."""
        from app.services.error_diagnosis import build_failure_report

        mocker.patch("app.services.frontend_worker.run_frontend_build", mocker.AsyncMock(return_value=False))

        await build_dispatcher._build_frontend_only("t1", _frontend_config(tmp_path), mocker.MagicMock())

        tm.update_task.assert_any_await("t1", "stage", "frontend")
        problem = build_failure_report("unrecognized noise", stage="frontend")["diagnosis"][0]["problem"]
        assert "frontend" in problem.lower() and "queued" not in problem


class TestCancelStopsLaterSteps:
    """Cancelling a full-stack build while its frontend builds must stop the backend too."""

    @staticmethod
    def _fullstack(tmp_path):
        return BuildConfig(project_name="fs", project_type=ProjectType.FULLSTACK,
                           project_path=str(tmp_path), frontend_dir=".")

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize("frontend_result", [True, False], ids=["frontend-finished-as-cancelled", "frontend-killed"])
    async def test_tc_brs_030_backend_never_starts_after_cancel(self, tmp_path, mocker, tm, frontend_result):
        """TC-BRS-030: whether Cancel killed the frontend or landed just as it finished,
        the Nuitka step is never started."""
        mocker.patch("app.services.frontend_worker.run_frontend_build", mocker.AsyncMock(return_value=frontend_result))
        nuitka = mocker.patch("app.services.nuitka_worker.run_nuitka_build", mocker.AsyncMock(return_value=True))
        mocker.patch("app.services.process_runner.is_cancelled", mocker.AsyncMock(return_value=True))

        await build_dispatcher._build_fullstack("t1", self._fullstack(tmp_path), mocker.MagicMock())

        nuitka.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_brs_031_docker_fullstack_stops_at_every_step(self, tmp_path, mocker, tm):
        """TC-BRS-031: full stack + Docker: cancelled after the frontend → no Nuitka, no Docker."""
        mocker.patch("app.services.frontend_worker.run_frontend_build", mocker.AsyncMock(return_value=True))
        nuitka = mocker.patch("app.services.nuitka_worker.run_nuitka_build", mocker.AsyncMock(return_value=True))
        docker = mocker.patch("app.services.docker_worker.run_docker_build", mocker.AsyncMock(return_value=True))
        mocker.patch("app.services.process_runner.is_cancelled", mocker.AsyncMock(return_value=True))

        await build_dispatcher._build_docker_nuitka("t1", self._fullstack(tmp_path), mocker.MagicMock())

        nuitka.assert_not_awaited()
        docker.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_brs_032_uncancelled_build_runs_every_step(self, tmp_path, mocker, tm):
        """TC-BRS-032: the check does not get in the way of a build nobody cancelled."""
        mocker.patch("app.services.frontend_worker.run_frontend_build", mocker.AsyncMock(return_value=True))
        nuitka = mocker.patch("app.services.nuitka_worker.run_nuitka_build", mocker.AsyncMock(return_value=True))
        docker = mocker.patch("app.services.docker_worker.run_docker_build", mocker.AsyncMock(return_value=True))
        mocker.patch("app.services.process_runner.is_cancelled", mocker.AsyncMock(return_value=False))

        await build_dispatcher._build_docker_nuitka("t1", self._fullstack(tmp_path), mocker.MagicMock())

        nuitka.assert_awaited_once()
        docker.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_brs_033_cancel_during_compile_skips_the_image(self, tmp_path, mocker, tm):
        """TC-BRS-033: cancelled while Nuitka compiled (it finished anyway) → no Docker build."""
        mocker.patch("app.services.frontend_worker.run_frontend_build", mocker.AsyncMock(return_value=True))
        nuitka = mocker.patch("app.services.nuitka_worker.run_nuitka_build", mocker.AsyncMock(return_value=True))
        docker = mocker.patch("app.services.docker_worker.run_docker_build", mocker.AsyncMock(return_value=True))
        mocker.patch("app.services.process_runner.is_cancelled", mocker.AsyncMock(side_effect=[False, True]))

        await build_dispatcher._build_docker_nuitka("t1", TestCancelStopsLaterSteps._fullstack(tmp_path), mocker.MagicMock())

        nuitka.assert_awaited_once()
        docker.assert_not_awaited()

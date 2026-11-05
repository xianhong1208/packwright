"""
Unit tests for temporary changes to files in a user's project.
Source: app/services/source_guard, and its use in frontend_worker / docker_worker

Local-source builds edit the user's own files for the duration of a build. The
frontend .env original used to live only in memory and a failed install returned
before the restore, so an ordinary failed build replaced the user's real .env for
good; after a crash, the entry point kept the injected loader forever.
"""

import asyncio
import os
import stat

import pytest

from app.schemas.task import BuildConfig, ProjectType
from app.services import docker_worker, frontend_worker, source_guard
from app.services.source_guard import SourceGuard, recover_interrupted


@pytest.fixture
def journal(tmp_path, mocker):
    root = tmp_path / "journal"
    mocker.patch.object(source_guard, "journal_root", return_value=root)
    return root


class TestSourceGuard:
    @pytest.mark.unit
    def test_tc_sg_001_restore_puts_the_original_back(self, tmp_path, journal):
        """TC-SG-001: a replaced file gets its original content and mode back."""
        f = tmp_path / ".env"
        f.write_text("REAL=prod\n")
        f.chmod(0o640)
        guard = SourceGuard("t1")
        guard.write(f, "BUILD=1\n")
        assert f.read_text() == "BUILD=1\n"

        guard.restore()

        assert f.read_text() == "REAL=prod\n"
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o640
        assert not (journal / "t1").exists()

    @pytest.mark.unit
    def test_tc_sg_002_created_file_is_removed(self, tmp_path, journal):
        """TC-SG-002: a file the build created (Dockerfile.generated) is deleted again."""
        f = tmp_path / "Dockerfile.generated"
        guard = SourceGuard("t1")
        guard.write(f, "FROM x\n")
        guard.restore()
        assert not f.exists()

    @pytest.mark.unit
    def test_tc_sg_003_second_write_keeps_the_first_original(self, tmp_path, journal):
        """TC-SG-003: writing the same file twice (.dockerignore generated, then
        appended to) still restores what the user had before the build."""
        f = tmp_path / ".dockerignore"
        f.write_text("node_modules\n")
        guard = SourceGuard("t1")
        guard.write(f, "generated\n")
        guard.write(f, "generated\n!frontend/.env\n")
        guard.restore()
        assert f.read_text() == "node_modules\n"

    @pytest.mark.unit
    def test_tc_sg_004_restore_is_idempotent(self, tmp_path, journal):
        """TC-SG-004: restoring twice (explicitly, then from a finally) is harmless."""
        f = tmp_path / ".env"
        f.write_text("REAL=prod\n")
        guard = SourceGuard("t1")
        guard.write(f, "BUILD=1\n")
        guard.restore()
        f.write_text("user edited after the build\n")
        assert guard.restore() == []
        assert f.read_text() == "user edited after the build\n"

    @pytest.mark.unit
    @pytest.mark.parametrize("existed", [True, False])
    def test_tc_sg_005_journal_is_private(self, tmp_path, journal, existed):
        """TC-SG-005: the saved originals (often an .env with secrets) are in a 0700
        directory, whether the first change replaced a file or created one."""
        f = tmp_path / ".env"
        if existed:
            f.write_text("SECRET=1\n")
        SourceGuard("t1").write(f, "BUILD=1\n")
        assert stat.S_IMODE(os.stat(journal / "t1").st_mode) == 0o700


class TestRecoverInterrupted:
    @pytest.mark.unit
    def test_tc_sg_010_crash_mid_build_is_undone_at_startup(self, tmp_path, journal):
        """TC-SG-010: a build that never restored (process killed) is undone by the
        journal it left behind — the journal is written before the file changes."""
        env, made = tmp_path / ".env", tmp_path / "Dockerfile.generated"
        env.write_text("REAL=prod\n")
        guard = SourceGuard("crashed")
        guard.write(env, "BUILD=1\n")
        guard.write(made, "FROM x\n")
        del guard  # the process dies here: no restore()

        messages = recover_interrupted()

        assert env.read_text() == "REAL=prod\n"
        assert not made.exists()
        assert len(messages) == 2 and all("[crashed]" in m for m in messages)
        assert not (journal / "crashed").exists()

    @pytest.mark.unit
    def test_tc_sg_011_failed_restore_keeps_the_journal(self, tmp_path, journal, mocker):
        """TC-SG-011: if a file cannot be put back, its saved original is not thrown away."""
        f = tmp_path / ".env"
        f.write_text("REAL=prod\n")
        guard = SourceGuard("t1")
        guard.write(f, "BUILD=1\n")
        mocker.patch.object(source_guard.shutil, "copy2", side_effect=PermissionError(13, "denied"))

        messages = guard.restore()

        assert any("could not restore" in m for m in messages)
        assert (journal / "t1" / "manifest.json").exists()

    @pytest.mark.unit
    def test_tc_sg_012_empty_and_unreadable_journals(self, journal):
        """TC-SG-012: a journal dir without a manifest (died before changing anything) is
        removed; an unreadable manifest is left for a human rather than guessed at."""
        (journal / "empty").mkdir(parents=True)
        (journal / "garbled").mkdir()
        (journal / "garbled" / "manifest.json").write_text("{not json")

        assert recover_interrupted() == []
        assert not (journal / "empty").exists()
        assert (journal / "garbled").exists()


def _quiet_task_manager(mocker, module):
    for name in ("append_log", "update_task", "set_process"):
        mocker.patch.object(module.task_manager, name, mocker.AsyncMock())


class TestWorkersRestoreOnEveryPath:
    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize("outcome", ["install fails", "cancelled"])
    async def test_tc_sg_020_frontend_env_survives_a_failed_build(self, tmp_path, journal, mocker, outcome):
        """TC-SG-020: the user's .env is back after a failed install or a cancellation —
        it used to stay replaced by the build's env content."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / ".env").write_text("REAL=prod\n")
        _quiet_task_manager(mocker, frontend_worker)
        mocker.patch("shutil.which", return_value="/usr/bin/npm")  # imported inside the function
        seen = []

        async def run(task_id, cmd, cwd, *a, **k):
            seen.append((tmp_path / ".env").read_text())
            if outcome == "cancelled":
                raise asyncio.CancelledError
            return False

        mocker.patch.object(frontend_worker, "_run_command", side_effect=run)
        config = BuildConfig(project_name="w", project_type=ProjectType.FRONTEND_ONLY, project_path=str(tmp_path),
                             frontend_dir=".", frontend_env_content="BUILD=1\n")

        if outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await frontend_worker.run_frontend_build("t1", config, mocker.MagicMock())
        else:
            assert await frontend_worker.run_frontend_build("t1", config, mocker.MagicMock()) is False

        assert seen == ["BUILD=1\n"]  # the build saw the configured env ...
        assert (tmp_path / ".env").read_text() == "REAL=prod\n"  # ... and the user's is back

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize("outcome", ["build fails", "cancelled"])
    async def test_tc_sg_021_docker_files_are_restored_after_a_failed_build(self, tmp_path, journal, mocker, outcome):
        """TC-SG-021: after a failed or cancelled docker build the project's .dockerignore
        is the user's again and Dockerfile.generated is gone."""
        (tmp_path / ".dockerignore").write_text("mine\n")
        (tmp_path / "dist").mkdir()
        _quiet_task_manager(mocker, docker_worker)
        mocker.patch.object(docker_worker.shutil, "which", return_value="/usr/bin/docker")
        mocker.patch.object(docker_worker, "_run_docker_command", mocker.AsyncMock(
            side_effect=asyncio.CancelledError if outcome == "cancelled" else None, return_value=False))
        config = BuildConfig(project_name="b", project_type=ProjectType.BACKEND_ONLY, project_path=str(tmp_path),
                             docker_enabled=True)

        if outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await docker_worker.run_docker_build("t1", config, mocker.MagicMock(), precompiled=True)
        else:
            assert await docker_worker.run_docker_build("t1", config, mocker.MagicMock(), precompiled=True) is False

        assert (tmp_path / ".dockerignore").read_text() == "mine\n"
        assert not (tmp_path / "Dockerfile.generated").exists()
        assert not list(tmp_path.glob("*.bak"))


class TestWorkspaceSweepSkipsServiceDirs:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_sg_030_orphan_sweep_leaves_dot_directories(self, tmp_path, mocker):
        """TC-SG-030: .restore (a journal kept because a restore failed) and .scratch are
        not task workspaces; the orphan sweep used to delete them after two days."""
        from app.services import workspace_cleanup

        for name in (".restore", ".scratch", "0b1e6c3a-orphan"):
            (tmp_path / name).mkdir()
            os.utime(tmp_path / name, (0, 0))  # far older than any TTL
        mocker.patch.object(workspace_cleanup, "get_settings", return_value=mocker.MagicMock(
            workspace_cleanup_enabled=True, git_workspace_dir=str(tmp_path),
            workspace_success_ttl_days=7, workspace_failed_ttl_days=30, workspace_orphan_ttl_days=2))
        db = mocker.MagicMock()
        db.execute = mocker.AsyncMock(return_value=mocker.MagicMock(
            scalars=lambda: mocker.MagicMock(all=lambda: [])))
        session = mocker.MagicMock()
        session.__aenter__ = mocker.AsyncMock(return_value=db)
        session.__aexit__ = mocker.AsyncMock(return_value=False)
        mocker.patch.object(workspace_cleanup, "async_session", return_value=session)

        summary = await workspace_cleanup.sweep_workspaces()

        assert summary["deleted_orphan"] == 1
        assert (tmp_path / ".restore").exists() and (tmp_path / ".scratch").exists()
        assert not (tmp_path / "0b1e6c3a-orphan").exists()

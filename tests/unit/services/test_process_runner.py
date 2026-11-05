"""
Unit tests for running build steps as cancellable process groups (real processes).
Source: app/services/process_runner

Cancel used to signal only the top process: Nuitka's scons and gcc children and
npm's node children were reparented to init and kept running, the frontend worker
registered no process at all, and a cancelled full-stack build started its next
step anyway.
"""

import asyncio
import os
import time

import pytest

from app.schemas.task import TaskStatus
from app.services import process_runner
from app.services.process_runner import run_step


def _group_alive(pgid: int, settle: float = 3.0) -> bool:
    """Whether any process is still in the group once killed ones have been reaped.

    A killed grandchild is reparented to init, which reaps it asynchronously, so a
    check right after the kill can still see it as a zombie for a moment (CI runners
    are slower at this than a workstation). Poll briefly instead of racing init.
    """
    end = time.monotonic() + settle
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        if time.monotonic() > end:
            return True
        time.sleep(0.05)


@pytest.fixture
def tm(mocker):
    """task_manager with a running task; records the handle registered for Cancel."""
    state = {"status": TaskStatus.RUNNING, "handles": [], "log": []}

    async def get_task(task_id):
        return mocker.MagicMock(status=state["status"])

    async def set_process(task_id, handle):
        state["handles"].append(handle)

    async def append_log(task_id, line):
        state["log"].append(line)

    mocker.patch.object(process_runner.task_manager, "get_task", side_effect=get_task)
    mocker.patch.object(process_runner.task_manager, "set_process", side_effect=set_process)
    mocker.patch.object(process_runner.task_manager, "append_log", side_effect=append_log)
    return state


class TestRunStep:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_pr_001_streams_output_and_reports_exit(self, tmp_path, tm):
        """TC-PR-001: output lines reach the log; exit status decides ok."""
        good = await run_step("t1", ["sh", "-c", "echo one; echo two"], cwd=tmp_path)
        bad = await run_step("t1", ["sh", "-c", "exit 3"], cwd=tmp_path)
        assert good.ok and tm["log"][:2] == ["one", "two"]
        assert not bad.ok and bad.returncode == 3

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_pr_002_cancel_stops_the_whole_tree(self, tmp_path, tm):
        """TC-PR-002: terminate() on the registered handle — what Cancel calls — stops the
        command's children too, not only the process at the top."""
        script = "sleep 60 & sleep 60 & echo started; wait"
        step = asyncio.create_task(run_step("t1", ["sh", "-c", script], cwd=tmp_path))
        while "started" not in tm["log"]:
            await asyncio.sleep(0.05)
        handle = tm["handles"][0]

        started = time.monotonic()
        handle.terminate()
        result = await asyncio.wait_for(step, timeout=10)

        assert not result.ok and time.monotonic() - started < 5
        assert not _group_alive(handle.pid)
        assert tm["handles"][-1] is None  # unregistered when done

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_pr_003_timeout_kills_the_group(self, tmp_path, tm):
        """TC-PR-003: a step past its timeout is killed with everything it started."""
        result = await run_step("t1", ["sh", "-c", "sleep 60 & wait"], cwd=tmp_path, timeout=0.5)
        assert result.timed_out and not result.ok
        assert not _group_alive(tm["handles"][0].pid)
        assert any("timed out" in line for line in tm["log"])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_pr_004_stragglers_die_with_the_step(self, tmp_path, tm):
        """TC-PR-004: a background process the step leaves behind does not outlive it."""
        result = await run_step("t1", ["sh", "-c", "sleep 60 >/dev/null 2>&1 & echo done"], cwd=tmp_path)
        assert result.ok
        await asyncio.sleep(0.2)
        assert not _group_alive(tm["handles"][0].pid)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_pr_005_cancelled_task_starts_no_new_step(self, tmp_path, tm):
        """TC-PR-005: after Cancel, the next step of the build is not started."""
        tm["status"] = TaskStatus.CANCELLED
        marker = tmp_path / "ran"
        result = await run_step("t1", ["touch", str(marker)], cwd=tmp_path)
        assert result.cancelled and not result.ok
        assert not marker.exists() and tm["handles"] == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_pr_006_failing_output_handler_still_cleans_up(self, tmp_path, tm):
        """TC-PR-006: if handling output raises, the group is killed and unregistered."""
        async def boom(lines, frame):
            if lines:
                raise RuntimeError("handler broke")

        with pytest.raises(RuntimeError):
            await run_step("t1", ["sh", "-c", "echo hi; sleep 60"], cwd=tmp_path, on_output=boom)
        assert not _group_alive(tm["handles"][0].pid)
        assert tm["handles"][-1] is None

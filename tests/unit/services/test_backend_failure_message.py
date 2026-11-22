"""
Tests for what a failed backend build says.
Source: app/services/build_dispatcher.py (_backend_failure_message)

A failed smoke test made run_nuitka_build return False, and the task then said
"Nuitka compilation failed" although the compile had succeeded.
"""

import pytest

from app.services import build_dispatcher


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(("stage", "smoke"), [("verify", True), ("compile", False), ("bundle", False)])
async def test_tc_bfm_001_a_failed_smoke_test_says_so(mocker, stage, smoke):
    """TC-BFM-001: at stage verify the message names the smoke test; otherwise the caller's message stands."""
    task = mocker.MagicMock(stage=stage)
    mocker.patch.object(build_dispatcher.task_manager, "get_task", mocker.AsyncMock(return_value=task))

    message = await build_dispatcher._backend_failure_message("t1", "Nuitka compilation failed")

    assert message.startswith("Smoke test failed") is smoke
    assert (message == "Nuitka compilation failed") is (not smoke)

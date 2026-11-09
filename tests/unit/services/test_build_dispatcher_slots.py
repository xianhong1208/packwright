"""
Tests for counting the builds that hold a build slot.
Source: app/services/build_dispatcher.py (_holding_slot, builds_in_slot)

The Nuitka worker divides the cores by this count, so it has to come back down
however a build ends; a count that only grows would starve every later build.
"""

import pytest

from app.services import build_dispatcher


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_slot_001_count_follows_the_slot():
    """TC-SLOT-001: counted while inside, released after, nested builds add up."""
    before = build_dispatcher.builds_in_slot()
    async with build_dispatcher._holding_slot():
        async with build_dispatcher._holding_slot():
            assert build_dispatcher.builds_in_slot() == before + 2
        assert build_dispatcher.builds_in_slot() == before + 1
    assert build_dispatcher.builds_in_slot() == before


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_slot_002_a_failed_build_gives_its_share_back():
    """TC-SLOT-002: a build that raises is no longer counted."""
    before = build_dispatcher.builds_in_slot()
    with pytest.raises(RuntimeError):
        async with build_dispatcher._holding_slot():
            raise RuntimeError("compile failed")
    assert build_dispatcher.builds_in_slot() == before


@pytest.fixture
def queue(mocker, monkeypatch):
    """start_build_task with two build slots and builds that run until released."""
    import asyncio
    import contextlib
    from types import SimpleNamespace

    from app.schemas.task import TaskStatus

    monkeypatch.setattr(build_dispatcher, "_build_semaphore", asyncio.Semaphore(2))
    state = SimpleNamespace(started=[], release={}, status={})

    async def fake_dispatch(task_id, config, db):
        state.started.append(task_id)
        await state.release.setdefault(task_id, asyncio.Event()).wait()

    @contextlib.asynccontextmanager
    async def session():
        yield None

    tm = build_dispatcher.task_manager
    for name in ("update_task", "append_log", "merge_result"):
        mocker.patch.object(tm, name, mocker.AsyncMock())
    mocker.patch.object(tm, "get_logs", mocker.AsyncMock(return_value=[]))
    mocker.patch.object(tm, "get_task", mocker.AsyncMock(
        side_effect=lambda tid: SimpleNamespace(status=state.status.get(tid, TaskStatus.RUNNING))))
    mocker.patch("app.database.async_session", session)
    mocker.patch.object(build_dispatcher, "dispatch_build", side_effect=fake_dispatch)
    mocker.patch.object(build_dispatcher, "_record_duration", mocker.AsyncMock())
    mocker.patch.object(build_dispatcher.notifications, "notify_build_soon")
    return state


def _local(path: str):
    from app.schemas.task import BuildConfig

    return BuildConfig(project_path=path, source_type="local")


async def _settle():
    import asyncio

    for _ in range(20):
        await asyncio.sleep(0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_slot_003_a_build_waiting_for_its_folder_holds_no_slot(queue):
    """TC-SLOT-003: with two slots, a second build of a busy folder waits for the folder
    without taking a slot, so a build of another folder starts at once."""
    import asyncio

    a = asyncio.create_task(build_dispatcher.start_build_task("a", _local("/srv/projects/shop")))
    await _settle()
    b = asyncio.create_task(build_dispatcher.start_build_task("b", _local("/srv/projects/shop")))
    await _settle()
    c = asyncio.create_task(build_dispatcher.start_build_task("c", _local("/srv/projects/blog")))
    await _settle()

    assert queue.started == ["a", "c"]
    assert build_dispatcher.builds_in_slot() == 2

    queue.release["a"].set()
    await _settle()
    assert queue.started == ["a", "c", "b"]  # b goes once its folder is free
    queue.release["b"] = queue.release.get("b") or asyncio.Event()
    for event in queue.release.values():
        event.set()
    await asyncio.gather(a, b, c)
    assert build_dispatcher.builds_in_slot() == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_slot_004_cancelled_while_waiting_for_the_folder(queue):
    """TC-SLOT-004: a build cancelled while it waits for its folder is skipped as soon as
    the folder is free, without then waiting for a slot or being built."""
    import asyncio

    from app.schemas.task import TaskStatus

    a = asyncio.create_task(build_dispatcher.start_build_task("a", _local("/srv/projects/shop")))
    c = asyncio.create_task(build_dispatcher.start_build_task("c", _local("/srv/projects/blog")))
    await _settle()
    d = asyncio.create_task(build_dispatcher.start_build_task("d", _local("/srv/projects/docs")))  # waits for a slot
    b = asyncio.create_task(build_dispatcher.start_build_task("b", _local("/srv/projects/shop")))  # waits for shop
    await _settle()
    queue.status["b"] = TaskStatus.CANCELLED

    queue.release["a"].set()  # a's slot goes to d, which asked first
    await _settle()

    assert b.done()
    assert queue.started == ["a", "c", "d"]
    for name in ("c", "d"):
        queue.release[name].set()
    await asyncio.gather(a, b, c, d)

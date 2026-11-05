"""Run one build step as a process group on a PTY, cancellable as a whole.

All three workers used to spawn their tools with their own copy of the same PTY
loop, and none of them could stop what they started:

- Cancel sent SIGTERM to the top process only. Nuitka's compile runs in scons and
  dozens of gcc children, npm runs the build script in node: those were reparented
  to init and kept compiling, while the UI said "cancelled".
- The frontend worker never registered its process at all, so Cancel did not
  stop an npm install or build in any way.
- A cancelled full-stack build went on to its next step (the Nuitka compile) as
  soon as the current one finished.

Here every step runs in its own session (``start_new_session``), so the step's
whole process tree shares one process group; the handle registered with the task
manager signals that group, a timeout kills the group, and leftovers are reaped
when the step ends. A step of a task that is already cancelled is not started.
"""
from __future__ import annotations

import asyncio
import os
import pty
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app.schemas.task import TaskStatus
from app.services.task_manager import task_manager
from app.services.terminal_output import TerminalLineBuffer

OutputHandler = Callable[[list[str], str | None], Awaitable[None]]


class ProcessGroup:
    """What the task manager holds for a running step: signals reach the whole tree."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process
        self.pid = process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    def send_signal(self, sig: int) -> None:
        try:
            os.killpg(self.pid, sig)
        except ProcessLookupError:
            pass  # the whole group is already gone

    def terminate(self) -> None:
        self.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        self.send_signal(signal.SIGKILL)

    async def wait(self) -> int:
        return await self._process.wait()


@dataclass
class StepResult:
    returncode: int | None
    timed_out: bool = False
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled


async def is_cancelled(task_id: str) -> bool:
    task = await task_manager.get_task(task_id)
    return task is not None and task.status == TaskStatus.CANCELLED


async def run_step(
    task_id: str,
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    on_output: OutputHandler | None = None,
) -> StepResult:
    """Run ``cmd`` on a PTY in its own process group and stream its output.

    ``on_output(lines, frame)`` gets completed lines (to log) and the progress
    frame being redrawn in place (for progress only); by default lines go to the
    task log. The group is registered with the task manager while it runs, so
    Cancel stops all of it.
    """
    if await is_cancelled(task_id):
        await task_manager.append_log(task_id, f"Skipped (build cancelled): {' '.join(cmd)}")
        return StepResult(None, cancelled=True)

    async def log_lines(lines: list[str], _frame: str | None) -> None:
        for line in lines:
            await task_manager.append_log(task_id, line)

    handle_output = on_output or log_lines
    master_fd, slave_fd = pty.openpty()
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            cwd=str(cwd), env=env, start_new_session=True,
        )
    except BaseException:
        os.close(master_fd)
        raise
    finally:
        os.close(slave_fd)

    group = ProcessGroup(process)
    await task_manager.set_process(task_id, group)
    os.set_blocking(master_fd, False)
    terminal = TerminalLineBuffer()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout if timeout else None
    timed_out = False

    def read() -> bytes:
        try:
            return os.read(master_fd, 65536)
        except OSError:  # incl. BlockingIOError: nothing to read right now
            return b""

    try:
        while process.returncode is None:
            if deadline is not None and loop.time() > deadline:
                timed_out = True
                group.kill()
                await process.wait()
                break
            data = read()
            if data:
                await handle_output(*terminal.feed(data))
            else:
                await asyncio.sleep(0.1)
        while data := read():
            await handle_output(*terminal.feed(data))
        await handle_output(terminal.flush(), None)
        returncode = await process.wait()
    finally:
        # Whatever the step left running in its group (a background watcher, a
        # straggling compiler) dies with it — including when this coroutine is
        # cancelled or the output handler raises.
        group.kill()
        os.close(master_fd)
        # Reap the leader on every path (an exception skips the wait above),
        # or it stays a zombie holding the group.
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
        await task_manager.set_process(task_id, None)

    if timed_out:
        await task_manager.append_log(
            task_id, f"Error: command timed out after {timeout:.0f}s and was stopped: {' '.join(cmd)}"
        )
    return StepResult(returncode, timed_out=timed_out, cancelled=await is_cancelled(task_id))

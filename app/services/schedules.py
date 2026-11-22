"""Scheduled builds: reading cron expressions, and the loop that runs them.

A schedule (app/models/schedule) names a branch or tag, a 5-field cron
expression and the time zone it is read in. When a run is due the scheduler:

1. claims it, by moving ``next_run_at`` to the next slot after *now* with a
   conditional UPDATE (``WHERE next_run_at = <the due time it read>``). Only one
   of several loops ticking at once updates the row, on SQLite and PostgreSQL
   alike, so a run fires once. Computing the next slot from now, never from the
   missed one, is also what keeps a restart from replaying missed runs: a run
   found more than ``MISSED_AFTER`` late is recorded as missed and not built;
2. checks the person it runs as (``triggered_builds.may_build``) and turns the
   schedule off with the reason when they can no longer build;
3. skips when a build of the project is queued or running (no overlap);
4. resolves the ref to a commit with ``git ls-remote``;
5. skips when "unchanged": the commit and the effective settings, packwright.toml's
   values included (``settings_fingerprint``, ``_same_settings``), equal those of
   the project's last successful build of the same ref;
6. otherwise files the build of exactly that commit, trigger ``schedule``.

Every run leaves a row in ``schedule_runs`` (the newest ``RUNS_KEPT``).

Cron expressions are read by ``cronsim`` (BSD-3-Clause, no dependencies, the
library behind Healthchecks.io's cron checks). Daylight-saving time follows it:
a slot inside a spring-forward gap (02:30 on the night clocks jump from 02:00 to
03:00) runs once at 03:00, the first moment that exists; a fixed-time slot inside
the repeated autumn hour runs once, at its first occurrence. Expressions with
``*`` or a step in the hour field run in both copies of the repeated hour.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

from cronsim import CronSim, CronSimError
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.project import Project
from app.models.schedule import ProjectSchedule, ScheduleRun
from app.models.task import Task
from app.schemas.task import BuildConfig, SourceType, TaskStatus
from app.services.audit import AuditAction, AuditStatus, ResourceType, log_action
from app.services.build_dispatcher import start_build_task
from app.services.projects import config_for_build
from app.services.triggered_builds import may_build, submit_build, submit_lock

logger = logging.getLogger(__name__)

# How often the loop looks for due runs.
TICK_SECONDS = 10
# A run found this late was due while Packwright was not running (or the loop
# was stuck): it is recorded as missed and not built. Missed runs are never made up.
MISSED_AFTER = timedelta(minutes=2)
# Runs kept per schedule, newest first.
RUNS_KEPT = 50
# Next run times the console shows while a schedule is being written.
PREVIEW_COUNT = 5

ALIASES: dict[str, str] = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


class ScheduleError(ValueError):
    """A cron expression or time zone that cannot be used; the message says why."""


def _utc(value: datetime) -> datetime:
    """``value`` in UTC. SQLite hands back naive datetimes; they were stored as UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def expand(cron: str) -> str:
    """The five fields an expression stands for (an @alias is replaced)."""
    return ALIASES.get(cron, cron)


def normalise_cron(raw: str) -> str:
    """``raw`` with its spacing tidied, or ScheduleError saying what is wrong with it.

    Exactly five fields (minute hour day-of-month month day-of-week), or one of
    the @aliases. cronsim would also take a sixth, seconds field; a build server
    has no use for it and it would read "0 0 * * * *" as hourly, not daily.
    """
    cron = " ".join((raw or "").split())
    if not cron:
        raise ScheduleError("Enter a cron expression, e.g. 0 2 * * * for every night at 02:00")
    if len(cron) > 100:
        raise ScheduleError("The cron expression is too long")
    if cron.startswith("@"):
        if cron.lower() not in ALIASES:
            raise ScheduleError(f"Unknown shortcut {cron}; use one of {', '.join(ALIASES)}")
        return cron.lower()
    fields = cron.split(" ")
    if len(fields) != 5:
        raise ScheduleError(
            f"A cron expression has 5 fields (minute hour day-of-month month day-of-week); this one has {len(fields)}"
        )
    try:
        CronSim(cron, datetime.now(timezone.utc))
    except CronSimError as exc:
        raise ScheduleError(f"Invalid cron expression: {exc}") from None
    return cron


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(available_timezones())


def valid_timezone(raw: str) -> str:
    """``raw`` if it is an IANA time zone this server knows, else ScheduleError."""
    name = (raw or "").strip()
    if name not in _zones():
        raise ScheduleError(f"Unknown time zone {name!r}; use an IANA name such as Asia/Taipei or UTC")
    return name


def server_timezone() -> str:
    """The zone new schedules default to: SCHEDULE_TIMEZONE, else the server's own, else UTC."""
    candidates = [get_settings().schedule_timezone, os.environ.get("TZ", "").lstrip(":")]
    try:
        candidates.append(Path("/etc/timezone").read_text().strip())
    except OSError:
        pass
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            candidates.append(target.split("zoneinfo/", 1)[1])
    except OSError:
        pass
    for name in candidates:
        if name and name in _zones():
            return name
    return "UTC"


def next_runs(cron: str, tz: str, after: datetime, count: int = 1) -> list[datetime]:
    """The next ``count`` slots strictly after ``after``, in UTC."""
    it = CronSim(expand(cron), _utc(after).astimezone(ZoneInfo(tz)))
    return [_utc(next(it)) for _ in range(count)]


def next_run(cron: str, tz: str, after: datetime) -> datetime:
    return next_runs(cron, tz, after, 1)[0]


def describe(cron: str) -> str | None:
    """A sentence for the expression ("At 02:00 every day"), when cronsim can say one."""
    try:
        return CronSim(expand(cron), datetime.now(timezone.utc)).explain()
    except Exception:  # explain() is a nicety; an expression it cannot word is still valid
        return None


def settings_fingerprint(config: BuildConfig | dict) -> str:
    """What "the same settings" means for skip-unchanged.

    The SHA-256 of the complete build configuration a build is filed with (the
    project's saved settings with the schedule's branch or tag on top, exactly
    what history.config stores), read through BuildConfig so that a setting added
    to Packwright since an old build compares by its default, and written as JSON
    with sorted keys. Any difference, a version label included, makes it differ.
    """
    if isinstance(config, dict):
        config = BuildConfig.model_validate(config)
    canonical = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def last_successful_build(db: AsyncSession, project_id: int, ref: str, ref_type: str) -> Task | None:
    """The project's most recent completed build of this branch or tag."""
    rows = (
        await db.execute(
            select(Task)
            .where(Task.project_id == project_id, Task.status == TaskStatus.COMPLETED)
            .order_by(Task.start_time.desc())
            .limit(200)
        )
    ).scalars().all()
    for task in rows:
        cfg = task.config or {}
        if cfg.get("git_ref") == ref and (cfg.get("git_ref_type") or "branch") == ref_type:
            return task
    return None


async def _active_build(db: AsyncSession, project_id: int) -> Task | None:
    return (
        await db.execute(
            select(Task)
            .where(Task.project_id == project_id, Task.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]))
            .limit(1)
        )
    ).scalars().first()


async def _record(
    db: AsyncSession,
    schedule: ProjectSchedule,
    due: datetime,
    now: datetime,
    result: str,
    reason: str | None = None,
    *,
    commit_sha: str | None = None,
    task_id: str | None = None,
) -> ScheduleRun:
    run = ScheduleRun(
        schedule_id=schedule.id,
        due_at=due,
        ran_at=now,
        result=result,
        reason=reason[:300] if reason else None,
        commit_sha=commit_sha,
        task_id=task_id,
    )
    db.add(run)
    await db.flush()
    keep = (
        await db.execute(
            select(ScheduleRun.id).where(ScheduleRun.schedule_id == schedule.id)
            .order_by(ScheduleRun.id.desc()).limit(RUNS_KEPT)
        )
    ).scalars().all()
    await db.execute(delete(ScheduleRun).where(ScheduleRun.schedule_id == schedule.id, ScheduleRun.id.not_in(keep)))
    await db.commit()
    return run


async def _turn_off(db: AsyncSession, schedule: ProjectSchedule, reason: str) -> None:
    schedule.enabled, schedule.disabled_reason, schedule.next_run_at = False, reason[:300], None
    await db.commit()
    await log_action(
        db, AuditAction.SCHEDULE_DISABLED, ResourceType.SCHEDULE, AuditStatus.SUCCESS,
        resource_id=schedule.id, error_message=reason,
        details={"project_id": schedule.project_id, "cron": schedule.cron, "runs_as": schedule.created_by},
    )


# Builds the scheduler started, kept so the event loop does not drop them.
_started: set[asyncio.Task] = set()


def _start(task_id: str, config: BuildConfig, commit: str) -> None:
    job = asyncio.create_task(start_build_task(task_id, config, commit), name=f"scheduled-build-{task_id}")
    _started.add(job)
    job.add_done_callback(_started.discard)


async def claim(db: AsyncSession, schedule: ProjectSchedule, now: datetime) -> bool:
    """Take the run due at ``schedule.next_run_at``; False when another loop took it.

    The next slot is counted from ``now``, never from the run being taken, so
    after downtime the schedule resumes at its next slot instead of replaying.
    """
    due = schedule.next_run_at
    try:
        following = next_run(schedule.cron, schedule.timezone, now)
    except (CronSimError, ValueError, KeyError) as exc:
        # The expression or zone stopped being usable (tzdata changed under it).
        reason = f"its cron expression or time zone can no longer be read ({exc})"
        await _turn_off(db, schedule, reason)
        await _record(db, schedule, _utc(due), now, "failed", f"schedule turned off: {reason}")
        return False
    result = await db.execute(
        update(ProjectSchedule)
        .where(
            ProjectSchedule.id == schedule.id,
            ProjectSchedule.enabled.is_(True),
            ProjectSchedule.next_run_at == due,
        )
        .values(next_run_at=following, last_run_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        return False
    await db.commit()
    await db.refresh(schedule)
    return True


async def fire(db: AsyncSession, schedule: ProjectSchedule, due: datetime, now: datetime) -> ScheduleRun:
    """Run a claimed slot: build, or record why not."""
    if now - due > MISSED_AFTER:
        local = f"{due.astimezone(ZoneInfo(schedule.timezone)):%Y-%m-%d %H:%M} {schedule.timezone}"
        return await _record(db, schedule, due, now, "skipped",
                             f"missed: Packwright was not running at {local}; missed runs are not made up")

    runner, reason = await may_build(db, schedule.created_by_id)
    if runner is None:
        await _turn_off(db, schedule, reason)
        return await _record(db, schedule, due, now, "failed", f"schedule turned off: {reason}")
    project = await db.get(Project, schedule.project_id)
    if project is None or project.source_type != SourceType.GIT.value:
        reason = "the project no longer builds from a Git URL"
        await _turn_off(db, schedule, reason)
        return await _record(db, schedule, due, now, "failed", f"schedule turned off: {reason}")

    busy = await _active_build(db, project.id)
    if busy is not None:
        return await _record(db, schedule, due, now, "skipped",
                             f"overlap: build {busy.task_id[:8]} of this project is still queued or running",
                             task_id=busy.task_id)

    from app.api.routes.tasks import _validate_build_config_paths
    from app.services import git_credentials, git_service

    try:
        config = config_for_build(project, {"git_ref": schedule.ref, "git_ref_type": schedule.ref_type})
        _validate_build_config_paths(config)
    except (ValueError, ValidationError, HTTPException) as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        return await _record(db, schedule, due, now, "failed", f"the project's settings cannot make a build: {detail}")

    kind = "branch" if schedule.ref_type == "branch" else "tag"
    try:
        token, provider = await git_credentials.resolve_for_url(db, config.git_url)
        commit = await git_service.resolve_ref(
            config.git_url, schedule.ref, schedule.ref_type, token, provider=provider, timeout=30.0,
        )
    except Exception as exc:  # GitUrlError (masked), an undecryptable credential, a timeout
        return await _record(db, schedule, due, now, "failed", f"could not read {kind} {schedule.ref}: {exc}")

    if schedule.skip_unchanged:
        last = await last_successful_build(db, project.id, schedule.ref, schedule.ref_type)
        if last is not None and last.commit_sha == commit and _same_settings(last, config):
            return await _record(
                db, schedule, due, now, "skipped",
                f"unchanged: commit {commit[:12]} and the settings were built as {last.task_id[:8]}",
                commit_sha=commit, task_id=last.task_id,
            )

    async with submit_lock:
        # Again, now that nothing else can file a build in between.
        busy = await _active_build(db, project.id)
        if busy is not None:
            return await _record(db, schedule, due, now, "skipped",
                                 f"overlap: build {busy.task_id[:8]} of this project is still queued or running",
                                 commit_sha=commit, task_id=busy.task_id)
        try:
            task, config = await submit_build(
                db, project, runner, trigger="schedule", ref=schedule.ref, ref_type=schedule.ref_type, commit=commit,
            )
        except (ValueError, ValidationError, HTTPException) as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            return await _record(db, schedule, due, now, "failed",
                                 f"the project's settings cannot make a build: {detail}", commit_sha=commit)
    run = await _record(db, schedule, due, now, "built", None, commit_sha=commit, task_id=task.id)
    _start(task.id, config, commit)
    return run


def _same_settings(last: Task, config: BuildConfig) -> bool:
    """Would this run build with exactly the settings ``last`` was built with?

    Compared on the *effective* settings, packwright.toml's values included.
    The run is only compared with a build of the same commit, so the file is the
    same file: what this run would build is ``config`` with the values ``last``
    took from it on top. (A changed packwright.toml is a new commit, and a new
    commit is always built.) A build from before packwright.toml was read is
    compared on the settings it was filed with, as before.
    """
    from app.services.packwright_toml import file_values

    if not last.config:
        return False
    try:
        taken = file_values(last.effective_config)
        if taken is None:
            return settings_fingerprint(last.config) == settings_fingerprint(config)
        candidate = {**config.model_dump(mode="json"), **taken}
        return settings_fingerprint(last.effective_config["config"]) == settings_fingerprint(candidate)
    except (ValidationError, ValueError, KeyError, TypeError):
        return False


async def run_due(now: datetime | None = None) -> list[ScheduleRun]:
    """Handle every run due by ``now``; what each came to."""
    from app.database import async_session

    now = _utc(now or datetime.now(timezone.utc))
    async with async_session() as db:
        due_ids = (
            await db.execute(
                select(ProjectSchedule.id)
                .where(ProjectSchedule.enabled.is_(True), ProjectSchedule.next_run_at.is_not(None),
                       ProjectSchedule.next_run_at <= now)
                .order_by(ProjectSchedule.next_run_at)
            )
        ).scalars().all()
    runs: list[ScheduleRun] = []
    for schedule_id in due_ids:
        try:
            async with async_session() as db:
                schedule = await db.get(ProjectSchedule, schedule_id)
                if schedule is None or not schedule.enabled or schedule.next_run_at is None:
                    continue
                due = _utc(schedule.next_run_at)
                if due > now or not await claim(db, schedule, now):
                    continue
                runs.append(await fire(db, schedule, due, now))
        except Exception:
            # One schedule's failure must not stop the others, or the loop.
            logger.exception("Scheduled run of schedule %s failed", schedule_id)
    return runs


async def scheduler_loop() -> None:
    """Look for due runs every TICK_SECONDS, for as long as the app runs."""
    if not get_settings().schedules_enabled:
        logger.info("Scheduled builds are off (SCHEDULES_ENABLED=false)")
        return
    if not _zones():
        logger.warning("No time zone data found: schedules cannot be created (install tzdata)")
    while True:
        try:
            await run_due()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("The scheduler loop raised an exception")
        await asyncio.sleep(TICK_SECONDS)

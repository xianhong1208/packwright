"""Scheduled builds: managing a project's schedules and reading their runs.

Everyone who may build sees a project's schedules; the project's creator and
holders of project:manage change them (as with webhooks). None of these routes
is in api_tokens.TOKEN_ROUTES, so an API token cannot create or change one. The
runs themselves are made by the scheduler loop (app/services/schedules).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_client_ip
from app.database import get_db
from app.models.project import Project
from app.models.schedule import ProjectSchedule, ScheduleRun
from app.schemas.schedule import (
    ScheduleCreate,
    ScheduleOut,
    SchedulePreview,
    SchedulePreviewIn,
    ScheduleRunOut,
    ScheduleUpdate,
)
from app.schemas.task import SourceType
from app.services import schedules
from app.services.audit import AuditAction, AuditStatus, ResourceType, log_action
from app.services.git_service import GitUrlError, validate_git_ref
from app.services.permission import CurrentUser, PermissionCode, get_current_user, require_permission
from app.services.projects import may_change
from app.services.triggered_builds import may_build

router = APIRouter(prefix="/api/projects/{project_id}/schedules", tags=["schedules"])

DB = Annotated[AsyncSession, Depends(get_db)]
AuthUser = Annotated[CurrentUser, Depends(get_current_user)]
CanBuild = Depends(require_permission(PermissionCode.TASK_CREATE))


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _last_run(db: AsyncSession, schedule_id: int) -> ScheduleRun | None:
    return (
        await db.execute(
            select(ScheduleRun).where(ScheduleRun.schedule_id == schedule_id).order_by(ScheduleRun.id.desc()).limit(1)
        )
    ).scalars().first()


async def _out(db: AsyncSession, s: ProjectSchedule, project: Project, user: CurrentUser) -> dict:
    last = await _last_run(db, s.id)
    return {
        "id": s.id,
        "cron": s.cron,
        "description": schedules.describe(s.cron),
        "timezone": s.timezone,
        "ref": s.ref,
        "ref_type": s.ref_type,
        "skip_unchanged": s.skip_unchanged,
        "enabled": s.enabled,
        "disabled_reason": s.disabled_reason,
        "next_run_at": schedules._utc(s.next_run_at) if s.next_run_at else None,
        "last_run_at": schedules._utc(s.last_run_at) if s.last_run_at else None,
        "last_run": ScheduleRunOut.model_validate(last, from_attributes=True) if last else None,
        "created_by": s.created_by,
        "created_at": s.created_at,
        "can_edit": may_change(project, user),
    }


async def _project(db: AsyncSession, project_id: int, user: CurrentUser, *, change: bool) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if change and not may_change(project, user):
        raise HTTPException(
            status_code=403, detail="Only whoever created this project, or a project manager, may change its schedules"
        )
    return project


async def _schedule(db: AsyncSession, project_id: int, schedule_id: int) -> ProjectSchedule:
    s = await db.get(ProjectSchedule, schedule_id)
    if s is None or s.project_id != project_id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return s


def _cron_and_zone(cron: str, tz: str | None) -> tuple[str, str]:
    try:
        return schedules.normalise_cron(cron), schedules.valid_timezone(tz or schedules.server_timezone())
    except schedules.ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _ref(ref: str) -> str:
    ref = (ref or "").strip()
    try:
        validate_git_ref(ref)
    except GitUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ref


async def _audit(db, action, s: ProjectSchedule, user: CurrentUser, request: Request, **details) -> None:
    await log_action(
        db, action, ResourceType.SCHEDULE, AuditStatus.SUCCESS,
        resource_id=s.id,
        actor_id=user.id,
        actor_name=user.username,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        details={"project_id": s.project_id, **details},
    )


@router.get("", response_model=list[ScheduleOut])
async def list_schedules(project_id: int, db: DB, user: AuthUser, _: None = CanBuild) -> list[dict]:
    project = await _project(db, project_id, user, change=False)
    rows = await db.execute(
        select(ProjectSchedule).where(ProjectSchedule.project_id == project_id).order_by(ProjectSchedule.id)
    )
    return [await _out(db, s, project, user) for s in rows.scalars().all()]


@router.post("/preview", response_model=SchedulePreview)
async def preview(project_id: int, body: SchedulePreviewIn, db: DB, user: AuthUser, _: None = CanBuild) -> dict:
    """The next run times of an expression, before it is saved (422 says what is wrong)."""
    await _project(db, project_id, user, change=False)
    cron, tz = _cron_and_zone(body.cron, body.timezone)
    return {
        "cron": cron,
        "timezone": tz,
        "description": schedules.describe(cron),
        "next_runs": schedules.next_runs(cron, tz, _now(), schedules.PREVIEW_COUNT),
    }


@router.post("", response_model=ScheduleOut, status_code=201)
async def create_schedule(
    project_id: int, body: ScheduleCreate, request: Request, db: DB, user: AuthUser, _: None = CanBuild,
) -> dict:
    project = await _project(db, project_id, user, change=True)
    if project.source_type != SourceType.GIT.value:
        raise HTTPException(status_code=422, detail="Schedules need a project that builds from a Git URL")
    cron, tz = _cron_and_zone(body.cron, body.timezone)
    cfg = project.config or {}
    ref = _ref(body.ref if body.ref is not None else str(cfg.get("git_ref") or ""))
    ref_type = body.ref_type or (cfg.get("git_ref_type") if body.ref is None else None) or "branch"
    s = ProjectSchedule(
        project_id=project.id,
        cron=cron,
        timezone=tz,
        ref=ref,
        ref_type=ref_type,
        skip_unchanged=body.skip_unchanged,
        enabled=True,
        next_run_at=schedules.next_run(cron, tz, _now()),
        created_by_id=user.id,
        created_by=user.username,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    await _audit(db, AuditAction.SCHEDULE_CREATE, s, user, request,
                 cron=cron, timezone=tz, ref=ref, ref_type=ref_type, skip_unchanged=s.skip_unchanged)
    return await _out(db, s, project, user)


@router.patch("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    project_id: int, schedule_id: int, body: ScheduleUpdate, request: Request, db: DB, user: AuthUser,
    _: None = CanBuild,
) -> dict:
    """Change a schedule, or turn it off or on.

    Turning on a schedule whose creator may no longer build is refused (409,
    with the reason) unless ``take_over`` says the caller's account runs its
    builds from now on. Changing the expression or zone, or turning it on,
    counts the next run from now.
    """
    project = await _project(db, project_id, user, change=True)
    s = await _schedule(db, project_id, schedule_id)
    changes: dict = {}
    if body.cron is not None or body.timezone is not None:
        cron, tz = _cron_and_zone(body.cron if body.cron is not None else s.cron, body.timezone or s.timezone)
        if (cron, tz) != (s.cron, s.timezone):
            s.cron, s.timezone = changes["cron"], changes["timezone"] = cron, tz
    if body.ref is not None:
        s.ref = changes["ref"] = _ref(body.ref)
    if body.ref_type is not None:
        s.ref_type = changes["ref_type"] = body.ref_type
    if body.skip_unchanged is not None:
        s.skip_unchanged = changes["skip_unchanged"] = body.skip_unchanged
    if body.enabled is False:
        s.enabled, s.disabled_reason = False, None
        changes["enabled"] = False
    elif body.enabled is True:
        if body.take_over:
            s.created_by_id, s.created_by = user.id, user.username
            changes["taken_over_by"] = user.username
        _runner, reason = await may_build(db, s.created_by_id)
        if reason is not None:
            raise HTTPException(
                status_code=409,
                detail=f"This schedule's builds run as {s.created_by}, but {reason}. Take it over to turn it on.",
            )
        if not s.enabled:
            changes["enabled"] = True
        s.enabled, s.disabled_reason = True, None
    if not s.enabled:
        s.next_run_at = None
    elif s.next_run_at is None or "cron" in changes or changes.get("enabled") is True:
        s.next_run_at = schedules.next_run(s.cron, s.timezone, _now())
    await db.commit()
    await db.refresh(s)
    if changes:
        await _audit(db, AuditAction.SCHEDULE_UPDATE, s, user, request, **changes)
    return await _out(db, s, project, user)


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    project_id: int, schedule_id: int, request: Request, db: DB, user: AuthUser, _: None = CanBuild,
) -> None:
    await _project(db, project_id, user, change=True)
    s = await _schedule(db, project_id, schedule_id)
    await _audit(db, AuditAction.SCHEDULE_DELETE, s, user, request, cron=s.cron)
    await db.delete(s)
    await db.commit()


@router.get("/{schedule_id}/runs", response_model=list[ScheduleRunOut])
async def list_runs(project_id: int, schedule_id: int, db: DB, user: AuthUser, _: None = CanBuild) -> list[ScheduleRun]:
    await _project(db, project_id, user, change=False)
    await _schedule(db, project_id, schedule_id)
    rows = await db.execute(
        select(ScheduleRun).where(ScheduleRun.schedule_id == schedule_id)
        .order_by(ScheduleRun.id.desc()).limit(schedules.RUNS_KEPT)
    )
    return list(rows.scalars().all())

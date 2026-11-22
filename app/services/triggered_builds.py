"""Builds nobody clicked: started by a webhook (and, later, a schedule) as a person.

A triggered build runs as the person who set up the trigger, so it is filed,
permitted and notified exactly like that person's own builds. That person is
checked again every time the trigger fires: an account deactivated, deleted or
stripped of task:create since must not keep building through a hook it left
behind. ``may_build`` says why not; the caller turns the trigger off with that
reason, which the console shows.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.user import User
from app.schemas.task import BuildConfig, BuildTrigger, SourceType, TaskCreate, TaskResponse
from app.services.permission import PermissionCode, get_user_permissions, has_permission
from app.services.projects import config_for_build
from app.services.task_manager import task_manager

# One process (see CLAUDE.md, "single process"): holding this makes "is this
# project or commit already being built?" and filing the build one step, so two
# triggers (two deliveries of one push, a delivery and a schedule) cannot both
# get past the check.
submit_lock = asyncio.Lock()


async def may_build(db: AsyncSession, user_id: int | None) -> tuple[User | None, str | None]:
    """The person a trigger runs as, or why they no longer may build."""
    user = await db.get(User, user_id) if user_id is not None else None
    if user is None:
        return None, "the person who set it up no longer has an account"
    if not user.is_active:
        return None, f"{user.username}'s account is deactivated"
    if not has_permission(await get_user_permissions(db, user.id), PermissionCode.TASK_CREATE.value):
        return None, f"{user.username} may no longer start builds (task:create)"
    return user, None


async def submit_build(
    db: AsyncSession,
    project: Project,
    user: User,
    *,
    trigger: BuildTrigger,
    ref: str | None = None,
    ref_type: str | None = None,
    commit: str | None = None,
    version: str = "",
) -> tuple[TaskResponse, BuildConfig]:
    """File a build of ``project`` with its saved settings, as ``user``.

    ``ref`` / ``ref_type`` replace the project's branch or tag for this build;
    ``commit`` pins the exact commit (app/services/build_dispatcher). The caller
    starts it: ``start_build_task(task.id, config, commit)``, in the background.
    Raises ValueError (pydantic's ValidationError included) when the project's
    settings cannot make a build.
    """
    from app.api.routes.tasks import _validate_build_config_paths

    if project.source_type != SourceType.GIT.value and (ref or commit):
        raise ValueError("this project does not build from Git")
    overrides: dict = {}
    if ref:
        overrides = {"git_ref": ref, "git_ref_type": ref_type or "branch"}
    config = config_for_build(project, overrides, version)
    _validate_build_config_paths(config)
    request = TaskCreate(
        project_name=project.name,
        config=config,
        project_id=project.id,
        user_name=user.username,
        git_commit=commit or None,
    )
    task = await task_manager.create_task(request, db, trigger=trigger)
    return task, config

"""Projects: the code the team builds again and again, and its versions.

Anyone who may build (task:create) sees every project and may build a new version
of it; whoever created a project, and holders of project:manage, may change or
delete it. A project page lists every build of it briefly — version, outcome, who,
when — since knowing which versions exist is the point of sharing one; a build's
settings and logs stay behind the history permissions on its own page.
"""

from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.project import Project
from app.models.task import Task
from app.schemas.project import BuildBrief, ProjectBuildRequest, ProjectDetail, ProjectSummary, ProjectUpdate
from app.schemas.task import TaskCreate, TaskResponse, TaskStatus
from app.services.build_dispatcher import start_build_task
from app.services.permission import CurrentUser, PermissionCode, get_current_user, require_permission
from app.services.projects import config_for_build, defaults_from, may_change, source_of
from app.services.task_manager import task_manager

router = APIRouter(prefix="/api/projects", tags=["projects"])

DB = Annotated[AsyncSession, Depends(get_db)]
AuthUser = Annotated[CurrentUser, Depends(get_current_user)]
CanBuild = Depends(require_permission(PermissionCode.TASK_CREATE))


def _brief(t: Task) -> BuildBrief:
    return BuildBrief(
        task_id=t.task_id, version=t.version, status=TaskStatus(t.status),
        user_name=t.user_name, start_time=t.start_time, end_time=t.end_time,
    )


def _summary(p: Project, builds: list[Task], user: CurrentUser) -> dict:
    """Builds newest first."""
    passed = next((b for b in builds if TaskStatus(b.status) == TaskStatus.COMPLETED), None)
    return {
        "id": p.id, "name": p.name, "project_type": p.project_type, "source_type": p.source_type,
        "source": p.source, "created_by": p.created_by, "created_at": p.created_at, "updated_at": p.updated_at,
        "builds": len(builds), "latest": _brief(builds[0]) if builds else None,
        "last_passed": _brief(passed) if passed else None, "can_edit": may_change(p, user),
    }


async def _get(db: AsyncSession, project_id: int) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _builds(db: AsyncSession, project_ids: list[int]) -> dict[int, list[Task]]:
    rows = (
        await db.execute(select(Task).where(Task.project_id.in_(project_ids)).order_by(Task.start_time.desc()))
    ).scalars().all()
    by_project: dict[int, list[Task]] = defaultdict(list)
    for t in rows:
        by_project[t.project_id].append(t)
    return by_project


@router.get("", response_model=list[ProjectSummary])
async def list_projects(db: DB, current_user: AuthUser, _: None = CanBuild) -> list[ProjectSummary]:
    """Every project, the most recently built first."""
    projects = (await db.execute(select(Project))).scalars().all()
    builds = await _builds(db, [p.id for p in projects])
    summaries = [ProjectSummary(**_summary(p, builds[p.id], current_user)) for p in projects]
    summaries.sort(key=lambda s: (s.latest.start_time if s.latest else s.created_at), reverse=True)
    return summaries


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: int, db: DB, current_user: AuthUser, _: None = CanBuild) -> ProjectDetail:
    project = await _get(db, project_id)
    builds = (await _builds(db, [project.id]))[project.id]
    return ProjectDetail(
        **_summary(project, builds, current_user),
        config=config_for_build(project, {}),
        history=[_brief(b) for b in builds],
    )


@router.put("/{project_id}", response_model=ProjectDetail)
async def update_project(
    project_id: int, request: ProjectUpdate, db: DB, current_user: AuthUser, _: None = CanBuild,
) -> ProjectDetail:
    """Rename a project or change its default settings (creator or project:manage)."""
    project = await _get(db, project_id)
    if not may_change(project, current_user):
        raise HTTPException(status_code=403, detail="Only whoever created this project, or a project manager, may change it")
    if request.name is not None and request.name != project.name:
        taken = (await db.execute(select(Project.id).where(Project.name == request.name))).scalar_one_or_none()
        if taken is not None:
            raise HTTPException(status_code=409, detail=f"There is already a project named {request.name}")
        project.name = request.name
        # Builds carry the name they were made under; keep them findable under the new one.
        await db.execute(update(Task).where(Task.project_id == project.id).values(project_name=request.name))
    if request.config is not None:
        from app.api.routes.tasks import _validate_build_config_paths

        _validate_build_config_paths(request.config)
        project.config = defaults_from(request.config)
        project.project_type = request.config.project_type.value
        project.source_type = request.config.source_type.value
        project.source = source_of(request.config)
    await db.commit()
    await db.refresh(project)
    return await get_project(project.id, db, current_user)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: int, db: DB, current_user: AuthUser, _: None = CanBuild) -> None:
    """Delete a project. Its builds stay in history, no longer filed under it."""
    project = await _get(db, project_id)
    if not may_change(project, current_user):
        raise HTTPException(status_code=403, detail="Only whoever created this project, or a project manager, may delete it")
    # history.project_id is ON DELETE SET NULL (and SQLite runs with foreign_keys=ON),
    # so the builds stay and are simply no longer filed under it.
    await db.delete(project)
    await db.commit()


@router.post("/{project_id}/builds", response_model=TaskResponse, status_code=201)
async def build_project(
    project_id: int,
    request: ProjectBuildRequest,
    background_tasks: BackgroundTasks,
    db: DB,
    current_user: AuthUser,
    _: None = CanBuild,
) -> TaskResponse:
    """Start a build of a new version with the project's settings."""
    from app.api.routes.tasks import _validate_build_config_paths

    project = await _get(db, project_id)
    try:
        config = config_for_build(project, request.overrides, request.version)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_url=False, include_context=False)) from e
    _validate_build_config_paths(config)
    task = await task_manager.create_task(
        TaskCreate(project_name=project.name, config=config, project_id=project.id, user_name=current_user.username), db
    )
    background_tasks.add_task(start_build_task, task.id, config)
    return task

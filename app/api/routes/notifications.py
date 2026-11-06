"""Where a project's build results are sent (app/services/notifications).

Same rules as the project's other settings: everyone who may build sees the
list (URLs masked), its creator and holders of project:manage change it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.notification import ProjectNotification
from app.models.project import Project
from app.schemas.notification import NotificationCreate, NotificationOut, NotificationUpdate, TestResult
from app.services import notifications
from app.services.crypto import encrypt_secret
from app.services.permission import CurrentUser, PermissionCode, get_current_user, require_permission
from app.services.projects import may_change

router = APIRouter(prefix="/api/projects/{project_id}/notifications", tags=["notifications"])

DB = Annotated[AsyncSession, Depends(get_db)]
AuthUser = Annotated[CurrentUser, Depends(get_current_user)]
CanBuild = Depends(require_permission(PermissionCode.TASK_CREATE))


async def _project(db: AsyncSession, project_id: int, user: CurrentUser, *, change: bool) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if change and not may_change(project, user):
        raise HTTPException(
            status_code=403, detail="Only whoever created this project, or a project manager, may change its notifications"
        )
    return project


async def _destination(db: AsyncSession, project_id: int, notification_id: int) -> ProjectNotification:
    row = await db.get(ProjectNotification, notification_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Notification not found")
    return row


def _checked(kind: str, url: str) -> str:
    try:
        return notifications.validate_url(kind, url)
    except notifications.InvalidDestination as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[NotificationOut])
async def list_notifications(project_id: int, db: DB, user: AuthUser, _: None = CanBuild) -> list[ProjectNotification]:
    await _project(db, project_id, user, change=False)
    rows = await db.execute(
        select(ProjectNotification).where(ProjectNotification.project_id == project_id).order_by(ProjectNotification.id)
    )
    return list(rows.scalars().all())


@router.post("", response_model=NotificationOut, status_code=201)
async def add_notification(
    project_id: int, body: NotificationCreate, db: DB, user: AuthUser, _: None = CanBuild,
) -> ProjectNotification:
    await _project(db, project_id, user, change=True)
    url = _checked(body.kind, body.url)
    row = ProjectNotification(
        project_id=project_id, kind=body.kind, url_encrypted=encrypt_secret(url), url_hint=notifications.url_hint(url),
        on_failed=body.on_failed, on_passed=body.on_passed, created_by=user.username,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.patch("/{notification_id}", response_model=NotificationOut)
async def update_notification(
    project_id: int, notification_id: int, body: NotificationUpdate, db: DB, user: AuthUser, _: None = CanBuild,
) -> ProjectNotification:
    await _project(db, project_id, user, change=True)
    row = await _destination(db, project_id, notification_id)
    if body.url is not None:
        url = _checked(row.kind, body.url)
        row.url_encrypted = encrypt_secret(url)
        row.url_hint = notifications.url_hint(url)
        # The last delivery was to the old URL.
        row.last_sent_at = row.last_ok = row.last_error = None
    if body.on_failed is not None:
        row.on_failed = body.on_failed
    if body.on_passed is not None:
        row.on_passed = body.on_passed
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{notification_id}", status_code=204)
async def delete_notification(project_id: int, notification_id: int, db: DB, user: AuthUser, _: None = CanBuild) -> None:
    await _project(db, project_id, user, change=True)
    await db.delete(await _destination(db, project_id, notification_id))
    await db.commit()


@router.post("/{notification_id}/test", response_model=TestResult)
async def send_test(project_id: int, notification_id: int, db: DB, user: AuthUser, _: None = CanBuild) -> TestResult:
    """Send a test message now and say how it went."""
    project = await _project(db, project_id, user, change=True)
    row = await _destination(db, project_id, notification_id)
    ok, error = await notifications.send_to(row, notifications.BuildOutcome(event="test", project=project.name))
    await db.commit()
    return TestResult(ok=ok, error=error)

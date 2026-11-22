"""Incoming webhooks: managing a project's hooks, and receiving deliveries.

Managing (``/api/projects/{id}/hooks``) follows the project's other settings:
everyone who may build sees the hooks (never their secrets), the project's
creator and holders of project:manage change them. None of these routes is in
api_tokens.TOKEN_ROUTES, so an API token cannot create a hook or read a secret.

Receiving (``/api/hooks/{provider}/{public_id}``) needs no session or API token:
the delivery proves itself with the hook's secret (app/services/hooks.verify).
Every way of failing that answers the same 401, so the URL reveals nothing
about which hooks exist; the reason is in the hook's deliveries list. A
delivery that is genuine but builds nothing (a ping, another branch, a deleted
tag, ``[skip ci]``) answers 200 "ignored": GitLab disables a hook after a few
4xx answers. A build answers 202 with its id.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_client_ip
from app.config import get_settings
from app.database import get_db
from app.models.hook import HookDelivery, ProjectHook
from app.models.project import Project
from app.models.task import Task
from app.schemas.hook import DeliveryOut, HookCreate, HookCreated, HookOut, HookUpdate, SigningKey
from app.schemas.task import SourceType, TaskStatus
from app.services import hooks
from app.services.audit import AuditAction, AuditStatus, ResourceType, log_action
from app.services.build_dispatcher import start_build_task
from app.services.crypto import DecryptionError, decrypt_secret, encrypt_secret
from app.services.permission import CurrentUser, PermissionCode, get_current_user, require_permission
from app.services.projects import may_change
from app.services.triggered_builds import may_build, submit_build, submit_lock

router = APIRouter(prefix="/api/projects/{project_id}/hooks", tags=["webhooks"])
receive_router = APIRouter(prefix="/api/hooks", tags=["webhooks"])

DB = Annotated[AsyncSession, Depends(get_db)]
AuthUser = Annotated[CurrentUser, Depends(get_current_user)]
CanBuild = Depends(require_permission(PermissionCode.TASK_CREATE))

# Deliveries kept per hook, newest first.
DELIVERIES_KEPT = 50
# A successful build of the same project, ref and commit this recent makes a
# new delivery for it a duplicate (a forge's retry with a fresh delivery id, or
# two hooks on one repository). Older than this, pushing the commit again builds.
RECENT_SUCCESS_WINDOW = timedelta(minutes=10)



# ---------- managing ----------


def _patterns(text: str) -> list[str]:
    return [p for p in text.split("\n") if p]


def _path(hook: ProjectHook) -> str:
    return f"/api/hooks/{hook.provider}/{hook.public_id}"


def _base_url(request: Request) -> str:
    public = get_settings().public_url.strip().rstrip("/")
    return public or str(request.base_url).rstrip("/")


def _out(hook: ProjectHook, project: Project, user: CurrentUser, request: Request) -> dict:
    return {
        "id": hook.id,
        "provider": hook.provider,
        "path": _path(hook),
        "url": _base_url(request) + _path(hook),
        "branches": _patterns(hook.branches),
        "tags": _patterns(hook.tags),
        "enabled": hook.enabled,
        "disabled_reason": hook.disabled_reason,
        "has_signing_key": hook.signing_key_encrypted is not None,
        "created_by": hook.created_by,
        "created_at": hook.created_at,
        "secret_rotated_at": hook.secret_rotated_at,
        "last_delivery_at": hook.last_delivery_at,
        "can_edit": may_change(project, user),
    }


async def _project(db: AsyncSession, project_id: int, user: CurrentUser, *, change: bool) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if change and not may_change(project, user):
        raise HTTPException(
            status_code=403, detail="Only whoever created this project, or a project manager, may change its webhooks"
        )
    return project


async def _hook(db: AsyncSession, project_id: int, hook_id: int) -> ProjectHook:
    hook = await db.get(ProjectHook, hook_id)
    if hook is None or hook.project_id != project_id:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return hook


def _checked_patterns(raw: str) -> str:
    try:
        return hooks.normalise_patterns(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _audit(db, action, hook: ProjectHook, user: CurrentUser | None, request: Request | None, **details) -> None:
    await log_action(
        db, action, ResourceType.HOOK, AuditStatus.SUCCESS,
        resource_id=hook.id,
        actor_id=user.id if user else None,
        actor_name=user.username if user else None,
        ip_address=get_client_ip(request) if request else None,
        user_agent=request.headers.get("user-agent") if request else None,
        details={"project_id": hook.project_id, "provider": hook.provider, **details},
    )


@router.get("", response_model=list[HookOut])
async def list_hooks(project_id: int, request: Request, db: DB, user: AuthUser, _: None = CanBuild) -> list[dict]:
    project = await _project(db, project_id, user, change=False)
    rows = await db.execute(select(ProjectHook).where(ProjectHook.project_id == project_id).order_by(ProjectHook.id))
    return [_out(h, project, user, request) for h in rows.scalars().all()]


@router.post("", response_model=HookCreated, status_code=201)
async def create_hook(
    project_id: int, body: HookCreate, request: Request, db: DB, user: AuthUser, _: None = CanBuild,
) -> dict:
    """Create a hook. The answer is the only place its secret appears (until a rotation)."""
    project = await _project(db, project_id, user, change=True)
    if project.source_type != SourceType.GIT.value:
        raise HTTPException(status_code=422, detail="Webhooks need a project that builds from a Git URL")
    secret = hooks.new_secret()
    hook = ProjectHook(
        public_id=hooks.new_public_id(),
        project_id=project.id,
        provider=body.provider,
        secret_encrypted=encrypt_secret(secret),
        branches=_checked_patterns(body.branches),
        tags=_checked_patterns(body.tags),
        enabled=True,
        created_by_id=user.id,
        created_by=user.username,
    )
    db.add(hook)
    await db.commit()
    await db.refresh(hook)
    await _audit(db, AuditAction.HOOK_CREATE, hook, user, request, branches=hook.branches, tags=hook.tags)
    return {**_out(hook, project, user, request), "secret": secret}


@router.patch("/{hook_id}", response_model=HookOut)
async def update_hook(
    project_id: int, hook_id: int, body: HookUpdate, request: Request, db: DB, user: AuthUser, _: None = CanBuild,
) -> dict:
    """Change the filters, or turn the hook off or on.

    Turning on a hook whose creator may no longer build is refused (409, with
    the reason) unless ``take_over`` says the caller's account runs its builds
    from now on.
    """
    project = await _project(db, project_id, user, change=True)
    hook = await _hook(db, project_id, hook_id)
    changes: dict = {}
    if body.branches is not None:
        hook.branches = changes["branches"] = _checked_patterns(body.branches)
    if body.tags is not None:
        hook.tags = changes["tags"] = _checked_patterns(body.tags)
    if body.enabled is False:
        hook.enabled, hook.disabled_reason = False, None
        changes["enabled"] = False
    elif body.enabled is True:
        if body.take_over:
            hook.created_by_id, hook.created_by = user.id, user.username
            changes["taken_over_by"] = user.username
        _runner, reason = await may_build(db, hook.created_by_id)
        if reason is not None:
            raise HTTPException(
                status_code=409,
                detail=f"This webhook's builds run as {hook.created_by}, but {reason}. Take it over to turn it on.",
            )
        hook.enabled, hook.disabled_reason = True, None
        changes["enabled"] = True
    await db.commit()
    await db.refresh(hook)
    if changes:
        await _audit(db, AuditAction.HOOK_UPDATE, hook, user, request, **changes)
    return _out(hook, project, user, request)


@router.post("/{hook_id}/rotate", response_model=HookCreated)
async def rotate_secret(project_id: int, hook_id: int, request: Request, db: DB, user: AuthUser, _: None = CanBuild) -> dict:
    """A new secret, shown once; the old one stops working at once."""
    project = await _project(db, project_id, user, change=True)
    hook = await _hook(db, project_id, hook_id)
    secret = hooks.new_secret()
    hook.secret_encrypted = encrypt_secret(secret)
    hook.secret_rotated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(hook)
    await _audit(db, AuditAction.HOOK_ROTATE, hook, user, request)
    return {**_out(hook, project, user, request), "secret": secret}


@router.put("/{hook_id}/signing-key", response_model=HookOut)
async def set_signing_key(
    project_id: int, hook_id: int, body: SigningKey, request: Request, db: DB, user: AuthUser, _: None = CanBuild,
) -> dict:
    """Store (or, with null, remove) the signing token GitLab generated for this hook."""
    project = await _project(db, project_id, user, change=True)
    hook = await _hook(db, project_id, hook_id)
    if hook.provider != "gitlab":
        raise HTTPException(status_code=422, detail="Only GitLab webhooks have a signing token")
    if body.signing_key is None or not body.signing_key.strip():
        hook.signing_key_encrypted = None
    else:
        try:
            hook.signing_key_encrypted = encrypt_secret(hooks.valid_signing_key(body.signing_key))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(hook)
    await _audit(db, AuditAction.HOOK_UPDATE, hook, user, request, signing_key=hook.signing_key_encrypted is not None)
    return _out(hook, project, user, request)


@router.delete("/{hook_id}", status_code=204)
async def delete_hook(project_id: int, hook_id: int, request: Request, db: DB, user: AuthUser, _: None = CanBuild) -> None:
    await _project(db, project_id, user, change=True)
    hook = await _hook(db, project_id, hook_id)
    await _audit(db, AuditAction.HOOK_DELETE, hook, user, request)
    await db.delete(hook)
    await db.commit()


@router.get("/{hook_id}/deliveries", response_model=list[DeliveryOut])
async def list_deliveries(project_id: int, hook_id: int, db: DB, user: AuthUser, _: None = CanBuild) -> list[HookDelivery]:
    await _project(db, project_id, user, change=False)
    await _hook(db, project_id, hook_id)
    rows = await db.execute(
        select(HookDelivery).where(HookDelivery.hook_id == hook_id).order_by(HookDelivery.id.desc()).limit(DELIVERIES_KEPT)
    )
    return list(rows.scalars().all())


# ---------- receiving ----------

def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": "Invalid signature or token"})


def _too_large() -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": "The request body is too large"})


class _TooLarge(Exception):
    pass


async def _read_body(request: Request, limit: int) -> bytes:
    """The body, read no further than ``limit`` bytes (a chunked request has no Content-Length)."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise _TooLarge
        except ValueError:
            raise _TooLarge from None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise _TooLarge
        chunks.append(chunk)
    return b"".join(chunks)


def _delivery_id(provider: str, headers: dict[str, str]) -> str | None:
    names = {
        "github": ("x-github-delivery",),
        "gitea": ("x-gitea-delivery", "x-github-delivery"),
        # webhook-id stays the same across GitLab's retries (= Idempotency-Key).
        "gitlab": ("webhook-id", "idempotency-key", "x-gitlab-event-uuid"),
        "generic": ("x-packwright-delivery", "idempotency-key"),
    }[provider]
    for name in names:
        value = headers.get(name, "").strip()
        if value:
            return value[:100]
    return None


def _payload(body: bytes, content_type: str) -> dict:
    """The JSON payload; GitHub's form encoding (payload=<json>) is accepted too."""
    if not body.strip():
        return {}
    if content_type.startswith("application/x-www-form-urlencoded"):
        form = parse_qs(body.decode("utf-8", "replace"))
        body = (form.get("payload") or [""])[0].encode()
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("payload is not a JSON object")
    return data


async def _record(
    db: AsyncSession,
    hook: ProjectHook,
    result: str,
    reason: str | None,
    *,
    delivery_id: str | None,
    parsed: hooks.Parsed | None = None,
    event: str | None = None,
    task_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    event = parsed.event if parsed else event
    db.add(HookDelivery(
        hook_id=hook.id,
        received_at=now,
        delivery_id=delivery_id,
        event=event[:64] if event else None,
        ref=(parsed.ref[:255] if parsed and parsed.ref else None),
        commit_sha=(parsed.sha[:64] if parsed and parsed.sha else None),
        result=result,
        reason=reason[:300] if reason else None,
        task_id=task_id,
    ))
    hook.last_delivery_at = now
    await db.flush()
    keep = (
        await db.execute(
            select(HookDelivery.id).where(HookDelivery.hook_id == hook.id)
            .order_by(HookDelivery.id.desc()).limit(DELIVERIES_KEPT)
        )
    ).scalars().all()
    await db.execute(delete(HookDelivery).where(HookDelivery.hook_id == hook.id, HookDelivery.id.not_in(keep)))
    await db.commit()


def _ignored(reason: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=200, content={"status": "ignored", "reason": reason, **extra})


async def _already_built(db: AsyncSession, project_id: int, push: hooks.Push) -> Task | None:
    """A build of this project, ref and commit that is queued, running, or just passed."""
    rows = (
        await db.execute(select(Task).where(Task.project_id == project_id, Task.commit_sha == push.sha))
    ).scalars().all()
    since = datetime.now(timezone.utc) - RECENT_SUCCESS_WINDOW
    for task in rows:
        cfg = task.config or {}
        if cfg.get("git_ref") != push.name or (cfg.get("git_ref_type") or "branch") != push.kind:
            continue
        status = TaskStatus(task.status)
        if status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            return task
        if status == TaskStatus.COMPLETED and task.end_time is not None:
            end = task.end_time if task.end_time.tzinfo else task.end_time.replace(tzinfo=timezone.utc)
            if end >= since:
                return task
    return None


@receive_router.post("/{provider}/{public_id}")
async def receive(
    provider: str,
    public_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DB,
    token: Annotated[str | None, Query(include_in_schema=False)] = None,
) -> JSONResponse:
    """Receive one delivery. See the module docstring for the answers."""
    try:
        body = await _read_body(request, get_settings().webhook_max_body_bytes)
    except _TooLarge:
        return _too_large()

    if provider not in hooks.PROVIDERS or len(public_id) > 64:
        return _unauthorized()
    hook = (
        await db.execute(select(ProjectHook).where(ProjectHook.public_id == public_id))
    ).scalar_one_or_none()
    if hook is None:
        return _unauthorized()

    headers = {k.lower(): v for k, v in request.headers.items()}
    delivery_id = _delivery_id(hook.provider, headers)
    event_header = (
        headers.get("x-github-event") or headers.get("x-gitea-event") or headers.get("x-gitlab-event") or None
    )

    if provider != hook.provider:
        await _record(db, hook, "rejected", f"sent to the {provider} URL of a {hook.provider} webhook",
                      delivery_id=delivery_id, event=event_header)
        return _unauthorized()
    try:
        secret = decrypt_secret(hook.secret_encrypted)
        signing_key = decrypt_secret(hook.signing_key_encrypted) if hook.signing_key_encrypted else None
    except DecryptionError:
        await _record(db, hook, "rejected", "the stored secret cannot be decrypted (SETTINGS_ENCRYPTION_KEY changed?)",
                      delivery_id=delivery_id, event=event_header)
        return _unauthorized()
    try:
        hooks.verify(provider, headers, body, secret, signing_key=signing_key, now=time.time(), query_token=token)
    except hooks.Rejected as rejected:
        await _record(db, hook, "rejected", rejected.reason, delivery_id=delivery_id, event=event_header)
        return _unauthorized()

    # From here on the sender is the forge (or script) the secret was given to.
    if not hook.enabled:
        reason = "hook disabled" + (f": {hook.disabled_reason}" if hook.disabled_reason else "")
        await _record(db, hook, "ignored", reason, delivery_id=delivery_id, event=event_header)
        return _ignored(reason)

    if delivery_id is not None:
        earlier = (
            await db.execute(
                select(HookDelivery).where(
                    HookDelivery.hook_id == hook.id,
                    HookDelivery.delivery_id == delivery_id,
                    HookDelivery.result != "rejected",
                ).order_by(HookDelivery.id)
            )
        ).scalars().first()
        if earlier is not None:
            reason = "duplicate delivery" + (f": already built as {earlier.task_id}" if earlier.task_id else "")
            await _record(db, hook, "ignored", reason, delivery_id=delivery_id, event=earlier.event,
                          task_id=earlier.task_id)
            return _ignored(reason, **({"build_id": earlier.task_id} if earlier.task_id else {}))

    project = await db.get(Project, hook.project_id)
    try:
        payload = _payload(body, headers.get("content-type", ""))
    except ValueError:
        await _record(db, hook, "rejected", "the body is not a JSON object", delivery_id=delivery_id,
                      event=event_header)
        return JSONResponse(status_code=400, content={"detail": "The body is not a JSON object"})

    if provider == "generic":
        cfg = project.config or {}
        parsed = hooks.parse_generic(payload, str(cfg.get("git_ref") or ""), str(cfg.get("git_ref_type") or "branch"))
    else:
        parsed = hooks.parse_forge(provider, headers, payload)

    async def ignore(reason: str) -> JSONResponse:
        await _record(db, hook, "ignored", reason, delivery_id=delivery_id, parsed=parsed)
        return _ignored(reason)

    if parsed.push is None:
        return await ignore(parsed.ignored or "nothing to build")
    push = parsed.push
    if project.source_type != SourceType.GIT.value:
        return await ignore("the project no longer builds from a Git URL")
    if provider != "generic" and not hooks.same_repository(project.source, push.repo_urls):
        named = push.repo_urls[0] if push.repo_urls else "no repository"
        return await ignore(f"the delivery is for {named}, not this project's repository")
    patterns = hook.branches if push.kind == "branch" else hook.tags
    if not hooks.ref_allowed(patterns, push.name):
        return await ignore(f"{push.kind} {push.name} does not match this webhook's {push.kind} patterns")
    if hooks.skip_requested(push.message):
        return await ignore("the commit message asks to skip builds ([skip ci])")

    runner, reason = await may_build(db, hook.created_by_id)
    if runner is None:
        hook.enabled, hook.disabled_reason = False, reason[:300]
        await db.commit()
        await log_action(
            db, AuditAction.HOOK_DISABLED, ResourceType.HOOK, AuditStatus.SUCCESS,
            resource_id=hook.id, error_message=reason,
            details={"project_id": hook.project_id, "provider": hook.provider, "runs_as": hook.created_by},
        )
        return await ignore(f"hook disabled: {reason}")

    trigger = "tag" if push.kind == "tag" else "push"
    version = (hooks_version(push.name) or "") if push.kind == "tag" else ""
    async with submit_lock:
        if push.sha:
            existing = await _already_built(db, project.id, push)
            if existing is not None:
                return await ignore(f"commit already built or being built as {existing.task_id}")
        try:
            task, config = await submit_build(
                db, project, runner, trigger=trigger, ref=push.name, ref_type=push.kind,
                commit=push.sha or None, version=version,
            )
        except (ValueError, ValidationError, HTTPException) as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            return await ignore(f"the project's settings cannot make a build: {detail}"[:300])
    await _record(db, hook, "built", None, delivery_id=delivery_id, parsed=parsed, task_id=task.id)
    background_tasks.add_task(start_build_task, task.id, config, push.sha or None)
    return JSONResponse(status_code=202, content={"status": "queued", "build_id": task.id})


def hooks_version(tag: str) -> str | None:
    """A pushed tag as the build's version, when it is one (v1.2.0, 2026.11)."""
    from app.services.project_version import _usable

    return _usable(tag)

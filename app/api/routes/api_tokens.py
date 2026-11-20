"""Console API for personal API tokens.

Everyone signed in to the console manages their own tokens; holders of
user:manage also see and revoke everyone's (never the secrets, which are not
stored). None of these routes is in api_tokens.TOKEN_ROUTES, so a token can
never create, list or revoke tokens.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.routes.auth import get_client_ip
from app.api.routes.tasks import DB, AuthUser
from app.models.api_token import ApiToken
from app.models.user import User
from app.schemas.api_token import ApiTokenCreate, ApiTokenCreated, ApiTokenOut
from app.services import api_tokens
from app.services.audit import AuditAction, AuditStatus, ResourceType, log_action
from app.services.permission import PermissionCode

router = APIRouter(prefix="/api/tokens", tags=["api-tokens"])


def _out(token: ApiToken, owner: str, now: datetime) -> dict:
    if token.revoked_at is not None:
        state = "revoked"
    elif token.expired(now):
        state = "expired"
    else:
        state = "active"
    return {
        "id": token.id,
        "name": token.name,
        "prefix": token.token_prefix,
        "scopes": token.scope_list,
        "owner": owner,
        "created_at": token.created_at,
        "expires_at": token.expires_at,
        "last_used_at": token.last_used_at,
        "revoked_at": token.revoked_at,
        "status": state,
    }


@router.get("", response_model=list[ApiTokenOut])
async def list_tokens(db: DB, current_user: AuthUser, everyone: bool = False):
    """The caller's tokens; ``?everyone=true`` lists all tokens (user:manage)."""
    if everyone and not current_user.has_permission(PermissionCode.USER_MANAGE):
        raise HTTPException(status_code=403, detail="Missing required permissions: user:manage")
    query = select(ApiToken, User.username).join(User, User.id == ApiToken.user_id)
    if not everyone:
        query = query.where(ApiToken.user_id == current_user.id)
    rows = (await db.execute(query.order_by(ApiToken.created_at.desc(), ApiToken.id.desc()))).all()
    now = datetime.now(timezone.utc)
    return [_out(token, owner, now) for token, owner in rows]


@router.post("", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(data: ApiTokenCreate, request: Request, db: DB, current_user: AuthUser):
    """Create a token for the caller. The answer is the only place the token appears."""
    token, raw = await api_tokens.create_token(
        db,
        user_id=current_user.id,
        name=data.name,
        scopes=data.scopes,
        expires_in_days=data.expires_in_days,
    )
    await log_action(
        db,
        AuditAction.API_TOKEN_CREATE,
        ResourceType.API_TOKEN,
        AuditStatus.SUCCESS,
        resource_id=token.id,
        actor_id=current_user.id,
        actor_name=current_user.username,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        details={
            "name": token.name,
            "prefix": token.token_prefix,
            "scopes": token.scope_list,
            "expires_at": token.expires_at,
        },
    )
    return {**_out(token, current_user.username, datetime.now(timezone.utc)), "token": raw}


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: int, request: Request, db: DB, current_user: AuthUser):
    """Revoke a token: its owner, or anyone with user:manage. Revoking twice is a no-op."""
    row = (
        await db.execute(
            select(ApiToken, User.username)
            .join(User, User.id == ApiToken.user_id)
            .where(ApiToken.id == token_id)
        )
    ).one_or_none()
    # Someone else's token answers 404 unless you may manage it, so ids cannot
    # be probed.
    if row is None or (
        row[0].user_id != current_user.id
        and not current_user.has_permission(PermissionCode.USER_MANAGE)
    ):
        raise HTTPException(status_code=404, detail="Token not found")
    token, owner = row
    if token.revoked_at is None:
        token.revoked_at = datetime.now(timezone.utc)
        await db.commit()
        await log_action(
            db,
            AuditAction.API_TOKEN_REVOKE,
            ResourceType.API_TOKEN,
            AuditStatus.SUCCESS,
            resource_id=token.id,
            actor_id=current_user.id,
            actor_name=current_user.username,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            details={"name": token.name, "prefix": token.token_prefix, "owner": owner},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

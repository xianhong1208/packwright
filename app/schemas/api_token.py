"""Pydantic schemas for personal API tokens. The token itself appears only in
ApiTokenCreated, the answer to the request that made it."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.api_tokens import MAX_EXPIRY_DAYS, normalize_scopes


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=10)
    expires_in_days: int = Field(ge=1, le=MAX_EXPIRY_DAYS)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Give the token a name")
        return v

    @field_validator("scopes")
    @classmethod
    def _known_scopes(cls, v: list[str]) -> list[str]:
        return normalize_scopes(v)


class ApiTokenOut(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: list[str]
    owner: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    status: Literal["active", "expired", "revoked"]


class ApiTokenCreated(ApiTokenOut):
    token: str

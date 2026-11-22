"""Request and response bodies for a project's incoming webhooks (app/models/hook).

The secret goes out exactly twice: when the hook is created and when it is
rotated (``HookCreated``). It is never listed.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Provider = Literal["github", "gitlab", "gitea", "generic"]


class HookOut(BaseModel):
    id: int
    provider: Provider
    # Path of the payload URL; ``url`` is the full URL when it can be told
    # (PUBLIC_URL, or the address the console was reached at).
    path: str
    url: str
    branches: list[str]
    tags: list[str]
    enabled: bool
    disabled_reason: str | None = None
    has_signing_key: bool = False
    created_by: str
    created_at: datetime
    secret_rotated_at: datetime | None = None
    last_delivery_at: datetime | None = None
    # Whether the caller may change it (the project's creator or project:manage).
    can_edit: bool = False


class HookCreated(HookOut):
    secret: str


class HookCreate(BaseModel):
    provider: Provider
    # Glob patterns, separated by new lines, spaces or commas.
    branches: str = Field(default="", max_length=4000)
    tags: str = Field(default="", max_length=4000)


class HookUpdate(BaseModel):
    """Only what is given changes."""

    branches: str | None = Field(default=None, max_length=4000)
    tags: str | None = Field(default=None, max_length=4000)
    enabled: bool | None = None
    # Enabling a hook whose creator may no longer build: run its builds as the
    # caller from now on.
    take_over: bool = False


class SigningKey(BaseModel):
    """GitLab's signing token (whsec_…), or null to remove it."""

    signing_key: str | None = Field(default=None, max_length=200)


class DeliveryOut(BaseModel):
    id: int
    received_at: datetime
    delivery_id: str | None = None
    event: str | None = None
    ref: str | None = None
    commit_sha: str | None = None
    result: Literal["built", "ignored", "rejected"]
    reason: str | None = None
    task_id: str | None = None

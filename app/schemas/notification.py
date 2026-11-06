"""Request and response bodies for a project's notification destinations.

The webhook URL goes in, never out: responses carry `url_hint` only.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["webhook", "discord", "slack"]


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: Kind
    url_hint: str
    on_failed: bool
    on_passed: bool
    created_by: str
    created_at: datetime
    last_sent_at: datetime | None = None
    last_ok: bool | None = None
    last_error: str | None = None


class NotificationCreate(BaseModel):
    kind: Kind
    url: str = Field(max_length=2000)
    on_failed: bool = True
    on_passed: bool = True


class NotificationUpdate(BaseModel):
    """Only what is given changes; a new URL replaces the stored one."""

    url: str | None = Field(default=None, max_length=2000)
    on_failed: bool | None = None
    on_passed: bool | None = None


class TestResult(BaseModel):
    ok: bool
    error: str | None = None

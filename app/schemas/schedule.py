"""Request and response bodies for a project's scheduled builds (app/models/schedule)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScheduleRunOut(BaseModel):
    id: int
    due_at: datetime
    ran_at: datetime
    result: Literal["built", "skipped", "failed"]
    reason: str | None = None
    commit_sha: str | None = None
    task_id: str | None = None


class ScheduleOut(BaseModel):
    id: int
    cron: str
    # The expression in words ("At 02:00"), when it can be said.
    description: str | None = None
    timezone: str
    ref: str
    ref_type: Literal["branch", "tag"]
    skip_unchanged: bool
    enabled: bool
    disabled_reason: str | None = None
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_run: ScheduleRunOut | None = None
    created_by: str
    created_at: datetime
    # Whether the caller may change it (the project's creator or project:manage).
    can_edit: bool = False


class ScheduleCreate(BaseModel):
    cron: str = Field(max_length=200)
    # IANA name; the server's zone when left out.
    timezone: str | None = Field(default=None, max_length=64)
    # The branch or tag to build; the project's own when left out.
    ref: str | None = Field(default=None, max_length=255)
    ref_type: Literal["branch", "tag"] | None = None
    skip_unchanged: bool = True


class ScheduleUpdate(BaseModel):
    """Only what is given changes."""

    cron: str | None = Field(default=None, max_length=200)
    timezone: str | None = Field(default=None, max_length=64)
    ref: str | None = Field(default=None, max_length=255)
    ref_type: Literal["branch", "tag"] | None = None
    skip_unchanged: bool | None = None
    enabled: bool | None = None
    # Turning on a schedule whose creator may no longer build: run its builds as
    # the caller from now on.
    take_over: bool = False


class SchedulePreviewIn(BaseModel):
    cron: str = Field(max_length=200)
    timezone: str | None = Field(default=None, max_length=64)


class SchedulePreview(BaseModel):
    cron: str
    timezone: str
    description: str | None = None
    next_runs: list[datetime]

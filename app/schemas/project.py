"""Request and response models for projects (app/models/project)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.task import BuildConfig, TaskStatus


class BuildBrief(BaseModel):
    """One build of a project, as a project page lists it. Settings and logs stay
    on the build's own page, which keeps the history permissions."""

    task_id: str
    version: str | None = None
    status: TaskStatus
    user_name: str
    start_time: datetime
    end_time: datetime | None = None


class ProjectSummary(BaseModel):
    id: int
    name: str
    project_type: str
    source_type: str
    source: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    builds: int = 0
    latest: BuildBrief | None = None
    last_passed: BuildBrief | None = None
    # Whether the caller may change or delete it.
    can_edit: bool = False


class ProjectDetail(ProjectSummary):
    config: BuildConfig
    history: list[BuildBrief] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    config: BuildConfig | None = None


class ProjectBuildRequest(BaseModel):
    """Build a new version: the project's defaults, this version, and any changes."""

    version: str = ""
    # Settings for this build only (e.g. {"git_ref": "v2.0.0", "docker_enabled": true}).
    overrides: dict = Field(default_factory=dict)

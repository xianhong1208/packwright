"""Projects: filing builds under them, and the defaults a new build starts from.

See app/models/project for what a project is and who may do what with one.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.schemas.task import BuildConfig, SourceType
from app.services.permission import CurrentUser, PermissionCode

# Per-build values that are not a project's defaults: they say which build this
# was, not how the project is built.
PER_BUILD_FIELDS = frozenset({"version"})


def source_of(config: BuildConfig) -> str:
    """The folder path or Git URL a build comes from — with the name, a project's identity."""
    raw = config.git_url if config.source_type == SourceType.GIT else config.project_path
    return (raw or "").strip().rstrip("/")


def defaults_from(config: BuildConfig) -> dict:
    """A build's settings as a project's defaults (without the per-build ones)."""
    return {k: v for k, v in config.model_dump(mode="json").items() if k not in PER_BUILD_FIELDS}


def may_change(project: Project, user: CurrentUser) -> bool:
    """Whoever created a project, and holders of project:manage, may change or delete it."""
    return project.created_by == user.username or user.has_permission(PermissionCode.PROJECT_MANAGE)


async def _free_name(db: AsyncSession, name: str) -> str:
    """``name``, or ``name (2)``, ``name (3)``… — the first one no project has."""
    taken = set((await db.execute(select(Project.name).where(Project.name.like(f"{name}%")))).scalars())
    if name not in taken:
        return name
    n = 2
    while f"{name} ({n})" in taken:
        n += 1
    return f"{name} ({n})"


async def file_build(db: AsyncSession, name: str, config: BuildConfig, user: str) -> Project:
    """The project a build without a project id belongs to.

    The same name built from the same source is the same project. A new source
    gets a new project; if its name is taken by another source's project, the new
    one is numbered ("shop (2)") rather than mixing two codebases' builds.
    """
    source = source_of(config)
    found = (
        await db.execute(select(Project).where(Project.name == name, Project.source == source))
    ).scalar_one_or_none()
    if found:
        return found
    project = Project(
        name=await _free_name(db, name),
        created_by=user,
        project_type=config.project_type.value,
        source_type=config.source_type.value,
        source=source,
        config=defaults_from(config),
    )
    db.add(project)
    await db.flush()
    return project


def config_for_build(project: Project, overrides: dict, version: str = "") -> BuildConfig:
    """A new build's settings: the project's defaults, with this build's changes on top."""
    return BuildConfig.model_validate({**project.config, **overrides, "version": version})

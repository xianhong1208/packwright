"""add projects, and file existing builds under them

A project is one piece of code the team builds again and again (app/models/project).
Existing builds are filed by (name, source): the same name built from the same
folder or Git URL is one project. When one name was used for different sources, the
most recently built keeps the name and the others become "name (2)", "name (3)"…
A project's default settings are those of its latest build.

The grouping is a pure function here rather than in app code, so that this
migration does what it did when it was written however the app changes later.

Revision ID: f5b8d2e6a1c3
Revises: e3a7c1d9b2f4
Create Date: 2026-11-06

"""
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f5b8d2e6a1c3"
down_revision: Union[str, Sequence[str], None] = "e3a7c1d9b2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def source_of(config: dict | None) -> str:
    """The folder path or Git URL a build came from ('' when its config is missing)."""
    config = config or {}
    raw = config.get("git_url") if config.get("source_type") == "git" else config.get("project_path")
    return str(raw or "").strip().rstrip("/")


def plan_projects(rows: Iterable[tuple[str, str, str, dict | None, Any]]) -> list[dict]:
    """Group (task_id, project_name, user_name, config, start_time) rows into projects.

    Returns one dict per project — name, created_by, project_type, source_type,
    source, config, created_at, task_ids — the most recently built first.
    """
    groups: dict[tuple[str, str], list[tuple[str, str, dict | None, Any]]] = {}
    for task_id, name, user, config, start in rows:
        groups.setdefault((name, source_of(config)), []).append((task_id, user, config, start))

    def when(row: tuple[str, str, dict | None, Any]) -> str:
        start = row[3]
        return start.isoformat() if isinstance(start, datetime) else str(start or "")

    plans = []
    for (name, source), builds in groups.items():
        builds.sort(key=when)
        first, latest = builds[0], builds[-1]
        config = latest[2] or {}
        plans.append({
            "name": name,
            "created_by": first[1],
            "project_type": config.get("project_type") or "backend_only",
            "source_type": config.get("source_type") or "local",
            "source": source,
            "config": config,
            "created_at": first[3],
            "last": when(latest),
            "task_ids": [b[0] for b in builds],
        })
    plans.sort(key=lambda p: p["last"], reverse=True)

    taken: dict[str, int] = {}
    for plan in plans:
        base = plan["name"]
        taken[base] = taken.get(base, 0) + 1
        if taken[base] > 1:
            plan["name"] = f"{base} ({taken[base]})"
        del plan["last"]
    return plans


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("project_type", sa.String(length=20), nullable=False),
        sa.Column("source_type", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=1000), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    with op.batch_alter_table("history") as batch:
        batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_history_project_id", "projects", ["project_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_history_project_id", ["project_id"])

    conn = op.get_bind()
    history = sa.table(
        "history",
        sa.column("task_id", sa.String),
        sa.column("project_name", sa.String),
        sa.column("user_name", sa.String),
        sa.column("config", sa.JSON),
        sa.column("start_time", sa.DateTime(timezone=True)),
        sa.column("project_id", sa.Integer),
    )
    projects = sa.table(
        "projects",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("created_by", sa.String),
        sa.column("project_type", sa.String),
        sa.column("source_type", sa.String),
        sa.column("source", sa.String),
        sa.column("config", sa.JSON),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    rows = conn.execute(
        sa.select(history.c.task_id, history.c.project_name, history.c.user_name, history.c.config, history.c.start_time)
    ).all()
    for plan in plan_projects(rows):
        task_ids = plan.pop("task_ids")
        if plan["created_at"] is None:
            plan.pop("created_at")
        conn.execute(projects.insert().values(**plan))
        project_id = conn.execute(sa.select(projects.c.id).where(projects.c.name == plan["name"])).scalar_one()
        for i in range(0, len(task_ids), 500):
            conn.execute(
                history.update().where(history.c.task_id.in_(task_ids[i:i + 500])).values(project_id=project_id)
            )


def downgrade() -> None:
    with op.batch_alter_table("history") as batch:
        batch.drop_index("ix_history_project_id")
        batch.drop_constraint("fk_history_project_id", type_="foreignkey")
        batch.drop_column("project_id")
    op.drop_table("projects")

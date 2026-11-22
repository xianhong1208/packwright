"""add project_schedules and schedule_runs

Scheduled builds per project and what each run came to; see
app/models/schedule.py.

Revision ID: e6b2c8d4f1a3
Revises: d4f7a9c2e8b1
Create Date: 2026-11-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e6b2c8d4f1a3"
down_revision: Union[str, Sequence[str], None] = "d4f7a9c2e8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("cron", sa.String(length=100), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("ref", sa.String(length=255), nullable=False),
        sa.Column("ref_type", sa.String(length=8), nullable=False),
        sa.Column("skip_unchanged", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("disabled_reason", sa.String(length=300), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE", name="fk_project_schedules_project_id"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL", name="fk_project_schedules_created_by_id"
        ),
    )
    op.create_index("ix_project_schedules_project_id", "project_schedules", ["project_id"])
    op.create_index("ix_project_schedules_next_run_at", "project_schedules", ["next_run_at"])
    op.create_table(
        "schedule_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["project_schedules.id"], ondelete="CASCADE", name="fk_schedule_runs_schedule_id"
        ),
    )
    op.create_index("ix_schedule_runs_schedule_id", "schedule_runs", ["schedule_id"])


def downgrade() -> None:
    op.drop_index("ix_schedule_runs_schedule_id", table_name="schedule_runs")
    op.drop_table("schedule_runs")
    op.drop_index("ix_project_schedules_next_run_at", table_name="project_schedules")
    op.drop_index("ix_project_schedules_project_id", table_name="project_schedules")
    op.drop_table("project_schedules")

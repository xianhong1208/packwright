"""add project_notifications

Where a project's build results are sent (Discord, Slack or a JSON webhook).
A new table only; existing data is untouched.

Revision ID: a7c3e9d1f2b8
Revises: f5b8d2e6a1c3
Create Date: 2026-11-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7c3e9d1f2b8"
down_revision: Union[str, Sequence[str], None] = "f5b8d2e6a1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id", sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_notifications_project_id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("url_encrypted", sa.Text(), nullable=False),
        sa.Column("url_hint", sa.String(length=120), nullable=False),
        sa.Column("on_failed", sa.Boolean(), nullable=False),
        sa.Column("on_passed", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ok", sa.Boolean(), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
    )
    op.create_index("ix_project_notifications_project_id", "project_notifications", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_notifications_project_id", table_name="project_notifications")
    op.drop_table("project_notifications")

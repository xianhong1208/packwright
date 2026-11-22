"""add project_hooks and hook_deliveries

Incoming webhooks per project (GitHub, GitLab, Gitea, generic) and the deliveries
each received; see app/models/hook.py.

Revision ID: d4f7a9c2e8b1
Revises: c9d4e1f7a2b6
Create Date: 2026-11-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4f7a9c2e8b1"
down_revision: Union[str, Sequence[str], None] = "c9d4e1f7a2b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_hooks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("signing_key_encrypted", sa.Text(), nullable=True),
        sa.Column("branches", sa.String(length=1000), nullable=False),
        sa.Column("tags", sa.String(length=1000), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("disabled_reason", sa.String(length=300), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("secret_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE", name="fk_project_hooks_project_id"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL", name="fk_project_hooks_created_by_id"
        ),
        sa.UniqueConstraint("public_id", name="uq_project_hooks_public_id"),
    )
    op.create_index("ix_project_hooks_project_id", "project_hooks", ["project_id"])
    op.create_table(
        "hook_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hook_id", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_id", sa.String(length=100), nullable=True),
        sa.Column("event", sa.String(length=64), nullable=True),
        sa.Column("ref", sa.String(length=255), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["hook_id"], ["project_hooks.id"], ondelete="CASCADE", name="fk_hook_deliveries_hook_id"
        ),
    )
    op.create_index("ix_hook_deliveries_hook_id_delivery_id", "hook_deliveries", ["hook_id", "delivery_id"])


def downgrade() -> None:
    op.drop_index("ix_hook_deliveries_hook_id_delivery_id", table_name="hook_deliveries")
    op.drop_table("hook_deliveries")
    op.drop_index("ix_project_hooks_project_id", table_name="project_hooks")
    op.drop_table("project_hooks")

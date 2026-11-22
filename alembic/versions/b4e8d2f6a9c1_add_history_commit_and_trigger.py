"""add history.commit_sha and history.trigger

commit_sha: the exact commit a Git build checked out. Existing rows keep NULL:
their clones were not pinned, so the commit is not known.
trigger: what started the build (console, api, push, tag, schedule). Every
existing row was started from the console, which is what the server default
gives it.

Revision ID: b4e8d2f6a9c1
Revises: a7c3e9d1f2b8
Create Date: 2026-11-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b4e8d2f6a9c1"
down_revision: Union[str, Sequence[str], None] = "a7c3e9d1f2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("history", sa.Column("commit_sha", sa.String(length=64), nullable=True))
    op.add_column(
        "history",
        sa.Column("trigger", sa.String(length=16), nullable=False, server_default="console"),
    )


def downgrade() -> None:
    with op.batch_alter_table("history") as batch:
        batch.drop_column("trigger")
        batch.drop_column("commit_sha")

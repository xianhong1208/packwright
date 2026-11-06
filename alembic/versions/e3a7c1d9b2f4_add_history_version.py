"""add history.version

The version a build was of (1.2.0, v2.0.0-rc.1), copied out of its config so a
project's builds can be grouped and an already-built version found by index.
Existing rows keep NULL: their configs predate the field.

Revision ID: e3a7c1d9b2f4
Revises: d8e2f3a4b5c6
Create Date: 2026-11-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e3a7c1d9b2f4"
down_revision: Union[str, Sequence[str], None] = "d8e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("history", sa.Column("version", sa.String(length=64), nullable=True))
    op.create_index("ix_history_project_version", "history", ["project_name", "version"])


def downgrade() -> None:
    op.drop_index("ix_history_project_version", table_name="history")
    op.drop_column("history", "version")

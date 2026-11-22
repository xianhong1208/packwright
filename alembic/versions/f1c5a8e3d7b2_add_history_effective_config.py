"""add history.effective_config

What a build was really made with once packwright.toml (app/services/packwright_toml)
was read: the effective settings, where each field came from (file, override,
project, detected) and the keys and lines the file set. history.config keeps
what was submitted, which a rebuild starts from. Existing rows keep NULL: they
were built from history.config alone.

Revision ID: f1c5a8e3d7b2
Revises: e6b2c8d4f1a3
Create Date: 2026-11-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f1c5a8e3d7b2"
down_revision: Union[str, Sequence[str], None] = "e6b2c8d4f1a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("history", sa.Column("effective_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("history") as batch:
        batch.drop_column("effective_config")

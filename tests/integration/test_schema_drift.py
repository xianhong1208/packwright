"""
Integration test: the Alembic migrations and the ORM models describe one schema.
Source: alembic/, app/models

The app creates tables with create_all() on a brand-new database, but every
existing deployment is migrated. A model change without a matching migration
passes every other test and then fails (or silently differs) in production.
This migrates an empty SQLite database to head and asks Alembic's
autogenerate comparison for any difference from the models.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

import app.models  # noqa: F401  registers every table on Base.metadata
from app.database import Base

ROOT = Path(__file__).resolve().parents[2]


def _migrate(url: str, revision: str = "head", *, down: bool = False) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["url"] = url
    (command.downgrade if down else command.upgrade)(cfg, revision)


@pytest.mark.integration
def test_tc_int_040_migrations_match_the_models(tmp_path):
    """TC-INT-040: upgrade head on an empty DB leaves no difference from the models."""
    _migrate(f"sqlite+aiosqlite:///{tmp_path / 'drift.db'}")

    engine = create_engine(f"sqlite:///{tmp_path / 'drift.db'}")
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            diff = compare_metadata(ctx, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], f"models and migrations disagree: {diff}"


@pytest.mark.integration
def test_tc_int_041_migrations_go_down_and_up_again(tmp_path):
    """TC-INT-041: every downgrade runs, and the chain re-applies cleanly."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'roundtrip.db'}"
    _migrate(url)
    _migrate(url, "base", down=True)
    _migrate(url)

"""
Filing existing builds under projects when the projects table arrives.
Source: alembic/versions/f5b8d2e6a1c3_add_projects.py (plan_projects, upgrade)
"""

import importlib.util
import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text

from .test_schema_drift import ROOT, _migrate


def _plan():
    path = ROOT / "alembic" / "versions" / "f5b8d2e6a1c3_add_projects.py"
    spec = importlib.util.spec_from_file_location("add_projects", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plan_projects


def _cfg(path: str, **extra) -> dict:
    return {"source_type": "local", "project_path": path, "project_type": "backend_only", **extra}


@pytest.mark.integration
def test_tc_int_050_same_name_and_source_is_one_project():
    """TC-INT-050: builds group by name and source; a name used for another source
    becomes "name (2)" (the most recently built keeps the plain name); defaults come
    from the latest build and the creator is whoever built first."""
    plan_projects = _plan()
    rows = [
        ("a1", "shop", "mei", _cfg("/srv/shop", pack_mode="full"), datetime(2026, 10, 1)),
        ("a2", "shop", "tony", _cfg("/srv/shop/", pack_mode="external"), datetime(2026, 11, 1)),
        ("b1", "shop", "tony", _cfg("/srv/old-shop"), datetime(2026, 9, 1)),
        ("c1", "web", "tony", {"source_type": "git", "git_url": "https://git.example.com/web.git", "project_type": "frontend_only"}, datetime(2026, 8, 1)),
    ]

    plans = {p["name"]: p for p in plan_projects(rows)}

    assert set(plans) == {"shop", "shop (2)", "web"}
    assert plans["shop"]["task_ids"] == ["a1", "a2"] and plans["shop"]["source"] == "/srv/shop"
    assert plans["shop"]["config"]["pack_mode"] == "external" and plans["shop"]["created_by"] == "mei"
    assert plans["shop (2)"]["task_ids"] == ["b1"]
    assert plans["web"]["source_type"] == "git" and plans["web"]["project_type"] == "frontend_only"


@pytest.mark.integration
def test_tc_int_051_upgrading_files_existing_builds(tmp_path):
    """TC-INT-051: migrating a database with builds creates their projects and links
    every build to one."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'backfill.db'}"
    _migrate(url, "e3a7c1d9b2f4")
    engine = create_engine(f"sqlite:///{tmp_path / 'backfill.db'}")
    try:
        with engine.begin() as conn:
            for task_id, name, path, start in [
                ("t1", "api", "/srv/api", "2026-11-01 10:00:00"),
                ("t2", "api", "/srv/api", "2026-11-02 10:00:00"),
                ("t3", "web", "/srv/web", "2026-11-03 10:00:00"),
            ]:
                conn.execute(
                    text("INSERT INTO history (task_id, user_name, project_name, python_version, start_time, status, config)"
                         " VALUES (:t, 'admin', :n, '3.13', :s, 'COMPLETED', :c)"),
                    {"t": task_id, "n": name, "s": start, "c": json.dumps(_cfg(path))},
                )
        _migrate(url)
        with engine.connect() as conn:
            projects = dict(conn.execute(text("SELECT name, id FROM projects")).all())
            links = dict(conn.execute(text("SELECT task_id, project_id FROM history")).all())
    finally:
        engine.dispose()

    assert set(projects) == {"api", "web"}
    assert links == {"t1": projects["api"], "t2": projects["api"], "t3": projects["web"]}

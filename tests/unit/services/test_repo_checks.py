"""
Tests for the project fingerprints New build reads to tell a backend from a
frontend from a full stack.
Source: app/services/git_service.py (check_repo_paths, path_lookup, diagnose_repo)
"""

import pytest

from app.services.git_service import check_repo_paths, diagnose_repo, path_lookup

FULLSTACK_FILES = ["app/main.py", "app/api/routes.py", "frontend/package.json", "frontend/src/main.tsx", "pyproject.toml"]


def _by_key(checks: list[dict]) -> dict:
    return {c["key"]: c for c in checks}


@pytest.mark.unit
def test_tc_repo_001_local_and_git_agree(tmp_path):
    """TC-REPO-001: a project gives the same fingerprints from disk (local mode)
    as from its file list (git mode)."""
    for rel in FULLSTACK_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")

    local = _by_key(diagnose_repo(tmp_path)["checks"])
    git = _by_key(check_repo_paths(path_lookup(FULLSTACK_FILES)))

    assert local == git
    assert local["entry_point"]["path"] == "app/main.py"
    assert local["package_json"]["path"] == "frontend/package.json"
    assert local["dockerfile"]["status"] == "warn"


@pytest.mark.unit
def test_tc_repo_002_first_listed_candidate_wins():
    """TC-REPO-002: with a root package.json and frontend/package.json, the root one
    is reported, in the order REPO_CHECKS lists them."""
    checks = _by_key(check_repo_paths(path_lookup(["package.json", "frontend/package.json"])))
    assert checks["package_json"]["path"] == "package.json"


@pytest.mark.unit
def test_tc_repo_003_a_directory_exists_when_a_file_is_under_it():
    """TC-REPO-003: git lists files, not directories; .venv counts as present when
    anything lies under it, and a file name that merely starts the same does not."""
    assert path_lookup([".venv/bin/python"])(".venv")
    assert not path_lookup([".venv-old/bin/python"])(".venv")
    assert not path_lookup(["main.py"])("main")


@pytest.mark.unit
def test_tc_repo_004_missing_or_not_a_directory(tmp_path):
    """TC-REPO-004: a path that is not a directory has no fingerprints."""
    (tmp_path / "file.txt").write_text("x")
    assert diagnose_repo(tmp_path / "nope") == {"checks": []}
    assert diagnose_repo(tmp_path / "file.txt") == {"checks": []}

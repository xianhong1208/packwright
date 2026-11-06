"""
Unit tests for the directories New build suggests to bundle.
Source: app/services/project_analysis (analyze_project_layout for a folder,
classify_from_paths for a Git tree)

The suggestions are ticked for the user, so a wrong one ships a broken program.
MCP Gate, built with them, compiled its alembic/ migrations in as Python (the
program then could not find them, and a package named alembic shadowed the real
library), bundled tests/ and examples/, and copied docs/ and the frontend's
sources beside the binary.
"""

from pathlib import Path

import pytest

from app.services.project_analysis import analyze_project_layout, classify_from_paths

# MCP Gate's layout, abridged: what `git ls-tree -r --name-only` lists.
MCP_GATE = [
    "main.py", "pyproject.toml",
    "src/__init__.py", "src/api/routes.py", "src/oauth/server.py",
    "db/__init__.py", "db/migrate.py",
    "alembic/env.py", "alembic/script.py.mako", "alembic/versions/0001_initial.py",
    "alembic/versions/0002_clients.py",
    "tests/test_oauth.py", "tests/conftest.py",
    "examples/client.py",
    "catalog/perplexity.yaml", "catalog/images/logo.svg",
    "config/config.yaml",
    "static/web/index.html", "static/web/assets/app.js",
    "docs/architecture.md", "docs/oauth.md",
    "frontend/package.json", "frontend/src/main.tsx", "frontend/index.html",
]


def _roles(result: dict) -> dict[str, str]:
    return {d["name"]: d["role"] for d in result["directories"]}


def _tree(root: Path, paths: list[str]) -> Path:
    for p in paths:
        f = root / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x = 1\n" if p.endswith(".py") else "x")
    return root


class TestGitTreeSuggestions:
    @pytest.mark.unit
    def test_tc_pan_001_mcp_gate_gets_a_program_that_starts(self):
        """TC-PAN-001: only its own packages are compiled in; what it reads from disk
        (migrations, catalog, config, the built console) is copied beside it."""
        result = classify_from_paths(MCP_GATE)
        assert result["suggested_extra_dirs"] == ["db", "src"]
        assert result["suggested_data_dirs"] == ["alembic", "catalog", "config", "static"]

    @pytest.mark.unit
    def test_tc_pan_002_alembic_migrations_are_data(self):
        """TC-PAN-002: env.py beside versions/ is Alembic's layout, run from disk."""
        role = next(d for d in classify_from_paths(MCP_GATE)["directories"] if d["name"] == "alembic")
        assert role["role"] == "data" and "Alembic" in role["reason"]

    @pytest.mark.unit
    @pytest.mark.parametrize("name", ["tests", "test", "examples", "example", "docs", "doc", "benchmarks"])
    def test_tc_pan_003_development_folders_are_skipped(self, name):
        """TC-PAN-003: tests, examples and docs are not part of the program."""
        assert _roles(classify_from_paths([f"{name}/a.py", f"{name}/b.md"]))[name] == "skip"

    @pytest.mark.unit
    def test_tc_pan_004_a_node_project_is_left_to_the_frontend_step(self):
        """TC-PAN-004: a folder with its own package.json is built by the frontend
        step; its sources are not copied as data."""
        assert _roles(classify_from_paths(MCP_GATE))["frontend"] == "skip"

    @pytest.mark.unit
    def test_tc_pan_005_a_package_named_like_a_skipped_folder_deeper_down_is_kept(self):
        """TC-PAN-005: only the top-level name counts; src/tests/ stays inside src."""
        result = classify_from_paths(["src/__init__.py", "src/tests/test_a.py", "app/versions/v.py"])
        assert _roles(result) == {"app": "source", "src": "source"}


class TestFolderSuggestions:
    @pytest.mark.unit
    def test_tc_pan_006_a_folder_gets_the_same_answer_as_its_git_tree(self, tmp_path):
        """TC-PAN-006: a local folder with MCP Gate's layout is classified the same way."""
        result = analyze_project_layout(str(_tree(tmp_path, MCP_GATE)), "main.py")
        assert sorted(result["suggested_extra_dirs"]) == ["db", "src"]
        assert result["suggested_data_dirs"] == ["alembic", "catalog", "config", "static"]
        assert _roles(result)["tests"] == _roles(result)["frontend"] == "skip"

    @pytest.mark.unit
    def test_tc_pan_007_ordinary_packages_and_data_are_unchanged(self, tmp_path):
        """TC-PAN-007: a plain package is source and a folder of assets is data, as before."""
        result = analyze_project_layout(str(_tree(tmp_path, [
            "main.py", "app/__init__.py", "app/core.py", "assets/logo.png", "templates/index.html",
        ])), "main.py")
        assert _roles(result) == {"app": "source", "assets": "data", "templates": "data"}

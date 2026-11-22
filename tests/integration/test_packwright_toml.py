"""
packwright.toml through the real app and database: where each setting came from, the
Config stage's record on the build and the project, schedules comparing the effective
settings, and downloads following what was built.
Source: app/services/packwright_toml.py, app/services/build_dispatcher.py (_config_stage),
        app/api/routes/tasks.py (create_task, _serve_task_output), app/api/routes/projects.py,
        app/services/schedules.py (_same_settings),
        alembic/versions/f1c5a8e3d7b2_add_history_effective_config.py

Builds are filed but not started; the Config stage is run by hand on a folder that
stands in for the checked-out commit.
"""

import io
import json
import sqlite3
import tarfile
import uuid

import pytest

from app.services.paths import git_workspace

from .test_artifact_download import _db_file
from .test_projects import _build, _git, _h
from . import test_schedules
from .test_schedules import SHA2, _due, _schedule, _settle, _tick

# The schedules suite's fixture: ls-remote answers env.sha, started builds are recorded.
schedules_env = test_schedules.sched_env

TOML = 'schema = 1\n\n[python]\nentry = "src/app.py"\n\n[project]\nversion = "2.0.0"\n'


def _task(client, token, task_id) -> dict:
    r = client.get(f"/api/tasks/{task_id}", headers=_h(token))
    assert r.status_code == 200, r.text
    return r.json()


def _config_stage(client, task: dict, root, text: str | None):
    """Run the build's Config stage on ``root`` holding ``text`` as packwright.toml."""
    from app.schemas.task import BuildConfig
    from app.services import build_dispatcher

    root.mkdir(parents=True, exist_ok=True)
    if text is not None:
        (root / "packwright.toml").write_text(text)

    async def run():
        return await build_dispatcher._config_stage(task["id"], BuildConfig.model_validate(task["config"]), root)

    return client.portal.call(run)


@pytest.mark.integration
def test_tc_int_124_origins_are_recorded_when_a_build_is_filed(client, admin_tokens, no_builds):
    """TC-INT-124: a first build's settings are the project's, except what the console
    says it detected; a later build's differences from the saved settings are its own
    changes; a project build's named overrides (and its version) are overrides."""
    token = admin_tokens["access_token"]
    url = "https://git.example.com/origins.git"
    r = client.post("/api/tasks", headers=_h(token), json={
        "project_name": "origins", "config": _git(url, entry_point="app.py"),
        "detected_fields": ["entry_point", "not_a_setting"],
    })
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["effective"]["origins"]["entry_point"] == "detected"
    assert first["effective"]["origins"]["onefile"] == "project"
    assert first["effective"]["config"] is None  # the Config stage has not run yet

    second = _build(client, token, "origins", _git(url, entry_point="app.py", generate_report=True))
    origins = _task(client, token, second["id"])["effective"]["origins"]
    assert origins["generate_report"] == "override" and origins["entry_point"] == "project"

    r = client.post(f"/api/projects/{first['project_id']}/builds", headers=_h(token),
                    json={"version": "1.1", "overrides": {"nuitka_jobs": 2}})
    assert r.status_code == 201, r.text
    origins = r.json()["effective"]["origins"]
    assert origins["nuitka_jobs"] == "override" and origins["version"] == "override"
    assert origins["entry_point"] == "project"


@pytest.mark.integration
def test_tc_int_125_the_config_stage_record_reaches_the_build_and_the_project(client, admin_tokens, no_builds, tmp_path):
    """TC-INT-125: after the Config stage the build shows its effective settings and every
    origin (the file over this build's own change, with the value it replaced), the
    history row's version follows the file, the project's saved settings are untouched,
    and the project lists the file's keys as read-only until a build finds no file."""
    token = admin_tokens["access_token"]
    url = "https://git.example.com/from-file.git"
    task = _build(client, token, "from-file", _git(url, entry_point="main.py"))
    pid = task["project_id"]
    second = _build(client, token, "from-file", _git(url, entry_point="mine.py"))

    _config_stage(client, second, tmp_path / "commit-1", TOML)

    built = _task(client, token, second["id"])
    eff = built["effective"]
    assert eff["config"]["entry_point"] == "src/app.py" and eff["config"]["version"] == "2.0.0"
    assert eff["origins"]["entry_point"] == "file" and eff["origins"]["version"] == "file"
    assert eff["origins"]["onefile"] == "project"
    entry = eff["file"]["fields"]["entry_point"]
    assert entry["key"] == "python.entry" and entry["line"] == 4 and entry["text"] == 'entry = "src/app.py"'
    assert entry["replaced"] == {"origin": "override", "value": "mine.py"}
    assert built["config"]["entry_point"] == "mine.py"  # what was submitted, which a rebuild starts from

    history = client.get(f"/api/history/{second['id']}", headers=_h(token)).json()
    assert history["effective"]["origins"]["entry_point"] == "file"
    with sqlite3.connect(_db_file()) as con:
        version, stored = con.execute(
            "SELECT h.version, p.config FROM history h JOIN projects p ON p.id = h.project_id WHERE h.task_id = ?",
            (second["id"],),
        ).fetchone()
    assert version == "2.0.0" and json.loads(stored)["entry_point"] == "main.py"

    project = client.get(f"/api/projects/{pid}", headers=_h(token)).json()
    assert project["config"]["entry_point"] == "main.py"
    assert project["from_file"]["task_id"] == second["id"]
    assert set(project["from_file"]["fields"]) == {"entry_point", "version"}
    assert project["from_file"]["fields"]["entry_point"]["line"] == 4

    # A build not yet past its Config stage does not count; one that found no file clears it.
    third = _build(client, token, "from-file", _git(url))
    assert client.get(f"/api/projects/{pid}", headers=_h(token)).json()["from_file"]["task_id"] == second["id"]
    _config_stage(client, third, tmp_path / "commit-2", None)
    assert client.get(f"/api/projects/{pid}", headers=_h(token)).json()["from_file"] is None
    assert _task(client, token, third["id"])["effective"]["file"] is None


@pytest.mark.integration
def test_tc_int_126_skip_unchanged_counts_the_files_values(client, admin_tokens, schedules_env, tmp_path):
    """TC-INT-126: a schedule's skip-unchanged compares the effective settings: at the same
    commit, a saved setting that packwright.toml overrides changes nothing (skipped); one
    it leaves alone builds; a new commit (a changed file) builds."""
    token = admin_tokens["access_token"]
    url = "https://github.com/acme/toml-sched.git"
    pid = _build(client, token, "toml-sched", _git(url))["project_id"]
    _settle(pid)
    s = _schedule(client, token, pid)

    [first] = _tick(client, _due(s["id"]))
    assert first.result == "built"
    _config_stage(client, _task(client, token, first.task_id), tmp_path / "c1", TOML)
    _settle(pid, "COMPLETED")

    # The project's entry point changes, but the file sets it: the same build.
    assert client.put(f"/api/projects/{pid}", headers=_h(token),
                      json={"config": _git(url, entry_point="other.py")}).status_code == 200
    [same] = _tick(client, _due(s["id"]))
    assert same.result == "skipped" and same.reason.startswith("unchanged") and same.task_id == first.task_id

    # A setting the file leaves alone changes: built.
    assert client.put(f"/api/projects/{pid}", headers=_h(token),
                      json={"config": _git(url, entry_point="other.py", generate_report=True)}).status_code == 200
    [changed] = _tick(client, _due(s["id"]))
    assert changed.result == "built"
    _config_stage(client, _task(client, token, changed.task_id), tmp_path / "c2", TOML)
    _settle(pid, "COMPLETED")
    [again] = _tick(client, _due(s["id"]))
    assert again.result == "skipped"

    # packwright.toml changed in the repository: a new commit, built.
    schedules_env.sha = SHA2
    [moved] = _tick(client, _due(s["id"]))
    assert moved.result == "built" and moved.commit_sha == SHA2


@pytest.mark.integration
def test_tc_int_127_a_download_follows_the_settings_the_build_was_made_with(client, admin_tokens):
    """TC-INT-127: when packwright.toml moved the output directory, the download serves
    the directory the build wrote, not the submitted one."""
    task_id = str(uuid.uuid4())
    submitted = {"source_type": "git", "project_path": "", "output_dir": "dist"}
    effective = {"config": {**submitted, "output_dir": "out"}, "origins": {"output_dir": "file"}, "file": None}
    with sqlite3.connect(_db_file()) as con:
        con.execute(
            "INSERT INTO history (task_id, user_name, project_name, python_version, start_time, status, config,"
            " effective_config) VALUES (?, 'admin', 'demo', '3.13', '2026-11-22 00:00:00', 'COMPLETED', ?, ?)",
            (task_id, json.dumps(submitted), json.dumps(effective)),
        )
    out = git_workspace(task_id) / "out"
    out.mkdir(parents=True)
    (out / "app.bin").write_bytes(b"built")

    r = client.get(f"/api/history/{task_id}/download", headers=_h(admin_tokens["access_token"]))
    assert r.status_code == 200, r.text
    names = tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz").getnames()
    assert any(n.endswith("out/app.bin") for n in names)

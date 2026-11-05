"""
Integration tests for serving a finished task's artifact.
Source: app/api/routes/tasks (_serve_task_output), app/services/paths
"""

import io
import json
import os
import sqlite3
import tarfile
import uuid
from pathlib import Path

import pytest

from app.config import get_settings
from app.services.paths import docker_export_path, git_workspace


def _db_file() -> str:
    return os.environ["DATABASE_URL"].split(":///", 1)[1]


def _completed_task(config: dict) -> str:
    task_id = str(uuid.uuid4())
    with sqlite3.connect(_db_file()) as con:
        con.execute(
            "INSERT INTO history (task_id, user_name, project_name, python_version, start_time, status, config)"
            " VALUES (?, 'admin', 'demo', '3.12', '2026-11-05 00:00:00', 'COMPLETED', ?)",
            (task_id, json.dumps(config)),
        )
    return task_id


def _download(client, admin_tokens, task_id):
    return client.get(f"/api/history/{task_id}/download",
                      headers={"Authorization": f"Bearer {admin_tokens['access_token']}"})


@pytest.mark.integration
def test_tc_int_020_git_task_serves_its_workspace(client, admin_tokens):
    """TC-INT-020: a git-mode download comes from git_workspace_dir/<task_id>/<output_dir>.

    It used to read project_path (blank for git tasks), i.e. the service's
    working directory: 404 or the wrong files.
    """
    task_id = _completed_task({"source_type": "git", "project_path": "", "output_dir": "dist"})
    out = git_workspace(task_id) / "dist"
    out.mkdir(parents=True)
    (out / "app.bin").write_bytes(b"built")

    r = _download(client, admin_tokens, task_id)

    assert r.status_code == 200
    names = tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz").getnames()
    assert any(n.endswith("app.bin") for n in names)


@pytest.mark.integration
def test_tc_int_021_git_task_never_serves_the_service_directory(client, admin_tokens):
    """TC-INT-021: output_dir="data" in git mode must not stream the service's own data/.

    The service's data/ holds the database: password hashes and every stored env.
    """
    task_id = _completed_task({"source_type": "git", "project_path": "", "output_dir": "data"})
    assert _download(client, admin_tokens, task_id).status_code == 404


@pytest.mark.integration
def test_tc_int_022_absolute_output_dir_is_refused(client, admin_tokens):
    """TC-INT-022: an absolute output_dir stored in a config cannot be served."""
    task_id = _completed_task({"source_type": "git", "project_path": "", "output_dir": "/etc"})
    assert _download(client, admin_tokens, task_id).status_code == 403


@pytest.mark.integration
def test_tc_int_023_docker_downloads_are_per_task(client, admin_tokens):
    """TC-INT-023: two builds tagged app:latest download their own image."""
    cfg = {"source_type": "local", "project_path": "/tmp", "docker_enabled": True,
           "docker_image_name": "app:latest"}
    first, second = _completed_task(cfg), _completed_task(cfg)
    Path(get_settings().docker_images_dir).mkdir(parents=True, exist_ok=True)
    docker_export_path(first).write_bytes(b"image-one")
    docker_export_path(second).write_bytes(b"image-two")

    assert _download(client, admin_tokens, first).content == b"image-one"
    assert _download(client, admin_tokens, second).content == b"image-two"


@pytest.mark.integration
def test_tc_int_024_git_mode_rejects_climbing_directory_names(client, admin_tokens):
    """TC-INT-024: create-time validation now covers git mode's directory names."""
    from app.api.routes.tasks import _validate_build_config_paths
    from app.schemas.task import BuildConfig
    from fastapi import HTTPException

    cfg = BuildConfig.model_validate({
        "project_name": "demo", "source_type": "git", "git_url": "https://example.com/r.git",
        "git_ref": "main", "output_dir": "../../etc",
    })
    with pytest.raises(HTTPException) as exc:
        _validate_build_config_paths(cfg)
    assert exc.value.status_code == 400

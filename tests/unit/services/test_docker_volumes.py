"""
Tests for state folders, the program's user and the suggested `docker run`.
Source: app/services/docker_worker.py (parse_volumes, _generate_dockerfile, run_hint,
run_docker_build), app/services/nuitka_worker.py (_created_dirs, _smoke_test)

Packaging MCP Gate gave an image with no VOLUME, running as root, and the hint
`docker run --rm --network host <image>`: every start made a new database, new
signing keys and a new encryption key. The image now declares the folders the
program created in its smoke run as volumes, owned by a non-root user, and the
hint mounts a named volume on each.
"""

import pytest
from pydantic import ValidationError

from app.schemas.task import BuildConfig
from app.services import docker_worker, nuitka_worker
from app.services.docker_worker import _generate_dockerfile, mount_point, parse_volumes, run_hint


def _config(tmp_path, **extra) -> BuildConfig:
    return BuildConfig(project_type="backend_only", project_path=str(tmp_path), docker_enabled=True,
                       output_name="main", **extra)


@pytest.mark.unit
def test_tc_dvol_001_volume_list_parsing():
    """TC-DVOL-001: parse_volumes — commas or newlines, trailing slashes, duplicates; mount points under /app."""
    assert parse_volumes("data, secrets/\nlogs\n\n data") == ["data", "secrets", "logs"]
    assert parse_volumes(None) == [] and parse_volumes("") == []
    assert mount_point("data") == "/app/data"
    assert mount_point("/var/lib/app") == "/var/lib/app"


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["../etc", "data/../..", "my data", "a;rm -rf", "x\"y", "/", "$HOME"])
def test_tc_dvol_002_a_volume_must_be_a_plain_path(bad):
    """TC-DVOL-002: the setting is refused when an entry could break out of the RUN/VOLUME line."""
    with pytest.raises(ValidationError):
        BuildConfig(docker_volumes=bad)


@pytest.mark.unit
def test_tc_dvol_003_non_root_with_owned_volumes(tmp_path):
    """TC-DVOL-003: by default the program's user owns its files (on the COPY) and its volumes, and runs it."""
    (tmp_path / "dist" / "config").mkdir(parents=True)
    dockerfile = _generate_dockerfile(_config(tmp_path, data_dirs="config", docker_volumes="data, secrets"),
                                      precompiled=True)
    lines = dockerfile.splitlines()

    assert "RUN useradd --system --uid 10001 --user-group --home-dir /app --no-create-home app" in lines
    assert all(line.startswith("COPY --chown=app:app ") for line in lines if line.startswith("COPY "))
    assert "RUN mkdir -p /app/data /app/secrets && chown app:app /app /app/data /app/secrets" in lines
    assert 'VOLUME ["/app/data", "/app/secrets"]' in lines
    assert lines.index("USER app") < lines.index('CMD ["./main"]')
    assert "chown -R" not in dockerfile  # a recursive chown would store every file again


@pytest.mark.unit
def test_tc_dvol_004_run_as_root_keeps_the_volumes(tmp_path):
    """TC-DVOL-004: Run as root drops the user, not the volumes."""
    dockerfile = _generate_dockerfile(_config(tmp_path, docker_volumes="data", docker_run_as_root=True),
                                      precompiled=True)
    assert "useradd" not in dockerfile and "USER " not in dockerfile and "--chown" not in dockerfile
    assert 'VOLUME ["/app/data"]' in dockerfile


@pytest.mark.unit
def test_tc_dvol_005_without_volumes_the_user_still_owns_app(tmp_path):
    """TC-DVOL-005: no volumes: no VOLUME line, and /app is the user's so it can create its folders."""
    dockerfile = _generate_dockerfile(_config(tmp_path), precompiled=True)
    assert "VOLUME" not in dockerfile
    assert "RUN chown app:app /app" in dockerfile.splitlines()


@pytest.mark.unit
def test_tc_dvol_006_run_hint_keeps_state(tmp_path):
    """TC-DVOL-006: run_hint — detached, port published, a named volume per folder; no --rm, no host network."""
    config = _config(tmp_path, docker_volumes="data, secrets", docker_expose_port=4598)
    hint = run_hint(config, "registry.example.com/team/mcp_gate:1.4.0", precompiled=True)
    assert hint == (
        "docker run -d --name mcp_gate -p 4598:4598 -v mcp_gate-data:/app/data "
        "-v mcp_gate-secrets:/app/secrets registry.example.com/team/mcp_gate:1.4.0"
    )
    assert "--rm" not in hint and "--network host" not in hint


@pytest.mark.unit
@pytest.mark.parametrize("standalone", [False, True])
def test_tc_dvol_007_created_dirs_beside_the_binary(tmp_path, standalone):
    """TC-DVOL-007: _created_dirs — new top-level folders where it ran or beside a standalone binary;
    not files, not folders that were there, not bytecode caches, not deeper folders."""
    out = tmp_path / "dist"
    home = out / "main.dist" if standalone else out
    (home / "config").mkdir(parents=True)
    before = nuitka_worker._tree_state(out)
    for d in ("data", "secrets/keys", "config/new", "__pycache__"):
        (home / d).mkdir(parents=True)
    (home / "app.db").write_text("x")
    (out / "logs").mkdir()

    assert nuitka_worker._created_dirs(out, home, before) == (["data", "logs", "secrets"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_dvol_008_smoke_test_reports_created_dirs(tmp_path, mocker):
    """TC-DVOL-008: _smoke_test — the folders are in the result, and still removed from the output."""
    mocker.patch.object(nuitka_worker, "_build_smoke_env", return_value={"PATH": "/usr/bin:/bin"})
    mocker.patch.object(nuitka_worker.task_manager, "append_log", mocker.AsyncMock())
    binary = tmp_path / "main"
    binary.write_text("#!/bin/sh\nmkdir -p data secrets logs\necho k > secrets/key\n")
    binary.chmod(0o755)

    result = await nuitka_worker._smoke_test("t", binary, tmp_path)

    assert result["created_dirs"] == ["data", "logs", "secrets"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["main"]


def _quiet(mocker):
    tm = docker_worker.task_manager
    for name in ("append_log", "update_task", "merge_result"):
        mocker.patch.object(tm, name, mocker.AsyncMock())
    return mocker.patch.object(tm, "record_config_value", mocker.AsyncMock())


def _smoke_result(mocker, dirs):
    verify = mocker.MagicMock(created_dirs=dirs)
    task = mocker.MagicMock(result=mocker.MagicMock(verify=verify))
    mocker.patch.object(docker_worker.task_manager, "get_task", mocker.AsyncMock(return_value=task))


def _capture_dockerfile(mocker, tmp_path):
    seen = {}

    async def build(task_id, cmd, cwd):
        seen["dockerfile"] = (tmp_path / "Dockerfile.generated").read_text()
        return False

    mocker.patch.object(docker_worker, "_run_docker_command", side_effect=build)
    mocker.patch.object(docker_worker.shutil, "which", return_value="/usr/bin/docker")
    return seen


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_dvol_009_unset_volumes_come_from_the_smoke_run(tmp_path, mocker):
    """TC-DVOL-009: run_docker_build — with Volumes unset, the smoke run's folders become VOLUMEs and are saved."""
    (tmp_path / "dist").mkdir()
    record = _quiet(mocker)
    _smoke_result(mocker, ["data", "secrets"])
    seen = _capture_dockerfile(mocker, tmp_path)

    await docker_worker.run_docker_build("t1", _config(tmp_path), db=None, precompiled=True)

    assert 'VOLUME ["/app/data", "/app/secrets"]' in seen["dockerfile"]
    record.assert_awaited_once_with("t1", "docker_volumes", "data, secrets", None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_dvol_010_a_set_value_wins(tmp_path, mocker):
    """TC-DVOL-010: run_docker_build — a Volumes value the user set (even empty) is used as it is."""
    (tmp_path / "dist").mkdir()
    record = _quiet(mocker)
    _smoke_result(mocker, ["data", "secrets", "logs"])
    seen = _capture_dockerfile(mocker, tmp_path)

    await docker_worker.run_docker_build("t1", _config(tmp_path, docker_volumes="state"), db=None, precompiled=True)
    assert 'VOLUME ["/app/state"]' in seen["dockerfile"]
    await docker_worker.run_docker_build("t1", _config(tmp_path, docker_volumes=""), db=None, precompiled=True)
    assert "VOLUME" not in seen["dockerfile"]
    record.assert_not_awaited()

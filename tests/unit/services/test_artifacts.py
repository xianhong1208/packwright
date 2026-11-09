"""
Unit tests for giving each local build its own output.
Source: app/services/artifacts.py (clear_output_dir, keep_output, output_dir_name)

A local build wrote into the user's folder and never emptied it, and Download
packed that folder when it was clicked: an archive held earlier builds' files,
or another build's binary altogether.
"""

import pytest

from app.schemas.task import BuildConfig
from app.services import artifacts


def _config(tmp_path, **extra) -> BuildConfig:
    return BuildConfig(project_path=str(tmp_path), source_type="local", **extra)


@pytest.fixture
def workspace(tmp_path, mocker):
    root = tmp_path / "workspace"
    mocker.patch.object(artifacts, "git_workspace", side_effect=lambda task_id: root / task_id)
    return root


def _project(tmp_path):
    project = tmp_path / "project"
    (project / "dist" / "libs" / "rich").mkdir(parents=True)
    (project / "dist" / "main").write_text("one-file build")
    (project / "dist" / "libs" / "rich" / "__init__.py").write_text("")
    (project / "main.py").write_text("print('hi')")
    return project


@pytest.mark.unit
def test_tc_art_001_the_output_directory_starts_empty(tmp_path):
    """TC-ART-001: everything an earlier build left in the output directory is removed,
    the directory itself stays, and nothing outside it is touched."""
    project = _project(tmp_path)

    line = artifacts.clear_output_dir(project, _config(project))

    assert (project / "dist").is_dir() and list((project / "dist").iterdir()) == []
    assert (project / "main.py").exists()
    assert "2 entries" in line


@pytest.mark.unit
@pytest.mark.parametrize(
    ("output_dir", "extra"),
    [
        (".", {}),                                              # the project itself
        ("dist", {"entry_point": "dist/main.py"}),              # holds the entry point
        ("src", {"extra_dirs": "src/pkg"}),                     # holds extra code
        ("web", {"project_type": "frontend_only", "frontend_dir": "web/app"}),
        ("dist", {"data_dirs": "static,dist/templates"}),       # holds a data dir
        ("app", {}),                                            # holds a .venv
    ],
)
def test_tc_art_002_source_is_never_emptied(tmp_path, output_dir, extra):
    """TC-ART-002: an output directory that is the project, or holds anything the build
    reads (entry point, code, frontend or data directory, a .venv), is left alone and the
    log line says why."""
    project = _project(tmp_path)
    (project / "dist" / "main.py").write_text("")
    for sub in ("src/pkg", "web/app", "dist/templates", "app/.venv"):
        (project / sub).mkdir(parents=True, exist_ok=True)
        (project / sub / "keep.txt").write_text("source")
    before = sorted(p.relative_to(project) for p in project.rglob("*"))

    line = artifacts.clear_output_dir(project, _config(project, output_dir=output_dir, **extra))

    assert sorted(p.relative_to(project) for p in project.rglob("*")) == before
    assert "not emptied" in line


@pytest.mark.unit
def test_tc_art_003_kept_output_does_not_follow_the_folder(tmp_path, workspace):
    """TC-ART-003: the kept copy is this build's: emptying the folder and building again
    there changes nothing in it."""
    project = _project(tmp_path)
    config = _config(project)

    kept = artifacts.keep_output("task-1", project, config)
    artifacts.clear_output_dir(project, config)
    (project / "dist" / "main.dist").mkdir()
    (project / "dist" / "main.dist" / "main").write_text("folder build")

    assert kept == workspace / "task-1" / "dist"
    assert sorted(str(p.relative_to(kept)) for p in kept.rglob("*")) == [
        "libs", "libs/rich", "libs/rich/__init__.py", "main"]
    assert (kept / "main").read_text() == "one-file build"


@pytest.mark.unit
def test_tc_art_004_symlinks_are_kept_as_links(tmp_path, workspace):
    """TC-ART-004: a symlink in the output is copied as a link, never as the file it
    points at, so a link cannot pull a host file into the download."""
    project = _project(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("host file")
    (project / "dist" / "peek").symlink_to(secret)

    kept = artifacts.keep_output("task-2", project, _config(project))

    assert (kept / "peek").is_symlink()
    assert (kept / "peek").readlink() == secret


@pytest.mark.unit
def test_tc_art_005_nothing_to_keep(tmp_path, workspace):
    """TC-ART-005: no copy when there is no output directory or it is the project itself."""
    project = tmp_path / "project"
    project.mkdir()

    assert artifacts.keep_output("t", project, _config(project)) is None
    assert artifacts.keep_output("t", project, _config(project, output_dir="")) is None
    assert not workspace.exists()


@pytest.mark.unit
def test_tc_art_006_docker_builds_default_to_dist(tmp_path):
    """TC-ART-006: a Docker build with no output directory compiles into dist/, so that
    is what gets emptied; a frontend-only Docker build has none."""
    assert artifacts.output_dir_name(_config(tmp_path, output_dir="", docker_enabled=True)) == "dist"
    assert artifacts.output_dir_name(
        _config(tmp_path, output_dir="", docker_enabled=True, project_type="frontend_only")) == ""


@pytest.fixture
def dispatcher(mocker, workspace):
    """dispatch_build with the workers replaced by a fake build that records what it
    found in dist/ and writes its own output."""
    from types import SimpleNamespace

    from app.schemas.task import TaskStatus
    from app.services import build_dispatcher

    state = SimpleNamespace(status=TaskStatus.COMPLETED, seen=None)

    async def fake_build(task_id, config, db):
        dist = artifacts.safe_join(artifacts.Path(config.project_path), "dist")
        state.seen = sorted(p.name for p in dist.iterdir()) if dist.exists() else None
        dist.mkdir(exist_ok=True)
        (dist / "main.dist").mkdir(exist_ok=True)
        (dist / "main.dist" / "main").write_text("folder build")

    mocker.patch.object(build_dispatcher, "_dispatch_locked", side_effect=fake_build)
    tm = build_dispatcher.task_manager
    mocker.patch.object(tm, "update_task", mocker.AsyncMock())
    mocker.patch.object(tm, "append_log", mocker.AsyncMock())
    mocker.patch.object(tm, "merge_result", mocker.AsyncMock())
    mocker.patch.object(tm, "get_task", mocker.AsyncMock(side_effect=lambda _id: SimpleNamespace(status=state.status)))
    state.dispatch = build_dispatcher.dispatch_build
    state.merge_result = tm.merge_result
    return state


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_art_007_a_local_build_starts_empty_and_keeps_its_output(tmp_path, dispatcher, workspace):
    """TC-ART-007: dispatch_build empties dist/ before the build and keeps what this
    build wrote, and records that on the result for the download."""
    project = _project(tmp_path)

    await dispatcher.dispatch("task-7", _config(project, pack_mode="full", onefile=False), db=None)

    assert dispatcher.seen == []
    kept = workspace / "task-7" / "dist"
    assert sorted(str(p.relative_to(kept)) for p in kept.rglob("*")) == ["main.dist", "main.dist/main"]
    dispatcher.merge_result.assert_awaited_once_with("task-7", {artifacts.KEPT_OUTPUT_KEY: True}, None)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["failed", "docker", "git"])
async def test_tc_art_008_nothing_kept_when_there_is_nothing_to_serve(tmp_path, dispatcher, workspace, case):
    """TC-ART-008: a failed build and a Docker build (served from its image) keep no
    copy; a Git build, already in its own workspace, is neither emptied nor copied."""
    from app.schemas.task import TaskStatus

    project = _project(tmp_path)
    extra = {}
    if case == "failed":
        dispatcher.status = TaskStatus.FAILED
    elif case == "docker":
        extra = {"docker_enabled": True}
    else:
        extra = {"source_type": "git", "git_url": "https://git.example.com/a.git", "git_ref": "main"}
    config = BuildConfig(**{"project_path": str(project), "source_type": "local", **extra})

    await dispatcher.dispatch("task-8", config, db=None)

    assert not (workspace / "task-8").exists()
    dispatcher.merge_result.assert_not_awaited()
    assert dispatcher.seen == ([] if case != "git" else ["libs", "main"])


@pytest.mark.unit
def test_tc_art_009_the_project_folder_is_named_as_such(tmp_path):
    """TC-ART-009: output_dir "." is refused as the project folder itself, before any
    other check, so the log names the real reason."""
    project = _project(tmp_path)

    line = artifacts.clear_output_dir(project, _config(project, output_dir="."))

    assert "project folder itself" in line

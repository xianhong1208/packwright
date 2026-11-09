"""
Unit tests confining a local-mode build to the allowed roots.
Source: app/api/routes/tasks._validate_build_config_paths

Seven read-only endpoints already route through _validate_allowed_path and the
README promises paths outside the configured LOCAL_SOURCE_ROOTS are refused. The one
request path that WRITES and RECURSIVELY DELETES — create_task — checked
nothing, handing the config straight to the dispatcher.

"task:create is effectively shell access" does not excuse it: that risk is
bounded by directories the user can already reach, while this reached the whole
filesystem and contradicted a control implemented in the same file.
"""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes.tasks import _validate_build_config_paths
from app.schemas.task import BuildConfig, SourceType

SAFE_ROOT = "/srv/packwright/projects/demo"


@pytest.fixture(autouse=True)
def _configure_local_roots(monkeypatch):
    """Local-source mode is enabled here by allowing SAFE_ROOT's tree."""
    monkeypatch.setattr(
        "app.api.routes.tasks._allowed_path_prefixes",
        lambda: ("/srv/packwright/",),
    )


def _check(**kwargs) -> None:
    _validate_build_config_paths(BuildConfig(**kwargs))


class TestProjectRoot:
    @pytest.mark.unit
    @pytest.mark.parametrize("path", ["/", "/etc", "/root", "/opt/x", "/home/someone"])
    def test_tc_pth_001_rejects_paths_outside_the_allowed_roots(self, path):
        """TC-PTH-001: create_task — a project path outside the roots is refused.

        _build_frontend_only rmtree's project_path/output_dir, so
        project_path="/" with output_dir="etc" deletes /etc as the service user.
        """
        with pytest.raises(HTTPException) as exc:
            _check(project_path=path)
        assert exc.value.status_code == 403

    @pytest.mark.unit
    def test_tc_pth_002_accepts_an_ordinary_project(self):
        """TC-PTH-002: create_task — a normal local build is unaffected."""
        _check(
            project_path=SAFE_ROOT,
            output_dir="dist",
            data_dirs="app, alembic",
            extra_dirs="src",
            frontend_dir="frontend",
        )

    @pytest.mark.unit
    def test_tc_pth_003_git_mode_is_exempt(self):
        """TC-PTH-003: create_task — git mode is not subject to this check.

        Its project_path is assigned by _prepare_git_workspace into a per-task
        directory, never supplied by the caller. Validating the caller's empty
        value would reject every git build.
        """
        _check(source_type=SourceType.GIT, git_url="https://gitlab/x.git", git_ref="main")


class TestSubdirectoryContainment:
    """Directory names are joined onto project_path, then deleted or written."""

    @pytest.mark.unit
    @pytest.mark.parametrize("value", ["../../../etc", "../..", "/etc", "a/../../../root"])
    def test_tc_pth_010_data_dirs_cannot_escape(self, value):
        """TC-PTH-010: create_task — data_dirs is rmtree'd per entry by nuitka_worker."""
        with pytest.raises(HTTPException) as exc:
            _check(project_path=SAFE_ROOT, data_dirs=value)
        assert exc.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.parametrize("value", ["../../../etc", "/etc"])
    def test_tc_pth_011_output_dir_cannot_escape(self, value):
        """TC-PTH-011: create_task — output_dir is the rmtree target in frontend builds."""
        with pytest.raises(HTTPException):
            _check(project_path=SAFE_ROOT, output_dir=value)

    @pytest.mark.unit
    def test_tc_pth_012_frontend_dir_cannot_escape(self):
        """TC-PTH-012: create_task — frontend_dir is where env content is written.

        Rejected by the schema validator before this function is reached, since
        the same value also lands in a Dockerfile COPY.
        """
        with pytest.raises(ValidationError):
            BuildConfig(project_path=SAFE_ROOT, frontend_dir="../../root")

    @pytest.mark.unit
    def test_tc_pth_013_only_the_escaping_entry_is_rejected(self):
        """TC-PTH-013: create_task — a comma list is checked entry by entry.

        A legitimate list must not be rejected because one entry is bad, nor a
        bad entry accepted because the others are fine.
        """
        _check(project_path=SAFE_ROOT, data_dirs="config, static, templates")
        with pytest.raises(HTTPException):
            _check(project_path=SAFE_ROOT, data_dirs="config, ../../../etc, static")

    @pytest.mark.unit
    def test_tc_pth_014_blank_entries_are_ignored(self):
        """TC-PTH-014: create_task — trailing commas and spaces are not paths."""
        _check(project_path=SAFE_ROOT, data_dirs="config,, , static,")

    @pytest.mark.unit
    def test_tc_pth_015_nested_subdirectories_are_allowed(self):
        """TC-PTH-015: create_task — depth inside the project is fine.

        The rule is containment, not a ban on slashes; rejecting these would
        break real projects.
        """
        _check(project_path=SAFE_ROOT, data_dirs="app/static, app/templates")


class TestEntryPointContainment:
    """The entry point gets the libs loader written into it and is compiled and
    shipped; entry_point="../../elsewhere/app.py" edited and packaged a file
    outside the allowed roots."""

    @pytest.mark.unit
    @pytest.mark.parametrize("value", ["../../qa/qa.py", "/etc/passwd", "src/../../../x.py", "..", ".", ""])
    def test_tc_pth_023_local_entry_point_cannot_escape(self, value):
        """TC-PTH-023: create_task — a local entry point outside the project (or the
        project folder itself) is refused with 400."""
        with pytest.raises(HTTPException) as exc:
            _check(project_path=SAFE_ROOT, entry_point=value)
        assert exc.value.status_code == 400
        assert "Entry point" in exc.value.detail

    @pytest.mark.unit
    @pytest.mark.parametrize("value", ["../../etc/hostname", "/etc/passwd", "a/../../b.py"])
    def test_tc_pth_024_git_entry_point_cannot_escape(self, value):
        """TC-PTH-024: create_task — in Git mode the name is checked lexically, like the
        directory names (the clone does not exist yet)."""
        with pytest.raises(HTTPException) as exc:
            _check(source_type=SourceType.GIT, git_url="https://gitlab/x.git", git_ref="main", entry_point=value)
        assert exc.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.parametrize("value", ["main.py", "src/app/main.py", "./main.py"])
    def test_tc_pth_025_entry_points_inside_are_fine(self, value):
        """TC-PTH-025: create_task — nested and ./ entry points inside the project pass."""
        _check(project_path=SAFE_ROOT, entry_point=value)
        _check(source_type=SourceType.GIT, git_url="https://gitlab/x.git", git_ref="main", entry_point=value)

    @pytest.mark.unit
    def test_tc_pth_026_a_symlink_out_of_the_project_is_refused(self, tmp_path, monkeypatch):
        """TC-PTH-026: create_task — the local check resolves symlinks: main.py linking
        to a file elsewhere is outside the project."""
        monkeypatch.setattr("app.api.routes.tasks._allowed_path_prefixes", lambda: (str(tmp_path) + "/",))
        project = tmp_path / "project"
        project.mkdir()
        (tmp_path / "elsewhere.py").write_text("print('x')")
        (project / "main.py").symlink_to(tmp_path / "elsewhere.py")

        with pytest.raises(HTTPException):
            _check(project_path=str(project), entry_point="main.py")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_pth_028_analysis_does_not_read_an_entry_point_elsewhere(self, tmp_path, monkeypatch):
        """TC-PTH-028: analyze-project parses the entry point's imports and returns them;
        an entry point outside the project is refused instead of read."""
        from app.api.routes.tasks import analyze_project

        monkeypatch.setattr("app.api.routes.tasks._allowed_path_prefixes", lambda: (str(tmp_path) + "/",))
        project = tmp_path / "project"
        project.mkdir()
        (tmp_path / "secret.py").write_text("import internal_billing\n")

        with pytest.raises(HTTPException) as exc:
            await analyze_project(current_user=None, path=str(project), entry_point="../secret.py")
        assert exc.value.status_code == 400

    @pytest.mark.unit
    def test_tc_pth_029_frontend_builds_ignore_the_entry_point(self):
        """TC-PTH-029: create_task — a frontend-only build never reads the entry point,
        so a blank or stale value there does not refuse it; a full-stack build compiles
        it, so it is checked."""
        _check(project_path=SAFE_ROOT, project_type="frontend_only", entry_point="")
        _check(source_type=SourceType.GIT, git_url="https://gitlab/x.git", git_ref="main",
               project_type="frontend_only", entry_point="../old.py")
        with pytest.raises(HTTPException):
            _check(project_path=SAFE_ROOT, project_type="fullstack", entry_point="../old.py")

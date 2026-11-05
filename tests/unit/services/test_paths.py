"""
Unit tests for task file locations and safe directory joins.
Source: app/services/paths
"""

import os

import pytest

from app.services import paths


class TestIsSafeRelative:
    @pytest.mark.unit
    @pytest.mark.parametrize("name", ["dist", "build/out", "a/../b", "./dist", "", "  "])
    def test_tc_pth_001_names_below_the_root_pass(self, name):
        """TC-PTH-001: ordinary relative names (and empty) are accepted."""
        assert paths.is_safe_relative(name)

    @pytest.mark.unit
    @pytest.mark.parametrize("name", ["/etc", "..", "../x", "a/../../x", "C:\\\\x", "c:/x"])
    def test_tc_pth_002_absolute_and_climbing_names_fail(self, name):
        """TC-PTH-002: absolute paths win a join outright; '..' walks out."""
        assert not paths.is_safe_relative(name)


class TestSafeJoin:
    @pytest.mark.unit
    def test_tc_pth_010_absolute_name_does_not_replace_the_root(self, tmp_path):
        """TC-PTH-010: Path(root) / "/etc" is /etc — safe_join refuses it."""
        with pytest.raises(paths.UnsafePathError):
            paths.safe_join(tmp_path, "/etc")

    @pytest.mark.unit
    def test_tc_pth_011_symlink_out_of_the_root_is_refused(self, tmp_path):
        """TC-PTH-011: the check runs on the resolved path, so a symlink cannot escape."""
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        os.symlink(outside, root / "dist")

        with pytest.raises(paths.UnsafePathError):
            paths.safe_join(root, "dist")

    @pytest.mark.unit
    def test_tc_pth_012_inside_names_resolve_below_the_root(self, tmp_path):
        """TC-PTH-012: a normal name resolves to root/name."""
        assert paths.safe_join(tmp_path, "dist") == (tmp_path / "dist").resolve()


class TestTaskLocations:
    @pytest.mark.unit
    def test_tc_pth_020_git_task_root_is_its_workspace(self, tmp_path, mocker):
        """TC-PTH-020: a git task's files live in git_workspace_dir/<task_id>.

        Its config has project_path="" by design; using that gave the service's
        working directory.
        """
        mocker.patch("app.config.get_settings", return_value=mocker.Mock(git_workspace_dir=str(tmp_path)))
        root = paths.task_source_root("t-1", {"source_type": "git", "project_path": ""})
        assert root == tmp_path.resolve() / "t-1"

    @pytest.mark.unit
    def test_tc_pth_021_local_task_root_is_its_project_path(self):
        """TC-PTH-021: local mode keeps the caller's (validated) project path."""
        assert str(paths.task_source_root("t", {"source_type": "local", "project_path": "/srv/app"})) == "/srv/app"

    @pytest.mark.unit
    def test_tc_pth_022_exports_are_keyed_by_task(self, tmp_path, mocker):
        """TC-PTH-022: two builds of app:latest get two files, not one shared name."""
        mocker.patch("app.config.get_settings", return_value=mocker.Mock(docker_images_dir=str(tmp_path)))
        assert paths.docker_export_path("a") != paths.docker_export_path("b")
        assert paths.docker_export_path("a").name == "a.tar.gz"

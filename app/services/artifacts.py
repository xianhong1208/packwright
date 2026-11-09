"""Each local-mode build gets its own output, and keeps it.

A local build writes into the user's folder (``<project>/<output_dir>``), and
the download used to pack that folder when someone clicked Download. Two
things went wrong with that:

* The output directory was never emptied, so it collected every earlier
  build's files: a folder-mode build's archive also held the one-file binary
  and the ``libs/`` of the External build before it, and a Docker build copied
  them into the image.
* The archive was made from whatever the folder held at download time, so a
  build downloaded after another build of the same folder served the other
  build's binary.

So the output directory is emptied before a local build starts, and a
completed build's output is copied to its own directory under the workspace
root (``GIT_WORKSPACE_DIR/<task_id>/<output_dir>``, the layout Git builds
already have), which the download serves and the workspace sweep expires like
a Git build's workspace. Both run while the build holds its project lock, so
no other build of the folder can write in between.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.schemas.task import BuildConfig, ProjectType
from app.services.paths import UnsafePathError, git_workspace, safe_join

# Recorded on the task's result once its output is kept, so the download knows
# to serve the copy (and that a missing copy has expired, rather than falling
# back to the live folder, which by then may hold another build's output).
KEPT_OUTPUT_KEY = "output_kept"

# Never emptied: a directory holding one of these (at its top) is a project or
# part of the source tree, not a build output (output_dir "src" by mistake).
_SOURCE_MARKERS = (".venv", ".git", "pyproject.toml")


def output_dir_name(config: BuildConfig) -> str:
    """The output directory a build writes, as the workers resolve it."""
    name = (config.output_dir or "").strip()
    if not name and config.docker_enabled and config.project_type != ProjectType.FRONTEND_ONLY:
        return "dist"  # _build_docker_nuitka's default
    return name


def _inputs(config: BuildConfig) -> list[str]:
    names = [config.entry_point, ".venv", ".git"]
    if config.project_type in (ProjectType.FRONTEND_ONLY, ProjectType.FULLSTACK):
        names.append(config.frontend_dir)
    for raw in (config.data_dirs, config.extra_dirs):
        names.extend((raw or "").split(","))
    return [n.strip() for n in names if n and n.strip()]


def clear_output_dir(project_path: Path, config: BuildConfig) -> str | None:
    """Empty the build's output directory; return a line for the build log.

    Refuses (and says why) when the directory is the project itself or holds
    something the build reads, so a mistyped output_dir costs stale files in
    the download, never the user's source.
    """
    name = output_dir_name(config)
    if not name:
        return None
    root = Path(project_path).resolve()
    try:
        target = safe_join(root, name)
    except UnsafePathError:
        return None  # the request was validated; the worker refuses it again
    if target == root:
        return "Output directory is the project folder itself; not emptied before the build"
    if not target.is_dir():
        return None
    for marker in _SOURCE_MARKERS:
        if (target / marker).exists():
            return f"Output directory {name}/ holds {marker}; not emptied before the build"
    for name_in in _inputs(config):
        try:
            source = safe_join(root, name_in)
        except UnsafePathError:
            continue
        if source == target or source.is_relative_to(target):
            return (
                f"Output directory {name}/ holds {name_in}; not emptied before the "
                "build, so files from earlier builds may be packaged with this one"
            )
    removed = 0
    for child in target.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    if not removed:
        return None
    return f"Emptied {name}/ ({removed} entries from earlier builds)"


def _link_or_copy(src: str, dst: str) -> None:
    # A hard link costs no space, and stays this build's: the next build of the
    # folder starts by emptying the output directory, which unlinks these names
    # instead of writing into their files. Across filesystems, copy.
    try:
        os.link(src, dst, follow_symlinks=False)
    except OSError:
        shutil.copy2(src, dst, follow_symlinks=False)


def keep_output(task_id: str, project_path: Path, config: BuildConfig) -> Path | None:
    """Copy a completed build's output to its own directory; None when there is none.

    The copy keeps symlinks as symlinks, as the archive does, so a link in the
    output cannot pull a file from elsewhere on the host into it.
    """
    name = output_dir_name(config)
    root = Path(project_path).resolve()
    if not name:
        return None
    source = safe_join(root, name)
    if source == root or not source.is_dir():
        return None
    destination = git_workspace(task_id) / name
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True, copy_function=_link_or_copy)
    return destination

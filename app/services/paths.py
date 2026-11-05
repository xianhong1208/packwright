"""Where a task's files live, and joining caller-supplied names onto them safely.

Build configs carry several directory names that are joined onto a project root
and then deleted, overwritten or served: output_dir, data_dirs, extra_dirs,
frontend_dir. Those joins used to be bare ``root / name``. An absolute name wins
the join outright (``Path("/srv/app") / "/etc"`` is ``/etc``) and ``..`` walks out,
so one field could turn "replace the build output" into an rmtree anywhere the
service user can write. Everything that touches such a path goes through
safe_join(); routes call is_safe_relative() up front for a readable error.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


class UnsafePathError(ValueError):
    """A configured directory name would resolve outside its root."""


def is_safe_relative(name: str) -> bool:
    """True for a relative path that stays below wherever it is joined.

    Purely lexical, so it can run before the root exists (git mode clones only
    after the task is accepted). safe_join() repeats the check on the real,
    symlink-resolved path.
    """
    name = (name or "").strip()
    if not name:
        return True
    if os.path.isabs(name) or re.match(r"^[A-Za-z]:", name):
        return False
    normalised = os.path.normpath(name)
    return normalised != ".." and not normalised.startswith(".." + os.sep)


def safe_join(root: Path, name: str) -> Path:
    """``root / name`` resolved, refusing anything that ends up outside ``root``."""
    base = Path(root).resolve()
    if not is_safe_relative(name):
        raise UnsafePathError(f"'{name}' must be a path inside the project, not absolute or above it")
    candidate = (base / (name or "").strip()).resolve()
    if not candidate.is_relative_to(base):
        raise UnsafePathError(f"'{name}' resolves outside the project ({candidate})")
    return candidate


def git_workspace(task_id: str) -> Path:
    """The per-task clone directory used by git-mode builds."""
    from app.config import get_settings

    return Path(get_settings().git_workspace_dir).resolve() / task_id


def task_source_root(task_id: str, config: dict) -> Path:
    """The directory a finished task built in.

    Git mode never stores its workspace path in the task config (project_path is
    blank there, by design, so Rebuild re-derives it). Reading project_path for a
    git task gave Path(""), i.e. the service's working directory: downloads
    returned the wrong files, and output_dir="data" would have served the
    service's own database.
    """
    if config.get("source_type") == "git":
        return git_workspace(task_id)
    return Path(config.get("project_path") or "")


def docker_export_path(task_id: str) -> Path:
    """Where a task's exported image tarball is written and served from.

    Keyed by task, not by image name: two builds tagged app:latest (from one user
    or two) used to share data/docker_images/app_latest.tar.gz, so downloading the
    older task served the newer image, and concurrent exports wrote one file.
    """
    from app.config import get_settings

    return Path(get_settings().docker_images_dir) / f"{task_id}.tar.gz"


def legacy_docker_export_path(image_name: str) -> Path:
    """Name used before exports were keyed by task; read-only fallback for old rows."""
    from app.config import get_settings

    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", image_name)
    return Path(get_settings().docker_images_dir) / f"{safe_name}.tar.gz"

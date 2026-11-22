"""The commands a build would run, worked out without running anything.

Shown on a project's settings so a setting's effect is visible before a build
(auto-py-to-exe's "current command" does the same for PyInstaller). It is built by
the functions the workers use — build_nuitka_command, install_command,
build_command, image_reference — so it cannot drift from what a build does. What
only a build can know (the standard-library modules and installed packages it
finds, the Python matching the .venv) is said in the notes rather than guessed.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from app.schemas.task import BuildConfig, PackMode, ProjectType, SourceType
from app.services.docker_worker import default_image_repo, image_reference
from app.services.frontend_worker import build_command, install_command
from app.services.nuitka_worker import StdlibSelection, auto_jobs, build_nuitka_command

GIT_CHECKOUT = Path("<checkout>")


def preview_commands(config: BuildConfig) -> dict:
    """``{"steps": [{"stage", "command"}], "notes": [...]}`` for this config."""
    project = Path(config.project_path) if config.source_type == SourceType.LOCAL and config.project_path else GIT_CHECKOUT
    steps: list[dict] = []
    notes: list[str] = []

    if config.project_type in (ProjectType.FRONTEND_ONLY, ProjectType.FULLSTACK):
        fe = project if config.frontend_dir in ("", ".") else project / config.frontend_dir
        has_lock = (fe / "package-lock.json").exists() if project != GIT_CHECKOUT else True
        steps.append({"stage": "Install frontend dependencies", "command": f"cd {shlex.quote(str(fe))} && {shlex.join(install_command(config.frontend_build_tool, has_lock))}"})
        steps.append({"stage": "Build the frontend", "command": shlex.join(build_command(config.frontend_build_tool, config.frontend_build_command))})

    if config.project_type in (ProjectType.BACKEND_ONLY, ProjectType.FULLSTACK):
        entry = project / config.entry_point
        jobs = config.nuitka_jobs if config.nuitka_jobs > 0 else auto_jobs(os.cpu_count() or 1, 1)
        plan = build_nuitka_command(
            config,
            nuitka_python="python",
            project_path=project,
            output_dir=project / config.output_dir,
            entry_point=entry,
            output_name=config.output_name or entry.stem,
            jobs=jobs,
            debug=False,
            lazy_packages=[],
            # Empty: the modules to include are found by scanning the .venv at build time.
            stdlib=StdlibSelection(valid_libs=[], force_packages=set(), used=set()) if config.pack_mode == PackMode.EXTERNAL else None,
            installed_packages=[],
            version_file=Path("VERSION") if config.version else None,
        )
        steps.append({"stage": "Compile with Nuitka", "command": shlex.join(plan.cmd)})
        notes.append("The build runs this with the Python that matches the project's .venv.")
        if config.pack_mode == PackMode.EXTERNAL:
            notes.append(
                "In External mode the build also leaves out the packages installed in the .venv (they are "
                "copied to libs/) and adds the standard-library modules they need; both lists are found at build time."
            )
        if config.nuitka_jobs <= 0:
            notes.append(f"CPU jobs is on Auto: {jobs} here, fewer when other builds run at the same time.")

    if config.docker_enabled:
        image = image_reference(config.docker_image_name, default_image_repo(config), config.version)
        steps.append({"stage": "Build the Docker image", "command": f"docker build -t {shlex.quote(image)} ."})

    return {"steps": steps, "notes": notes}

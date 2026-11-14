"""Docker build worker for packaging projects as Docker images."""

import asyncio
import os
import re
import shutil
import time
from pathlib import Path
from textwrap import dedent

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.task import BuildConfig, ProjectType, PackMode, SourceType
from app.services.source_guard import SourceGuard
from app.services.task_manager import task_manager
from app.services.build_env import build_environment
from app.services.process_runner import run_step
from app.services.system_libs import SystemPackages, system_packages
from app.services.image_smoke import smoke_test_image


async def run_docker_build(
    task_id: str,
    config: BuildConfig,
    db: AsyncSession,
    precompiled: bool = False,
) -> bool:
    """Build and export the image; project files changed for it are put back on every path."""
    guard = SourceGuard(task_id)
    try:
        return await _run_docker_build(task_id, config, db, precompiled, guard)
    finally:
        await _restore_and_log(task_id, guard)


async def _restore_and_log(task_id: str, guard: SourceGuard) -> None:
    for line in await asyncio.to_thread(guard.restore):
        await task_manager.append_log(task_id, line)


async def _run_docker_build(
    task_id: str,
    config: BuildConfig,
    db: AsyncSession,
    precompiled: bool,
    guard: SourceGuard,
) -> bool:
    """Build a Docker image for the project.

    Args:
        task_id: Task ID for logging
        config: Build configuration
        db: Database session

    Returns:
        True if build succeeded, False otherwise
    """
    project_path = Path(config.project_path)

    # Check if docker is available
    if not shutil.which("docker"):
        await task_manager.append_log(task_id, "Error: Docker not found in PATH")
        return False

    await task_manager.append_log(task_id, "Docker found, preparing build...")

    # Determine image name
    image_name = image_reference(config.docker_image_name, default_image_repo(config), config.version)

    await task_manager.append_log(task_id, f"Image name: {image_name}")

    # Generate .dockerignore
    # Every file written into the project below goes through the guard, which
    # restores the original (or removes the file) when the build is done.
    dockerignore_path = project_path / ".dockerignore"

    if precompiled:
        # Precompiled mode: always use our .dockerignore so the output directory
        # is not excluded.
        guard.write(dockerignore_path, _generate_dockerignore(precompiled=True))
        await task_manager.append_log(task_id, "Generated .dockerignore (precompiled)")
    elif not dockerignore_path.exists():
        guard.write(dockerignore_path, _generate_dockerignore())
        await task_manager.append_log(task_id, "Generated .dockerignore")

    # Write .env file for frontend if configured (backup original, restore after build)
    # Skip for precompiled mode — frontend was already built on host
    if not precompiled and config.frontend_env_content.strip() and config.project_type in (
        ProjectType.FRONTEND_ONLY, ProjectType.FULLSTACK
    ):
        env_filename = config.frontend_env_filename or ".env"
        fe_dir = project_path / config.frontend_dir
        if fe_dir.exists():
            env_file_path = fe_dir / env_filename
            guard.write(env_file_path, config.frontend_env_content)
            await task_manager.append_log(task_id, f"Wrote {env_filename} in {fe_dir} for Docker build")

            # Add negation to .dockerignore so Docker COPY can pick it up
            if dockerignore_path.exists():
                relative_env = f"{config.frontend_dir}/{env_filename}"
                ignore_content = dockerignore_path.read_text() + f"\n# Allow env file for frontend build\n!{relative_env}\n"
                guard.write(dockerignore_path, ignore_content)

    # Generate Dockerfile based on project type
    dockerfile_path = project_path / "Dockerfile.generated"

    system = None
    if precompiled:
        system = await asyncio.to_thread(system_packages, _scan_roots(config))
        await task_manager.append_log(task_id, f"System packages: {' '.join(system.packages)}")
        for pkg, (soname, needed_by) in system.reasons.items():
            await task_manager.append_log(task_id, f"  + {pkg}: {needed_by} needs {soname}")

    if precompiled and config.docker_volumes is None:
        # Not set yet: the folders the program created when the smoke test ran
        # it, saved into this build's settings (and the project's, while unset
        # there) so the next build shows them in the Volumes field.
        detected = await _smoke_created_dirs(task_id)
        if detected:
            config.docker_volumes = ", ".join(detected)
            await task_manager.append_log(
                task_id, f"Volumes (from the folders the smoke run created): {config.docker_volumes}"
            )
            await task_manager.record_config_value(task_id, "docker_volumes", config.docker_volumes, db)

    try:
        dockerfile_content = _generate_dockerfile(config, precompiled=precompiled, system=system)
        guard.write(dockerfile_path, dockerfile_content)
        await task_manager.append_log(task_id, "Generated Dockerfile")
        await task_manager.append_log(task_id, "")
        await task_manager.append_log(task_id, "=== Dockerfile ===")
        for line in dockerfile_content.split("\n")[:40]:
            await task_manager.append_log(task_id, line)
        if dockerfile_content.count("\n") > 40:
            await task_manager.append_log(task_id, "... (truncated)")
        await task_manager.append_log(task_id, "==================")

    except Exception as e:
        await task_manager.append_log(task_id, f"Error generating Dockerfile: {e}")
        return False

    # Build Docker image
    await task_manager.append_log(task_id, "")
    await task_manager.append_log(task_id, "=== Building Docker image ===")
    await task_manager.update_task(task_id, "status_msg", "Building Docker image...")
    await task_manager.update_task(task_id, "progress", 20)

    build_cmd = [
        "docker", "build",
        "-t", image_name,
        "-f", str(dockerfile_path),
        str(project_path),
    ]

    await task_manager.append_log(task_id, f"Command: {' '.join(build_cmd)}")

    success = await _run_docker_command(task_id, build_cmd, project_path)

    if success and config.verify_after_build:
        success = await _verify_image(task_id, config, image_name, build_cmd, project_path, precompiled, system,
                                      guard, dockerfile_path, db)

    # Put the project's files back now rather than after the (long) export.
    await _restore_and_log(task_id, guard)

    if success:
        await task_manager.append_log(task_id, "")
        await task_manager.append_log(task_id, "=" * 50)
        await task_manager.append_log(task_id, f"Docker image built successfully: {image_name}")
        size = await _image_size(image_name)
        if size is not None:
            await task_manager.append_log(task_id, f"Image size: {size / 1_000_000:.1f} MB")
        await task_manager.merge_result(
            task_id,
            {"image": {
                "name": image_name,
                "size_bytes": size,
                "run_command": run_hint(config, image_name, precompiled=precompiled),
                "volumes": [mount_point(v) for v in parse_volumes(config.docker_volumes)] if precompiled else [],
                "user": "root" if config.docker_run_as_root or not precompiled else f"{APP_USER} (uid {APP_UID})",
            }},
            db,
        )
        run_command = run_hint(config, image_name, precompiled=precompiled)
        await task_manager.append_log(task_id, "")
        await task_manager.append_log(task_id, "To run the container:")
        await task_manager.append_log(task_id, f"  {run_command}")
        await task_manager.append_log(task_id, "=" * 50)

        # Export Docker image as .tar.gz for download
        await task_manager.append_log(task_id, "")
        await task_manager.append_log(task_id, "Exporting Docker image...")
        await task_manager.update_task(task_id, "status_msg", "Exporting Docker image...")

        from app.config import get_settings

        docker_export_dir = Path(get_settings().docker_images_dir)
        docker_export_dir.mkdir(parents=True, exist_ok=True)

        from app.services.paths import docker_export_path

        tar_path = docker_export_path(task_id)

        compress_argv, compressor_name = _compressor_argv(
            get_settings().docker_export_compress_threads
        )
        await task_manager.append_log(task_id, f"Compressor: {compressor_name}")

        try:
            started = time.monotonic()
            # Use os.pipe() for real fd piping between docker save and the
            # compressor, so a multi-GB image never lands in this process.
            read_fd, write_fd = os.pipe()

            docker_proc = await asyncio.create_subprocess_exec(
                "docker", "save", image_name,
                stdout=write_fd,
                stderr=asyncio.subprocess.PIPE,
            )
            os.close(write_fd)  # Close write end in parent so the compressor sees EOF

            tar_file = open(tar_path, "wb")
            gzip_proc = await asyncio.create_subprocess_exec(
                *compress_argv,
                stdin=read_fd,
                stdout=tar_file.fileno(),
                stderr=asyncio.subprocess.PIPE,
            )
            os.close(read_fd)  # Close read end in parent
            tar_file.close()

            _, gzip_err = await gzip_proc.communicate()
            await docker_proc.wait()

            if docker_proc.returncode == 0 and gzip_proc.returncode == 0 and tar_path.exists():
                elapsed = time.monotonic() - started
                size_mb = tar_path.stat().st_size / (1024 * 1024)
                rate = size_mb / elapsed if elapsed > 0 else 0
                await task_manager.append_log(
                    task_id,
                    f"Exported: {tar_path.name} ({size_mb:.1f} MB in {elapsed:.1f}s, {rate:.1f} MB/s)",
                )
            else:
                err_msg = gzip_err.decode().strip() if gzip_err else "Unknown error"
                await task_manager.append_log(task_id, f"Warning: Failed to export Docker image: {err_msg}")
                tar_path.unlink(missing_ok=True)
        except Exception as e:
            await task_manager.append_log(task_id, f"Warning: Failed to export Docker image: {e}")
            tar_path.unlink(missing_ok=True)

    return success


async def _verify_image(
    task_id: str,
    config: BuildConfig,
    image_name: str,
    build_cmd: list[str],
    project_path: Path,
    precompiled: bool,
    system: SystemPackages | None,
    guard: SourceGuard,
    dockerfile_path: Path,
    db: AsyncSession,
) -> bool:
    """Smoke-test the image (see image_smoke); False when it failed.

    With Volumes not set, the folders the program created in the container
    become volumes: the Dockerfile gets them, the image is built again (every
    layer but the last few comes from the cache) and that image is tested, so
    what ships is what passed, with its volumes owned by the program's user.
    """
    from app.services.nuitka_worker import docker_port_check
    from app.services.process_runner import is_cancelled

    await task_manager.set_stage(task_id, "verify")
    await task_manager.update_task(task_id, "status_msg", "Smoke-testing the image...")
    await task_manager.append_log(task_id, "")
    await task_manager.append_log(task_id, f"=== Smoke test: starting the image {image_name} ===")

    async def cancelled() -> bool:
        return await is_cancelled(task_id)

    verify = await smoke_test_image(image_name, is_cancelled=cancelled)
    await task_manager.append_log(task_id, f"Ran it as container {verify.get('container')} (removed)")
    detected = verify.get("created_dirs") or []
    if detected:
        await task_manager.append_log(task_id, "The program created " + ", ".join(f"/app/{d}/" for d in detected))

    if precompiled and config.docker_volumes is None and detected and verify["status"] != "fail":
        config.docker_volumes = ", ".join(detected)
        await task_manager.record_config_value(task_id, "docker_volumes", config.docker_volumes, db)
        await task_manager.append_log(
            task_id, f"Volumes (not set, so taken from that run): {config.docker_volumes} — building the image again"
        )
        guard.write(dockerfile_path, _generate_dockerfile(config, precompiled=precompiled, system=system))
        await task_manager.set_stage(task_id, "docker")
        if not await _run_docker_command(task_id, build_cmd, project_path):
            return False
        await task_manager.set_stage(task_id, "verify")
        await task_manager.append_log(task_id, "=== Smoke test: the image with its volumes ===")
        verify = await smoke_test_image(image_name, is_cancelled=cancelled)
        await task_manager.append_log(task_id, f"Ran it as container {verify.get('container')} (removed)")
        verify["created_dirs"] = detected

    marker = {"pass": "✓", "warn": "⚠", "fail": "✗"}.get(verify["status"], "•")
    await task_manager.append_log(task_id, f"Verify (image): {marker} {verify['detail']}")
    if verify.get("listeners"):
        await task_manager.append_log(
            task_id, "Listening in the container: "
            + ", ".join(f"{x['address']}:{x['port']}" for x in verify["listeners"])
        )
    patch: dict = {"verify": verify}
    checked = docker_port_check(config, verify, container=True)
    if checked:
        patch["port_check"] = checked
        if checked["message"]:
            await task_manager.append_log(task_id, f"⚠ Port: {checked['message']}")
    await task_manager.merge_result(task_id, patch, db)
    if verify["status"] == "fail":
        await task_manager.append_log(task_id, "Smoke test failed — marking build as failed")
        return False
    await task_manager.set_stage(task_id, "docker")  # on to the export
    return True


def _compressor_argv(threads: int) -> tuple[list[str], str]:
    """Pick the gzip-compatible compressor to pipe `docker save` into.

    pigz produces a standard gzip stream from multiple threads, so the output
    stays a normal .tar.gz that `docker load` and `tar -xzf` read unchanged —
    only the time to produce it differs. A multi-GB image is minutes of a
    single core with plain gzip on a machine that has 128.

    Falls back to gzip when pigz is absent rather than failing the export: the
    image is already built by this point, and refusing to package it over a
    missing optional tool would throw the whole build away.
    """
    pigz = shutil.which("pigz")
    if pigz:
        # -p caps the thread count. Deliberately NOT "all cores": this host
        # runs up to MAX_CONCURRENT_BUILDS Nuitka compiles at once, and a
        # 128-thread compressor would starve them for the tail of a build that
        # is otherwise finished. Most of the speedup is in the first few
        # threads anyway — beyond that disk throughput becomes the limit.
        return ([pigz, "-p", str(max(1, threads))], f"pigz -p {threads}")
    return (["gzip"], "gzip (single-threaded — install pigz for a much faster export)")


def _generate_dockerignore(precompiled: bool = False) -> str:
    """Generate a .dockerignore to reduce build context size."""
    lines = [
        ".venv",
        "__pycache__",
        "*.pyc",
        ".git",
        ".gitignore",
        ".env",
        ".env.*",
        "node_modules",
        "*.egg-info",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "Dockerfile*",
        ".dockerignore",
    ]
    # Don't exclude dist/build when precompiled — output may be there
    if not precompiled:
        lines.extend(["dist", "build"])
    return "\n".join(lines) + "\n"


_ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")

# Commands considered safe for Docker RUN instructions.
# Only well-known package managers, file operations, and system commands are allowed.
ALLOWED_COMMAND_PREFIXES = (
    "apt-get ", "apt ", "apk ", "yum ", "dnf ", "pip ", "pip3 ",
    "npm ", "yarn ", "pnpm ", "bun ",
    "mkdir ", "chmod ", "chown ", "cp ", "mv ", "ln ",
    "echo ", "cat ", "sed ", "touch ",
    "useradd ", "groupadd ", "adduser ", "addgroup ",
)


def _render_docker_env_vars(env_vars: str) -> str:
    """Render environment variables as Dockerfile ENV instructions.

    Each non-empty line (KEY=VALUE) becomes a separate ENV instruction.
    Lines starting with # are treated as comments and skipped.
    Lines that don't match KEY=VALUE format are rejected.
    """
    lines = [line.strip() for line in env_vars.splitlines()
             if line.strip() and not line.strip().startswith("#")]
    if not lines:
        return ""

    valid_lines = []
    for line in lines:
        if not _ENV_VAR_PATTERN.match(line):
            raise ValueError(f"Invalid env var format (must be KEY=VALUE): {line!r}")
        valid_lines.append(line)

    result = "\n# User environment variables\n"
    result += "\n".join(f"ENV {line}" for line in valid_lines)
    return result + "\n"


def _render_custom_commands(commands: str) -> str:
    """Render custom shell commands as Dockerfile RUN instructions.

    Each non-empty line becomes a separate RUN instruction.
    Only commands from the allowlist are permitted for safety.
    """
    lines = [line.strip() for line in commands.splitlines() if line.strip()]
    if not lines:
        return ""

    for line in lines:
        if not any(line.startswith(prefix) for prefix in ALLOWED_COMMAND_PREFIXES):
            raise ValueError(
                f"Command not in allowlist: {line!r}. "
                f"Allowed prefixes: {', '.join(p.strip() for p in ALLOWED_COMMAND_PREFIXES)}"
            )

    result = "\n# Custom commands\n"
    result += "\n".join(f"RUN {line}" for line in lines)
    return result + "\n"


# nginx directive values are pasted by the user and land inside a generated
# config file. A quote or newline turns one directive into several, and a
# `#` comments out the rest of the line — all of which surface as an
# incomprehensible nginx syntax error minutes into a Docker build rather than
# as a form validation message.
_NGINX_VALUE_FORBIDDEN = re.compile(r"""["'\n\r;{}#\\]""")


def _validate_nginx_value(value: str, field: str) -> str:
    """Reject characters that would break out of a single nginx directive.

    Raises ValueError with the offending field named, so the failure is
    reported before the build starts instead of as an nginx parse error.
    """
    value = (value or "").strip()
    if _NGINX_VALUE_FORBIDDEN.search(value):
        raise ValueError(
            f"{field} contains a character that is not allowed (quote, semicolon, brace, # or "
            f"newline): {value!r}. The value is written straight into the nginx config, so use a "
            "plain value such as '120s' or "
            "'http://backend:8000'。"
        )
    return value


_DEFAULT_BASE_IMAGE = "python:3.13-slim"


def _sanitize_base_image(base_image: str | None) -> str:
    """Guard against a base image whose tag was built from the literal python
    version "auto" (the auto-detect sentinel). `python:auto-slim` is not a real
    Docker tag, so `docker build` would fail at pull time. A Nuitka standalone
    binary bundles its own Python runtime, so the base image only supplies system
    libs — falling back to a valid default tag is safe. Defends old tasks and
    direct API callers even though the frontend no longer emits this.
    """
    image = (base_image or "").strip()
    if not image or re.search(r"python:auto\b", image, re.IGNORECASE):
        return _DEFAULT_BASE_IMAGE
    return image


def docker_tag(version: str) -> str:
    """A version as a Docker tag: [A-Za-z0-9_.-], at most 128, not starting with . or -."""
    tag = re.sub(r"[^A-Za-z0-9_.-]", "_", version).lstrip(".-")[:128]
    return tag or "latest"


def default_image_repo(config: BuildConfig) -> str:
    """What an image is named after when no name is set: the repository for a Git
    build, the folder for a local one.

    A Git build is cloned into a workspace named after the task, so the folder's
    name is a task id: packaging MCP Gate from Git produced the image
    "be1d3c22-b30d-479d-8cc7-101d31c6ec90:1.3.1", a new repository on every build.
    """
    if config.source_type == SourceType.GIT and config.git_url.strip():
        last = re.split(r"[/:]", config.git_url.strip().rstrip("/"))[-1]
        last = re.sub(r"\.git$", "", last, flags=re.IGNORECASE)
        if last:
            return last
    return Path(config.project_path).name


def image_reference(configured: str, folder_name: str, version: str) -> str:
    """The image a build is tagged as.

    Without a configured name: the folder's name, lowercased (Docker refuses
    upper-case repository names, so "MCP_Center:latest" never built), tagged with
    the version, or latest. A configured name without a tag gets the version as
    its tag; one with a tag or digest is used as given.
    """
    tag = docker_tag(version) if version else "latest"
    if not configured:
        repo = re.sub(r"[^a-z0-9._-]+", "-", folder_name.lower()).strip("._-") or "app"
        return f"{repo}:{tag}"
    last = configured.rsplit("/", 1)[-1]
    if ":" in last or "@" in configured or not version:
        return configured
    return f"{configured}:{tag}"


def _version_block(version: str) -> str:
    """Appended to the Dockerfile, so it lands in the final stage: the standard
    version label, and the version where the program can read it."""
    if not version:
        return ""
    return (
        "\n# The version this image was built as (Packwright)\n"
        f'LABEL org.opencontainers.image.version="{version}"\n'
        f"ENV PACKWRIGHT_BUILD_VERSION={version}\n"
    )


# The program's user in a backend image. A fixed number rather than whatever
# useradd picks, so files on a bind mount can be given to it with one chown.
APP_USER = "app"
APP_UID = 10001

_VOLUME_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")


def parse_volumes(value: str | None) -> list[str]:
    """The folders in a Volumes setting, in order, without duplicates.

    Comma- or newline-separated; each relative to /app (the image's WORKDIR) or
    absolute. Raises ValueError naming an entry that could not be a plain path:
    it lands in a Dockerfile RUN and VOLUME line.
    """
    out: list[str] = []
    for raw in re.split(r"[,\n]", value or ""):
        entry = raw.strip()
        if not entry:
            continue
        norm = entry.rstrip("/") or "/"
        parts = [p for p in norm.split("/") if p]
        if not _VOLUME_PATH.match(entry) or ".." in parts or not parts:
            raise ValueError(
                f"Volume {entry!r} is not a plain folder path: use letters, digits, '.', '_', '-' and '/', "
                "relative to /app (e.g. data) or absolute (e.g. /var/lib/myapp), without '..'"
            )
        if norm not in out:
            out.append(norm)
    return out


def mount_point(volume: str) -> str:
    """Where a Volumes entry is inside the image."""
    return volume if volume.startswith("/") else f"/app/{volume}"


def _volume_name(repo: str, volume: str) -> str:
    """A named volume for the run hint: <repo>-<folder>, e.g. mcp_gate-data."""
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", volume.strip("/")).strip("-.") or "data"
    return f"{repo}-{slug}"


def run_hint(config: BuildConfig, image_name: str, precompiled: bool) -> str:
    """The `docker run` command the build suggests.

    It used to be `docker run --rm --network host <image>`: --rm threw away
    everything the program wrote (MCP Gate: a new database, new signing keys and
    a new encryption key on every start), and host networking hid a wrong EXPOSE.
    Now a detached container with its port published and a named volume per
    state folder, which survive restarts and re-creating the container.
    """
    last = image_name.rsplit("/", 1)[-1]
    repo = re.sub(r"[^A-Za-z0-9_.-]+", "-", re.split(r"[:@]", last)[0]).strip("-.") or "app"
    port = config.docker_expose_port
    parts = ["docker run -d", f"--name {repo}", f"-p {port}:{port}"]
    if precompiled:
        for volume in parse_volumes(config.docker_volumes):
            parts.append(f"-v {_volume_name(repo, volume)}:{mount_point(volume)}")
    parts.append(image_name)
    return " ".join(parts)


async def _smoke_created_dirs(task_id: str) -> list[str]:
    """The folders the program created in its smoke run (see nuitka_worker._smoke_test)."""
    task = await task_manager.get_task(task_id)
    verify = task.result.verify if task and task.result else None
    return list(verify.created_dirs) if verify else []


def _scan_roots(config: BuildConfig) -> list[Path]:
    """Where the shared objects that ship in the image are: the output folder
    (libs/ or the standalone .dist folder), and for Full mode the project's
    packages too, since a onefile binary keeps its copies inside itself."""
    project = Path(config.project_path)
    roots = [project / (config.output_dir or "dist")]
    if config.pack_mode == PackMode.FULL:
        roots.extend(sorted((project / ".venv").glob("lib/python*/site-packages")))
    return roots


async def _image_size(image_name: str) -> int | None:
    """The image's size in bytes as `docker image ls` reports it, or None."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "image", "inspect", "-f", "{{.Size}}", image_name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except OSError:
        return None
    text = out.decode().strip()
    return int(text) if proc.returncode == 0 and text.isdigit() else None


def _generate_dockerfile(
    config: BuildConfig, precompiled: bool = False, system: SystemPackages | None = None
) -> str:
    """Generate Dockerfile based on project type and configuration.

    Backend/fullstack projects always use precompiled Nuitka binaries
    (compiled on host before Docker build).
    """
    project_type = config.project_type
    base_image = _sanitize_base_image(config.docker_base_image)
    port = config.docker_expose_port

    if project_type == ProjectType.FRONTEND_ONLY and not precompiled:
        return _generate_frontend_dockerfile(config, port) + _version_block(config.version)

    # Backend and fullstack always use precompiled binary
    if system is None:
        system = system_packages(_scan_roots(config))
    return _generate_precompiled_dockerfile(config, base_image, port, system) + _version_block(config.version)


def _generate_frontend_dockerfile(config: BuildConfig, port: int) -> str:
    """Generate Dockerfile for frontend-only projects.

    Picks a builder stage that actually HAS the requested package manager:
      - npm        → node:20-alpine (npm bundled)
      - yarn       → node:20-alpine (yarn classic bundled)
      - pnpm       → node:20-alpine + `corepack enable pnpm`
      - bun        → oven/bun:1-alpine (bun is not a node tool)
    Previously every tool was run on node:20-alpine, so pnpm/bun silently
    failed at build time with "not found".
    """
    frontend_dir = config.frontend_dir
    output_dir = config.frontend_output_dir
    tool = config.frontend_build_tool.value
    build_command = config.frontend_build_command

    # ── Builder stage selection per package manager ──
    if tool == "bun":
        builder_base = "oven/bun:1-alpine"
        enable_pm = ""
        lock_copies = (
            f"COPY {frontend_dir}/package*.json ./\n"
            f"        COPY {frontend_dir}/bun.lock* ./"
        )
    else:
        builder_base = "node:20-alpine"
        # corepack ships with node; enabling pnpm activates its shim. yarn
        # classic is already bundled, npm needs nothing — so only pnpm here.
        enable_pm = "RUN corepack enable pnpm" if tool == "pnpm" else ""
        lock_copies = (
            f"COPY {frontend_dir}/package*.json ./\n"
            f"        COPY {frontend_dir}/yarn.lock* ./\n"
            f"        COPY {frontend_dir}/pnpm-lock.yaml* ./"
        )

    # Reproducible install: use the lockfile (frozen) when one is present, fall
    # back to a plain install when the repo ships none. This matches the host
    # build path and keeps Docker images deterministic, without breaking
    # lock-less repos (a hard --frozen-lockfile would fail those).
    install_run = {
        "npm": "if [ -f package-lock.json ]; then npm ci --legacy-peer-deps; else npm install; fi",
        "yarn": "if [ -f yarn.lock ]; then yarn install --frozen-lockfile; else yarn install; fi",
        "pnpm": "if [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile; else pnpm install; fi",
        "bun": "if [ -f bun.lockb ] || [ -f bun.lock ]; then bun install --frozen-lockfile; else bun install; fi",
    }.get(tool, f"{tool} install")

    # ── nginx server config (user-configurable) ──
    body_size = _validate_nginx_value(
        config.nginx_client_max_body_size or "0", "nginx_client_max_body_size"
    )
    # 300s, not nginx's 60s. Almost nobody who configures an API proxy changes
    # the default, and the few who do are the ones who already hit the wall. A
    # speech-to-text or LLM call returns nothing at all until it finishes, so
    # the idle timer expires mid-request and the user gets a 504 that looks
    # like their backend crashed.
    read_timeout = _validate_nginx_value(
        config.nginx_proxy_read_timeout or "300s", "nginx_proxy_read_timeout"
    )

    gzip_block = ""
    if config.nginx_gzip:
        gzip_block = (
            "  gzip on;\n"
            "  gzip_comp_level 5;\n"
            "  gzip_min_length 1024;\n"
            "  gzip_proxied any;\n"
            "  gzip_vary on;\n"
            "  gzip_types text/plain text/css application/javascript\n"
            "             application/json image/svg+xml application/xml;\n"
        )

    # Buffering is nginx's default and is wrong for streaming APIs. With
    # proxy_buffering on, nginx collects the whole upstream response before
    # sending any of it, so an LLM streaming tokens over SSE arrives as one
    # block at the end — the feature silently stops working and looks like a
    # frontend bug. proxy_request_buffering on likewise makes nginx receive an
    # entire upload (a long audio file for STT) before the backend sees byte
    # one, adding the upload time to the user's wait.
    streaming_block = ""
    if getattr(config, "nginx_streaming", True):
        streaming_block = (
            "    proxy_buffering off;\n"
            "    proxy_request_buffering off;\n"
            "    proxy_cache off;\n"
            # Some upstreams emit this to ask a proxy not to buffer; honouring
            # it costs nothing and helps apps that already set it.
            "    proxy_set_header X-Accel-Buffering no;\n"
        )

    proxy_block = ""
    map_block = ""
    if config.docker_api_proxy:
        target = _validate_nginx_value(
            config.docker_api_proxy.rstrip("/"), "docker_api_proxy"
        )
        # Sending `Connection: upgrade` on every request — which is what a
        # hardcoded value does — breaks keepalive to the upstream and confuses
        # backends that check the header. The map makes it conditional: upgrade
        # only when the client actually asked for one, close otherwise.
        map_block = (
            "map $http_upgrade $connection_upgrade {\n"
            "  default upgrade;\n"
            # nginx accepts "" for the empty-string key. Written with DOUBLE
            # quotes on purpose: each config line is emitted as a
            # single-quoted shell argument, and a '' inside one is swallowed
            # by the shell's string concatenation, silently producing a map
            # entry with no key.
            '  ""      close;\n'
            "}\n\n"
        )
        proxy_block = (
            # `location /api` is a PREFIX match, so it also captures /api-docs,
            # /apiv2 and anything else merely starting with those characters.
            # `^~ /api/` matches the path segment and beats regex locations.
            f"  location ^~ /api/ {{\n"
            f"    proxy_pass {target};\n"
            f"    proxy_set_header Host $host;\n"
            f"    proxy_set_header X-Real-IP $remote_addr;\n"
            f"    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
            f"    proxy_set_header X-Forwarded-Proto $scheme;\n"
            f"    proxy_http_version 1.1;\n"
            f"    proxy_set_header Upgrade $http_upgrade;\n"
            f"    proxy_set_header Connection $connection_upgrade;\n"
            # Without this, a dead backend still takes nginx's default 75s to
            # give up and the page just appears frozen.
            f"    proxy_connect_timeout 10s;\n"
            # read_timeout is an IDLE timeout, not a total-duration cap: it
            # fires when the upstream has sent nothing for this long. That is
            # why it kills single-shot calls (STT, a non-streaming LLM reply)
            # while never cutting a slow response that keeps trickling. It is
            # also the WebSocket idle timeout, so an app without heartbeats
            # needs a value longer than its quiet periods.
            f"    proxy_read_timeout {read_timeout};\n"
            f"    proxy_send_timeout {read_timeout};\n"
            f"{streaming_block}"
            f"  }}\n"
        )

    nginx_conf = (
        f"{map_block}"
        f"server {{\n"
        f"  listen {port};\n"
        f"  client_max_body_size {body_size};\n"
        f"{gzip_block}"
        f"  root /usr/share/nginx/html;\n"
        f"  index index.html;\n"
        f"\n"
        f"{proxy_block}"
        # Bundlers emit content-hashed filenames (index-a1b2c3.js), so the file
        # at a given URL can never change — cache it hard. Without this every
        # visit re-validates every asset, which is most of the load time on a
        # site whose whole job is serving static files.
        f"  location /assets/ {{\n"
        f"    expires 1y;\n"
        f'    add_header Cache-Control "public, immutable";\n'
        f"    access_log off;\n"
        f"  }}\n"
        f"\n"
        # index.html must NOT be cached, or a deploy ships new hashed assets
        # that nobody's browser ever asks for.
        f"  location = /index.html {{\n"
        f'    add_header Cache-Control "no-cache";\n'
        f"  }}\n"
        f"\n"
        f"  location / {{\n"
        f"    try_files $uri $uri/ /index.html;\n"
        f"  }}\n"
        f"}}\n"
    )

    # One shell-quoted argument per config line. Continuations keep the
    # generated Dockerfile readable — the user is shown its first 20 lines in
    # the build log, and an unreadable wall of text there helps nobody.
    _conf_args = " \\\n            ".join(
        f"'{line}'" for line in nginx_conf.rstrip("\n").split("\n")
    )
    nginx_write_cmd = (
        f"printf '%s\\n' \\\n            {_conf_args} \\\n"
        f"            > /etc/nginx/conf.d/default.conf"
    )

    return dedent(f"""\
        # === Frontend Only Dockerfile ===

        # Build stage
        FROM {builder_base} AS builder

        WORKDIR /app
        {enable_pm}

        # Copy manifest + lockfiles (whichever exist)
        {lock_copies}

        # Install dependencies (frozen when a lockfile exists)
        RUN {install_run}

        # Copy source and build
        COPY {frontend_dir}/ ./
        RUN {tool} run {build_command}

        # Production stage - serve with nginx
        FROM nginx:alpine

        # Copy built files
        COPY --from=builder /app/{output_dir} /usr/share/nginx/html

        # Limit worker processes (default 'auto' spawns one per CPU core)
        RUN sed -i '/worker_processes/c\\worker_processes 2;' /etc/nginx/nginx.conf \\
            && rm -f /docker-entrypoint.d/30-tune-worker-processes.sh

        # Custom nginx config for SPA routing.
        # printf with one quoted argument per line, rather than a heredoc
        # (needs a BuildKit-era Dockerfile frontend) or a single `echo`
        # (cannot express multiple lines portably). Single quotes keep the
        # shell from expanding $uri / $host, which must reach nginx literally;
        # _validate_nginx_value() has already rejected any quote that could
        # close one of these strings early.
        RUN {nginx_write_cmd}

        # Validate at build time. Otherwise a bad directive ships an image that
        # crash-loops on startup, with the reason buried in container logs the
        # user may never think to look at.
        RUN nginx -t

        EXPOSE {port}

        CMD ["nginx", "-g", "daemon off;"]
    """)


def _outermost_dirs(dirs: list[str]) -> list[str]:
    """The listed directories without those inside another listed one, in order.

    A full-stack build adds its frontend output to the data dirs; when that
    output sits in a data dir already listed (MCP Gate: static/web inside
    static), COPYing both put the frontend into the image twice.
    """
    norm = [os.path.normpath(d) for d in dirs]
    kept: list[str] = []
    for d in norm:
        if d in kept or any(d.startswith(other + os.sep) for other in norm if other != d):
            continue
        kept.append(d)
    return kept


def _generate_precompiled_dockerfile(
    config: BuildConfig, base_image: str, port: int, system: SystemPackages
) -> str:
    """Generate Dockerfile for precompiled Nuitka binary built on host.

    Only copies the compiled output into a slim runtime image.
    No compilation happens inside Docker.
    """
    entry_stem = Path(config.entry_point).stem
    binary_name = config.output_name if config.output_name else entry_stem
    output_dir = config.output_dir

    # Runtime extras
    extra_blocks = ""
    if config.docker_install_node:
        extra_blocks += (
            "\n# Install Node.js\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \\\n"
            "    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \\\n"
            "    && apt-get install -y --no-install-recommends nodejs \\\n"
            "    && apt-get purge -y curl \\\n"
            "    && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*\n"
        )
    extra_blocks += _render_docker_env_vars(config.docker_env_vars)
    extra_blocks += _render_custom_commands(config.docker_custom_commands)

    # The program runs as a non-root user unless asked otherwise. Its files are
    # given to it on the COPY itself (--chown), never by a RUN chown afterwards,
    # which would store every file a second time (see the --chmod note below).
    as_root = config.docker_run_as_root
    own = "" if as_root else f"--chown={APP_USER}:{APP_USER} "
    if not as_root:
        extra_blocks += (
            "\n# The program's own user\n"
            f"RUN useradd --system --uid {APP_UID} --user-group --home-dir /app --no-create-home {APP_USER}\n"
        )

    # Copy compiled binary
    if config.onefile:
        # --chmod on the COPY, not a RUN chmod afterwards: changing a file's mode
        # in a later layer stores the whole file again, which doubled the
        # binary's share of the image (MCP Gate: 2 x 49.7 MB). The build runs
        # with DOCKER_BUILDKIT=1, which --chmod needs.
        copy_binary = f"COPY {own}--chmod=755 {output_dir}/{binary_name} ./\n"
    else:
        copy_binary = f"COPY {own}{output_dir}/{entry_stem}.dist/ ./\n"

    # Third-party packages (only in EXTERNAL mode — libs/ created by nuitka_worker)
    copy_libs = ""
    if config.pack_mode == PackMode.EXTERNAL:
        copy_libs = f"COPY {own}{output_dir}/libs/ ./libs/\n"

    # Data directories (copied to output_dir by nuitka_worker).
    # Only COPY dirs that actually landed in dist/: nuitka_worker skips (with a
    # warning) any data_dir that doesn't exist in the project, so emitting a
    # blind `COPY dist/<dir>/` for a missing one makes `docker build` fail with
    # "COPY ... not found". Keep the two stages consistent — skip the same dirs.
    data_copy_lines = ""
    if config.data_dirs:
        dist_root = Path(config.project_path) / output_dir
        for data_dir in _outermost_dirs([d.strip() for d in config.data_dirs.split(",") if d.strip()]):
            if (dist_root / data_dir).is_dir():
                data_copy_lines += f"COPY {own}{output_dir}/{data_dir}/ ./{data_dir}/\n"

    # State folders: created in the image and owned by the program's user, so a
    # new named volume mounted there starts with that owner (Docker copies the
    # image folder's ownership into an empty volume). Without the folder in the
    # image, Docker creates the mount point as root and a non-root program
    # cannot write its own data. /app itself is given to the user too, for the
    # folders it creates that are not volumes (logs, caches).
    volumes = [mount_point(v) for v in parse_volumes(config.docker_volumes)]
    state_block = ""
    if not as_root:
        state_block += f"RUN mkdir -p {' '.join(volumes)} && chown {APP_USER}:{APP_USER} /app {' '.join(volumes)}\n" if volumes \
            else f"RUN chown {APP_USER}:{APP_USER} /app\n"
    elif volumes:
        state_block += f"RUN mkdir -p {' '.join(volumes)}\n"
    if volumes:
        state_block += "VOLUME [" + ", ".join(f'"{v}"' for v in volumes) + "]\n"
    if not as_root:
        state_block += f"USER {APP_USER}\n"

    # Only what the shipped extensions load (see system_libs): the GUI and
    # OpenGL libraries every image used to get were 221 MB of MCP Gate's 449.
    packages = " ".join(system.packages)
    return dedent(f"""\
        # === Precompiled Backend Dockerfile ===
        FROM {base_image}
        WORKDIR /app
        RUN apt-get update && apt-get install -y --no-install-recommends {packages} \\
            && apt-get clean && rm -rf /var/lib/apt/lists/*
    """) + extra_blocks + "\n# Copy precompiled Nuitka output\n" + copy_binary + copy_libs + data_copy_lines \
        + state_block + dedent(f"""\
        ENV HOST=0.0.0.0
        ENV PORT={port}
        ENV LANG=C.UTF-8
        ENV LC_ALL=C.UTF-8
        ENV PYTHONIOENCODING=utf-8

        EXPOSE {port}

        CMD ["./{binary_name}"]
    """)


async def _run_docker_command(task_id: str, cmd: list[str], cwd: Path) -> bool:
    """Run a Docker command with output streaming.

    Note: Commands are constructed programmatically from validated config,
    not from raw user input.
    """
    current_progress = 20

    async def consume(lines: list[str], _frame: str | None) -> None:
        nonlocal current_progress
        for text in lines:
            await task_manager.append_log(task_id, text)
            # Classic builder prints "Step 3/9"; BuildKit's plain output does not.
            match = re.search(r"step\s+(\d+)/(\d+)", text.lower())
            if match:
                step, total = int(match.group(1)), int(match.group(2))
                current_progress = 20 + int((step / total) * 70)
                await task_manager.update_task(task_id, "progress", current_progress)

    try:
        result = await run_step(
            task_id, cmd, cwd=cwd, on_output=consume,
            env=build_environment({"TERM": "xterm-256color", "DOCKER_BUILDKIT": "1"}),
        )
    except OSError as e:
        await task_manager.append_log(task_id, f"Error running Docker command: {e}")
        return False
    return result.ok

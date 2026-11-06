"""Frontend build worker for building frontend projects."""

import asyncio
import hashlib
import os
import re
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.task import BuildConfig, FrontendBuildTool
from app.services.source_guard import SourceGuard
from app.services.task_manager import task_manager
from app.services.process_runner import is_cancelled, run_step

# Hard ceiling per install/build step so a hung npm/yarn (network stall, an
# interactive prompt) never holds the build slot — and the whole queue — forever.
FRONTEND_CMD_TIMEOUT = 1800.0  # seconds (30 min)


def _detect_vite_output_dir(fe_path: Path) -> str | None:
    """Detect build.outDir from vite.config.js/ts.

    Returns the outDir value if found, None otherwise.
    """
    for cfg_name in ("vite.config.ts", "vite.config.js", "vite.config.mts", "vite.config.mjs"):
        cfg_file = fe_path / cfg_name
        if cfg_file.exists():
            try:
                content = cfg_file.read_text(encoding="utf-8")
                match = re.search(r"""outDir\s*:\s*['"](.+?)['"]""", content)
                if match:
                    return match.group(1)
            except Exception:
                pass
            break
    return None


# Maps the detected build tool to the lockfile whose contents decide whether a
# reinstall is actually needed. bun ships either a binary (bun.lockb) or a text
# (bun.lock) lockfile depending on version, so it lists both — first match wins.
_TOOL_LOCK_FILES = {
    FrontendBuildTool.NPM: ("package-lock.json",),
    FrontendBuildTool.YARN: ("yarn.lock",),
    FrontendBuildTool.PNPM: ("pnpm-lock.yaml",),
    FrontendBuildTool.BUN: ("bun.lockb", "bun.lock"),
}

# Marker file inside node_modules recording the lockfile hash of the last
# successful install. Used to skip reinstalling unchanged dependencies.
_LOCK_HASH_MARKER = ".bc-lock-hash"


def _compute_lockfile_hash(fe_path: Path, tool: FrontendBuildTool) -> str | None:
    """Return the sha256 hex digest of the lockfile matching ``tool``.

    Returns None if no matching lockfile exists or it cannot be read — the
    caller then falls back to always installing. Never raises.
    """
    for lock_name in _TOOL_LOCK_FILES.get(tool, ()):  # noqa: PLC0206
        lock_path = fe_path / lock_name
        if lock_path.exists():
            try:
                return hashlib.sha256(lock_path.read_bytes()).hexdigest()
            except Exception:
                return None
    return None


def _read_stored_lock_hash(fe_path: Path) -> str | None:
    """Read the stored lockfile hash from node_modules, or None if absent."""
    try:
        marker = fe_path / "node_modules" / _LOCK_HASH_MARKER
        if marker.exists():
            return marker.read_text(encoding="utf-8").strip() or None
    except Exception:
        pass
    return None


def _write_stored_lock_hash(fe_path: Path, digest: str) -> None:
    """Persist the lockfile hash into node_modules. Best-effort, never raises."""
    try:
        marker = fe_path / "node_modules" / _LOCK_HASH_MARKER
        marker.write_text(digest, encoding="utf-8")
    except Exception:
        pass



def install_command(tool: FrontendBuildTool, has_package_lock: bool) -> list[str]:
    """How dependencies are installed: from the lock file where the tool has one."""
    if tool == FrontendBuildTool.NPM:
        return ["npm", "ci", "--legacy-peer-deps"] if has_package_lock else ["npm", "install"]
    if tool in (FrontendBuildTool.YARN, FrontendBuildTool.PNPM, FrontendBuildTool.BUN):
        return [tool.value, "install", "--frozen-lockfile"]
    return [tool.value, "install"]


def build_command(tool: FrontendBuildTool, script: str) -> list[str]:
    """How the frontend is built: the package.json script, run by its tool."""
    return [tool.value, "run", script]

async def run_frontend_build(
    task_id: str,
    config: BuildConfig,
    db: AsyncSession,
    frontend_path: Path | None = None,
) -> bool:
    """Run the frontend build; the project's env file is put back on every path out."""
    guard = SourceGuard(task_id)
    try:
        return await _run_frontend_build(task_id, config, db, frontend_path, guard)
    finally:
        await _restore_and_log(task_id, guard)


async def _restore_and_log(task_id: str, guard: SourceGuard) -> None:
    for line in await asyncio.to_thread(guard.restore):
        await task_manager.append_log(task_id, line)


async def _run_frontend_build(
    task_id: str,
    config: BuildConfig,
    db: AsyncSession,
    frontend_path: Path | None,
    guard: SourceGuard,
) -> bool:
    """Run frontend build (npm/yarn/pnpm/bun).

    Args:
        task_id: Task ID for logging
        config: Build configuration
        db: Database session
        frontend_path: Override frontend path (for fullstack builds)

    Returns:
        True if build succeeded, False otherwise
    """
    project_path = Path(config.project_path)

    # Determine frontend directory
    if frontend_path:
        fe_path = frontend_path
    else:
        fe_path = project_path / config.frontend_dir

    if not fe_path.exists():
        await task_manager.append_log(task_id, f"Error: Frontend directory not found: {fe_path}")
        return False

    # Auto-detect outDir from vite.config
    detected_out_dir = _detect_vite_output_dir(fe_path)
    if detected_out_dir:
        config.frontend_output_dir = detected_out_dir
        await task_manager.append_log(task_id, f"Detected vite outDir: {detected_out_dir}")

    await task_manager.append_log(task_id, f"Frontend directory: {fe_path}")

    import shutil

    # Determine build tool. The lockfile is the source of truth for a
    # reproducible install — if a lockfile for a DIFFERENT tool than the one
    # selected is present, switch to it (and say so) instead of silently
    # running a mismatched installer against it.
    tool = config.frontend_build_tool
    lock_files = {
        "package-lock.json": FrontendBuildTool.NPM,
        "yarn.lock": FrontendBuildTool.YARN,
        "pnpm-lock.yaml": FrontendBuildTool.PNPM,
        "bun.lockb": FrontendBuildTool.BUN,
        "bun.lock": FrontendBuildTool.BUN,
    }
    for lock_file, detected_tool in lock_files.items():
        if (fe_path / lock_file).exists():
            if detected_tool != tool:
                await task_manager.append_log(
                    task_id,
                    f"Found {lock_file}: using {detected_tool.value} instead of "
                    f"{tool.value} to match the lockfile",
                )
                tool = detected_tool
            else:
                await task_manager.append_log(task_id, f"Detected {lock_file}")
            break

    tool_cmd = tool.value

    # Check if the (possibly switched) tool is actually available on the host
    if not shutil.which(tool_cmd):
        await task_manager.append_log(task_id, f"Error: {tool_cmd} not found in PATH")
        return False

    await task_manager.append_log(task_id, f"Using build tool: {tool_cmd}")

    # Step 0: Write env file if configured (the guard restores the original)
    if config.frontend_env_content.strip():
        env_filename = config.frontend_env_filename or ".env"
        env_file_path = fe_path / env_filename
        try:
            guard.write(env_file_path, config.frontend_env_content)
            await task_manager.append_log(task_id, f"Wrote {env_filename} for build: {env_file_path}")

            # Log env keys for verification (values hidden for security)
            env_keys = [
                line.split("=", 1)[0].strip()
                for line in config.frontend_env_content.splitlines()
                if line.strip() and not line.strip().startswith("#") and "=" in line
            ]
            if env_keys:
                await task_manager.append_log(task_id, f"Env keys: {', '.join(env_keys)}")
        except Exception as e:
            await task_manager.append_log(task_id, f"Error: Failed to write .env file: {e}")
            return False

    # Step 1: Install dependencies
    await task_manager.append_log(task_id, "")
    await task_manager.append_log(task_id, "=== Installing dependencies ===")
    await task_manager.update_task(task_id, "status_msg", "Installing dependencies...")
    await task_manager.update_task(task_id, "progress", 10)

    install_cmd = install_command(tool, (fe_path / "package-lock.json").exists())

    # Lockfile-hash skip: if the lockfile hasn't changed since the last
    # successful install and node_modules is still present, reinstalling is a
    # waste of time — skip straight to the build. A missing lockfile or any
    # hash failure falls back to always installing (current_lock_hash is None).
    current_lock_hash = _compute_lockfile_hash(fe_path, tool)
    node_modules_dir = fe_path / "node_modules"

    if (
        current_lock_hash is not None
        and node_modules_dir.exists()
        and _read_stored_lock_hash(fe_path) == current_lock_hash
    ):
        await task_manager.append_log(
            task_id, "Dependencies unchanged (lockfile not modified); skipping install"
        )
    else:
        await task_manager.append_log(task_id, f"Command: {' '.join(install_cmd)}")

        success = await _run_command(task_id, install_cmd, fe_path)
        if not success:
            await _log_step_failure(task_id, "Error: Failed to install dependencies")
            return False

        # Record the lockfile hash so the next build can skip this step.
        if current_lock_hash is not None:
            _write_stored_lock_hash(fe_path, current_lock_hash)
            await task_manager.append_log(task_id, "Recorded the lockfile hash for the next build to compare")

    await task_manager.update_task(task_id, "progress", 40)

    # Step 2: Run build command
    await task_manager.append_log(task_id, "")
    await task_manager.append_log(task_id, "=== Building frontend ===")
    await task_manager.update_task(task_id, "status_msg", "Building frontend...")

    build_cmd = build_command(tool, config.frontend_build_command)
    await task_manager.append_log(task_id, f"Command: {' '.join(build_cmd)}")

    success = await _run_command(task_id, build_cmd, fe_path)
    if not success:
        await _log_step_failure(task_id, "Error: Frontend build failed")
        return False

    await task_manager.update_task(task_id, "progress", 90)

    # Verify output exists
    output_path = fe_path / config.frontend_output_dir
    if not output_path.exists():
        await task_manager.append_log(task_id, f"Warning: Build output not found at {output_path}")
    else:
        # Count files in output
        if config.version:
            # Served with the site (/VERSION), so a deployed frontend says which build it is.
            (output_path / "VERSION").write_text(config.version + "\n", encoding="utf-8")
        file_count = sum(1 for _ in output_path.rglob("*") if _.is_file())
        await task_manager.append_log(task_id, f"Build output: {output_path} ({file_count} files)")

    return True


async def _log_step_failure(task_id: str, message: str) -> None:
    """A step stopped by Cancel is not a broken build; say which it was."""
    await task_manager.append_log(
        task_id, "Stopped: the build was cancelled" if await is_cancelled(task_id) else message
    )


async def _run_command(
    task_id: str,
    cmd: list[str],
    cwd: Path,
    timeout: float = FRONTEND_CMD_TIMEOUT,
) -> bool:
    """Run a command with PTY for proper output handling.

    Enforces an overall `timeout`: if the command runs longer, the process is
    killed and the step fails — so a stuck install/build can't pin the build
    slot indefinitely.

    Note on injection: this spawns argv-form with no shell, so metacharacters
    in an argument are inert HERE. That is a property of the call, not of the
    inputs — `frontend_build_command` IS raw user input. It reaches a shell in
    the Docker path, where it is interpolated into `RUN {tool} run {cmd}`, so
    it is constrained by a field_validator on BuildConfig rather than by this
    function. An earlier version of this note claimed the values were not user
    input, which would have made it reasonable to copy this call pattern
    somewhere a shell is involved.
    """
    try:
        result = await run_step(
            task_id, cmd, cwd=cwd, timeout=timeout,
            env={**os.environ, "TERM": "xterm-256color", "CI": "true"},
        )
    except OSError as e:  # e.g. the tool vanished between the PATH check and here
        await task_manager.append_log(task_id, f"Error running command: {e}")
        return False
    return result.ok

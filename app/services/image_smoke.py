"""Smoke-test a built Docker image by starting it.

A Docker build used to smoke-test the binary on the build host, with the Docker
ENV block as its environment. That block describes the container: MCP Gate's
`MCP_GATE_CONFIG_DIR=/app/config` does not exist on the host, so a correct image
failed the build, while the image itself was never started and a broken one
(a missing system library, a bad CMD) passed as long as the host binary did.

Now the image runs, as it will in production: `docker run -d` under a unique
name, its ENV baked in, on the default bridge network (no published ports, so
nothing collides with the host). Within the same 10 s window as the binary
test, it passes when it exits 0 or is still running; a failed exit is judged
with the same rules (nuitka_worker.classify_exit). Meanwhile its listening
ports are read from inside the container, and afterwards `docker diff` says
which folders it created under /app. The container is always removed.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from typing import Any

from app.services.build_env import build_environment
from app.services.ports import Listener, parse_proc_net_tcp

SMOKE_WINDOW = 10.0
_POLL = 0.5
_WORKDIR = "/app"


async def _docker(*args: str, timeout: float = 60) -> tuple[int, str]:
    """Run a docker CLI command; (returncode, stdout+stderr). -1 on a timeout or no docker."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env=build_environment(),
        )
    except OSError as e:
        return -1, str(e)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, f"docker {args[0]} timed out"
    return proc.returncode or 0, out.decode("utf-8", "replace")


def container_name(image: str) -> str:
    """A unique container name from the image's repository: <repo>-smoke-<hex>."""
    last = image.rsplit("/", 1)[-1]
    repo = re.sub(r"[^A-Za-z0-9_.-]+", "-", re.split(r"[:@]", last)[0]).strip("-.") or "image"
    return f"{repo}-smoke-{secrets.token_hex(4)}"


def created_dirs(diff: str, existing_dirs: set[str] | None = None) -> list[str]:
    """Top-level folders added under /app, from `docker diff` output.

    An added path with added paths below it is a folder; when the container was
    still running, `existing_dirs` (from `ls -p` inside it) settles the rest.
    Hidden folders (caches under the user's home, /app) and bytecode caches are
    not state.
    """
    added = [line[2:].strip() for line in diff.splitlines() if line.startswith("A ")]
    names: list[str] = []
    for path in added:
        if not path.startswith(_WORKDIR + "/"):
            continue
        name = path[len(_WORKDIR) + 1:]
        if "/" in name or name.startswith(".") or name == "__pycache__" or name in names:
            continue
        has_children = any(p.startswith(f"{path}/") for p in added)
        if has_children or (existing_dirs is not None and name in existing_dirs):
            names.append(name)
    return sorted(names)


async def smoke_test_image(image: str, *, window: float | None = None, is_cancelled=None) -> dict[str, Any]:
    """Start the image, judge it, note its ports and new folders, and remove it.

    Returns a VerifyResult-shaped dict with `target: "image"`, `listeners` and
    `created_dirs`, plus `container` (the name it ran under).
    """
    from app.services.nuitka_worker import classify_exit

    window = SMOKE_WINDOW if window is None else window
    name = container_name(image)
    listeners: set[Listener] = set()
    result: dict[str, Any]
    try:
        code, out = await _docker("run", "-d", "--name", name, "--label", "packwright.smoke=1", image)
        if code != 0:
            return {"status": "fail", "detail": f"The image did not start: {out.strip()[-500:]}",
                    "exit_code": None, "target": "image", "container": name}

        deadline = time.monotonic() + window
        running, exit_code = True, None
        while True:
            code, state = await _docker("inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", name)
            if code == 0:
                running_s, _, exit_s = state.strip().partition(" ")
                running = running_s == "true"
                exit_code = None if running else int(exit_s or 0)
            if not running:
                break
            code, tcp = await _docker("exec", name, "cat", "/proc/net/tcp", "/proc/net/tcp6", timeout=10)
            if code == 0:
                # Both files concatenated: each starts with a header line, which
                # the parser skips as a malformed row.
                listeners |= parse_proc_net_tcp("header\n" + tcp)
            if is_cancelled is not None and await is_cancelled():
                return {"status": "skipped", "detail": "Build cancelled during the image smoke test",
                        "exit_code": None, "target": "image", "container": name}
            left = deadline - time.monotonic()
            if left <= 0:
                break
            await asyncio.sleep(min(_POLL, left))

        existing = None
        if running:
            code, listing = await _docker("exec", name, "ls", "-1p", _WORKDIR, timeout=10)
            if code == 0:
                existing = {line[:-1] for line in listing.splitlines() if line.endswith("/")}
        _, diff = await _docker("diff", name)
        dirs = created_dirs(diff, existing)

        if running:
            result = {
                "status": "pass",
                "detail": f"The image is still running after {window:g}s (long-running service) — startup OK",
                "exit_code": None,
            }
        else:
            _, logs = await _docker("logs", "--tail", "400", name)
            result = classify_exit(exit_code or 0, logs)
            result["detail"] = result["detail"].replace("Binary", "The image's program", 1)
        result.update({
            "target": "image",
            "container": name,
            "created_dirs": dirs,
            "listeners": [{"port": lst.port, "address": lst.address} for lst in sorted(listeners)],
        })
        return result
    finally:
        # Always, also on cancellation: a smoke container left running holds
        # memory and whatever it opened on the shared Docker host.
        await asyncio.shield(_docker("rm", "-f", "-v", name, timeout=60))

"""The C compile cache Nuitka uses, and what it did for a build.

Nuitka compiles every module it includes into C and then runs gcc on each file.
When ccache is installed (on PATH, or named by NUITKA_CCACHE_BINARY), Nuitka
routes gcc through it on its own and keeps the store under its cache directory,
so a rebuild only compiles the C files that changed. Measured on a Full-mode
build of a small Starlette app: 123 s cold, 21 s when rebuilt from another
workspace directory, with 80 of its 81 C files reused. Packwright clones every
build into a new directory, and ccache still hits there, so nothing more than
having it installed is needed.

Nothing told anyone whether it was installed, though: without ccache every
build compiles everything again, silently. This module finds the binary and
the store the way Nuitka does, reads the store's size, and turns Nuitka's own
summary lines into numbers for the build result.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import signal
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

# Nuitka prints, after compiling:
#   Nuitka-Scons: Cached C files (using ccache) with result 'cache hit': 80
#   Nuitka-Scons: Cached C files (using ccache) with result 'cache miss': 1
_RESULT_LINE = re.compile(r"Cached C files \(using ccache\) with result '([^']+)': (\d+)")

_STATS_TIMEOUT = 5.0


def ccache_binary(environ: Mapping[str, str] | None = None) -> str | None:
    """The ccache Nuitka will use, or None when it will compile without one.

    Same order as Nuitka (build/SconsCaching._injectCcache): NUITKA_CCACHE_BINARY
    if set, else ccache on PATH. A NUITKA_CCACHE_BINARY that does not exist makes
    Nuitka skip ccache, so it is reported as missing too.
    """
    env = os.environ if environ is None else environ
    named = env.get("NUITKA_CCACHE_BINARY")
    if named:
        return named if Path(named).exists() else None
    return shutil.which("ccache", path=env.get("PATH"))


def nuitka_cache_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Nuitka's cache directory for a build run with this environment
    (nuitka/utils/AppDirs._getCacheDir): NUITKA_CACHE_DIR, else the user cache."""
    env = os.environ if environ is None else environ
    if env.get("NUITKA_CACHE_DIR"):
        return Path(os.path.expanduser(env["NUITKA_CACHE_DIR"])).absolute()
    base = env.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base).absolute() / "Nuitka"


def ccache_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Where ccache keeps its store for Nuitka builds.

    Nuitka respects a CCACHE_DIR already in the environment; otherwise it points
    ccache at <cache dir>/ccache (NUITKA_CACHE_DIR_CCACHE overrides that one).
    """
    env = os.environ if environ is None else environ
    if env.get("CCACHE_DIR"):
        return Path(os.path.expanduser(env["CCACHE_DIR"])).absolute()
    if env.get("NUITKA_CACHE_DIR_CCACHE"):
        return Path(os.path.expanduser(env["NUITKA_CACHE_DIR_CCACHE"])).absolute()
    return nuitka_cache_dir(env) / "ccache"


def build_environment(base: Mapping[str, str], cache_dir_setting: str) -> dict[str, str]:
    """The environment a Nuitka build runs with: the service's own, with
    NUITKA_CACHE_DIR set when the operator configured one."""
    env = dict(base)
    if cache_dir_setting.strip():
        env["NUITKA_CACHE_DIR"] = str(Path(os.path.expanduser(cache_dir_setting.strip())).absolute())
    return env


def parse_build_summary(lines: Iterable[str]) -> dict[str, int] | None:
    """Count the C files Nuitka took from the cache and the ones it compiled.

    None when Nuitka printed no ccache summary: ccache was not used, or the
    build stopped before compiling. Results other than hit and miss (e.g. a file
    ccache cannot cache) count as compiled, since that is what they cost.
    """
    hits = compiled = 0
    seen = False
    for line in lines:
        match = _RESULT_LINE.search(line)
        if not match:
            continue
        seen = True
        if match.group(1) == "cache hit":
            hits += int(match.group(2))
        else:
            compiled += int(match.group(2))
    return {"hits": hits, "compiled": compiled} if seen else None


def describe_summary(summary: dict[str, int] | None, binary: str | None) -> str:
    """One build-log line about the compile cache."""
    if summary is None:
        if binary is None:
            return ("C compile cache: off, ccache is not installed. Every build compiles all C files "
                    "again; install ccache on the build host to reuse unchanged ones.")
        return "C compile cache: no C files were compiled."
    total = summary["hits"] + summary["compiled"]
    return f"C compile cache: reused {summary['hits']} of {total} C files, compiled {summary['compiled']}."


def _parse_print_stats(text: str) -> dict[str, int]:
    stats: dict[str, int] = {}
    for line in text.splitlines():
        key, _, value = line.partition("\t")
        if value.strip().isdigit():
            stats[key.strip()] = int(value.strip())
    return stats


async def cache_status(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """What the Machine page shows: is the cache on, where it is, how big.

    Size and limit come from ccache's own counters (`ccache --print-stats`),
    which are kept up to date by ccache, rather than from walking a store that
    can hold hundreds of thousands of files.
    """
    env = dict(os.environ if environ is None else environ)
    binary = ccache_binary(env)
    directory = ccache_dir(env)
    status: dict[str, Any] = {
        "enabled": binary is not None,
        "binary": binary,
        "directory": str(directory),
        "size_bytes": None,
        "max_size_bytes": None,
        "files": None,
    }
    if binary is None:
        return status
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "--print-stats",
            env={**env, "CCACHE_DIR": str(directory)},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            # Its own process group, so a timeout stops anything it started too;
            # a surviving child would hold the pipe open and keep the page waiting.
            start_new_session=True,
        )
    except OSError:
        return status
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=_STATS_TIMEOUT)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()
        return status
    stats = _parse_print_stats(out.decode(errors="replace"))
    if "cache_size_kibibyte" in stats:
        status["size_bytes"] = stats["cache_size_kibibyte"] * 1024
    if stats.get("max_cache_size_kibibyte"):  # 0 means no limit
        status["max_size_bytes"] = stats["max_cache_size_kibibyte"] * 1024
    if "files_in_cache" in stats:
        status["files"] = stats["files_in_cache"]
    return status

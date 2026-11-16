"""Local worker service for running Nuitka builds directly on the host."""

import ast
import asyncio
import contextlib
import hashlib
import importlib.util
import json
import logging
import os
import re
import shutil
import signal
import tempfile
import site
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.paths import UnsafePathError, safe_join
from app.config import get_settings
from app.schemas.task import BuildConfig, PackMode
from app.services.source_guard import SourceGuard
from app.services.task_manager import task_manager
from app.services.process_runner import run_step
from app.services import compile_cache
from app.services.ports import Listener, group_listeners, port_check
from app.services.build_env import build_environment

settings = get_settings()
logger = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parents[2]

# The per-project lock lives in app/services/project_lock.py and is taken by
# build_dispatcher, not here.
#
# It used to be defined in this module and acquired by run_nuitka_build, which
# covered this worker's in-place injection into the entry point but left
# docker_worker — which backs up and overwrites .dockerignore, writes
# Dockerfile.generated and replaces the project's frontend .env — completely
# unguarded. Two builds of the same local path destroyed each other's backups.
# Do not reintroduce a second lock here; one owner for the whole
# prepare -> build -> restore window is the point.

# Nuitka's in-place progress bars ("PASS 1:  34% 102/296 [...]") mapped onto the
# task's 0-100 progress: (label, start, span, status message).
_NUITKA_BARS: tuple[tuple[str, float, float, str], ...] = (
    ("pass 1", 10, 10, "Analyzing Python..."),
    ("pass 2", 20, 20, "Optimizing..."),
    ("backend c", 50, 45, "Compiling C code..."),
)
_BAR_RE = re.compile(r"^\s*([A-Za-z][\w .]*?):\s+(\d{1,3})%")


def parse_nuitka_progress(text: str, current: float, status_msg: str = "") -> tuple[float, str]:
    """Advance the task's progress from one line (or progress-bar frame) of Nuitka output.

    Progress only ever moves forward. Returns ``(progress, status_msg)``; the status
    is left unchanged when the text says nothing about the build phase.
    """
    lower = text.lower()
    bar = _BAR_RE.match(lower)
    if bar:
        for label, start, span, message in _NUITKA_BARS:
            if bar.group(1) == label:
                percent = min(int(bar.group(2)), 100)
                return max(current, start + span * percent / 100), f"{message} {percent}%"

    if "starting python compilation" in lower:
        return max(current, 10), "Starting compilation..."
    if "completed python level" in lower:
        return max(current, 40), "Python compiled"
    if "generating source code" in lower:
        return max(current, 45), "Generating C code..."
    if "running c compilation" in lower or "running scons" in lower:
        return max(current, 50), "Compiling C code..."
    if "linking" in lower:
        return max(current, 95), "Linking..."
    if "onefile" in lower and "creating" in lower:
        return max(current, 97), "Creating executable..."
    if "successfully created" in lower:
        return 100.0, "Complete!"
    if "error" in lower and "nuitka" in lower:
        return current, "Error occurred"
    return current, status_msg


# Known packages that use lazy/dynamic imports and need --include-package
# Maps: package install name -> list of Nuitka --include-package values
KNOWN_LAZY_PACKAGES: dict[str, list[str]] = {
    "litellm": ["litellm"],
    "pydantic": ["pydantic"],
    "google-cloud-aiplatform": ["google.cloud.aiplatform", "google.api_core"],
    "google-generativeai": ["google.generativeai"],
    "openai": ["openai"],
    "langchain": ["langchain"],
    "langchain-core": ["langchain_core"],
    "anthropic": ["anthropic"],
    "boto3": ["boto3", "botocore"],
    "transformers": ["transformers"],
    "tiktoken": ["tiktoken", "tiktoken_ext"],
    "aiohttp": ["aiohttp"],
    "grpcio": ["grpc"],
    "lupa": ["lupa"],
    "fakeredis": ["fakeredis"],
}


def detect_lazy_packages(project_path: Path) -> list[str]:
    """Scan project dependencies and return --include-package values for known lazy-import packages.

    Checks both declared dependencies (requirements.txt / pyproject.toml) AND
    actually installed packages in the project's .venv to catch indirect dependencies.
    """
    found_deps: set[str] = set()

    # Parse requirements.txt
    req_file = project_path / "requirements.txt"
    if req_file.exists():
        try:
            for line in req_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                # Extract package name (before any version specifier)
                pkg_name = re.split(r"[>=<!\[;]", line)[0].strip().lower()
                if pkg_name:
                    found_deps.add(pkg_name)
        except Exception:
            logger.warning("Failed to parse %s for lazy-package detection", req_file, exc_info=True)

    # Parse pyproject.toml dependencies
    pyproject_file = project_path / "pyproject.toml"
    if pyproject_file.exists():
        try:
            content = pyproject_file.read_text(encoding="utf-8")
            # Simple regex extraction for dependencies lists
            # Matches lines like: "litellm>=1.0", 'openai', etc. inside arrays
            in_deps = False
            for line in content.splitlines():
                stripped = line.strip()
                if re.match(r"^(dependencies|requires)\s*=\s*\[", stripped):
                    in_deps = True
                    continue
                if in_deps:
                    if stripped.startswith("]"):
                        in_deps = False
                        continue
                    # Extract quoted package name
                    match = re.match(r"""^["']([a-zA-Z0-9_-]+)""", stripped)
                    if match:
                        found_deps.add(match.group(1).lower())
        except Exception:
            logger.warning("Failed to parse %s for lazy-package detection", pyproject_file, exc_info=True)

    # Also scan installed packages in .venv to catch indirect dependencies
    # (e.g., lupa pulled in by fakeredis[lua] pulled in by pydocket)
    venv_path = project_path / ".venv"
    if venv_path.exists():
        for pkg_name in get_installed_packages(venv_path):
            found_deps.add(pkg_name.lower().replace("-", "_"))

    # Match against known lazy packages
    include_packages: list[str] = []
    for dep_name in found_deps:
        # Normalize: both hyphens and underscores
        normalized = dep_name.replace("-", "_").replace("_", "-")
        for known_name, packages in KNOWN_LAZY_PACKAGES.items():
            known_normalized = known_name.replace("-", "_").replace("_", "-")
            if dep_name == known_name or normalized == known_normalized or dep_name.replace("-", "_") == known_name.replace("-", "_"):
                include_packages.extend(packages)

    return sorted(set(include_packages))


# Runtime code injected into the entry point so an External-mode binary finds the
# libs/ directory shipped next to it. It runs inside the user's program, so it must
# stay invisible: no output (it would corrupt a CLI's piped stdout) and no names left
# behind in the user's __main__ namespace.
INJECT_CODE = """# ==================== [LIBS LOADER] ====================
import os as _pw_os, sys as _pw_sys
_pw_libs = _pw_os.path.join(_pw_os.path.dirname(_pw_os.path.abspath(_pw_sys.argv[0])), "libs")
if _pw_os.path.isdir(_pw_libs):
    _pw_sys.path.insert(0, _pw_libs)
del _pw_os, _pw_sys, _pw_libs
# =======================================================
"""


def inject_libs_loader(source: str) -> str:
    """Insert INJECT_CODE into an entry point's source, after its module docstring
    and ``from __future__`` imports.

    Python requires ``from __future__`` imports to come first (only the docstring
    may precede them), so code prepended at line 1 turns every entry point that
    uses ``from __future__ import annotations`` into a SyntaxError and the build
    fails. Source that does not parse is prepended to unchanged: Nuitka reports
    the user's own syntax error either way.
    """
    try:
        body = ast.parse(source).body
    except SyntaxError:
        return INJECT_CODE + source
    end_line = 0
    for i, node in enumerate(body):
        is_docstring = (
            i == 0 and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        )
        if is_docstring or (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            end_line = node.end_lineno or node.lineno
        else:
            break
    if not end_line:
        return INJECT_CODE + source
    lines = source.splitlines(keepends=True)
    head = "".join(lines[:end_line])
    if not head.endswith("\n"):
        head += "\n"
    return head + INJECT_CODE + "".join(lines[end_line:])


_MODULE_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")


def _normalize_top_level_entry(raw: str) -> str | None:
    """Turn a top_level.txt line into a valid dotted module name, or None.

    top_level.txt is *supposed* to list importable module names (one per line,
    e.g. ``sentencepiece``), but some wheels record file PATHS instead
    (``sentencepiece/__init__``, ``nvidia/cusparselt``). Nuitka's
    ``--nofollow-import-to`` only accepts a dotted module name — a ``/`` makes it
    reject the whole option and exit 1 *before* compiling. Normalize the path
    into a module name: drop a ``.py`` suffix, drop a trailing ``/__init__`` (that
    IS the package), and turn path separators into dots. Return None for anything
    that still isn't a clean dotted identifier so it's skipped rather than passed
    through to break the command line.
    """
    s = raw.strip().replace("\\", "/").strip("/")
    if not s:
        return None
    if s.endswith(".py"):
        s = s[:-3]
    if s.endswith("/__init__"):
        s = s[: -len("/__init__")]
    s = s.replace("/", ".")
    return s if _MODULE_NAME_RE.fullmatch(s) else None


def get_installed_packages(venv_path: Path | None = None) -> list[str]:
    """Get list of installed third-party packages.

    Args:
        venv_path: Path to project's virtual environment. If provided,
                   reads packages from there instead of system site-packages.
    """
    packages = set()

    # Determine site-packages directories to scan
    if venv_path and venv_path.exists():
        # Find site-packages in the venv
        site_packages_dirs = []
        for pattern in ["lib/python*/site-packages", "Lib/site-packages"]:
            site_packages_dirs.extend(venv_path.glob(pattern))
    else:
        # Fallback to system site-packages
        site_packages_dirs = [Path(p) for p in site.getsitepackages()]

    for sp_dir in site_packages_dirs:
        if not sp_dir.exists():
            continue
        for item in sp_dir.iterdir():
            name = item.name
            if name.startswith(".") or name == "__pycache__":
                continue
            if name.endswith(".dist-info") or name.endswith(".egg-info"):
                pkg_name = name.split("-")[0]
                if pkg_name in ("pip", "setuptools", "wheel", "nuitka"):
                    continue
                packages.add(pkg_name)
                # The distribution name often differs from the import name
                # (Pillow → PIL, PyYAML → yaml). top_level.txt records the
                # actual importable names — add those too so
                # --nofollow-import-to matches what code really imports.
                top_level = item / "top_level.txt"
                if top_level.is_file():
                    try:
                        for line in top_level.read_text(encoding="utf-8").splitlines():
                            # Normalize: some wheels record file paths here
                            # (sentencepiece/__init__), which would inject a "/"
                            # into --nofollow-import-to and make Nuitka exit 1.
                            norm = _normalize_top_level_entry(line)
                            if norm and not norm.startswith("_"):
                                packages.add(norm)
                    except OSError:
                        pass
            elif item.is_dir():
                if name not in ["pip", "setuptools", "wheel", "nuitka", "_distutils_hack"]:
                    packages.add(name)
    # Sorted: a set's order changes with every process (hash randomization), so the
    # same project produced a differently ordered Nuitka command on each build.
    return sorted(packages)


def get_valid_std_libs() -> tuple[list[str], set[str]]:
    """Get all valid standard library modules.

    Uses sys.stdlib_module_names (Python 3.10+) to get the complete list,
    then validates each module exists and is importable.
    """
    # Get all stdlib module names
    if hasattr(sys, "stdlib_module_names"):
        candidates = list(sys.stdlib_module_names)
    else:
        # Fallback for Python < 3.10
        candidates = [
            "asyncio", "collections", "contextlib", "copy", "csv", "ctypes",
            "datetime", "decimal", "email", "functools", "hashlib", "http",
            "importlib", "inspect", "io", "itertools", "json", "logging",
            "math", "multiprocessing", "os", "pathlib", "pickle", "random",
            "re", "shutil", "socket", "sqlite3", "ssl", "string", "subprocess",
            "sys", "threading", "time", "typing", "unittest", "urllib", "uuid",
            "warnings", "xml", "zoneinfo", "zlib",
        ]

    # Auto-detect which stdlib modules are packages (have submodules)
    # by checking spec.submodule_search_locations instead of a manual list
    force_packages: set[str] = set()

    # Validate modules exist
    valid_libs = []
    for lib in candidates:
        # Skip private modules and test modules
        if lib.startswith("_") or "test" in lib:
            if lib != "unittest":
                continue
        # Skip builtin modules (always available)
        if lib in sys.builtin_module_names:
            continue
        try:
            spec = importlib.util.find_spec(lib)
            if spec is not None:
                valid_libs.append(lib)
                # If it has submodule_search_locations, it's a package
                if spec.submodule_search_locations is not None:
                    force_packages.add(lib)
        except Exception:
            continue

    return valid_libs, force_packages


def _path_present(path: Path, *, accept_dangling: bool = False) -> bool:
    """``Path.exists()`` that answers instead of raising.

    On Python 3.13 ``exists()`` raises PermissionError — rather than returning
    False — when a symlink's target sits in a directory this account cannot enter.
    That is the normal case for a venv created by root with uv (its python links
    into /root/.local/share/uv/...) when the service runs as another user, and it
    used to crash the build's preflight.

    ``accept_dangling`` counts a symlink as present without looking at its target
    (lstat only), for callers that need the path but not a runnable file.
    """
    try:
        if accept_dangling and path.is_symlink():
            return True
        return path.exists()
    except OSError:
        return False


def find_nuitka_python(version: str) -> tuple[str, bool]:
    """Return (python_executable, version_matched) for running Nuitka.

    The compiled binary is ABI-bound to the Python that runs Nuitka — a
    mismatch breaks native extensions (.so) at runtime with
    ModuleNotFoundError. Prefer the dedicated per-version venv
    (.venv-py312/313/314, see scripts/setup_nuitka_venvs.sh); fall back to
    this service's interpreter only when no matching venv exists.
    """
    compact = version.replace(".", "")
    candidate = _APP_ROOT / f".venv-py{compact}" / "bin" / "python"
    # exists() follows symlinks — a venv cloned from another machine has a
    # dangling python symlink and is correctly rejected here — as is one whose
    # target this account cannot reach, since Nuitka could not run it either.
    if _path_present(candidate):
        return str(candidate), True
    service_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    return sys.executable, service_version == version


# Matches the ABI tag on a compiled C-extension, e.g.
# "_pydantic_core.cpython-314-x86_64-linux-gnu.so" -> "314"
_ABI_TAG_RE = re.compile(r"\.cpython-(3\d{1,2})-")


def _find_project_site_packages(project_path: Path) -> Path | None:
    """Locate the target project's .venv site-packages, if any."""
    venv = project_path / ".venv"
    for pattern in ("lib/python*/site-packages", "Lib/site-packages"):
        matches = sorted(venv.glob(pattern))
        if matches:
            return matches[0]
    return None


def detect_project_python_version(project_path: Path) -> tuple[str | None, str]:
    """Detect the Python version a project's .venv was actually built for.

    The ONLY trustworthy source is the ``cpython-XY`` ABI tag on the
    compiled C-extension (.so) files in site-packages — that is exactly
    what EXTERNAL mode copies into libs/ and what the produced binary must
    load. Declaration files (pyvenv.cfg / pyproject requires-python /
    .python-version) are deliberately NOT trusted: a .venv can be rebuilt
    with a different Python without those being updated, silently producing
    an ABI-mismatched build (observed in the wild — a .venv declared 3.13
    whose .so files were all cpython-314).

    Returns (version, detail):
      - ("3.14", "..from _pydantic_core..so")  → confident, use this
      - (None, "no compiled extensions..")     → pure-Python project; the
        caller may fall back to a declaration file or the user's choice
      - (None, "mixed ABI tags: 3.13, 3.14..") → the .venv is broken; the
        caller should surface this rather than guess
    """
    site_packages = _find_project_site_packages(project_path)
    if site_packages is None:
        return None, "no .venv/site-packages found in project"

    counts: dict[str, int] = {}       # tag -> number of .so with that ABI
    example: dict[str, str] = {}      # tag -> an example filename
    for so in site_packages.rglob("*.so"):
        m = _ABI_TAG_RE.search(so.name)
        if m:
            tag = m.group(1)  # "312"
            counts[tag] = counts.get(tag, 0) + 1
            example.setdefault(tag, so.name)
    # Windows extension modules
    for pyd in site_packages.rglob("*.pyd"):
        m = re.search(r"\.cp(3\d{1,2})-", pyd.name)
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
            example.setdefault(m.group(1), pyd.name)

    if not counts:
        return None, "no compiled extensions (.so/.pyd) — pure-Python project"

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top_tag, top_count = ranked[0]
    total = sum(counts.values())

    # Majority rule: a healthy .venv built with one Python still often carries a
    # few .so for OTHER versions, because some wheels ship multi-version binaries
    # (e.g. ROCm's rocpd/roctx). So treat an overwhelming majority as the answer;
    # only flag "mixed/broken" when versions are genuinely close to even.
    if len(ranked) == 1 or top_count >= total * 0.8:
        version = f"3.{top_tag[1:]}"  # "312" -> "3.12"
        note = (
            ""
            if len(ranked) == 1
            else f" ({top_count}/{total} .so files; the few for other versions ship inside packages and were ignored)"
        )
        return version, f"from {example[top_tag]}{note}"

    versions = ", ".join(f"3.{t[1:]}({c})" for t, c in ranked)
    return None, f"mixed ABI tags ({versions}) — this .venv looks inconsistent"


# Runs inside the TARGET python so the stdlib list matches the version the
# binary will embed (e.g. 3.12's stdlib differs from this service's 3.13).
_STDLIB_PROBE = """
import importlib.util, json, sys
valid, pkgs = [], []
for lib in sorted(sys.stdlib_module_names):
    if (lib.startswith("_") or ("test" in lib and lib != "unittest")
            or lib in sys.builtin_module_names):
        continue
    try:
        spec = importlib.util.find_spec(lib)
    except Exception:
        continue
    if spec is None:
        continue
    valid.append(lib)
    if spec.submodule_search_locations is not None:
        pkgs.append(lib)
print(json.dumps({"libs": valid, "packages": pkgs}))
"""


async def get_valid_std_libs_for(python_exe: str) -> tuple[list[str], set[str]]:
    """Get valid stdlib modules as seen by the given Python executable.

    Falls back to probing this service's own interpreter if the subprocess
    fails for any reason.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            python_exe, "-c", _STDLIB_PROBE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=build_environment(),
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            data = json.loads(stdout.decode())
            return data["libs"], set(data["packages"])
        logger.warning(
            "stdlib probe via %s failed (exit %s): %s",
            python_exe, proc.returncode, stderr.decode(errors="replace")[:500],
        )
    except Exception:
        logger.warning("stdlib probe via %s crashed", python_exe, exc_info=True)
    return get_valid_std_libs()


def find_target_python(version: str, project_path: Path) -> str | None:
    """Find Python executable in the target project's virtual environment.

    This is used to determine the Python version for compilation target,
    not for running Nuitka itself.
    """
    venv_candidates = [
        project_path / ".venv" / "bin" / f"python{version}",
        project_path / ".venv" / "bin" / "python3",
        project_path / ".venv" / "bin" / "python",
        project_path / "venv" / "bin" / f"python{version}",
        project_path / "venv" / "bin" / "python3",
        project_path / "venv" / "bin" / "python",
        # Windows paths
        project_path / ".venv" / "Scripts" / "python.exe",
        project_path / "venv" / "Scripts" / "python.exe",
    ]
    for venv_python in venv_candidates:
        # A dangling or unreachable link still identifies the project's
        # interpreter (uv links to /root/.local/...): only the path is needed.
        if _path_present(venv_python, accept_dangling=True):
            return str(venv_python)
    return None


# Captures the keyword + the rest of an import statement so we can parse
# multi-imports like `import os, sys` and `from a.b import c` correctly.
_IMPORT_RE = re.compile(r"^[ \t]*(import|from)[ \t]+([^\n#]+)", re.MULTILINE)
# stdlib modules that are startup-critical or commonly loaded via dynamic
# import, so we always keep them even if a static scan didn't see them.
_ALWAYS_STDLIB = {"encodings"}


def _top_names(keyword: str, rest: str) -> list[str]:
    """Extract top-level module names from one import statement.

    `from a.b import c`  -> ['a']
    `import a, b.c as d`  -> ['a', 'b']
    """
    if keyword == "from":
        head = rest.split()[0] if rest.split() else ""
        return [head.split(".")[0]] if head else []
    names: list[str] = []
    for part in rest.split(","):
        toks = part.strip().split()
        if toks:
            names.append(toks[0].split(".")[0])
    return names


def collect_used_stdlib(
    scan_root: Path, stdlib_names: set[str], max_files: int = 8000
) -> set[str]:
    """Scan .py files under scan_root and return the stdlib modules they import.

    Regex-based (fast) and file-capped; best-effort — unreadable files are
    skipped. Used to figure out which stdlib the third-party packages in libs/
    depend on, so EXTERNAL mode can include just those instead of the whole
    standard library.
    """
    used: set[str] = set()
    scanned = 0
    for py in scan_root.rglob("*.py"):
        if scanned >= max_files:
            break
        scanned += 1
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for keyword, rest in _IMPORT_RE.findall(text):
            for name in _top_names(keyword, rest):
                if name in stdlib_names:
                    used.add(name)
    return used


_LIBS_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "tests", "test")


def _copytree_fast(src: Path, dst: Path) -> None:
    """Copy a package dir into libs/, preferring hardlinks (same filesystem →
    near-instant, no extra disk) and dropping bytecode/test dirs. Falls back to
    a normal byte copy across filesystems (os.link raises EXDEV)."""
    try:
        shutil.copytree(src, dst, copy_function=os.link, ignore=_LIBS_IGNORE)
    except (OSError, shutil.Error):
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst, ignore=_LIBS_IGNORE)


_LIBS_SKIP_PREFIXES = ("pip", "setuptools", "wheel", "nuitka")


def ships_in_libs(name: str) -> bool:
    """Whether a site-packages entry is copied into libs/.

    Left out: bytecode caches and hidden files, the packaging tools, .pth hooks,
    and the finder of an editable install. uv installs a Git project itself in
    editable mode, as __editable___<name>_finder.py pointing at the build
    workspace; the program's own code is compiled into the binary, so the finder
    only shipped a dead path to a folder that is deleted after the build.
    """
    if name == "__pycache__" or name.startswith("."):
        return False
    # Underscore-prefixed entries are legitimate packages / extensions (e.g.
    # _cffi_backend, _rocm_sdk_core, _rocm_sdk_libraries_gfx1151 — dynamically
    # imported at runtime by rocm_sdk). The old blanket "skip _*" rule silently
    # dropped these, breaking runtime imports. Only setuptools' internal shims
    # and editable-install finders are skipped explicitly.
    if name in ("pkg_resources", "easy_install.py", "_distutils_hack"):
        return False
    if name.startswith("__editable__"):
        return False
    if any(name.startswith(p) for p in _LIBS_SKIP_PREFIXES):
        return False
    # .pth files are setuptools hooks that cause issues at runtime
    return not name.endswith(".pth")


async def has_zstandard(python: str) -> bool:
    """Whether the compiling interpreter can compress a onefile binary.

    Without the zstandard package Nuitka stores the payload uncompressed and
    says so only in a warning in the middle of the compile log (MCP Gate: a
    49.7 MB binary that compresses to about a third).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            python, "-c", "import zstandard",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            env=build_environment(),
        )
        return await proc.wait() == 0
    except OSError:
        return False


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def _summarize_artifact(path: Path) -> dict[str, Any]:
    """Blocking artifact summary — run via asyncio.to_thread."""
    if path.is_file():
        size = path.stat().st_size
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        return {
            "path": str(path),
            "size_bytes": size,
            "size_human": _human_size(size),
            "file_count": 1,
            "sha256": digest.hexdigest(),
        }
    total = 0
    count = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                continue
            count += 1
    return {
        "path": str(path),
        "size_bytes": total,
        "size_human": _human_size(total),
        "file_count": count,
        "sha256": None,  # directory artifact — no single-file digest
    }


def _parse_env_lines(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines (Docker ENV block or a .env file).

    Skips blanks and '#' comments, tolerates a leading 'export ', and strips
    a single pair of surrounding quotes from the value. Good enough for
    feeding a smoke test — not a full dotenv parser (no interpolation).
    """
    env: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            env[key] = val
    return env


def _resolve_smoke_env(config: BuildConfig, project_path: Path) -> tuple[dict[str, str], str]:
    """Decide which env vars to give the smoke-tested binary.

    Priority (per user requirement): the Docker ENV block the user filled in
    ('runtime Docker ENV'), because that's the real runtime config; if empty,
    fall back to the project's .env file; otherwise nothing.
    Returns (env_dict, human-readable source description).
    """
    if config.docker_env_vars and config.docker_env_vars.strip():
        parsed = _parse_env_lines(config.docker_env_vars)
        if parsed:
            return parsed, f"Docker ENV ({len(parsed)} vars)"
    env_file = project_path / ".env"
    if env_file.exists():
        try:
            parsed = _parse_env_lines(env_file.read_text(encoding="utf-8"))
            if parsed:
                return parsed, f".env file ({len(parsed)} vars)"
        except OSError:
            pass
    return {}, "none (no Docker ENV or .env found)"


# The host variables a smoke-tested binary is launched with. Everything else
# in the service's environment is dropped.
#
# The binary being launched is code the user supplied, and the environment it
# used to receive was the service's whole os.environ — which is not the
# platform's configuration but whatever happened to be in the shell that ran
# start.sh. That is unbounded and unknowable: an operator's API tokens, agent
# credentials, another project's settings. The application's own secrets were
# never in there (pydantic-settings reads .env directly), which is exactly why
# this looked harmless; switching the service to a systemd EnvironmentFile=
# would have put them there without changing a line of this file.
#
# Chosen for what a process needs to start at all, not for what an application
# might want — the application's own configuration arrives through extra_env,
# resolved by _resolve_smoke_env from the Docker ENV block or the project's
# .env.
#
# LD_LIBRARY_PATH and PYTHONPATH are deliberately absent. They would let the
# binary resolve against the build host's libraries and pass here while
# failing on the machine it ships to, which is the one failure mode this smoke
# test exists to catch.
_SMOKE_ENV_PASSTHROUGH = (
    "PATH",       # finding subprocesses it shells out to
    "HOME",       # cache and config directories; unset breaks many libraries
    "LANG",       # text encoding — the wrong locale changes how strings decode
    "LC_ALL",
    "LC_CTYPE",
    "TZ",         # timestamps in its own output
    "TMPDIR",     # extraction target for a onefile binary
    "TERM",
)


def _build_smoke_env(extra_env: dict[str, str] | None) -> dict[str, str]:
    """Assemble the environment for the smoke-tested binary.

    Layered host basics -> caller-resolved runtime config -> the marker, so a
    project that legitimately sets PATH or TMPDIR in its .env still wins.
    """
    env = {
        name: os.environ[name]
        for name in _SMOKE_ENV_PASSTHROUGH
        if name in os.environ
    }
    env.update(extra_env or {})
    env["PACKWRIGHT_SMOKE_TEST"] = "1"
    # The former name, kept so binaries built while this was Build Center still
    # detect the smoke run.
    env["BUILD_CENTER_SMOKE_TEST"] = "1"
    return env


# What torch, ROCm, CUDA and NVML print when there is no GPU to start on.
_GPU_HINTS = (
    "rocm_sdk", "_rocm_init", "rocminfo", "libamdhip", "hip error",
    "cuda error", "cudaerror", "no cuda-capable device", "libcuda",
    "no hip", "torch/cuda",
)
# Words that make a generic "failed to initialize" line about a GPU.
_GPU_WORDS = ("cuda", "hip", "rocm", "nvml", "gpu", "accelerator")


def _looks_like_gpu_failure(low: str) -> bool:
    """Whether a binary's (lower-cased) output says it stopped for want of a GPU.

    "failed to initialize" counts only on a line that also names a GPU: on its
    own it matched "Failed to initialize database", and a program that could not
    start was excused as an environment problem and its build marked completed.
    """
    if any(h in low for h in _GPU_HINTS):
        return True
    return any(
        "failed to initialize" in line and any(re.search(rf"\b{w}\b", line) for w in _GPU_WORDS)
        for line in low.splitlines()
    )


# How long a binary gets to start before it counts as a running service.
_SMOKE_WINDOW = 10.0


def _signal_group(pid: int, sig: int) -> None:
    """Signal the smoke-tested binary's process group, if anything is left in it."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)


def _tree_state(root: Path) -> dict[str, tuple[int, int] | None]:
    """Every path under root (relative), with (size, mtime_ns) for files and None
    for directories. Symlinks are listed, never followed."""
    state: dict[str, tuple[int, int] | None] = {}
    for current, dirnames, filenames in os.walk(root):
        base = Path(current)
        for name in dirnames:
            path = base / name
            state[str(path.relative_to(root))] = None if not path.is_symlink() else (0, 0)
        for name in filenames:
            path = base / name
            try:
                st = path.lstat()
            except OSError:
                continue
            state[str(path.relative_to(root))] = (st.st_size, st.st_mtime_ns)
    return state


def _undo_smoke_writes(root: Path, before: dict[str, tuple[int, int] | None]) -> tuple[list[str], list[str]]:
    """Remove what the smoke-tested program created under root.

    The binary runs in the output directory, and that directory is what the
    build hands out. A service writes its state where it runs: packaging MCP
    Gate left data/mcp_gate.db (its signing keys), secrets/secrets.json (its
    encryption key and setup token) and logs/ in the downloadable archive, so
    every deployment of that build would have started with the same keys.

    Returns (removed, changed): the top-most paths removed, and existing files
    the program modified, which cannot be put back and are only reported.
    """
    after = _tree_state(root)
    created = sorted(p for p in after if p not in before)
    removed: list[str] = []
    for rel in created:
        if any(rel.startswith(done + os.sep) for done in removed):
            continue
        path = root / rel
        with contextlib.suppress(OSError):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(rel)
    changed = sorted(p for p, st in before.items() if st is not None and p in after and after[p] != st)
    return removed, changed


def _created_dirs(cwd: Path, binary_dir: Path, before: dict[str, tuple[int, int] | None]) -> list[str]:
    """The folders the program created beside itself or where it ran, by name.

    Both places are /app in a Docker image (a standalone build's binary sits in
    <entry>.dist/ here, but its contents are copied to /app). These are where a
    service keeps its state (MCP Gate: data/, secrets/, logs/), so they are what
    a Docker build offers as volumes. Bytecode caches are not state.
    """
    after = _tree_state(cwd)
    try:
        prefix = binary_dir.resolve().relative_to(cwd.resolve())
    except ValueError:
        prefix = Path(".")
    names: list[str] = []
    for rel, state in after.items():
        if state is not None or rel in before:
            continue
        path = Path(rel)
        if path.parent in (Path("."), prefix) and path.name != "__pycache__" and path.name not in names:
            names.append(path.name)
    return sorted(names)


def _describe_removed(removed: list[str]) -> str:
    """The removed paths for the log, with Python's bytecode caches counted rather
    than listed: MCP Gate's run left one in nearly every package in libs/."""
    caches = [p for p in removed if Path(p).name == "__pycache__"]
    named = [p for p in removed if Path(p).name != "__pycache__"]
    parts = named[:20]
    if len(named) > 20:
        parts.append(f"{len(named) - 20} more")
    if caches:
        parts.append(f"{len(caches)} __pycache__ folder{'s' if len(caches) != 1 else ''}")
    return ", ".join(parts)


def docker_port_check(config: BuildConfig, verify: dict[str, Any], *, container: bool = False) -> dict | None:
    """For a Docker build, what the smoke run's ports say about the exposed port (see ports.port_check)."""
    if not config.docker_enabled:
        return None
    listeners = {Listener(x["port"], x["address"]) for x in verify.get("listeners") or []}
    return port_check(listeners, config.docker_expose_port, container=container)


async def _wait_watching_ports(proc: asyncio.subprocess.Process, window: float, seen: set[Listener]) -> int:
    """proc.wait() with a timeout of `window`, noting every port the process
    group listens on meanwhile (a service may bind seconds after it starts).
    Raises asyncio.TimeoutError when the window passes, like wait_for."""
    deadline = time.monotonic() + window
    while True:
        seen.update(await asyncio.to_thread(group_listeners, proc.pid))
        left = deadline - time.monotonic()
        if left <= 0:
            raise asyncio.TimeoutError
        try:
            return await asyncio.wait_for(proc.wait(), timeout=min(0.5, left))
        except asyncio.TimeoutError:
            continue


async def _smoke_test(
    task_id: str,
    binary: Path,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run the binary once (see _run_smoke_test), then take away what it wrote in cwd."""
    before = await asyncio.to_thread(_tree_state, cwd)
    try:
        listeners: set[Listener] = set()
        verify = await _run_smoke_test(task_id, binary, cwd, extra_env, listeners)
        verify["listeners"] = [{"port": lst.port, "address": lst.address} for lst in sorted(listeners)]
        if listeners:
            await task_manager.append_log(
                task_id, "Smoke test: the program listened on " + ", ".join(
                    f"{lst.address}:{lst.port}" for lst in sorted(listeners))
            )
        verify["created_dirs"] = await asyncio.to_thread(_created_dirs, cwd, binary.parent, before)
        if verify["created_dirs"]:
            await task_manager.append_log(
                task_id, "Smoke test: the program created " + ", ".join(f"{d}/" for d in verify["created_dirs"])
            )
        return verify
    finally:
        removed, changed = await asyncio.to_thread(_undo_smoke_writes, cwd, before)
        if removed:
            await task_manager.append_log(
                task_id, "Smoke test: removed what the program wrote in the output directory: " + _describe_removed(removed)
            )
        if changed:
            await task_manager.append_log(
                task_id,
                "⚠ Smoke test: the program changed these files in the output, and they ship as changed: "
                + ", ".join(changed),
            )


async def _run_smoke_test(
    task_id: str,
    binary: Path,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
    listeners: set[Listener] | None = None,
) -> dict[str, Any]:
    """Launch the produced binary briefly to catch import/startup crashes.

    Exit 0 within the window → pass. Still running after the window → pass
    (long-running service started fine; it gets terminated). Non-zero exit →
    fail, with the tail of its output as detail.

    ``extra_env`` (Docker ENV or .env, resolved by the caller) is layered on
    top of a small allow-list of host variables so services needing runtime
    config don't get a false failure for a missing variable. See
    _SMOKE_ENV_PASSTHROUGH for why the host environment is not passed whole.
    """
    if not binary.exists():
        return {
            "status": "warn",
            "detail": f"Binary not found for verification: {binary}",
            "exit_code": None,
        }
    try:
        proc = await asyncio.create_subprocess_exec(
            str(binary),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd),
            env=_build_smoke_env(extra_env),
            # Its own process group, so stopping it stops what it started: a
            # onefile binary is a launcher whose child is the real program.
            start_new_session=True,
        )
    except OSError as e:
        return {"status": "fail", "detail": f"Failed to launch binary: {e}", "exit_code": None}

    try:
        ret = await _wait_watching_ports(proc, _SMOKE_WINDOW, listeners if listeners is not None else set())
        output = b""
        if proc.stdout:
            try:
                # Read a generous chunk so a long traceback (the failure reason
                # is usually at the END) is available for pattern matching.
                output = await asyncio.wait_for(proc.stdout.read(262144), timeout=2)
            except asyncio.TimeoutError:
                pass
        full = output.decode("utf-8", errors="replace")
        tail = full.strip()[-500:]
        if ret == 0:
            return {"status": "pass", "detail": "Binary exited cleanly", "exit_code": 0}
        # Environment-only failures: the binary started fine (imports, config,
        # logging all executed) but couldn't finish because of something
        # external — most commonly the service port already being in use by
        # another running instance. That proves the binary itself is healthy,
        # so treat it as a warning, NOT a build failure.
        low = full.lower()
        if (
            "address already in use" in low
            or "errno 98" in low
            or "eaddrinuse" in low
        ):
            return {
                "status": "warn",
                "detail": (
                    "Binary started successfully but the port is already in use "
                    "(likely another instance is still running) — environment "
                    f"issue, not a build problem (exit {ret})"
                ),
                "exit_code": ret,
            }
        # GPU / accelerator init failures: the build host usually has no GPU, so
        # a torch/ROCm/CUDA program can't initialize here even when the binary is
        # fine — same idea as the port case. Treat as a warning and tell the user
        # to verify on the target GPU machine, rather than failing the build.
        if _looks_like_gpu_failure(low):
            return {
                "status": "warn",
                "detail": (
                    "The binary stopped while initialising a GPU/accelerator (torch/ROCm/CUDA), "
                    "and build hosts usually have no GPU — most likely the environment, not the "
                    f"build. Verify it on a target machine with a GPU (exit {ret}): {tail[-200:]}"
                ),
                "exit_code": ret,
            }
        # External-service connection failures: the binary imported cleanly and
        # ran far enough to open a DB/cache/broker connection, then failed because
        # that backing service isn't reachable/authenticated ON THE BUILD HOST —
        # its Postgres/Redis credentials and network differ from the deploy host.
        # Reaching the connect() call proves the app itself is healthy, so this is
        # an environment issue (same class as the port/GPU cases), not a build bug.
        service_hints = (
            "operationalerror", "password authentication failed",
            "connection refused", "could not connect to server",
            "connection to server at", "could not translate host name",
            "no route to host", "econnrefused", "redis.exceptions",
            "connectionerror", "psycopg2", "could not connect",
            "access denied for user", "authentication failed",
            "timeout expired", "server closed the connection",
        )
        if any(h in low for h in service_hints):
            return {
                "status": "warn",
                "detail": (
                    "The binary started and only failed when connecting to an external service "
                    "(database/cache/queue) — the build host's addresses and credentials differ from "
                    "the deployment's, so this is the environment, not the build. Verify it on the "
                    f"target machine, where the services are reachable (exit {ret}): {tail[-200:]}"
                ),
                "exit_code": ret,
            }
        # Missing required CLI arguments: the smoke test runs the binary with no
        # args, but the program legitimately requires some (e.g. --config). argparse
        # prints a usage message and exits 2. That PROVES the binary launched and its
        # arg parser ran — it's a smoke-test invocation gap, not a build defect. The
        # real service is started with the proper flags. Treat as a warning.
        argparse_hints = (
            "the following arguments are required",
            "are required:",
            "is required:",
            "unrecognized arguments",
            "invalid choice",
            "expected one argument",
            "error: argument",
        )
        looks_like_usage = "usage:" in low and "error:" in low
        if looks_like_usage or any(h in low for h in argparse_hints):
            return {
                "status": "warn",
                "detail": (
                    "The binary started and exited because required command-line arguments were "
                    "missing (the smoke test runs it with none) — so the program and its argument "
                    "parsing work; this is how it was called, not the build. Run the real service "
                    f"with its arguments (e.g. --config) (exit {ret}): {tail[-200:]}"
                ),
                "exit_code": ret,
            }
        # Missing license / required runtime resource file: the binary launched
        # and ran its startup (logging configured, etc.) but exited because a
        # license/credential/config FILE that lives on the DEPLOY host isn't
        # present on the build host. Same class as the DB/CLI-arg cases — the app
        # is healthy, the build machine just lacks a deploy-time resource.
        license_hints = (
            "license file not found", "license error", "license not found",
            "invalid license", "license expired", "license_file",
            # "授權檔" ("license file") matches Chinese-language programs' own output.
            "no license", "license.lic", "授權檔", "license required",
        )
        if any(h in low for h in license_hints):
            return {
                "status": "warn",
                "detail": (
                    "The binary started and exited because a license or required resource file "
                    "(e.g. license.lic) was not found — that file is provided on the deployment "
                    "machine (or via LICENSE_FILE), so its absence on the build host is expected, "
                    f"not a build error. Verify it there once the file is in place (exit {ret}): {tail[-200:]}"
                ),
                "exit_code": ret,
            }
        return {
            "status": "fail",
            "detail": f"Binary exited with code {ret}" + (f": {tail}" if tail else ""),
            "exit_code": ret,
        }
    except asyncio.TimeoutError:
        _signal_group(proc.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            _signal_group(proc.pid, signal.SIGKILL)
            await proc.wait()
        return {
            "status": "pass",
            "detail": f"Binary still running after {_SMOKE_WINDOW:g}s (long-running service) — startup OK",
            "exit_code": None,
        }
    finally:
        # Whatever the binary started goes with it. Stopping only the launcher
        # left every service built here running on the build host, holding its
        # port, until someone killed it by hand.
        _signal_group(proc.pid, signal.SIGKILL)


@dataclass
class StdlibSelection:
    """What External mode has to compile in from the standard library."""

    valid_libs: list[str]
    force_packages: set[str]
    # Stdlib modules the packages in libs/ import; None when the scan could not
    # run, in which case every valid module is included rather than too few.
    used: set[str] | None


async def select_stdlib(nuitka_python: str, project_path: Path) -> StdlibSelection:
    """Probe the target Python's stdlib and scan which of it the project's packages use.

    The binary is standalone, so Nuitka already follows and bundles the stdlib the
    MAIN program uses. What it cannot see is the stdlib imported by the third-party
    packages in libs/ (they are --nofollow'd), so scan site-packages and include
    only what those import — a faster compile and a smaller output. If the scan
    cannot run, fall back to the full stdlib so nothing is silently left out.
    """
    # Probed through the TARGET python so the list matches the version being
    # compiled, not the service's.
    valid_libs, force_packages = await get_valid_std_libs_for(nuitka_python)
    site_packages = _find_project_site_packages(project_path)
    used: set[str] | None = None
    if site_packages is not None:
        try:
            used = await asyncio.to_thread(collect_used_stdlib, site_packages, set(valid_libs))
        except Exception:
            logger.warning("stdlib import scan failed; falling back to full stdlib", exc_info=True)
            used = None
    return StdlibSelection(valid_libs, force_packages, used)


@dataclass
class NuitkaPlan:
    cmd: list[str]
    report_file: Path | None
    log: list[str] = field(default_factory=list)


def auto_jobs(cpu_count: int, builds_running: int, floor: int = 4) -> int:
    """C compile jobs for a build that did not set its own.

    One job per core is fastest for a build that has the machine to itself, but
    builds that run together each started one too: three builds on 128 cores ran
    384 compilers, and the extra ones only added switching and memory. Each build
    now gets its share of the cores that are busy building, never below ``floor``
    (or the core count, on a small machine).
    """
    cpu_count = max(1, cpu_count)
    share = cpu_count // max(1, builds_running)
    return max(min(floor, cpu_count), share)


def build_nuitka_command(
    config: BuildConfig,
    *,
    nuitka_python: str,
    project_path: Path,
    output_dir: Path,
    entry_point: Path,
    output_name: str,
    jobs: int,
    debug: bool,
    lazy_packages: list[str],
    stdlib: StdlibSelection | None,
    installed_packages: list[str],
    version_file: Path | None = None,
) -> NuitkaPlan:
    """The Nuitka command line for a build, and the log lines explaining it.

    Pure apart from checking which extra_dirs exist. A mistake here does not
    raise — it produces a binary that compiles and then breaks where it runs —
    which is why it is kept out of run_nuitka_build and tested on its own.
    """
    log: list[str] = []
    cmd = [
        nuitka_python,
        "-u",  # Unbuffered output
        "-m", "nuitka",
        "--standalone",
        f"--output-filename={output_name}",
        f"--output-dir={output_dir}",
        "--remove-output",
        # Never block on an interactive y/n prompt: Nuitka may want to
        # download ccache/gcc/dependency-walker, and we run it on a PTY,
        # so without this the build would hang waiting for stdin.
        "--assume-yes-for-downloads",
    ]
    # --show-scons prints every gcc invocation, flooding the log pipeline
    # on large projects. Only enable it in debug mode.
    if debug:
        cmd.append("--show-scons")

    # Parallel compilation jobs (0 = auto is resolved by the caller to all cores,
    # so the C compile — the slowest phase — actually parallelizes).
    cmd.append(f"--jobs={jobs}")
    log.append(f"Parallel jobs: {jobs}")

    if config.onefile:
        cmd.append("--onefile")

    log.append(f"Pack mode: {config.pack_mode.value}")
    blacklist: list[str] = []

    if config.pack_mode == PackMode.FULL:
        # FULL mode: Let Nuitka bundle everything, no exclusions
        log.append("Full mode: all dependencies will be bundled")
        if lazy_packages:
            log.append(f"Auto-detected lazy-import packages: {', '.join(lazy_packages)}")
        manual_includes = [
            p.strip() for p in config.include_packages.split(",") if p.strip()
        ] if config.include_packages else []
        if manual_includes:
            log.append(f"Manual include packages: {', '.join(manual_includes)}")
        all_includes = sorted(set(lazy_packages + manual_includes))
        for pkg in all_includes:
            cmd.append(f"--include-package={pkg}")
        if all_includes:
            log.append(f"Total force-included packages: {', '.join(all_includes)}")

    elif config.pack_mode == PackMode.EXTERNAL:
        # EXTERNAL mode: the stdlib the packages in libs/ need is compiled in,
        # and every installed third-party package is left to libs/.
        log.append("External mode: third-party from libs/")
        assert stdlib is not None, "External mode needs the stdlib selection"
        stdlib_names = set(stdlib.valid_libs)
        if stdlib.used is not None:
            include_libs = stdlib.used | (_ALWAYS_STDLIB & stdlib_names)
            for lib in sorted(include_libs):
                cmd.append(f"--include-package={lib}" if lib in stdlib.force_packages else f"--include-module={lib}")
            log.append(
                f"Stdlib auto-detect: including {len(include_libs)} standard-library modules "
                f"needed by libs/ (Nuitka handles the ones the program imports itself; "
                f"{len(stdlib.valid_libs)} available)"
            )
        else:
            for lib in stdlib.valid_libs:
                cmd.append(f"--include-package={lib}" if lib in stdlib.force_packages else f"--include-module={lib}")
            log.append(
                f"Could not scan site-packages; including all {len(stdlib.valid_libs)} "
                "standard-library modules to be safe"
            )
        # Read from the PROJECT's .venv, not the service's.
        blacklist = list(installed_packages)
        log.append(f"Found {len(blacklist)} packages in .venv to blacklist")

    # Extra source directories (local packages to include)
    if config.extra_dirs:
        for extra_dir in config.extra_dirs.split(","):
            extra_dir = extra_dir.strip()
            if extra_dir:
                extra_path = project_path / extra_dir
                # Only something importable is followed: a directory is a package and a
                # .py file a module. Any other file is data; following it by name would
                # pass Nuitka a module that cannot exist, and --include-data-dir only
                # takes directories.
                if extra_path.is_dir():
                    cmd.append(f"--follow-import-to={extra_dir}")
                    cmd.append(f"--include-package={extra_dir}")
                    log.append(f"Including package: {extra_dir}")
                    if extra_dir in blacklist:
                        blacklist.remove(extra_dir)
                elif extra_path.is_file() and extra_path.suffix == ".py":
                    module = extra_dir[: -len(".py")].replace("/", ".")
                    cmd.append(f"--follow-import-to={module}")
                    cmd.append(f"--include-module={module}")
                    log.append(f"Including module: {module}")
                    if module in blacklist:
                        blacklist.remove(module)
                elif extra_path.is_file():
                    cmd.append(f"--include-data-files={extra_path}={extra_dir}")
                    log.append(f"Including data file: {extra_dir}")

    # Data directories are copied after compilation (like libs/), not embedded.
    if config.data_dirs:
        log.append(f"Data dirs to copy after build: {config.data_dirs}")

    # nofollow for blacklisted packages, with a .* entry so submodules are
    # excluded too. Only VALID dotted module names: a stray "/" (a file path
    # leaking in from package metadata) makes Nuitka reject the option and exit
    # 1 before compiling.
    skipped = [p for p in blacklist if not _MODULE_NAME_RE.fullmatch(p)]
    if skipped:
        log.append(
            f"Skipped {len(skipped)} invalid module names (not dotted identifiers; left out of nofollow): "
            + ", ".join(sorted(skipped)[:10])
        )
    nofollowed = False
    for pkg in blacklist:
        if not _MODULE_NAME_RE.fullmatch(pkg):
            continue
        cmd.append(f"--nofollow-import-to={pkg}")
        cmd.append(f"--nofollow-import-to={pkg}.*")
        nofollowed = True
    if nofollowed:
        # Nuitka 4 compiles a loader into the program that raises ImportError
        # ("actively excluded from Nuitka compilation") for every module it was
        # told not to follow, and it sits on sys.meta_path ahead of the libs/
        # directory External mode puts on sys.path. Left on, every External
        # build of a project with a dependency compiled and then failed on its
        # first import. libs/ is where those modules are meant to come from.
        cmd.append("--no-deployment-flag=excluded-module-usage")
        log.append("Excluded packages load from libs/ (excluded-module-usage guard off)")

    # Optimization / diagnostics options
    if not config.enable_anti_bloat:
        # anti-bloat is auto-enabled in Nuitka — only the opt-out needs a flag
        cmd.append("--disable-plugins=anti-bloat")
        log.append("anti-bloat plugin disabled by config")

    report_file: Path | None = None
    if config.generate_report:
        report_file = output_dir / "nuitka-report.xml"
        cmd.append(f"--report={report_file}")
        log.append(f"Compilation report: {report_file}")

    if config.include_package_data:
        for pkg in config.include_package_data.split(","):
            pkg = pkg.strip()
            if pkg:
                cmd.append(f"--include-package-data={pkg}")
                log.append(f"Including package data: {pkg}")

    # The version, inside the program: it sits next to the main module at run
    # time (os.path.dirname(__file__)), in one-file and folder builds alike.
    if version_file is not None:
        cmd.append(f"--include-data-files={version_file}=VERSION")
        log.append("Embedding VERSION")

    # Last: everything after the program file belongs to the program, not to Nuitka.
    cmd.append(str(entry_point))
    return NuitkaPlan(cmd, report_file, log)


async def run_nuitka_build(task_id: str, config: BuildConfig, db: AsyncSession) -> bool:
    """Run a local Nuitka build asynchronously.

    Args:
        task_id: Task ID for logging
        config: Build configuration
        db: Database session

    Returns:
        True if build succeeded, False otherwise
    """
    await task_manager.append_log(
        task_id,
        f"Nuitka Build | Output: {config.output_name or Path(config.entry_point).stem} | Python: {config.python_version}",
    )

    guard = SourceGuard(task_id)  # puts the entry point back however the build ends
    entry_point = None
    start_ts = time.monotonic()
    build_result: dict[str, Any] = {"preflight": []}
    preflight = build_result["preflight"]

    # The project lock is held by build_dispatcher for the whole
    # prepare -> build -> restore window, covering docker_worker's file
    # shuffling as well as this worker's in-place entry-point injection. It
    # used to be taken here, which left docker_worker unprotected.
    try:
        await task_manager.set_stage(task_id, "preflight")

        # Verify project path exists
        project_path = Path(config.project_path)
        path_ok = project_path.exists() and project_path.is_dir()
        preflight.append({
            "label": "Project path exists",
            "passed": path_ok,
            "detail": str(project_path),
            "critical": True,
        })
        if not project_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {config.project_path}")
        if not project_path.is_dir():
            raise NotADirectoryError(f"Project path is not a directory: {config.project_path}")

        await task_manager.append_log(task_id, f"Project path: {config.project_path}")

        # Resolve the compile target Python version.
        # The produced binary is ABI-bound to whichever Python runs Nuitka;
        # EXTERNAL mode copies the project's .so files into libs/, so the
        # binary MUST match the project .venv's real ABI. Detect that ABI
        # from the .so tags (the only trustworthy source) — either because
        # the user asked for "auto", or to sanity-check a manual choice.
        detected_version, detect_detail = detect_project_python_version(project_path)
        abi_required = detected_version is not None  # project ships compiled extensions

        requested = (config.python_version or "auto").strip().lower()
        if requested == "auto":
            if detected_version:
                target_version = detected_version
                await task_manager.append_log(
                    task_id,
                    f"Auto-detected Python {detected_version} ({detect_detail})",
                )
            else:
                # No .so to bind to (pure-Python) or a broken/mixed .venv —
                # fall back to this service's Python and note why.
                target_version = f"{sys.version_info.major}.{sys.version_info.minor}"
                await task_manager.append_log(
                    task_id,
                    f"Auto-detect: {detect_detail} — using service Python {target_version}",
                )
        else:
            target_version = requested
            # A manual version that contradicts the project's actual .so ABI is
            # a guaranteed failure (the binary can't load those extensions), so
            # fail preflight NOW instead of wasting a full compile that only
            # dies at the smoke test.
            if detected_version and detected_version != requested:
                preflight.append({
                    "label": "Python version matches dependencies",
                    "passed": False,
                    "detail": f"selected {requested}, dependencies are {detected_version}",
                    "critical": True,
                })
                await task_manager.set_result(task_id, dict(build_result), db)
                raise RuntimeError(
                    f"You chose Python {requested}, but this project's dependencies were built "
                    f"for Python {detected_version} ({detect_detail}). A binary compiled with "
                    f"{requested} cannot load them. Set \"Python version\" to \"Auto-detect\", "
                    f"or choose {detected_version}."
                )

        # Pick the toolchain venv for the resolved version.
        nuitka_python, version_matched = find_nuitka_python(target_version)
        preflight.append({
            "label": f"Python {target_version} toolchain"
            + (" (auto-detected)" if requested == "auto" and detected_version else ""),
            "passed": version_matched,
            # ABI-bound projects MUST compile with the matching interpreter —
            # a mismatch silently produces a binary that crashes on startup,
            # so make it a hard preflight failure instead of a fallback.
            "critical": abi_required,
            "detail": nuitka_python,
        })
        await task_manager.append_log(task_id, f"Nuitka Python: {nuitka_python}")
        if not version_matched:
            venv_name = f".venv-py{target_version.replace('.', '')}"
            if abi_required:
                # Do NOT fall back — that's exactly what produced the
                # 3.13-binary-vs-3.14-.so crash. Fail preflight clearly.
                raise RuntimeError(
                    f"This project needs Python {target_version} (its compiled "
                    f"extensions are {detect_detail}), but Packwright has no usable "
                    f"{venv_name}. Build it with:  bash scripts/setup_nuitka_venvs.sh  "
                    f"(run as the same user that starts the service, not sudo)."
                )
            await task_manager.append_log(
                task_id,
                f"⚠ No dedicated venv for Python {target_version} ({venv_name}) — "
                f"falling back to service Python {sys.version.split()[0]}. This is a "
                "pure-Python project so ABI mismatch is unlikely, but for correctness "
                "run scripts/setup_nuitka_venvs.sh.",
            )

        # Check target project's Python version (for reference/logging)
        target_python = find_target_python(target_version, project_path)
        venv_exists = (project_path / ".venv").exists()
        preflight.append({
            "label": "Project .venv present",
            "passed": venv_exists,
            "detail": target_python or "No .venv found — dependencies won't be bundled/copied",
            "critical": False,
        })
        if target_python:
            await task_manager.append_log(task_id, f"Target project Python: {target_python}")
        else:
            await task_manager.append_log(task_id, "Note: No .venv found in target project")

        # Verify nuitka is available in the selected toolchain
        check_proc = await asyncio.create_subprocess_exec(
            nuitka_python, "-m", "nuitka", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=build_environment(),
        )
        stdout, stderr = await check_proc.communicate()

        nuitka_ok = check_proc.returncode == 0
        nuitka_version = stdout.decode().strip().split('\n')[0] if nuitka_ok else ""
        preflight.append({
            "label": "Nuitka available",
            "passed": nuitka_ok,
            "detail": nuitka_version or "Not installed in the selected toolchain",
            "critical": True,
        })
        if not nuitka_ok:
            raise RuntimeError(
                "Nuitka not installed in the selected Python environment. "
                "Run scripts/setup_nuitka_venvs.sh (per-version venvs) or `uv add nuitka`."
            )
        await task_manager.append_log(task_id, f"Nuitka version: {nuitka_version}")

        # Prepare output directory
        output_dir = project_path / config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        await task_manager.append_log(task_id, f"Output directory: {output_dir}")

        # Build Nuitka command. safe_join: the loader is written into this file,
        # and it is compiled and shipped, so it has to be the project's own (the
        # route checks the name; this also catches a symlink in a Git clone).
        try:
            entry_point = safe_join(project_path, config.entry_point)
        except UnsafePathError as e:
            preflight.append({"label": "Entry point exists", "passed": False, "detail": str(e), "critical": True})
            raise ValueError(f"Entry point refused: {e}") from e
        entry_ok = entry_point.exists()
        preflight.append({
            "label": "Entry point exists",
            "passed": entry_ok,
            "detail": str(entry_point),
            "critical": True,
        })
        if not entry_ok:
            raise FileNotFoundError(f"Entry point not found: {entry_point}")
        if config.onefile:
            compressed = await has_zstandard(nuitka_python)
            preflight.append({
                "label": "Onefile compression",
                "passed": compressed,
                "detail": "zstandard installed" if compressed else (
                    "zstandard is not installed in the selected toolchain, so the binary is stored "
                    "uncompressed. Install nuitka[onefile] (scripts/setup_nuitka_venvs.sh does)."
                ),
                "critical": False,
            })

        # Inject libs loading code into entry point (only for non-FULL modes)
        if config.pack_mode != PackMode.FULL:
            original_content = entry_point.read_text(encoding="utf-8")
            # A crash before this guard existed left the loader in the file and the
            # original in <entry>.py.backup, and later builds skipped both. Undo it.
            legacy_backup = entry_point.with_suffix(".py.backup")
            if "[LIBS LOADER]" in original_content and legacy_backup.is_file():
                await asyncio.to_thread(shutil.move, str(legacy_backup), str(entry_point))
                original_content = entry_point.read_text(encoding="utf-8")
                await task_manager.append_log(
                    task_id, f"Restored {entry_point.name} from a backup left by an interrupted build"
                )

            if "[LIBS LOADER]" not in original_content:
                await task_manager.append_log(task_id, "Injecting libs loader into entry point...")
                guard.write(entry_point, inject_libs_loader(original_content))
            else:
                # The user's own file carries the loader (e.g. committed by mistake).
                await task_manager.append_log(task_id, "Libs loader already present, skipping injection")
        else:
            await task_manager.append_log(task_id, "Full mode: skipping libs loader injection")

        # Derive output name from entry point if not specified
        output_name = config.output_name or Path(config.entry_point).stem
        await task_manager.append_log(task_id, f"Output name: {output_name}")

        if config.nuitka_jobs > 0:
            jobs = config.nuitka_jobs
        else:
            from app.services.build_dispatcher import builds_in_slot

            running = builds_in_slot()
            jobs = auto_jobs(os.cpu_count() or 1, running)
            await task_manager.append_log(
                task_id,
                f"Compiling with {jobs} of {os.cpu_count() or 1} cores "
                f"({running} {'build' if running == 1 else 'builds'} running)",
            )
        external = config.pack_mode == PackMode.EXTERNAL
        # A VERSION file to embed, written outside the project: the source tree is
        # the user's, and SourceGuard restores what it touches.
        version_dir = Path(tempfile.mkdtemp(prefix="packwright-version-")) if config.version else None
        if version_dir is not None:
            (version_dir / "VERSION").write_text(config.version + "\n", encoding="utf-8")
        plan = build_nuitka_command(
            config,
            nuitka_python=nuitka_python,
            project_path=project_path,
            output_dir=output_dir,
            entry_point=entry_point,
            output_name=output_name,
            jobs=jobs,
            debug=settings.debug,
            lazy_packages=detect_lazy_packages(project_path) if config.pack_mode == PackMode.FULL else [],
            stdlib=await select_stdlib(nuitka_python, project_path) if external else None,
            installed_packages=get_installed_packages(project_path / ".venv") if external else [],
            version_file=version_dir / "VERSION" if version_dir is not None else None,
        )
        for line in plan.log:
            await task_manager.append_log(task_id, line)
        nuitka_cmd, report_file = plan.cmd, plan.report_file

        # Publish preflight results before the long compile starts
        await task_manager.set_result(task_id, dict(build_result), db)
        await task_manager.set_stage(task_id, "compile")

        await task_manager.append_log(task_id, "Starting Nuitka compilation...")
        await task_manager.append_log(task_id, f"Command: {' '.join(nuitka_cmd)}")

        # Build environment for Nuitka process
        nuitka_env = compile_cache.build_environment(build_environment(), settings.nuitka_cache_dir)
        nuitka_env["TERM"] = "xterm-256color"
        ccache = compile_cache.ccache_binary(nuitka_env)
        if ccache:
            await task_manager.append_log(
                task_id,
                f"C compile cache: ccache ({ccache}), store in {compile_cache.ccache_dir(nuitka_env)}",
            )

        # For FULL mode, add project's .venv/site-packages to PYTHONPATH
        # so Nuitka can discover and bundle all project dependencies
        if config.pack_mode == PackMode.FULL:
            venv_path = project_path / ".venv"
            if venv_path.exists():
                site_pkgs_dirs = list(venv_path.glob("lib/python*/site-packages"))
                if not site_pkgs_dirs:
                    site_pkgs_dirs = list(venv_path.glob("Lib/site-packages"))
                if site_pkgs_dirs:
                    extra_path = str(site_pkgs_dirs[0])
                    existing = nuitka_env.get("PYTHONPATH", "")
                    nuitka_env["PYTHONPATH"] = f"{extra_path}:{existing}" if existing else extra_path
                    await task_manager.append_log(task_id, f"Added to PYTHONPATH: {extra_path}")

        current_progress = 0.0
        # Nuitka's own ccache summary, read back into the build result.
        cache_lines: list[str] = []

        async def consume(lines: list[str], frame: str | None) -> None:
            nonlocal current_progress
            status_msg = ""
            for text in lines:
                await task_manager.append_log(task_id, text)
                if "Cached C files" in text:
                    cache_lines.append(text)
                current_progress, status_msg = parse_nuitka_progress(text, current_progress, status_msg)
            if frame:  # an in-place progress bar: drives progress, never logged
                current_progress, status_msg = parse_nuitka_progress(frame, current_progress, status_msg)
            if not lines and not frame:
                return
            if status_msg:
                await task_manager.update_task(task_id, "status_msg", status_msg)
            current_progress = max(current_progress, 5.0)
            await task_manager.update_task(
                task_id,
                "progress",
                min(int(current_progress), 99 if current_progress < 100 else 100),
            )

        # On a PTY (Nuitka draws progress only for a TTY), in its own process
        # group: Cancel has to stop scons and every gcc it started, not just
        # the Nuitka process at the top.
        step = await run_step(task_id, nuitka_cmd, cwd=project_path, env=nuitka_env, on_output=consume)
        ret_code = -1 if step.returncode is None else step.returncode
        cache_summary = compile_cache.parse_build_summary(cache_lines)
        if cache_summary is not None:
            build_result["compile_cache"] = cache_summary
        if ret_code == 0:
            await task_manager.append_log(task_id, compile_cache.describe_summary(cache_summary, ccache, nuitka_env))
        if version_dir is not None:
            shutil.rmtree(version_dir, ignore_errors=True)

        # Restore original entry point file
        if guard.active:
            await task_manager.append_log(task_id, "Restoring original entry point...")
            for line in await asyncio.to_thread(guard.restore):
                await task_manager.append_log(task_id, line)

        # Handle completion
        if ret_code == 0:
            # Find the dist folder (Nuitka creates {entry_name}.dist/)
            entry_stem = entry_point.stem  # e.g., "main" from "main.py"
            dist_folder = output_dir / f"{entry_stem}.dist"

            await task_manager.set_stage(task_id, "bundle")
            if config.version:
                # Beside the output too, for whoever unpacks it.
                (output_dir / "VERSION").write_text(config.version + "\n", encoding="utf-8")
                await task_manager.append_log(task_id, f"Wrote VERSION ({config.version})")

            # Skip libs copy for FULL mode (all deps are bundled)
            if config.pack_mode == PackMode.FULL:
                await task_manager.append_log(task_id, "")
                await task_manager.append_log(task_id, "Full mode: skipping libs/ copy (all deps bundled)")
                target_folder = None
            else:
                await task_manager.update_task(task_id, "status_msg", "Copying packages...")
                await task_manager.append_log(task_id, "")
                await task_manager.append_log(task_id, "Copying .venv packages to libs/...")

                # Determine target folder based on onefile mode
                if config.onefile:
                    target_folder = output_dir / "libs"
                    target_folder.mkdir(parents=True, exist_ok=True)
                else:
                    target_folder = dist_folder if dist_folder.exists() else None

            if target_folder:
                # Find .venv site-packages
                venv_path = project_path / ".venv"
                site_packages = None

                if venv_path.exists():
                    # Find site-packages (could be lib/pythonX.X/site-packages or Lib/site-packages on Windows)
                    for pattern in ["lib/python*/site-packages", "Lib/site-packages"]:
                        matches = list(venv_path.glob(pattern))
                        if matches:
                            site_packages = matches[0]
                            break

                if site_packages and site_packages.exists():
                    await task_manager.append_log(task_id, f"Source: {site_packages}")
                    await task_manager.append_log(task_id, f"Target: {target_folder}")

                    # Copy each package (including .dist-info for importlib.metadata)
                    copied_count = 0
                    skipped = []
                    for item in site_packages.iterdir():
                        if not ships_in_libs(item.name):
                            continue

                        target = target_folder / item.name
                        if target.exists():
                            skipped.append(item.name)
                            continue

                        try:
                            # Off-loop copy — site-packages can be gigabytes;
                            # a sync copy here would freeze every request/WS.
                            # _copytree_fast hardlinks + drops pyc/tests.
                            if item.is_dir():
                                await asyncio.to_thread(_copytree_fast, item, target)
                            else:
                                await asyncio.to_thread(shutil.copy2, item, target)
                            copied_count += 1
                        except Exception as e:
                            await task_manager.append_log(task_id, f"Warning: Failed to copy {item.name}: {e}")

                    await task_manager.append_log(task_id, f"Copied {copied_count} packages")
                    if skipped:
                        await task_manager.append_log(task_id, f"Skipped {len(skipped)} existing: {', '.join(skipped[:5])}{'...' if len(skipped) > 5 else ''}")
                else:
                    await task_manager.append_log(task_id, "No .venv/site-packages found, skipping package copy")
            else:
                if not config.pack_mode == PackMode.FULL:
                    await task_manager.append_log(task_id, f"Dist folder not found: {dist_folder}")

            # Copy data directories to output folder (like libs/)
            if config.data_dirs:
                await task_manager.append_log(task_id, "")
                await task_manager.append_log(task_id, "Copying data directories...")
                for data_dir in config.data_dirs.split(","):
                    data_dir = data_dir.strip()
                    if data_dir:
                        # Both joins feed rmtree/copytree: refuse names that
                        # are absolute or climb out of the project.
                        src_path = safe_join(project_path, data_dir)
                        dst_path = safe_join(output_dir, data_dir)
                        if src_path.exists():
                            try:
                                if dst_path.exists():
                                    await asyncio.to_thread(shutil.rmtree, dst_path)
                                await asyncio.to_thread(shutil.copytree, src_path, dst_path)
                                file_count = await asyncio.to_thread(
                                    lambda p=dst_path: sum(1 for f in p.rglob("*") if f.is_file())
                                )
                                await task_manager.append_log(task_id, f"Copied: {data_dir}/ ({file_count} files)")
                            except Exception as e:
                                await task_manager.append_log(task_id, f"Warning: Failed to copy {data_dir}: {e}")
                        else:
                            await task_manager.append_log(task_id, f"Warning: Data dir not found: {src_path}")

            # Artifact summary (path/size/hash) for the detail page
            if config.onefile:
                artifact_path = output_dir / output_name
                binary_path = artifact_path
            else:
                artifact_path = dist_folder if dist_folder.exists() else output_dir
                binary_path = dist_folder / output_name

            if artifact_path.exists():
                build_result["artifact"] = await asyncio.to_thread(
                    _summarize_artifact, artifact_path
                )
                await task_manager.append_log(
                    task_id,
                    f"Artifact: {artifact_path} "
                    f"({build_result['artifact']['size_human']}, "
                    f"{build_result['artifact']['file_count']} files)",
                )

            if report_file and report_file.exists():
                build_result["report_file"] = str(report_file)

            # Post-build smoke test
            if config.verify_after_build:
                await task_manager.set_stage(task_id, "verify")
                await task_manager.update_task(task_id, "status_msg", "Verifying binary...")
                # Runtime env for the test: Docker ENV first, else project .env
                smoke_env, env_source = _resolve_smoke_env(config, project_path)
                await task_manager.append_log(
                    task_id, f"Smoke test env source: {env_source}"
                )
                verify = await _smoke_test(
                    task_id, binary_path, cwd=output_dir, extra_env=smoke_env
                )
                build_result["verify"] = verify
                marker = {"pass": "✓", "warn": "⚠", "fail": "✗"}.get(verify["status"], "•")
                await task_manager.append_log(
                    task_id, f"Verify: {marker} {verify['detail']}"
                )
                checked = docker_port_check(config, verify)
                if checked:
                    build_result["port_check"] = checked
                    if checked["message"]:
                        await task_manager.append_log(task_id, f"⚠ Port: {checked['message']}")
            else:
                build_result["verify"] = {
                    "status": "skipped",
                    "detail": "Verification disabled in config",
                    "exit_code": None,
                }

            build_result["duration_seconds"] = round(time.monotonic() - start_ts, 1)
            await task_manager.set_result(task_id, dict(build_result), db)
            # A failed smoke test leaves the build at "verify", so the failure
            # report names that stage instead of "finishing up".
            failed_verify = build_result["verify"]["status"] == "fail"
            await task_manager.set_stage(task_id, "verify" if failed_verify else "done")

            await task_manager.append_log(task_id, "")
            await task_manager.append_log(task_id, "=" * 50)
            await task_manager.append_log(task_id, "Nuitka build completed successfully!")
            await task_manager.append_log(task_id, f"Output: {dist_folder if dist_folder.exists() else output_dir}")
            await task_manager.append_log(task_id, "=" * 50)

            # A failed smoke test means the artifact is broken — fail the build
            if failed_verify:
                await task_manager.append_log(
                    task_id, "Smoke test failed — marking build as failed"
                )
                return False
            return True

        elif ret_code in (-15, -9):
            await task_manager.append_log(task_id, "Build cancelled by user")
            return False
        else:
            await task_manager.append_log(task_id, f"Build failed with exit code: {ret_code}")
            build_result["duration_seconds"] = round(time.monotonic() - start_ts, 1)
            await task_manager.set_result(task_id, dict(build_result), db)
            return False

    except Exception as e:
        await task_manager.append_log(task_id, f"Error: {e!s}")
        await task_manager.set_process(task_id, None)
        for line in await asyncio.to_thread(guard.restore):
            await task_manager.append_log(task_id, line)
        # Persist whatever preflight/result data we collected before dying
        try:
            build_result["duration_seconds"] = round(time.monotonic() - start_ts, 1)
            await task_manager.set_result(task_id, dict(build_result), db)
        except Exception:
            logger.warning("Failed to persist build result for task %s", task_id, exc_info=True)
        return False

    finally:
        # Every exit — failure, exception, cancellation — puts the entry point back.
        if guard.active:
            for line in guard.restore():
                logger.info("Task %s: %s", task_id, line)
        # No lock release here — build_dispatcher owns the project lock now.


# NOTE: `start_build_task` deliberately does NOT live here.
#
# There used to be a second one, whose docstring called itself "the main entry
# point for background builds" — but the API imports build_dispatcher's. The
# two were not stylistic variants: this one had no semaphore (ignoring
# MAX_CONCURRENT_BUILDS, letting any number of Nuitka compiles saturate the
# CPU), no cancellation checks, no git workspace preparation (so git-mode tasks
# would dispatch with an empty project_path), no failure diagnosis and no
# post-build cleanup.
#
# Two importable functions with the same name and duelling docstrings is a
# coin-flip for autocomplete, and picking the wrong one raises nothing at
# import or call time. Build entry stays in build_dispatcher.

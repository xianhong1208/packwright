"""Git operations for the Git-URL source mode.

SECURITY INVARIANTS (do not violate):
    1. Git tokens are SERVER-ONLY. They are never persisted to DB, returned
       via API, or logged unmasked, and never put in a URL: they reach git as
       an http.<url>.extraHeader through GIT_CONFIG_* environment variables
       (see _git_env), scoped to the repository's host. A token in the clone
       URL used to be written into each workspace's .git/config (kept for
       days, readable by the build's own npm scripts, copied into Docker
       contexts) and was visible in `ps` while git ran.
    2. All subprocess calls use argv-list form with shell=False. No string
       interpolation into a shell.
    3. All external URLs are validated via validate_git_url() before ANY
       network operation. SSRF vectors (file://, ssh://, git://, localhost,
       link-local, userinfo in URL, '..' in path) are rejected.
    4. Long-running operations (ls-remote, clone) are wrapped in
       asyncio.wait_for() with timeouts; timed-out processes are killed.
    5. git never reads the host's configuration or credentials: no system or
       global config, no credential helper, an empty HOME (so no ~/.netrc
       either). The service account's git login (e.g. `gh auth git-credential`
       in ~/.gitconfig) used to answer for any URL a user typed, so anyone
       allowed to build could clone whatever that login could reach. Only
       Packwright's own stored credentials, scoped by host, are ever sent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import base64
import ipaddress
import logging
import os
import re
import shutil
import socket
import tempfile
import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

# Alias the argv-list subprocess spawner used by the rest of the codebase
# (see app/services/nuitka_worker.py). Using an alias keeps call sites short
# and avoids ambiguity with shell-based launchers.
_spawn = asyncio.create_subprocess_exec

logger = logging.getLogger(__name__)


# ---------- URL validation ----------

_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTNAMES = {"localhost", "ip6-localhost", "ip6-loopback"}


class GitUrlError(ValueError):
    """Raised when a provided Git URL fails validation."""


def _scratch_root() -> Path:
    """Where scan/preview clones go: under git_workspace_dir, not the system /tmp.

    /tmp is often a small tmpfs, and a big repository cloned there for a preview
    could fill it for the whole machine. A clone left behind by a crash is
    swept as an orphan by workspace_cleanup.
    """
    from app.config import get_settings

    root = Path(get_settings().git_workspace_dir) / ".scratch"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _current_allowed_hosts() -> list[str]:
    """Fetch the current GIT_ALLOWED_HOSTS from settings.

    Used by the async git operations below so that even direct internal
    callers (not via the HTTP route) get the same allowlist enforcement
    as the route handlers. Import locally to avoid a top-level cycle.
    """
    from app.config import get_settings
    return get_settings().allowed_git_hosts


def validate_git_url(url: str, allowed_hosts: list[str] | None = None) -> None:
    """Validate a Git HTTP(S) URL for use with our cloning pipeline.

    Raises GitUrlError with a human-readable message on failure.
    Returns None on success.

    Always rejects:
    - Non-http/https schemes (file, ssh, git, etc.)
    - URLs that already embed userinfo (we inject our own token)
    - localhost / ip6-localhost (even if explicitly allowlisted)
    - Path components containing '..'

    Allowlist semantics:
    - If ``allowed_hosts`` is a non-empty list, the URL's host MUST be in
      it (IP literals or hostnames). Membership here also acts as an
      explicit opt-in to IPs that would otherwise be blocked by SSRF
      defences below (e.g. private-range internal GitLab instances).
    - If ``allowed_hosts`` is None/empty, strict SSRF heuristics apply:
      IP literals pointing at loopback / link-local / private ranges /
      multicast / reserved / unspecified are rejected.
    """
    if not url or not isinstance(url, str):
        raise GitUrlError("Git URL is required")

    url = url.strip()
    if len(url) > 2048:
        raise GitUrlError("Git URL is too long")

    try:
        parsed = urlparse(url)
    except ValueError as e:
        raise GitUrlError(f"Git URL is malformed: {e}") from e

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise GitUrlError(
            f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are allowed."
        )

    if parsed.username or parsed.password:
        # We inject our own token. A user-supplied credential in the URL is
        # almost always a mistake or an attempt to bypass policy.
        raise GitUrlError(
            "Git URL must not contain embedded credentials (username/password). "
            "The server injects its own token automatically."
        )

    # A trailing dot is the same name to the resolver ("localhost." is localhost).
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise GitUrlError("Git URL is missing a host component")

    if ".." in (parsed.path or ""):
        raise GitUrlError("Git URL path must not contain '..'")

    # Always-blocked hostnames — no allowlist override. Every *.localhost name
    # resolves to loopback (RFC 6761), so the whole zone is blocked.
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise GitUrlError(f"Git URL host '{host}' is not allowed")

    # Allowlist semantics: explicit membership grants trust and short-circuits
    # the SSRF heuristics below. This lets operators opt into internal
    # GitLab instances that live on private RFC-1918 addresses.
    if allowed_hosts:
        if host not in allowed_hosts:
            raise GitUrlError(
                f"Git URL host '{host}' is not in the allowlist. "
                f"Permitted hosts: {', '.join(allowed_hosts)}"
            )
        return  # trusted — skip IP range checks

    # No allowlist configured — apply strict SSRF defence for IP literals.
    # Hostnames are NOT resolved here (DNS-based SSRF isn't handled);
    # operators who need stricter control should populate GIT_ALLOWED_HOSTS.
    ip = _numeric_host_ip(host)
    if ip is not None and (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
    ):
        raise GitUrlError(
            f"Git URL host '{host}' is not a routable public address. "
            "If this is an intentional internal target, add it to GIT_ALLOWED_HOSTS."
        )


def _numeric_host_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address a numeric host denotes, in any spelling git/libcurl accept.

    ipaddress.ip_address() only knows dotted-quad, so 127.1, 2130706433 and
    0x7f000001 (all loopback to the resolver) passed as "not an IP literal".
    IPv4-mapped IPv6 (::ffff:127.0.0.1) is unwrapped to its IPv4 address.
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
        if re.fullmatch(r"[0-9a-fx.]+", host) and not host.endswith("."):
            try:
                ip = ipaddress.IPv4Address(socket.inet_aton(host))
            except OSError:
                ip = None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


# ---------- Ref name validation ----------

# A branch/tag name used as a positional arg to `git clone --branch ...`.
# Defense in depth: even though we pass it via argv (not shell), reject
# values that could be mistaken for an option, contain whitespace, or
# escape a directory.
_REF_BAD_CHARS = re.compile(r"[\s\x00-\x1f~^:?*\[\\]")


def validate_git_ref(ref: str) -> None:
    """Raise GitUrlError if `ref` is unsafe to pass to git.

    Rules:
    - Must be 1..255 chars
    - Must not start with '-' (would be interpreted as a git option)
    - Must not contain whitespace, control chars, or git-forbidden chars
    - Must not contain '..'
    """
    if not ref or not isinstance(ref, str):
        raise GitUrlError("Git ref (branch or tag) is required")
    if len(ref) > 255:
        raise GitUrlError("Git ref is too long")
    if ref.startswith("-"):
        raise GitUrlError("Git ref must not start with '-'")
    if ".." in ref:
        raise GitUrlError("Git ref must not contain '..'")
    if _REF_BAD_CHARS.search(ref):
        raise GitUrlError("Git ref contains forbidden characters")


# ---------- Token injection & masking ----------

# Username portion of the injected userinfo, per provider. GitHub authenticates a
# token as "x-access-token"; GitLab (and self-hosted) use "oauth2". Both accept a
# Personal Access Token as the password.
_PROVIDER_USERINFO_USER = {"github": "x-access-token", "gitlab": "oauth2", "generic": "oauth2"}


def _auth_config(url: str, token: str | None, provider: str = "gitlab") -> list[tuple[str, str]]:
    """The config entry that makes git send the token to this repository's host only.

    Equivalent to ``git -c http.<origin>/.extraHeader="Authorization: Basic ..."``
    but passed through GIT_CONFIG_COUNT/KEY/VALUE (git >= 2.31, see _git_env),
    so the secret is in neither argv nor any config file. The URL-scoped key
    means a redirect to another host does not receive it. The username depends
    on the provider (GitHub -> x-access-token, GitLab -> oauth2).
    """
    if not token:
        return []
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")
    user = _PROVIDER_USERINFO_USER.get(provider, "oauth2")
    basic = base64.b64encode(f"{user}:{token}".encode()).decode()
    return [(f"http.{origin}/.extraHeader", f"Authorization: Basic {basic}")]


def _auth_env(url: str, token: str | None, provider: str = "gitlab") -> dict[str, str]:
    """_auth_config as GIT_CONFIG_* variables (empty without a token)."""
    return _config_env(_auth_config(url, token, provider))


def _config_env(entries: list[tuple[str, str]]) -> dict[str, str]:
    if not entries:
        return {}
    env = {"GIT_CONFIG_COUNT": str(len(entries))}
    for i, (key, value) in enumerate(entries):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    return env


_OAUTH_PATTERN = re.compile(r"((?:oauth2|x-access-token):)[^@\s/]+(@)")


def mask_token_in_log(text: str, token: str | None = None) -> str:
    """Return `text` with any occurrence of the token or an oauth2 userinfo
    triple replaced by '***'. Safe to call on subprocess stderr/stdout
    before passing it to logs, notifications, or error messages.
    """
    if not text:
        return text
    masked = text
    if token:
        masked = masked.replace(token, "***")
    masked = _OAUTH_PATTERN.sub(r"\1***\2", masked)
    return masked


# ---------- Subprocess environment ----------

# The host's git configuration is not read (SECURITY INVARIANT 5), so a proxy or a
# private CA reaches git only through these, as it does for builds (build_env.py).
_GIT_ENV_PASSTHROUGH = (
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    "GIT_SSL_CAINFO", "GIT_SSL_CAPATH", "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE",
)

_empty_home: Path | None = None


def _git_home() -> str:
    """An empty directory for git's HOME, made once per process.

    Not the service's HOME: git reads ~/.gitconfig and ~/.config/git/config
    from there, and libcurl reads ~/.netrc, any of which can hold the host's
    own credentials.
    """
    global _empty_home
    if _empty_home is None or not _empty_home.is_dir():
        _empty_home = Path(tempfile.mkdtemp(prefix="packwright-git-home-"))
    return str(_empty_home)


def _git_env(url: str | None = None, token: str | None = None, provider: str = "gitlab") -> dict[str, str]:
    """Minimal environment for git subprocesses, plus the credential if any.

    No system or global config and an empty HOME, and an empty credential.helper
    on top (it resets the helper list), so git never asks the host's credential
    helpers: they answered for any URL with the service account's own login, and
    were told to "erase" it when a request failed. Only the stored credential for
    this URL's host is sent (_auth_config).

    GIT_TERMINAL_PROMPT=0 and GIT_ASKPASS=/bin/true ensure that git NEVER
    blocks on an interactive credential prompt — bad tokens fail fast
    instead of hanging the request. Every git call of one operation must get
    the credential: a --filter=blob:none clone fetches blobs lazily on a later
    `git show`.
    """
    env = {name: os.environ[name] for name in _GIT_ENV_PASSTHROUGH if name in os.environ}
    return env | _config_env([("credential.helper", ""), *_auth_config(url or "", token, provider)]) | {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": _git_home(),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/true",
    }


# What git prints when the server refused the credential it was sent.
_REJECTED_CREDENTIAL = re.compile(
    r"Authentication failed|returned error: 40[13]|HTTP Basic: Access denied|Invalid username or password",
    re.IGNORECASE,
)


async def _run_git(cmd: list[str], env: dict[str, str], timeout: float, what: str,
                   cwd: str | None = None) -> tuple[int, bytes, bytes]:
    """Run one git command; (returncode, stdout, stderr). Kills it on timeout."""
    try:
        proc = await _spawn(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env, cwd=cwd)
    except FileNotFoundError as e:
        raise GitUrlError("git binary not found on server") from e
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise GitUrlError(f"{what} timed out after {timeout:.0f}s")
    return proc.returncode, stdout, stderr


async def _fetch_with_fallback(
    cmd: list[str], url: str, token: str | None, provider: str, timeout: float, what: str,
    before_retry: Callable[[], None] | None = None,
) -> tuple[int, bytes, bytes, str | None]:
    """Run a command that talks to the remote; retry once without the stored token
    if the server refused it. Returns the result and the token that worked (None
    when anonymous), so the later commands of one operation send the same.

    A stale or revoked stored credential used to make every repository on its
    host fail, public ones included. A public repository now still clones; a
    private one fails with the original error, which names the refused login.
    """
    rc, out, err = await _run_git(cmd, _git_env(url, token, provider), timeout, what)
    if rc == 0 or not token or not _REJECTED_CREDENTIAL.search(err.decode("utf-8", "replace")):
        return rc, out, err, token
    if before_retry is not None:
        before_retry()
    rc2, out2, err2 = await _run_git(cmd, _git_env(url, None, provider), timeout, what)
    if rc2 != 0:
        return rc, out, err, token
    logger.warning("The stored Git credential for %s was refused; used anonymous access",
                   urlparse(url).hostname)
    return rc2, out2, err2, None


# ---------- list_refs ----------

async def list_refs(
    url: str,
    token: str | None,
    *,
    provider: str = "gitlab",
    timeout: float = 30.0,
) -> dict[str, list[str]]:
    """Return {"branches": [...], "tags": [...]} for a remote.

    Uses `git ls-remote --heads --tags <url>` — no clone, no working tree.
    Output is de-duplicated and sorted; annotated-tag '^{}' peelings are
    collapsed to the tag name. All errors are masked before re-raising.
    """
    validate_git_url(url, _current_allowed_hosts())
    injected = url  # credentials travel in the environment, see _git_env

    cmd = ["git", "ls-remote", "--heads", "--tags", injected]
    returncode, stdout_bytes, stderr_bytes, _ = await _fetch_with_fallback(
        cmd, url, token, provider, timeout, "git ls-remote")

    if returncode != 0:
        stderr = mask_token_in_log(stderr_bytes.decode("utf-8", "replace"), token)
        raise GitUrlError(f"git ls-remote failed: {stderr.strip() or 'unknown error'}")

    stdout = stdout_bytes.decode("utf-8", "replace")

    branches: set[str] = set()
    tags: set[str] = set()
    for line in stdout.splitlines():
        # Format: "<sha>\trefs/heads/<name>" or "refs/tags/<name>" or "refs/tags/<name>^{}"
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        ref = parts[1]
        if ref.startswith("refs/heads/"):
            branches.add(ref[len("refs/heads/"):])
        elif ref.startswith("refs/tags/"):
            name = ref[len("refs/tags/"):]
            if name.endswith("^{}"):
                name = name[:-3]
            tags.add(name)

    return {
        "branches": sorted(branches),
        "tags": sorted(tags),
    }


# ---------- clone_repo ----------

async def clone_repo(
    url: str,
    ref: str,
    ref_type: Literal["branch", "tag"],
    target_dir: Path,
    token: str | None,
    *,
    provider: str = "gitlab",
    timeout: float = 600.0,
) -> bool:
    """Clone `url` @ `ref` into `target_dir` (which must not yet exist).

    Uses `--depth 1 --single-branch --branch <ref>` for speed.
    On any error, partial state at target_dir is removed and a masked
    exception is raised. Returns True when the stored credential was refused
    and the clone succeeded without it (see _fetch_with_fallback).
    """
    validate_git_url(url, _current_allowed_hosts())
    validate_git_ref(ref)
    if ref_type not in ("branch", "tag"):
        raise GitUrlError(f"Invalid ref_type '{ref_type}'")

    target_dir = Path(target_dir)
    if target_dir.exists():
        raise GitUrlError(f"Clone target already exists: {target_dir}")

    target_dir.parent.mkdir(parents=True, exist_ok=True)

    injected = url  # credentials travel in the environment, see _git_env
    cmd = [
        "git",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        ref,
        injected,
        str(target_dir),
    ]

    try:
        returncode, _, stderr_bytes, used = await _fetch_with_fallback(
            cmd, url, token, provider, timeout, "git clone", before_retry=lambda: _safe_rmtree(target_dir))
    except GitUrlError:
        _safe_rmtree(target_dir)
        raise

    if returncode != 0:
        stderr = mask_token_in_log(stderr_bytes.decode("utf-8", "replace"), token)
        _safe_rmtree(target_dir)
        raise GitUrlError(f"git clone failed: {stderr.strip() or 'unknown error'}")
    return bool(token) and used is None


def _safe_rmtree(path: Path) -> None:
    """Best-effort recursive delete; swallows errors so cleanup never masks
    the original exception."""
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


# ---------- pyproject dependency-groups ----------


def parse_dependency_groups(toml_text: str) -> list[str]:
    """Return the sorted PEP 735 dependency-group names from pyproject text.

    Reads the ``[dependency-groups]`` table (NOT ``[project.optional-dependencies]``).
    Returns an empty list when the table is absent or the TOML can't be parsed,
    so callers can treat "no groups" and "unreadable" identically — the picker
    just shows nothing to select.
    """
    try:
        data = tomllib.loads(toml_text)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    groups = data.get("dependency-groups")
    if not isinstance(groups, dict):
        return []
    return sorted(groups.keys())


# ---------- scan_tree ----------

# Directories to hide from the scan result — mirrors the exclusion list used
# by the existing /api/directories endpoint so local-mode and git-mode give
# users the same menu of choices.
_SCAN_EXCLUDED_DIRS = {
    "__pycache__", ".git", ".svn", ".hg",
    "node_modules", ".venv", "venv", "env",
    ".idea", ".vscode", ".mypy_cache", ".pytest_cache", ".tox",
    "dist", "build",
}


async def scan_tree(
    url: str,
    ref: str,
    ref_type: Literal["branch", "tag"],
    token: str | None,
    *,
    provider: str = "gitlab",
    timeout: float = 30.0,
) -> dict:
    """Return top-level directory names + pyproject dependency-groups for ``url @ ref``.

    Returns ``{"directories": [...], "dependency_groups": [...]}``.

    Implementation is a "treeless" partial clone + no-checkout:
      git clone --depth 1 --filter=blob:none --no-checkout
                --single-branch --branch <ref> <url> <tmp>
      git -C <tmp> ls-tree -d --name-only HEAD

    The clone fetches only commit + tree objects — no blobs, no working tree —
    so listing dirs is fast (<1 s) and cheap. Reading the root pyproject.toml
    uses ``git show HEAD:pyproject.toml``, which lazily fetches just that one
    blob from the promisor remote (missing file → no groups, not an error).
    The temporary clone is removed unconditionally before returning.
    """
    validate_git_url(url, _current_allowed_hosts())
    validate_git_ref(ref)
    if ref_type not in ("branch", "tag"):
        raise GitUrlError(f"Invalid ref_type '{ref_type}'")

    # Dedicated per-call temp dir — never collides with concurrent scans.
    tmp_root = Path(tempfile.mkdtemp(prefix="pw_scan_", dir=_scratch_root()))
    target = tmp_root / "repo"
    try:
        injected = url  # credentials travel in the environment, see _git_env
        clone_cmd = [
            "git",
            "clone",
            "--depth", "1",
            "--filter=blob:none",
            "--no-checkout",
            "--single-branch",
            "--branch", ref,
            injected,
            str(target),
        ]
        returncode, _, stderr_bytes, used = await _fetch_with_fallback(
            clone_cmd, url, token, provider, timeout, "git scan-tree clone",
            before_retry=lambda: _safe_rmtree(target))
        if returncode != 0:
            stderr = mask_token_in_log(stderr_bytes.decode("utf-8", "replace"), token)
            raise GitUrlError(
                f"git scan-tree clone failed: {stderr.strip() or 'unknown error'}"
            )
        token = used  # the blobs fetched lazily below need what the clone used

        # List top-level dirs via ls-tree (reads tree objects only, does not
        # trigger lazy blob fetch).
        ls_cmd = ["git", "ls-tree", "-d", "--name-only", "HEAD"]
        proc2 = await _spawn(
            *ls_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_git_env(url, token, provider),
            cwd=str(target),
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc2.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc2.kill()
            await proc2.wait()
            raise GitUrlError(f"git ls-tree timed out after {timeout:.0f}s")

        if proc2.returncode != 0:
            stderr = mask_token_in_log(stderr_bytes.decode("utf-8", "replace"), token)
            raise GitUrlError(
                f"git ls-tree failed: {stderr.strip() or 'unknown error'}"
            )

        names: list[str] = []
        for raw in stdout_bytes.decode("utf-8", "replace").splitlines():
            name = raw.strip()
            if not name:
                continue
            # Exclude hidden dirs and known junk, matching list_directories
            if name.startswith(".") and name != ".streamlit":
                continue
            if name.lower() in _SCAN_EXCLUDED_DIRS or name.endswith(".egg-info"):
                continue
            names.append(name)

        # Read root pyproject.toml (lazy single-blob fetch) for PEP 735 groups.
        # Any failure — file absent, fetch error, parse error — degrades to an
        # empty group list rather than failing the whole scan.
        dependency_groups: list[str] = []
        pyproject_text: str | None = None
        show_cmd = ["git", "show", "HEAD:pyproject.toml"]
        try:
            proc3 = await _spawn(
                *show_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_git_env(url, token, provider),
                cwd=str(target),
            )
            pyproject_bytes, _ = await asyncio.wait_for(
                proc3.communicate(), timeout=timeout
            )
            if proc3.returncode == 0:
                pyproject_text = pyproject_bytes.decode("utf-8", "replace")
                dependency_groups = parse_dependency_groups(pyproject_text)
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            dependency_groups = []

        # Classify subdirectories (source/data/skip) from the full file list —
        # git mode's equivalent of local analyze_project_layout. ls-tree -r
        # reads tree objects only (no blob fetch), so contents aren't available
        # and there's no import analysis; best-effort, never fails the scan.
        analysis: dict = {
            "directories": [],
            "entry_imports": [],
            "suggested_extra_dirs": [],
            "suggested_data_dirs": [],
        }
        checks: list[dict] = []
        try:
            lsr_cmd = ["git", "ls-tree", "-r", "--name-only", "HEAD"]
            proc4 = await _spawn(
                *lsr_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_git_env(url, token, provider),
                cwd=str(target),
            )
            lsr_bytes, _ = await asyncio.wait_for(proc4.communicate(), timeout=timeout)
            if proc4.returncode == 0:
                from app.services.project_analysis import classify_from_paths

                paths = lsr_bytes.decode("utf-8", "replace").splitlines()
                analysis = classify_from_paths(paths)
                checks = check_repo_paths(path_lookup(paths))
        except Exception:
            pass

        # The version: the tag itself, pyproject.toml (read above), or package.json,
        # which is only fetched when neither of the others says.
        from app.services.project_version import detect_version

        version = detect_version(pyproject_text, None, ref, ref_type)
        package_json = next((c["path"] for c in checks if c["key"] == "package_json" and c["status"] == "ok"), None)
        if version is None and package_json:
            try:
                proc5 = await _spawn(
                    "git", "show", f"HEAD:{package_json}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=_git_env(url, token, provider),
                    cwd=str(target),
                )
                pkg_bytes, _ = await asyncio.wait_for(proc5.communicate(), timeout=timeout)
                if proc5.returncode == 0:
                    version = detect_version(None, pkg_bytes.decode("utf-8", "replace"))
            except (asyncio.TimeoutError, FileNotFoundError, OSError):
                pass

        return {
            "directories": sorted(names),
            "analysis": analysis,
            "dependency_groups": dependency_groups,
            "version": version,
            # The same fingerprints a local path gets from /git/diagnose, so
            # New build can tell a backend from a frontend from a full stack.
            "checks": checks,
        }
    finally:
        _safe_rmtree(tmp_root)


# ---------- preview_frontend ----------

# Matches the /api/list-env-files + /api/env-file behavior in routes/tasks.py.
_ENV_FILENAME_RE = re.compile(r"^\.env(\.\w+)*$")


def _repo_file(path: Path, root: Path | None) -> bool:
    """True for a regular file that really lives inside the cloned repo.

    A repository can commit a symlink (``.env -> /opt/packwright/.env``) and the
    preview would read and return whatever it points at: the service's own .env
    holds JWT_SECRET_KEY, i.e. admin tokens on demand. Symlinks are refused
    outright, and the resolved path must stay under ``root``.
    """
    if path.is_symlink() or not path.is_file():
        return False
    return root is None or path.resolve().is_relative_to(root.resolve())


def _detect_frontend_config(fe_path: Path, root: Path | None = None) -> dict:
    """Read package.json + vite.config to infer build tool, build command,
    and outDir. Ported from /api/detect-frontend-config in routes/tasks.py
    so that git-mode preview gives the same shape of result as local mode.
    """
    import json as _json

    result: dict = {
        "detected": False,
        "build_tool": None,
        "build_command": None,
        "output_dir": None,
        "scripts": [],
        "has_vite_config": False,
    }

    # 1. vite.config.*
    for cfg_name in ("vite.config.ts", "vite.config.js", "vite.config.mts", "vite.config.mjs"):
        cfg_file = fe_path / cfg_name
        if _repo_file(cfg_file, root):
            result["has_vite_config"] = True
            try:
                content = cfg_file.read_text(encoding="utf-8")
                match = re.search(r"""outDir\s*:\s*['"](.+?)['"]""", content)
                if match:
                    result["output_dir"] = match.group(1)
            except Exception:
                pass
            break

    # 2. package.json
    pkg_json = fe_path / "package.json"
    if _repo_file(pkg_json, root):
        try:
            pkg = _json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            result["scripts"] = list(scripts.keys())
            for cmd in ("build", "build:prod", "build:production"):
                if cmd in scripts:
                    result["build_command"] = cmd
                    break
            pm_field = pkg.get("packageManager", "")
            if pm_field:
                pm_name = pm_field.split("@")[0].strip().lower()
                if pm_name in ("npm", "yarn", "pnpm", "bun"):
                    result["build_tool"] = pm_name
        except Exception:
            pass

    # 3. Lockfile fallback
    if not result["build_tool"]:
        lock_map = {
            "bun.lockb": "bun",
            "bun.lock": "bun",
            "pnpm-lock.yaml": "pnpm",
            "yarn.lock": "yarn",
            "package-lock.json": "npm",
        }
        for lock_file, tool in lock_map.items():
            if (fe_path / lock_file).exists():
                result["build_tool"] = tool
                break

    result["detected"] = bool(
        result["has_vite_config"] or result["build_tool"] or result["build_command"]
    )
    return result


def _read_env_files(fe_path: Path, max_size: int = 100_000, root: Path | None = None) -> dict[str, str]:
    """Return a mapping of `.env*` filename -> content (UTF-8).

    Files larger than ``max_size`` bytes are skipped silently — env files are
    tiny by convention and a huge one usually means the filename pattern got
    lucky on something else (bug, committed data, etc.).
    """
    result: dict[str, str] = {}
    try:
        for item in sorted(fe_path.iterdir()):
            if not _repo_file(item, root):
                continue
            if not _ENV_FILENAME_RE.match(item.name):
                continue
            try:
                if item.stat().st_size > max_size:
                    continue
                result[item.name] = item.read_text(encoding="utf-8")
            except Exception:
                continue
    except Exception:
        pass
    return result


async def preview_frontend(
    url: str,
    ref: str,
    ref_type: Literal["branch", "tag"],
    token: str | None,
    frontend_dir: str = ".",
    *,
    provider: str = "gitlab",
    timeout: float = 120.0,
    max_env_file_size: int = 100_000,
) -> dict:
    """Shallow-clone a repo to temp and return everything the CreateTask
    form needs to populate the Frontend Settings card in git mode:

    Returns:
        {
            "frontend_config": { detected, build_tool, build_command,
                                 output_dir, scripts, has_vite_config },
            "env_files":       { ".env.example": "content...", ... },
            "frontend_dir_exists": bool,
        }

    Unlike ``scan_tree``, this function DOES download blobs — we need to
    read ``package.json`` / ``vite.config.*`` / ``.env*`` file contents.
    """
    validate_git_url(url, _current_allowed_hosts())
    validate_git_ref(ref)
    if ref_type not in ("branch", "tag"):
        raise GitUrlError(f"Invalid ref_type '{ref_type}'")

    # Defence in depth: frontend_dir is used as a relative path below.
    if ".." in frontend_dir or frontend_dir.startswith("/"):
        raise GitUrlError("frontend_dir must be a relative path without '..'")

    tmp_root = Path(tempfile.mkdtemp(prefix="pw_preview_fe_", dir=_scratch_root()))
    target = tmp_root / "repo"
    try:
        injected = url  # credentials travel in the environment, see _git_env
        clone_cmd = [
            "git",
            "clone",
            "--depth", "1",
            "--single-branch",
            "--branch", ref,
            injected,
            str(target),
        ]
        returncode, _, stderr_bytes, _ = await _fetch_with_fallback(
            clone_cmd, url, token, provider, timeout, "preview-frontend clone",
            before_retry=lambda: _safe_rmtree(target))
        if returncode != 0:
            stderr = mask_token_in_log(stderr_bytes.decode("utf-8", "replace"), token)
            raise GitUrlError(
                f"preview-frontend clone failed: {stderr.strip() or 'unknown error'}"
            )

        # Resolve frontend dir within the clone, reject anything that escapes.
        target_resolved = target.resolve()
        fe_path = (target / frontend_dir).resolve()
        try:
            fe_path.relative_to(target_resolved)
        except ValueError:
            raise GitUrlError(
                f"frontend_dir '{frontend_dir}' escapes the cloned repo root"
            )

        if not fe_path.is_dir():
            return {
                "frontend_config": {
                    "detected": False,
                    "build_tool": None,
                    "build_command": None,
                    "output_dir": None,
                    "scripts": [],
                    "has_vite_config": False,
                },
                "env_files": {},
                "frontend_dir_exists": False,
            }

        return {
            "frontend_config": _detect_frontend_config(fe_path, root=target_resolved),
            "env_files": _read_env_files(fe_path, max_size=max_env_file_size, root=target_resolved),
            "frontend_dir_exists": True,
        }
    finally:
        _safe_rmtree(tmp_root)


# ---------- diagnose_repo ----------
#
# TODO(user): This is one of the places where your domain knowledge matters
# most. The REPO_CHECKS below are a starting set — please extend them with
# the structural fingerprints YOUR projects actually rely on. Things to
# consider:
#   - Is there a convention in your team (e.g. always `uv.lock`, always
#     `Makefile`, always a specific env file layout)?
#   - Should "missing .venv" be a red flag or just a hint? Nuitka pipelines
#     here expect .venv — arguably it should be status="missing" not "warn".
#   - Do you want a check that detects monorepos (multiple frontend/ dirs)?
#   - Do you want a check for "has a README" to help humans sanity-check the
#     clone worked?
# The label strings are displayed verbatim as <Tag> chips in the frontend;
# keep them in Traditional Chinese and short.

REPO_CHECKS: list[dict] = [
    # {
    #     "key": str — stable identifier (e.g. "venv")
    #     "label_ok": str — Traditional Chinese label when the check finds the target
    #     "label_missing": str — Traditional Chinese label when it doesn't
    #     "status_when_missing": "warn" | "missing" — is it bad, or just a hint?
    #     "paths": list[str] — relative paths to look for. First match wins.
    # },
    {
        "key": "venv",
        "label_ok": ".venv found",
        "label_missing": "No .venv (a Nuitka build may need one first)",
        "status_when_missing": "warn",
        "paths": [".venv"],
    },
    {
        "key": "pyproject",
        "label_ok": "pyproject.toml found",
        "label_missing": "No pyproject.toml",
        "status_when_missing": "warn",
        "paths": ["pyproject.toml"],
    },
    {
        "key": "entry_point",
        "label_ok": "Python entry point found",
        "label_missing": "No common Python entry point found",
        "status_when_missing": "warn",
        "paths": ["main.py", "app/main.py", "src/main.py", "run.py"],
    },
    {
        "key": "package_json",
        "label_ok": "package.json found",
        "label_missing": "No package.json (fine for a backend-only project)",
        "status_when_missing": "warn",
        "paths": ["package.json", "frontend/package.json"],
    },
    {
        "key": "dockerfile",
        "label_ok": "Dockerfile found",
        "label_missing": "No Dockerfile (fine without Docker output)",
        "status_when_missing": "warn",
        "paths": ["Dockerfile"],
    },
]


def check_repo_paths(exists: Callable[[str], bool]) -> list[dict]:
    """Run REPO_CHECKS against a project, given a way to ask whether a relative
    path exists in it.

    One definition for both sources: a local project answers from the file
    system, a Git repository from its ``ls-tree`` file list, so New build infers
    the same project type whichever way the code arrives.
    """
    results: list[dict] = []
    for check in REPO_CHECKS:
        hit_path = next((c for c in check["paths"] if exists(c)), None)
        if hit_path is not None:
            results.append({"key": check["key"], "label": check["label_ok"], "status": "ok", "path": hit_path})
        else:
            results.append({
                "key": check["key"],
                "label": check["label_missing"],
                "status": check["status_when_missing"],
                "path": None,
            })
    return results


def path_lookup(paths: list[str]) -> Callable[[str], bool]:
    """``exists`` for check_repo_paths over a repository file list, in which a
    directory exists when any file lies under it."""
    files = set(paths)
    dirs = {p.rsplit("/", i)[0] for p in paths for i in range(1, p.count("/") + 1)}
    return lambda rel: rel in files or rel in dirs


def diagnose_repo(path: Path) -> dict:
    """Scan `path` for structural fingerprints and return status chips.

    Returns:
        {"checks": [{"key", "label", "status", "path"}, ...]}

    Status values:
    - "ok":      target found
    - "warn":    target missing but might be fine
    - "missing": target missing and almost certainly a problem
    """
    path = Path(path)
    if not path.exists() or not path.is_dir():
        return {"checks": []}
    checks = check_repo_paths(lambda rel: (path / rel).exists())
    return {"checks": checks, "version": _local_version(path, checks)}


def _local_version(path: Path, checks: list[dict]) -> dict | None:
    """The project's version from its pyproject.toml or package.json, if they say."""
    from app.services.project_version import detect_version

    def read(rel: str | None) -> str | None:
        if not rel:
            return None
        try:
            return (path / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    package_json = next((c["path"] for c in checks if c["key"] == "package_json" and c["status"] == "ok"), None)
    return detect_version(read("pyproject.toml"), read(package_json))

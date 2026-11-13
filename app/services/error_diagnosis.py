"""Build failure diagnosis helpers.

This module is consumed by the build pipeline to turn raw build/packaging logs
(Nuitka compilation, Docker image builds, frontend/npm builds, etc.) into a
small set of actionable, human-friendly failure reasons that can be surfaced
directly in the UI.

The single public entry point, :func:`diagnose_build_failure`, performs a
case-insensitive scan of the log text and returns a list of diagnosis dicts,
each shaped as ``{"problem": str, "suggestion": str, "evidence": str}``. The
list is ordered most-specific first so the UI can show the most relevant
explanation at the top. All user-facing text is in English, like the console.

The function is intentionally defensive: it never raises, treats ``None`` as an
empty string, and de-duplicates so the same problem is not reported twice.
"""

from __future__ import annotations

import logging
import re

__all__ = ["diagnose_build_failure"]

# Maximum length of an evidence snippet before it gets trimmed with an ellipsis.
_MAX_EVIDENCE_LEN = 300

logger = logging.getLogger(__name__)


def _trim(snippet: str) -> str:
    """Normalize and length-limit a matched log snippet for display."""
    if snippet is None:
        return ""
    snippet = snippet.strip()
    if len(snippet) > _MAX_EVIDENCE_LEN:
        snippet = snippet[:_MAX_EVIDENCE_LEN].rstrip() + " ..."
    return snippet


def _search(pattern: str, text: str) -> "re.Match | None":
    """Run a case-insensitive regex search, swallowing any regex errors."""
    try:
        return re.search(pattern, text, re.IGNORECASE)
    except Exception:
        return None


def _line_containing(text_lower: str, original: str, needle_lower: str) -> str:
    """Return the first original-cased line containing ``needle_lower``."""
    try:
        idx = text_lower.find(needle_lower)
        if idx < 0:
            return ""
        start = original.rfind("\n", 0, idx) + 1
        end = original.find("\n", idx)
        if end < 0:
            end = len(original)
        return original[start:end]
    except Exception:
        return ""


def diagnose_build_failure(log_text: str) -> list[dict]:
    """Return a list of {"problem": str, "suggestion": str, "evidence": str}
    for known failure patterns found in the build log. Empty list if nothing
    recognized. Ordered most-specific first. 'evidence' is the matched log
    snippet (trimmed). All text is in English, like the console."""
    if not log_text:
        return []

    try:
        text = str(log_text)
    except Exception:
        return []

    text_lower = text.lower()

    diagnoses: list[dict] = []
    seen_problems: set[str] = set()
    matched_generic_modules: set[str] = set()

    def add(
        problem: str,
        suggestion: str,
        evidence: str,
        action: dict | None = None,
    ) -> None:
        """Record a diagnosis, optionally with a fix the platform can apply.

        `action` is {"label": str, "overrides": {config field: value}} — the
        rule states what should change and the UI turns it into a button, so a
        new rule gains a one-click fix without touching the frontend.
        """
        if not problem or problem in seen_problems:
            return
        seen_problems.add(problem)
        entry = {
            "problem": problem,
            "suggestion": suggestion,
            "evidence": _trim(evidence),
        }
        if action:
            entry["action"] = action
        diagnoses.append(entry)

    # ------------------------------------------------------------------
    # 1. Python ABI mismatch
    #    ModuleNotFoundError: No module named '<pkg>._<pkg>'  OR
    #    a cpython-3XX .so that can't load.
    # ------------------------------------------------------------------
    try:
        abi_match = _search(
            r"ModuleNotFoundError:\s*No module named\s*['\"]([A-Za-z0-9_]+)\._\1['\"]",
            text,
        )
        # A bare `cpython-3XX...\.so` path is NORMAL, healthy output — Nuitka
        # lists the .so files it bundles, and any traceback frame inside a
        # compiled extension prints that path too. It is ONLY evidence of an ABI
        # mismatch when the .so actually FAILS TO LOAD, so require an error
        # indicator on the same line (import/link failure), not the mere path.
        so_match = _search(
            r"[^\n]*cpython-3\d{1,2}[^\n]*\.so[^\n]*"
            r"(?:cannot open shared object|undefined symbol|wrong elf class|"
            r"invalid elf header|no such file|importerror|"
            r"incompatible|symbol not found)[^\n]*",
            text,
        ) or _search(
            r"(?:cannot open shared object|undefined symbol|wrong elf class|"
            r"invalid elf header|importerror)[^\n]*cpython-3\d{1,2}[^\n]*\.so[^\n]*",
            text,
        )
        if abi_match or so_match:
            pkg = abi_match.group(1) if abi_match else ""
            evidence = abi_match.group(0) if abi_match else so_match.group(0)
            add(
                "The Python used to compile does not match the ABI of the project's .so dependencies",
                "Set \"Python version\" to \"Auto-detect\", or make sure Packwright has the matching "
                ".venv-pyXYZ (run scripts/setup_nuitka_venvs.sh).",
                evidence,
                # The single most common diagnosed failure, and the fix is one
                # field. Making the user re-enter the whole form to change it
                # is how the same mistake gets submitted dozens of times.
                action={
                    "label": "Rebuild with auto-detect",
                    "overrides": {"python_version": "auto"},
                },
            )
            if abi_match and pkg:
                # The ABI-form module name is not a "generic" missing module.
                matched_generic_modules.add(f"{pkg}._{pkg}")
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 2. python-dotenv find_dotenv stack walk failure
    #    find_dotenv AND (AssertionError OR frame.f_back)
    # ------------------------------------------------------------------
    try:
        if "find_dotenv" in text_lower and (
            "assertionerror" in text_lower or "frame.f_back" in text_lower
        ):
            evidence = _line_containing(text_lower, text, "find_dotenv")
            add(
                "python-dotenv's load_dotenv() failed walking the call stack under Nuitka",
                "Pass load_dotenv() an explicit path in the project, e.g. "
                'load_dotenv(BASE_DIR / ".env").',
                evidence,
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 3. Port already in use
    # ------------------------------------------------------------------
    try:
        needles = ["address already in use", "errno 98", "eaddrinuse"]
        found = next((n for n in needles if n in text_lower), None)
        if found:
            evidence = _line_containing(text_lower, text, found)
            add(
                "The port the service binds is already in use",
                "Usually an old instance is still running — not a problem with the artifact (this "
                "is treated as a warning). For a full check, stop whatever holds the port first.",
                evidence,
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 4. Docker COPY missing source
    #    COPY .* not found  OR  failed to compute cache key  OR
    #    "/<dir>": not found
    # ------------------------------------------------------------------
    try:
        copy_match = _search(r"COPY\b.*not found", text)
        cache_match = _search(r"failed to compute cache key", text)
        dir_match = _search(r'"/[^"\n]+"\s*:\s*not found', text)
        if copy_match or cache_match or dir_match:
            m = copy_match or dir_match or cache_match
            add(
                "A directory the Dockerfile COPYs does not exist in dist/",
                "Check whether \"Data directories\" (data_dirs) lists a directory the project does "
                "not have (missing ones are skipped automatically).",
                m.group(0),
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 5. Generic ModuleNotFoundError (not matching #1)
    # ------------------------------------------------------------------
    try:
        for m in re.finditer(
            r"ModuleNotFoundError:\s*No module named\s*['\"]([^'\"]+)['\"]",
            text,
            re.IGNORECASE,
        ):
            mod = m.group(1)
            # Skip the ABI-form ('<pkg>._<pkg>') already handled by #1.
            if mod in matched_generic_modules:
                continue
            if re.fullmatch(r"([A-Za-z0-9_]+)\._\1", mod):
                continue
            add(
                f"Module {mod} not found at run time",
                f"The package probably imports it dynamically or lazily, which Nuitka cannot see; "
                f"add {mod} to \"Include packages\".",
                m.group(0),
            )
            break
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 6. Nuitka not installed
    # ------------------------------------------------------------------
    try:
        needles = ["nuitka not installed", "no module named nuitka"]
        found = next((n for n in needles if n in text_lower), None)
        if found:
            evidence = _line_containing(text_lower, text, found)
            add(
                "Nuitka is not installed in the selected Python environment",
                "Run scripts/setup_nuitka_venvs.sh to create the venv for that version.",
                evidence,
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 7. npm / frontend build fail
    #    npm ERR!  OR  vite's "error during build"  OR  Cannot find module
    # ------------------------------------------------------------------
    try:
        npm_err = "npm err!" in text_lower
        # Vite says "error during build:" when it fails. "vite build" plus the
        # word "error" anywhere in the log matched every fullstack build that
        # failed later for any reason: MCP Gate's smoke test ("Error loading
        # config") was reported as "Frontend build failed".
        vite_err = "error during build" in text_lower
        cant_find = "cannot find module" in text_lower
        if npm_err or vite_err or cant_find:
            if npm_err:
                needle = "npm err!"
            elif cant_find:
                needle = "cannot find module"
            else:
                needle = "error during build"
            evidence = _line_containing(text_lower, text, needle)
            add(
                "Frontend build failed",
                "Check the frontend directory, the build command and the Node version; "
                "the red lines in the frontend build log below say what broke.",
                evidence,
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 8. Out of memory
    # ------------------------------------------------------------------
    try:
        needles = ["memoryerror", "killed", "cannot allocate memory"]
        found = next((n for n in needles if n in text_lower), None)
        if found:
            evidence = _line_containing(text_lower, text, found)
            add(
                "Out of memory while compiling",
                "Lower \"CPU jobs\" (nuitka_jobs), or use the External pack mode. Each job is "
                "another C compiler process, so memory use grows almost linearly with it.",
                evidence,
                # 2 keeps some parallelism while cutting peak memory hard. Going
                # to 1 as a first move makes an already-slow build far slower for
                # no extra chance of success.
                action={
                    "label": "Rebuild with 2 CPU jobs",
                    "overrides": {"nuitka_jobs": 2},
                },
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 9. Disk full
    # ------------------------------------------------------------------
    try:
        needles = ["no space left on device", "errno 28"]
        found = next((n for n in needles if n in text_lower), None)
        if found:
            evidence = _line_containing(text_lower, text, found)
            add(
                "Out of disk space",
                "Free up the output directory or workspace, and check the disks holding dist/ and "
                "the Docker image exports.",
                evidence,
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 10. Permission denied (Python environment access)
    #     Permission denied AND (.venv OR python)
    # ------------------------------------------------------------------
    try:
        if "permission denied" in text_lower and (
            ".venv" in text_lower or "python" in text_lower
        ):
            evidence = _line_containing(text_lower, text, "permission denied")
            add(
                "Permission denied while accessing the Python environment",
                "Make sure the venv was created by the same user that runs the service (not "
                "root); see setup_nuitka_venvs.sh.",
                evidence,
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 11. Git clone — authentication rejected
    # ------------------------------------------------------------------
    try:
        needles = [
            "authentication failed",
            "could not read username",
            "invalid username or password",
            "http basic: access denied",
            "403 forbidden",
        ]
        found = next((n for n in needles if n in text_lower), None)
        if found and ("git" in text_lower or "clone" in text_lower):
            add(
                "Git authentication failed: the repository could not be fetched",
                "For a private repo, add a valid access token for its host in Settings -> Git "
                "credentials (tokens expire); for a public one, check the URL for typos. Do not "
                "put a username or password in the URL — credentials are added automatically.",
                _line_containing(text_lower, text, found),
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 12. Git clone — branch/tag does not exist
    # ------------------------------------------------------------------
    try:
        ref_match = _search(
            r"(?:remote branch|pathspec|couldn't find remote ref)[^\n]*not found[^\n]*"
            r"|Remote branch [^\n]+ not found in upstream",
            text,
        )
        if ref_match:
            add(
                "The branch or tag does not exist on the remote",
                "Go back to the first step and pick the branch/tag again — the list is read live "
                "from the remote. Usually the branch was deleted or renamed.",
                ref_match.group(0),
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 13. Entry point missing
    #     Nuitka refuses to start when the main script is not where we say.
    # ------------------------------------------------------------------
    try:
        entry_match = _search(
            r"(?:FATAL:[^\n]*|Error,[^\n]*)?(?:file|path)[^\n]{0,40}"
            r"(?:does not exist|not found|no such file)[^\n]*\.py[^\n]*"
            r"|python:\s*can't open file[^\n]*",
            text,
        )
        if entry_match:
            add(
                "Entry point file not found",
                "Check \"Entry point\" in the second step. It is relative to the project root, "
                "e.g. main.py or src/app.py — not an absolute path.",
                entry_match.group(0),
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 14. Dependency install failed (uv / pip) — distinct from a build error
    # ------------------------------------------------------------------
    try:
        dep_match = _search(
            r"(?:No solution found when resolving|error: Failed to (?:download|build|prepare)"
            r"|Could not find a version that satisfies|ERROR: Could not install)[^\n]*",
            text,
        )
        if dep_match:
            add(
                "Installing the project's dependencies failed",
                "This is a problem with the project's own dependencies, not the build settings. "
                "Run uv sync (or pip install -r requirements.txt) in the project yourself, and "
                "rebuild once that succeeds.",
                dep_match.group(0),
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 15a. No package.json where the frontend build looked. Checked before the
    #      install rule: npm fails at the install step here too, and "fix your
    #      lock file" would send the reader after the wrong thing.
    # ------------------------------------------------------------------
    missing_package_json = False
    try:
        pkg_match = _search(
            r"[^\n]*(?:could not read package\.json|enoent[^\n]*package\.json)[^\n]*", text
        )
        if pkg_match:
            missing_package_json = True
            add(
                "No package.json in the frontend directory",
                "The frontend directory has to be the folder that holds package.json. Check "
                "Frontend directory on the Frontend step (in a full-stack repository it is usually "
                "frontend), and that the path or branch you chose has one.",
                pkg_match.group(0),
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 15. npm install failed — separate from "frontend build failed" so the
    #     suggestion can point at the lock file rather than the build script.
    # ------------------------------------------------------------------
    try:
        npm_match = _search(
            # npm 10 prints "npm error"; earlier versions "npm ERR!".
            r"(?:npm ERR!|npm error|ERR_PNPM_[A-Z_]+|error Couldn't find any versions)[^\n]*", text
        )
        if npm_match and not missing_package_json and (
            "npm ci" in text_lower
            or "npm install" in text_lower
            or "err_pnpm" in text_lower
            or "yarn install" in text_lower
        ):
            add(
                "Installing frontend dependencies failed",
                "Usually package-lock.json / pnpm-lock.yaml no longer matches package.json. "
                "Regenerate the lockfile in the frontend directory, commit it, and rebuild.",
                npm_match.group(0),
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 16. Docker daemon unreachable
    # ------------------------------------------------------------------
    try:
        needles = [
            "cannot connect to the docker daemon",
            "is the docker daemon running",
            "permission denied while trying to connect to the docker daemon",
        ]
        found = next((n for n in needles if n in text_lower), None)
        if found:
            add(
                "Cannot connect to the Docker daemon",
                "This is a server-side problem, not your settings. Ask an administrator to check "
                "that Docker is running and that the service's user may use it.",
                _line_containing(text_lower, text, found),
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 17b. Gateway timeout from a proxy in front of the app
    #      Checked BEFORE the generic timeout rule: "504" and "gateway
    #      time-out" also contain the word "timeout", and the generic advice
    #      (raise a build setting) is wrong for this one.
    # ------------------------------------------------------------------
    try:
        gw_match = _search(
            r"(?:504\s*(?:gateway\s*time-?out)?|gateway\s*time-?out"
            r"|upstream timed out[^\n]*while reading)[^\n]*",
            text,
        )
        if gw_match and (
            "504" in text_lower or "gateway" in text_lower or "upstream timed out" in text_lower
        ):
            add(
                "Cut off by the reverse proxy's timeout (504)",
                "The backend did not crash — nginx's proxy_read_timeout counts how long the "
                "backend has sent nothing. Long, silent requests such as speech-to-text hit it "
                "most: nginx gives up and returns 504 while the backend keeps working and later "
                "writes to a connection nobody is listening on, so its own log shows success."
                "\nFix: (1) set the Docker setting for how long the backend may stay silent to "
                "twice the worst case; (2) more robust: have the backend send data while it works "
                "(an SSE \": keepalive\" line every 10 s), which resets the timer of every proxy in "
                "the chain at once — if another reverse proxy (an outer nginx, a load balancer) "
                "sits in front of the container, changing only the one inside does nothing.",
                gw_match.group(0),
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    # ------------------------------------------------------------------
    # 17. Timed out
    # ------------------------------------------------------------------
    try:
        needles = ["timed out", "timeout expired", "operation timed out"]
        found = next((n for n in needles if n in text_lower), None)
        if found:
            add(
                "A step timed out and was stopped",
                "Cloning or installing dependencies of a large project can exceed the default "
                "limits. Ask an administrator to raise GIT_CLONE_TIMEOUT / VENV_BOOTSTRAP_TIMEOUT.",
                _line_containing(text_lower, text, found),
            )
    except Exception:
        # Isolated on purpose: a bug in one rule must not take the rest
        # down. Logged so a broken rule shows up as something other than
        # silently vanishing coverage.
        logger.debug("A diagnosis rule raised and was skipped", exc_info=True)

    return diagnoses


# ----------------------------------------------------------------------
# Guaranteed explanation
# ----------------------------------------------------------------------

# Lines worth showing a user who has no idea what went wrong. Ordered by how
# strongly they indicate the actual cause rather than downstream noise.
_ERROR_LINE_MARKERS = (
    "fatal:",
    "error:",
    "error ",
    "exception",
    "traceback",
    "failed",
    "err!",
    "cannot ",
    "no such file",
    "permission denied",
    "not found",
)

# Stage names come from task["stage"]; phrase them the way the UI already does.
_STAGE_HINTS = {
    "queued": "The build ended while it was still queued",
    "frontend": "Failed while building the frontend — installing its dependencies or running its build command",
    "docker": "Failed while building or exporting the Docker image",
    "preflight": "Failed during preflight — usually a path, the Python version or the dependency environment",
    "compile": "Failed while compiling — Nuitka reported an error",
    "bundle": "Failed while bundling — copying dependencies or data directories went wrong",
    "verify": "Failed verification — the binary was built but its test run failed",
    "done": "Failed while finishing up",
}


def extract_error_lines(log_text: str, limit: int = 6) -> list[str]:
    """Pull the lines most likely to explain a failure, newest last.

    Scans from the END of the log: the first error is often a symptom of a
    later, more specific one, and the last thing printed before the process
    died is usually the real reason.
    """
    if not log_text:
        return []
    hits: list[str] = []
    for line in reversed(str(log_text).splitlines()):
        stripped = line.strip()
        if not stripped or len(stripped) > 500:
            continue
        low = stripped.lower()
        if any(m in low for m in _ERROR_LINE_MARKERS):
            if stripped not in hits:
                hits.append(stripped)
            if len(hits) >= limit:
                break
    return list(reversed(hits))


def build_failure_report(log_text: str, *, stage: str | None = None) -> dict:
    """Explain a failed build — always, even when no pattern matches.

    The pattern rules match only a minority of real failures, and the caller
    used to persist a result only when something matched. So most of the time a
    user was shown a red "failed" and nothing else: there was nothing to act on,
    so people just ran it again, sometimes dozens of times.

    This never returns an empty diagnosis. When no rule fires it still names
    the stage that failed and surfaces the error lines from the log, which is
    the information someone would otherwise have to go digging for.
    """
    diagnoses = diagnose_build_failure(log_text)
    error_lines = extract_error_lines(log_text)

    if not diagnoses:
        stage_hint = _STAGE_HINTS.get((stage or "").lower())
        problem = stage_hint or "The build failed, and the cause could not be determined automatically"
        if error_lines:
            suggestion = (
                "This does not match a known failure pattern; below are the last error lines in "
                "the log. If they don't help, send them with a link to this build to an administrator."
            )
        else:
            suggestion = (
                "The log has no obvious error lines. Read the full log from the end backwards, "
                "or send a link to this build to an administrator."
            )
        diagnoses = [
            {
                "problem": problem,
                "suggestion": suggestion,
                "evidence": _trim(error_lines[-1]) if error_lines else "",
            }
        ]

    return {
        "diagnosis": diagnoses,
        "error_lines": error_lines,
        "failed_stage": stage or None,
    }

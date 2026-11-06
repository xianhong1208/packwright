"""Which version of a project is being built, read from the project itself.

A version that is already written down somewhere should not have to be typed
again — and when it is typed into the project name instead ("app v1.2 test"),
a project's builds scatter across names. In order of precedence:

1. the Git tag being built (a tag *is* a version the team chose to mark),
2. ``[project].version`` in pyproject.toml,
3. ``version`` in package.json.

A dynamic version (``dynamic = ["version"]``) is not readable without running the
build backend, so it is left to the person. Anything that is not a usable version
(the characters BuildConfig.version accepts) is ignored rather than passed on.
"""

from __future__ import annotations

import json
import tomllib

from app.schemas.task import _VERSION_RE


def _usable(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if _VERSION_RE.fullmatch(value) else None


def version_from_pyproject(text: str | None) -> str | None:
    """``[project].version``, unless the version is declared dynamic."""
    if not text:
        return None
    try:
        project = tomllib.loads(text).get("project") or {}
    except tomllib.TOMLDecodeError:
        return None
    if "version" in (project.get("dynamic") or []):
        return None
    return _usable(project.get("version"))


def version_from_package_json(text: str | None) -> str | None:
    """``version`` in package.json."""
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return _usable(data.get("version")) if isinstance(data, dict) else None


def detect_version(
    pyproject_text: str | None = None,
    package_json_text: str | None = None,
    ref: str | None = None,
    ref_type: str | None = None,
) -> dict | None:
    """``{"value": "1.2.0", "source": "pyproject.toml"}``, or None if nothing says."""
    if ref_type == "tag" and (tag := _usable(ref)):
        return {"value": tag, "source": "Git tag"}
    if value := version_from_pyproject(pyproject_text):
        return {"value": value, "source": "pyproject.toml"}
    if value := version_from_package_json(package_json_text):
        return {"value": value, "source": "package.json"}
    return None

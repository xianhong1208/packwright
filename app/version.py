"""The running version, read from the single source of truth: pyproject.toml.

Resolution order: pyproject.toml next to the app (always current in a checkout),
then installed package metadata (a wheel install has no pyproject), then a
sentinel. pyproject goes first on purpose: metadata is written at install time,
so after a version bump it keeps reporting the old number until the next
`uv sync` (a trap the sibling projects fell into).

Every other place that shows a version derives from this: the startup banner,
the OpenAPI document, /health, and the console (which reads /health at runtime,
so a stale frontend build is visible). frontend/package.json is synced from
pyproject.toml by `npm run sync-version`, which `npm run build` runs first.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _resolve() -> str:
    try:
        with _PYPROJECT.open("rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        pass
    try:
        return _installed_version("packwright")
    except PackageNotFoundError:
        return "0.0.0+unknown"


__version__ = _resolve()

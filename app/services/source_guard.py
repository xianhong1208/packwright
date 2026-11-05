"""Temporary changes to files in a user's project, undone on every path out.

Local-source builds work in the user's own directory, and a few steps have to
change files there for the duration of a build: the libs/ loader goes into the
entry point, the configured frontend env file replaces theirs, a .dockerignore
and Dockerfile.generated are written. Each worker used to back these up its own
way, and every way had a hole:

- the frontend .env original was kept only in memory, and a failed install or
  build returned before the restore — so an ordinary failed build left the
  user's real .env replaced by the build's env content, original gone;
- after a crash, the entry point kept the loader for good: the next build saw
  the marker, assumed "already injected" and never restored the backup.

A SourceGuard records the original (or the fact that there was no file) in an
on-disk journal *before* touching anything. ``restore()`` undoes everything and
runs from ``finally`` blocks, so every return path restores; and
``recover_interrupted()`` replays any journal left behind at startup, before
the first build can run, which covers a crash or a kill mid-build.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_MANIFEST = "manifest.json"


def journal_root() -> Path:
    return Path(get_settings().git_workspace_dir) / ".restore"


class SourceGuard:
    """Change files in a project and remember how to put them back."""

    def __init__(self, task_id: str, root: Path | None = None) -> None:
        self._dir = (root or journal_root()) / task_id
        self._entries: list[dict] = []

    @property
    def active(self) -> bool:
        return bool(self._entries)

    def _save_manifest(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self._dir / (_MANIFEST + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._entries, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._dir / _MANIFEST)

    def _remember(self, path: Path) -> None:
        """Record the original state of ``path`` once, before its first change."""
        path = path.absolute()
        if any(e["path"] == str(path) for e in self._entries):
            return
        entry: dict = {"path": str(path), "existed": path.exists()}
        if entry["existed"]:
            self._dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            saved = self._dir / f"{len(self._entries)}.orig"
            shutil.copy2(path, saved)  # may hold secrets (an .env): the journal dir is 0700
            entry["saved"] = saved.name
        self._entries.append(entry)
        self._save_manifest()

    def write(self, path: Path, content: str) -> None:
        """Replace (or create) ``path`` with ``content`` until ``restore()``."""
        self._remember(path)
        path.write_text(content, encoding="utf-8")

    def restore(self) -> list[str]:
        """Undo every change, newest first. Returns one line per file, for the log."""
        messages = _restore_entries(self._dir, self._entries)
        self._entries = []
        return messages


def _restore_entries(directory: Path, entries: list[dict]) -> list[str]:
    messages: list[str] = []
    failed = False
    for entry in reversed(entries):
        path = Path(entry["path"])
        try:
            if entry["existed"]:
                shutil.copy2(directory / entry["saved"], path)
                messages.append(f"Restored {path}")
            else:
                path.unlink(missing_ok=True)
                messages.append(f"Removed {path}")
        except OSError as e:
            failed = True
            messages.append(f"Warning: could not restore {path}: {e}")
            logger.warning("Could not restore %s from %s", path, directory, exc_info=True)
    if not failed:  # keep the journal when something could not be put back
        shutil.rmtree(directory, ignore_errors=True)
    return messages


def recover_interrupted(root: Path | None = None) -> list[str]:
    """Restore files left changed by builds that never finished (startup only)."""
    root = root or journal_root()
    if not root.is_dir():
        return []
    messages: list[str] = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest = directory / _MANIFEST
        if not manifest.exists():
            shutil.rmtree(directory, ignore_errors=True)  # died before changing anything
            continue
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Unreadable restore journal %s left in place", directory, exc_info=True)
            continue
        for line in _restore_entries(directory, entries):
            messages.append(f"[{directory.name}] {line}")
    for line in messages:
        logger.warning("Interrupted build: %s", line)
    return messages

"""Back up Packwright's database — SQLite or PostgreSQL — to a gzip file.

Run through ``scripts/backup_db.sh`` (cron-friendly) or ``python -m app.services.db_backup``.

The database holds what cannot be rebuilt from code: build history with the
exact config of every build, users and roles, audit and login records.
Workspaces and artifacts have a TTL and come back by rerunning a build.

The target is resolved exactly as the service resolves it (DATABASE_URL, then
DB_*, then the default SQLite file). The previous shell script read only DB_*
and ran pg_dump, so it backed up the wrong database when DATABASE_URL was set
and could not back up the default SQLite install at all.
"""
from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import get_settings


def _finish(partial: Path, final: Path) -> Path:
    # Take the final name only once the dump is complete, so a crashed run never
    # leaves a truncated file that looks like a good backup.
    os.chmod(partial, 0o600)  # dumps hold password hashes and pasted env content
    os.replace(partial, final)
    return final


def _backup_sqlite(db_file: Path, out: Path) -> Path:
    """Online backup: a consistent snapshot even while the service is writing."""
    partial = out.with_name(out.name + ".partial")
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        snapshot = Path(tmp) / "snapshot.db"
        src = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        dst = sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(snapshot, "rb") as f_in, gzip.open(partial, "wb", compresslevel=9) as f_out:
            shutil.copyfileobj(f_in, f_out)
    return _finish(partial, out)


def _backup_postgres(url, out: Path) -> Path:
    partial = out.with_name(out.name + ".partial")
    argv = ["pg_dump", "--format=plain", "--no-owner", "--no-privileges", f"--dbname={url.database}"]
    if url.host:
        argv.append(f"--host={url.host}")
    if url.port:
        argv.append(f"--port={url.port}")
    if url.username:
        argv.append(f"--username={url.username}")
    # The password goes through the environment, never argv (visible to every
    # user via `ps`).
    env = {**os.environ, **({"PGPASSWORD": url.password} if url.password else {})}
    with gzip.open(partial, "wb", compresslevel=9) as f_out:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, env=env)
        assert proc.stdout is not None
        shutil.copyfileobj(proc.stdout, f_out)
        if proc.wait() != 0:
            raise RuntimeError(f"pg_dump exited with {proc.returncode}")
    return _finish(partial, out)


def backup(backup_dir: Path, retention_days: int) -> tuple[Path, int]:
    """Write one backup and rotate out ones older than ``retention_days``.

    Returns (backup file, number rotated out). Rotation runs only after a
    successful backup, so a broken database never deletes the last good ones.
    """
    url = make_url(get_settings().sync_database_url)
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    if url.get_backend_name() == "sqlite":
        db_file = Path(url.database or "")
        if not db_file.is_file():
            raise FileNotFoundError(f"SQLite database not found: {db_file}")
        prefix, suffix = db_file.stem, ".sqlite.gz"
        out = backup_dir / f"{prefix}-{stamp}{suffix}"
        run = lambda: _backup_sqlite(db_file, out)  # noqa: E731
    elif url.get_backend_name() == "postgresql":
        prefix, suffix = url.database or "packwright", ".sql.gz"
        out = backup_dir / f"{prefix}-{stamp}{suffix}"
        run = lambda: _backup_postgres(url, out)  # noqa: E731
    else:
        raise ValueError(f"Unsupported database for backup: {url.get_backend_name()}")
    try:
        result = run()
    except BaseException:
        out.with_name(out.name + ".partial").unlink(missing_ok=True)
        raise

    cutoff = time.time() - retention_days * 86400
    rotated = 0
    for old in backup_dir.glob(f"{prefix}-*{suffix}"):
        if old != result and old.stat().st_mtime < cutoff:
            old.unlink()
            rotated += 1
    return result, rotated


def main() -> int:
    backup_dir = Path(os.environ.get("BACKUP_DIR", "./data/backups"))
    retention = int(os.environ.get("RETENTION_DAYS", "30"))
    now = lambda: datetime.now().strftime("%F %T")  # noqa: E731
    try:
        path, rotated = backup(backup_dir, retention)
    except Exception as e:  # cron reads the exit code and the log line
        print(f"[{now()}] Backup FAILED: {e}", file=sys.stderr)
        return 1
    print(f"[{now()}] OK — {path} ({path.stat().st_size / 1024:.0f} KB)")
    if rotated:
        print(f"[{now()}] Rotated out {rotated} backup(s) older than {retention}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

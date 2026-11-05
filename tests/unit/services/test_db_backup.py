"""
Unit tests for database backups.
Source: app/services/db_backup

The old shell script read only DB_* and ran pg_dump, so it backed up the wrong
database when DATABASE_URL was set and could not back up the default SQLite
install at all.
"""

import gzip
import io
import os
import sqlite3
import stat
import time

import pytest

from app.services import db_backup


def _settings(mocker, url):
    mocker.patch.object(db_backup, "get_settings", return_value=mocker.MagicMock(sync_database_url=url))


@pytest.fixture
def sqlite_db(tmp_path):
    path = tmp_path / "build_center.db"
    con = sqlite3.connect(path)
    con.execute("create table history (task_id text, project_name text)")
    con.executemany("insert into history values (?, ?)", [("t1", "web"), ("t2", "cli")])
    con.commit()
    con.close()
    return path


class TestSqlite:
    @pytest.mark.unit
    def test_tc_bak_001_backup_is_a_complete_private_database(self, tmp_path, sqlite_db, mocker):
        """TC-BAK-001: the default SQLite install is backed up; the gzip holds a database
        with every row, readable only by the owner, with no .partial left behind."""
        _settings(mocker, f"sqlite:///{sqlite_db}")
        out_dir = tmp_path / "backups"

        path, rotated = db_backup.backup(out_dir, retention_days=30)

        assert path.name.startswith("build_center-") and path.name.endswith(".sqlite.gz")
        restored = tmp_path / "restored.db"
        restored.write_bytes(gzip.decompress(path.read_bytes()))
        rows = sqlite3.connect(restored).execute("select task_id from history order by 1").fetchall()
        assert rows == [("t1",), ("t2",)]
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(out_dir).st_mode) == 0o700
        assert not list(out_dir.glob("*.partial")) and rotated == 0

    @pytest.mark.unit
    def test_tc_bak_002_rotation_removes_only_old_backups_of_this_database(self, tmp_path, sqlite_db, mocker):
        """TC-BAK-002: backups past the retention go; recent ones and unrelated files stay."""
        _settings(mocker, f"sqlite:///{sqlite_db}")
        out_dir = tmp_path / "backups"
        out_dir.mkdir()
        old, recent, other = (out_dir / "build_center-20200101-000000.sqlite.gz",
                              out_dir / "build_center-20990101-000000.sqlite.gz", out_dir / "notes.txt")
        for f in (old, recent, other):
            f.write_text("x")
        os.utime(old, (time.time() - 40 * 86400,) * 2)
        os.utime(other, (time.time() - 400 * 86400,) * 2)

        _, rotated = db_backup.backup(out_dir, retention_days=30)

        assert rotated == 1 and not old.exists()
        assert recent.exists() and other.exists()

    @pytest.mark.unit
    def test_tc_bak_003_missing_database_fails_without_rotating(self, tmp_path, mocker):
        """TC-BAK-003: a missing database is an error, and the last good backups survive it."""
        _settings(mocker, f"sqlite:///{tmp_path / 'gone.db'}")
        out_dir = tmp_path / "backups"
        out_dir.mkdir()
        old = out_dir / "gone-20200101-000000.sqlite.gz"
        old.write_text("x")
        os.utime(old, (0, 0))

        with pytest.raises(FileNotFoundError):
            db_backup.backup(out_dir, retention_days=1)
        assert old.exists()


class TestPostgres:
    @staticmethod
    def _popen(mocker, rc=0):
        proc = mocker.MagicMock(stdout=io.BytesIO(b"-- dump\n"), returncode=rc)
        proc.wait.return_value = rc
        return mocker.patch.object(db_backup.subprocess, "Popen", return_value=proc)

    @pytest.mark.unit
    def test_tc_bak_010_database_url_is_what_gets_dumped(self, tmp_path, mocker):
        """TC-BAK-010: the dump targets the configured URL, and the password goes through
        the environment, never argv (visible to every user via ps)."""
        _settings(mocker, "postgresql://pw_user:s3cret@db.internal:6543/packwright_prod")
        popen = self._popen(mocker)

        path, _ = db_backup.backup(tmp_path / "b", retention_days=30)

        argv, env = popen.call_args.args[0], popen.call_args.kwargs["env"]
        assert argv[0] == "pg_dump"
        assert {"--dbname=packwright_prod", "--host=db.internal", "--port=6543", "--username=pw_user"} <= set(argv)
        assert not any("s3cret" in a for a in argv) and env["PGPASSWORD"] == "s3cret"
        assert path.name.startswith("packwright_prod-") and gzip.decompress(path.read_bytes()) == b"-- dump\n"

    @pytest.mark.unit
    def test_tc_bak_011_failed_dump_leaves_no_backup_and_keeps_old_ones(self, tmp_path, mocker):
        """TC-BAK-011: a failed pg_dump raises, leaves nothing behind (not even the
        .partial), and rotates nothing."""
        _settings(mocker, "postgresql://u@localhost/packwright")
        self._popen(mocker, rc=1)
        out_dir = tmp_path / "b"
        out_dir.mkdir()
        old = out_dir / "packwright-20200101-000000.sql.gz"
        old.write_text("x")
        os.utime(old, (0, 0))

        with pytest.raises(RuntimeError):
            db_backup.backup(out_dir, retention_days=1)
        assert [p.name for p in out_dir.iterdir()] == [old.name]


class TestRetentionZero:
    @pytest.mark.unit
    def test_tc_bak_020_zero_retention_never_deletes_the_new_backup(self, tmp_path, sqlite_db, mocker):
        """TC-BAK-020: RETENTION_DAYS=0 ("keep only the latest") must not rotate out the
        backup that was just written, whose mtime is already before 'now'."""
        _settings(mocker, f"sqlite:///{sqlite_db}")
        out_dir = tmp_path / "backups"
        out_dir.mkdir()
        older = out_dir / "build_center-20200101-000000.sqlite.gz"
        older.write_text("x")
        os.utime(older, (0, 0))
        time.sleep(0.01)

        path, rotated = db_backup.backup(out_dir, retention_days=0)

        assert path.exists() and not older.exists() and rotated == 1

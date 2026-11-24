"""
Unit tests for moving the pre-rename SQLite file.
Source: app.config (Settings._resolve_url, move_legacy_sqlite_file)

Up to 1.4 the default database was data/build_center.db; it is now
data/packwright.db. Resolving the default URL renames an old file (with its
-wal / -shm / -journal) once, before anything opens it, and refuses to guess
when both files exist.
"""

import logging
import sqlite3

import pytest

from app.config import LegacyDatabaseConflict, Settings, move_legacy_sqlite_file


def _default_settings(**overrides):
    # Constructor values beat the environment, where the test conftest sets DATABASE_URL.
    return Settings(**{"database_url": "", "db_host": "", **overrides})


def _old_style_db(data_dir, rows=("t1", "t2")):
    """A WAL-mode build_center.db whose last commit is still only in its -wal file."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "build_center.db"
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("create table history (task_id text)")
    con.executemany("insert into history values (?)", [(r,) for r in rows])
    con.commit()
    # Copy the files while the connection is open, so the -wal and -shm are there
    # and hold the committed rows (closing would checkpoint and delete them).
    snapshot = {s: (data_dir / f"build_center.db{s}").read_bytes() for s in ("", "-wal", "-shm")}
    con.close()
    for s, body in snapshot.items():
        (data_dir / f"build_center.db{s}").write_bytes(body)
    return snapshot


def _rows(path):
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("select task_id from history order by 1")]
    finally:
        con.close()


class TestDefaultFileName:
    @pytest.mark.unit
    def test_tc_dbn_001_only_old_file_is_moved_with_its_wal(self, tmp_path, monkeypatch, caplog):
        """TC-DBN-001: only data/build_center.db → it, its -wal and -shm become packwright.db*,
        byte for byte, the URL names the new file, the committed rows that lived only in
        the WAL are readable there, and the move is logged once."""
        monkeypatch.chdir(tmp_path)
        data = tmp_path / "data"
        before = _old_style_db(data)

        with caplog.at_level(logging.WARNING, logger="app.config"):
            url = _default_settings().async_database_url
            _default_settings().sync_database_url  # a second resolve finds nothing to move

        assert url == f"sqlite+aiosqlite:///{data / 'packwright.db'}"
        for suffix, body in before.items():
            assert (data / f"packwright.db{suffix}").read_bytes() == body
            assert not (data / f"build_center.db{suffix}").exists()
        assert _rows(data / "packwright.db") == ["t1", "t2"]
        moved = [r for r in caplog.records if "renamed" in r.getMessage()]
        assert len(moved) == 1 and "build_center.db" in moved[0].getMessage()

    @pytest.mark.unit
    def test_tc_dbn_002_only_new_file_is_left_alone(self, tmp_path, monkeypatch):
        """TC-DBN-002: only data/packwright.db → nothing is renamed or created."""
        monkeypatch.chdir(tmp_path)
        data = tmp_path / "data"
        data.mkdir()
        (data / "packwright.db").write_bytes(b"new")

        url = _default_settings().async_database_url

        assert url.endswith("/data/packwright.db")
        assert sorted(p.name for p in data.iterdir()) == ["packwright.db"]
        assert (data / "packwright.db").read_bytes() == b"new"

    @pytest.mark.unit
    def test_tc_dbn_003_both_files_refuse_to_start(self, tmp_path, monkeypatch):
        """TC-DBN-003: both files → LegacyDatabaseConflict naming both and the way out
        (DATABASE_URL); neither file nor any sidecar is moved or changed."""
        monkeypatch.chdir(tmp_path)
        data = tmp_path / "data"
        before = _old_style_db(data)
        (data / "packwright.db").write_bytes(b"new")

        with pytest.raises(LegacyDatabaseConflict) as err:
            _default_settings().async_database_url

        msg = str(err.value)
        assert "build_center.db" in msg and "packwright.db" in msg and "DATABASE_URL" in msg
        assert (data / "packwright.db").read_bytes() == b"new"
        for suffix, body in before.items():
            assert (data / f"build_center.db{suffix}").read_bytes() == body
        assert not (data / "packwright.db-wal").exists()

    @pytest.mark.unit
    def test_tc_dbn_004_neither_file_starts_fresh(self, tmp_path, monkeypatch):
        """TC-DBN-004: a new install → the URL names data/packwright.db; nothing is created
        but the data directory (SQLite creates the file on first use)."""
        monkeypatch.chdir(tmp_path)

        url = _default_settings().async_database_url

        assert url == f"sqlite+aiosqlite:///{tmp_path / 'data' / 'packwright.db'}"
        assert list((tmp_path / "data").iterdir()) == []

    @pytest.mark.unit
    @pytest.mark.parametrize("overrides", [
        {"database_url": "sqlite:///./data/other.db"},
        {"database_url": "postgresql://u:p@localhost/packwright"},
        {"db_host": "db.example"},
    ], ids=["sqlite-url", "postgres-url", "db-host"])
    def test_tc_dbn_005_configured_database_never_touches_the_files(self, tmp_path, monkeypatch, overrides):
        """TC-DBN-005: DATABASE_URL (SQLite or PostgreSQL) or DB_HOST set → the old file is
        not moved, even with no packwright.db next to it."""
        monkeypatch.chdir(tmp_path)
        data = tmp_path / "data"
        before = _old_style_db(data)

        _default_settings(**overrides).async_database_url

        for suffix, body in before.items():
            assert (data / f"build_center.db{suffix}").read_bytes() == body
        assert not (data / "packwright.db").exists()

    @pytest.mark.unit
    def test_tc_dbn_006_interrupted_move_finishes_on_next_start(self, tmp_path):
        """TC-DBN-006: sidecars move before the main file; a run stopped after the sidecars
        left only build_center.db behind, and the next start completes the move with
        the WAL's rows intact."""
        data = tmp_path / "data"
        _old_style_db(data)
        for suffix in ("-wal", "-shm"):
            (data / f"build_center.db{suffix}").rename(data / f"packwright.db{suffix}")

        assert move_legacy_sqlite_file(data / "packwright.db") is True

        assert not (data / "build_center.db").exists()
        assert _rows(data / "packwright.db") == ["t1", "t2"]

    @pytest.mark.unit
    def test_tc_dbn_009_crash_mid_move_leaves_the_old_main_file(self, tmp_path, monkeypatch):
        """TC-DBN-009: the main file is renamed last. A crash after the first rename still
        finds build_center.db in place (so TC-DBN-006's recovery applies); renaming it
        first would leave packwright.db without its WAL, silently dropping commits."""
        import app.config as config

        data = tmp_path / "data"
        _old_style_db(data)
        real_rename, calls = config.os.rename, []

        def rename_then_crash(src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise OSError("simulated crash")
            real_rename(src, dst)

        monkeypatch.setattr(config.os, "rename", rename_then_crash)
        with pytest.raises(OSError):
            move_legacy_sqlite_file(data / "packwright.db")

        assert (data / "build_center.db").exists() and not (data / "packwright.db").exists()

    @pytest.mark.unit
    def test_tc_dbn_007_sidecar_clash_refuses_and_moves_nothing(self, tmp_path):
        """TC-DBN-007: build_center.db-wal and a stray packwright.db-wal both present →
        refused, nothing renamed (the stray WAL would be applied to the wrong database)."""
        data = tmp_path / "data"
        before = _old_style_db(data)
        (data / "packwright.db-wal").write_bytes(b"stray")

        with pytest.raises(LegacyDatabaseConflict, match="packwright.db-wal"):
            move_legacy_sqlite_file(data / "packwright.db")

        for suffix, body in before.items():
            assert (data / f"build_center.db{suffix}").read_bytes() == body
        assert (data / "packwright.db-wal").read_bytes() == b"stray"
        assert not (data / "packwright.db").exists()

    @pytest.mark.unit
    def test_tc_dbn_008_postgres_default_database_name(self):
        """TC-DBN-008: the DB_* form now connects to the database `packwright` by default."""
        url = _default_settings(db_host="db.example").async_database_url
        assert url.endswith("@db.example:5432/packwright")

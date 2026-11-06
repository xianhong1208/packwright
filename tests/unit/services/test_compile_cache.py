"""
Unit tests for the C compile cache report.
Source: app/services/compile_cache

Without ccache every Nuitka build compiles all of its C files again, and
nothing said so. These pin how Packwright finds the ccache and store Nuitka will
use (the same order Nuitka uses, or the Machine page would describe a cache the
build never touches), how it reads Nuitka's summary into numbers, and how it
reads the store's size from ccache itself.
"""

import stat
import time
from pathlib import Path

import pytest

from app.services import compile_cache

# The lines Nuitka 4.1 prints after compiling (Nuitka-Scons prefix included).
NUITKA_SUMMARY = [
    "Nuitka-Scons: Compiled 81 C files using ccache.",
    "Nuitka-Scons: Cached C files (using ccache) with result 'cache hit': 80",
    "Nuitka-Scons: Cached C files (using ccache) with result 'cache miss': 1",
]


def _executable(path: Path, body: str = "#!/bin/sh\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestCcacheBinary:
    @pytest.mark.unit
    def test_tc_cch_001_named_binary_wins_over_path(self, tmp_path):
        """TC-CCH-001: NUITKA_CCACHE_BINARY is used before ccache on PATH, as Nuitka does."""
        named = _executable(tmp_path / "opt" / "ccache")
        on_path = _executable(tmp_path / "bin" / "ccache")
        env = {"NUITKA_CCACHE_BINARY": str(named), "PATH": str(on_path.parent)}
        assert compile_cache.ccache_binary(env) == str(named)

    @pytest.mark.unit
    def test_tc_cch_002_missing_named_binary_means_no_cache(self, tmp_path):
        """TC-CCH-002: a NUITKA_CCACHE_BINARY that does not exist is reported as no
        cache even with ccache on PATH: Nuitka does not fall back to PATH then."""
        on_path = _executable(tmp_path / "bin" / "ccache")
        env = {"NUITKA_CCACHE_BINARY": str(tmp_path / "gone"), "PATH": str(on_path.parent)}
        assert compile_cache.ccache_binary(env) is None

    @pytest.mark.unit
    def test_tc_cch_003_found_on_path_or_not_at_all(self, tmp_path):
        """TC-CCH-003: ccache is looked up on the build's PATH."""
        on_path = _executable(tmp_path / "bin" / "ccache")
        assert compile_cache.ccache_binary({"PATH": str(on_path.parent)}) == str(on_path)
        assert compile_cache.ccache_binary({"PATH": str(tmp_path / "empty")}) is None


class TestCacheDirectories:
    @pytest.mark.unit
    def test_tc_cch_004_nuitka_cache_dir_order(self, tmp_path, monkeypatch):
        """TC-CCH-004: NUITKA_CACHE_DIR, then XDG_CACHE_HOME, then ~/.cache, each + Nuitka."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        assert compile_cache.nuitka_cache_dir({"NUITKA_CACHE_DIR": str(tmp_path / "c")}) == tmp_path / "c"
        assert compile_cache.nuitka_cache_dir({"XDG_CACHE_HOME": str(tmp_path / "x")}) == tmp_path / "x" / "Nuitka"
        assert compile_cache.nuitka_cache_dir({}) == tmp_path / "home" / ".cache" / "Nuitka"

    @pytest.mark.unit
    def test_tc_cch_005_ccache_store_order(self, tmp_path):
        """TC-CCH-005: CCACHE_DIR, then NUITKA_CACHE_DIR_CCACHE, then <cache dir>/ccache."""
        base = {"NUITKA_CACHE_DIR": str(tmp_path / "nuitka")}
        assert compile_cache.ccache_dir(base) == tmp_path / "nuitka" / "ccache"
        assert compile_cache.ccache_dir({**base, "NUITKA_CACHE_DIR_CCACHE": str(tmp_path / "n")}) == tmp_path / "n"
        assert compile_cache.ccache_dir(
            {**base, "NUITKA_CACHE_DIR_CCACHE": str(tmp_path / "n"), "CCACHE_DIR": str(tmp_path / "cc")}
        ) == tmp_path / "cc"

    @pytest.mark.unit
    def test_tc_cch_006_configured_cache_dir_reaches_the_build(self, tmp_path):
        """TC-CCH-006: NUITKA_CACHE_DIR is set for the build only when configured,
        and the service's own environment is left as it was."""
        base = {"PATH": "/usr/bin", "NUITKA_CACHE_DIR": "/elsewhere"}
        env = compile_cache.build_environment(base, str(tmp_path / "cache"))
        assert env["NUITKA_CACHE_DIR"] == str(tmp_path / "cache")
        assert base["NUITKA_CACHE_DIR"] == "/elsewhere"
        assert compile_cache.build_environment(base, "  ") == base


class TestBuildSummary:
    @pytest.mark.unit
    def test_tc_cch_007_reads_nuitkas_summary(self):
        """TC-CCH-007: hits and misses are read from Nuitka's own lines."""
        assert compile_cache.parse_build_summary(NUITKA_SUMMARY) == {"hits": 80, "compiled": 1}

    @pytest.mark.unit
    def test_tc_cch_008_other_results_count_as_compiled(self):
        """TC-CCH-008: a result that is not a hit (e.g. uncacheable) cost a compile."""
        lines = NUITKA_SUMMARY + ["Nuitka-Scons: Cached C files (using ccache) with result 'unsupported compiler option': 2"]
        assert compile_cache.parse_build_summary(lines) == {"hits": 80, "compiled": 3}

    @pytest.mark.unit
    def test_tc_cch_009_no_summary_without_ccache(self):
        """TC-CCH-009: no ccache lines (no ccache, or stopped early) gives None, not zeros."""
        assert compile_cache.parse_build_summary(["Nuitka: Starting Python compilation."]) is None

    @pytest.mark.unit
    def test_tc_cch_010_log_line(self):
        """TC-CCH-010: the log says what was reused, or how to turn the cache on."""
        assert compile_cache.describe_summary({"hits": 80, "compiled": 1}, "/usr/bin/ccache") == (
            "C compile cache: reused 80 of 81 C files, compiled 1."
        )
        off = compile_cache.describe_summary(None, None)
        assert "ccache is not installed" in off and "install ccache" in off


STATS = (
    "cache_miss\t82\n"
    "cache_size_kibibyte\t4848\n"
    "direct_cache_hit\t80\n"
    "files_in_cache\t164\n"
    "max_cache_size_kibibyte\t{max}\n"
)


def _fake_ccache(tmp_path: Path, max_kib: int = 5242880, extra: str = "") -> Path:
    """A ccache stand-in that records the store it was pointed at and prints stats."""
    record = tmp_path / "ccache_dir_seen"
    return _executable(
        tmp_path / "bin" / "ccache",
        f'#!/bin/sh\n{extra}echo "$CCACHE_DIR" > {record}\nprintf "{STATS.format(max=max_kib)}"\n',
    )


class TestCacheStatus:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_cch_011_reports_size_limit_and_store(self, tmp_path):
        """TC-CCH-011: size, limit and file count come from ccache, asked about the
        store Nuitka builds use."""
        binary = _fake_ccache(tmp_path)
        env = {"PATH": str(binary.parent), "NUITKA_CACHE_DIR": str(tmp_path / "nuitka")}
        status = await compile_cache.cache_status(env)
        assert status == {
            "enabled": True,
            "binary": str(binary),
            "directory": str(tmp_path / "nuitka" / "ccache"),
            "size_bytes": 4848 * 1024,
            "max_size_bytes": 5242880 * 1024,
            "files": 164,
        }
        assert (tmp_path / "ccache_dir_seen").read_text().strip() == str(tmp_path / "nuitka" / "ccache")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_cch_012_no_limit_is_none(self, tmp_path):
        """TC-CCH-012: a max size of 0 means unlimited, shown as no limit rather than 0 B."""
        binary = _fake_ccache(tmp_path, max_kib=0)
        status = await compile_cache.cache_status({"PATH": str(binary.parent), "NUITKA_CACHE_DIR": str(tmp_path)})
        assert status["max_size_bytes"] is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_cch_013_without_ccache_nothing_runs(self, tmp_path):
        """TC-CCH-013: without ccache the report says off, with where the store would be."""
        status = await compile_cache.cache_status({"PATH": str(tmp_path), "NUITKA_CACHE_DIR": str(tmp_path / "n")})
        assert status["enabled"] is False
        assert status["directory"] == str(tmp_path / "n" / "ccache")
        assert status["size_bytes"] is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_cch_014_a_hanging_ccache_does_not_hang_the_page(self, tmp_path, monkeypatch):
        """TC-CCH-014: a ccache that does not answer is given up on, with anything it
        started, so the page still loads; a surviving child kept the pipe open."""
        monkeypatch.setattr(compile_cache, "_STATS_TIMEOUT", 0.2)
        binary = _fake_ccache(tmp_path, extra="/bin/sleep 5\n")
        started = time.monotonic()
        status = await compile_cache.cache_status({"PATH": str(binary.parent), "NUITKA_CACHE_DIR": str(tmp_path)})
        assert time.monotonic() - started < 2
        assert status["enabled"] is True
        assert status["size_bytes"] is None

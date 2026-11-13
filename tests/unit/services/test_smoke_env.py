"""
Unit tests for the environment handed to a smoke-tested binary.
Source: app/services/nuitka_worker._build_smoke_env

The binary is code the user supplied, and it used to be launched with the
service's entire os.environ. That is not the platform's configuration — it is
whatever happened to be in the shell that ran start.sh, which is unbounded:
an operator's API tokens, agent credentials, another project's settings. On
the machine this was found on, the running service carried an agent messaging
token inherited from the terminal that started it.

The application's own secrets were never in there, because pydantic-settings
reads .env directly. That is precisely why it looked harmless — and moving the
service to a systemd EnvironmentFile= would have put them there without
touching this file.

Nothing here fails loudly if it regresses: the binary starts either way.
"""

import pytest
from pytest_mock import MockerFixture

from app.services.nuitka_worker import _SMOKE_ENV_PASSTHROUGH, _build_smoke_env


@pytest.fixture
def host_env(mocker: MockerFixture):
    """Replace os.environ wholesale so the real one cannot influence a result."""

    def _set(**values: str):
        mocker.patch.dict("app.services.nuitka_worker.os.environ", values, clear=True)

    return _set


class TestSecretsAreNotForwarded:
    @pytest.mark.unit
    def test_tc_smk_001_unlisted_host_variables_are_dropped(self, host_env):
        """TC-SMK-001: _build_smoke_env — the operator's shell does not reach the binary."""
        host_env(
            PATH="/usr/bin",
            CLAUDE_CODE_MESSAGING_TOKEN="agent-secret",
            AWS_SECRET_ACCESS_KEY="aws-secret",
            GITLAB_TOKEN="glpat-xxxx",
            JWT_SECRET_KEY="signing-key",
        )

        env = _build_smoke_env(None)

        assert env == {"PATH": "/usr/bin", "PACKWRIGHT_SMOKE_TEST": "1", "BUILD_CENTER_SMOKE_TEST": "1"}

    @pytest.mark.unit
    def test_tc_smk_002_the_allowlist_carries_nothing_secret_shaped(self):
        """TC-SMK-002: _build_smoke_env — the list itself stays free of credentials.

        Guards the list against growing a plausible-sounding entry later.
        """
        joined = " ".join(_SMOKE_ENV_PASSTHROUGH).upper()
        for word in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH"):
            assert word not in joined

    @pytest.mark.unit
    def test_tc_smk_003_build_host_library_paths_are_not_inherited(self, host_env):
        """TC-SMK-003: _build_smoke_env — the binary cannot resolve against this host.

        LD_LIBRARY_PATH or PYTHONPATH from the build server would let a binary
        find libraries here that will not exist on the machine it ships to —
        it passes the smoke test and fails at the customer, which is the exact
        failure this test is meant to catch.
        """
        host_env(
            PATH="/usr/bin",
            LD_LIBRARY_PATH="/opt/buildhost/lib",
            PYTHONPATH="/srv/projects/other-project",
            PYTHONHOME="/srv/projects/venv",
            VIRTUAL_ENV="/srv/projects/venv",
        )

        env = _build_smoke_env(None)

        assert "LD_LIBRARY_PATH" not in env
        assert "PYTHONPATH" not in env
        assert "PYTHONHOME" not in env
        assert "VIRTUAL_ENV" not in env


class TestTheBinaryCanStillStart:
    """A withheld variable produces a false failure, which is its own bug."""

    @pytest.mark.unit
    def test_tc_smk_010_process_basics_are_passed_through(self, host_env):
        """TC-SMK-010: _build_smoke_env — what a process needs to run at all."""
        host_env(
            PATH="/usr/bin",
            HOME="/home/svc",
            LANG="en_US.UTF-8",
            TZ="Asia/Taipei",
            TMPDIR="/var/tmp",
        )

        env = _build_smoke_env(None)

        assert env["PATH"] == "/usr/bin"
        assert env["HOME"] == "/home/svc"
        assert env["LANG"] == "en_US.UTF-8"
        assert env["TZ"] == "Asia/Taipei"
        assert env["TMPDIR"] == "/var/tmp"

    @pytest.mark.unit
    def test_tc_smk_011_absent_variables_are_omitted_not_blanked(self, host_env):
        """TC-SMK-011: _build_smoke_env — an unset var stays unset.

        Passing HOME="" is worse than not passing it: libraries that test for
        the key find one and build paths from an empty string.
        """
        host_env(PATH="/usr/bin")

        env = _build_smoke_env(None)

        assert "HOME" not in env
        assert "LANG" not in env

    @pytest.mark.unit
    def test_tc_smk_012_the_projects_runtime_config_is_layered_on(self, host_env):
        """TC-SMK-012: _build_smoke_env — Docker ENV and .env still arrive."""
        host_env(PATH="/usr/bin")

        env = _build_smoke_env({"DATABASE_URL": "postgres://x", "API_KEY": "k"})

        assert env["DATABASE_URL"] == "postgres://x"
        assert env["API_KEY"] == "k"

    @pytest.mark.unit
    def test_tc_smk_013_the_project_wins_over_the_host(self, host_env):
        """TC-SMK-013: _build_smoke_env — a project setting PATH is not overridden.

        The host values are a floor, not a policy; a project that ships its
        own PATH or TMPDIR in .env means it.
        """
        host_env(PATH="/usr/bin", TMPDIR="/var/tmp")

        env = _build_smoke_env({"PATH": "/opt/app/bin", "TMPDIR": "/opt/app/tmp"})

        assert env["PATH"] == "/opt/app/bin"
        assert env["TMPDIR"] == "/opt/app/tmp"

    @pytest.mark.unit
    def test_tc_smk_014_the_marker_cannot_be_overridden(self, host_env):
        """TC-SMK-014: _build_smoke_env — a project cannot claim it is not a smoke test.

        Applications branch on this to skip work they shouldn't do during a
        ten-second verification; letting .env unset it would hang the build
        slot instead.
        """
        host_env(PATH="/usr/bin")

        env = _build_smoke_env({"PACKWRIGHT_SMOKE_TEST": "0", "BUILD_CENTER_SMOKE_TEST": "0"})

        assert env["PACKWRIGHT_SMOKE_TEST"] == "1"
        assert env["BUILD_CENTER_SMOKE_TEST"] == "1"


class TestGpuFailureIsNotGuessed:
    """A start-up failure is excused as "no GPU on the build host" only when the
    output is about a GPU. "failed to initialize" alone matched MCP Gate's
    "Failed to initialize database: Auto migration failed", and a program that
    could not start was reported as a warning on a completed build."""

    @pytest.mark.unit
    @pytest.mark.parametrize("line", [
        "RuntimeError: No CUDA-capable device is detected",
        "hipErrorNoDevice: HIP error: no ROCm-capable device is detected",
        "pynvml.NVMLError: Failed to initialize NVML: Driver/library version mismatch",
        "RuntimeError: Failed to initialize the GPU backend",
        "ImportError: libcuda.so.1: cannot open shared object file",
    ])
    def test_tc_smk_015_gpu_initialisation_failures_are_recognised(self, line):
        """TC-SMK-015: what torch, ROCm and NVML print without a GPU still counts."""
        from app.services.nuitka_worker import _looks_like_gpu_failure

        assert _looks_like_gpu_failure(line.lower())

    @pytest.mark.unit
    @pytest.mark.parametrize("line", [
        "ERROR | main:main:324 - Failed to initialize database: Auto migration failed",
        "Failed to initialize logging: permission denied",
        "Traceback ...\nModuleNotFoundError: No module named 'hipster'",
    ])
    def test_tc_smk_016_other_initialisation_failures_are_not(self, line):
        """TC-SMK-016: a failure that names no GPU is a failure."""
        from app.services.nuitka_worker import _looks_like_gpu_failure

        assert not _looks_like_gpu_failure(line.lower())

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_smk_017_a_program_that_cannot_start_fails_the_check(self, tmp_path, mocker):
        """TC-SMK-017: end to end, MCP Gate's start-up failure fails the smoke test."""
        from app.services import nuitka_worker

        mocker.patch.object(nuitka_worker, "_build_smoke_env", return_value={"PATH": "/usr/bin:/bin"})
        binary = tmp_path / "app"
        binary.write_text(
            "#!/bin/sh\n"
            "echo '2026-11-06 16:40:24 | ERROR | main:main:324 - Failed to initialize database: Auto migration failed'\n"
            "exit 1\n"
        )
        binary.chmod(0o755)
        result = await nuitka_worker._smoke_test("t", binary, tmp_path)
        assert result["status"] == "fail"
        assert "Failed to initialize database" in result["detail"]


class TestSmokeTestCleansUp:
    """A service that is still running after the smoke test's window passes, and is
    stopped. A Nuitka onefile binary is a small launcher that starts the real
    program as its child; only the launcher was stopped, so every build of a
    service left the program running on the build host, holding its port (the
    next build of MCP Gate then failed with "port already in use")."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_smk_018_a_long_running_service_is_stopped_with_its_children(self, tmp_path, mocker):
        """TC-SMK-018: the launcher and the program it started are both gone afterwards."""
        from app.services import nuitka_worker

        mocker.patch.object(nuitka_worker, "_build_smoke_env", return_value={"PATH": "/usr/bin:/bin"})
        mocker.patch.object(nuitka_worker, "_SMOKE_WINDOW", 1.0)
        child_pid = tmp_path / "child.pid"
        binary = tmp_path / "launcher"
        # Like a onefile launcher: start the real program, then wait on it.
        binary.write_text(f"#!/bin/sh\n/bin/sleep 300 &\necho $! > {child_pid}\nwait\n")
        binary.chmod(0o755)

        import asyncio

        # Bounded: when the launcher alone is stopped, waiting on it can hang.
        # Run it elsewhere: what the program writes in its cwd is removed afterwards.
        out = tmp_path / "out"
        out.mkdir()
        result = await asyncio.wait_for(nuitka_worker._smoke_test("t", binary, out), timeout=15)

        assert result["status"] == "pass" and "still running" in result["detail"]
        pid = int(child_pid.read_text())
        assert _stopped_within(pid, seconds=3), "the program the launcher started is still running"


def _stopped_within(pid: int, seconds: float) -> bool:
    """Whether a process has stopped: gone, or dead and waiting to be reaped.

    A killed child whose parent died too is a zombie until init reaps it; in a CI
    container that can take a while, and os.kill(pid, 0) still finds it there.
    """
    import time
    from pathlib import Path

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            return True
        if state == "Z":
            return True
        time.sleep(0.05)
    return False


class TestSmokeTestLeavesNoState:
    """The program runs in the output directory, and that directory is what the
    build hands out. Packaging MCP Gate left its database (signing keys),
    secrets/secrets.json (encryption key, setup token) and logs/ from the smoke
    run in the downloadable archive."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_smk_019_what_the_program_writes_is_removed(self, tmp_path, mocker):
        """TC-SMK-019: new files and folders are gone afterwards; the output's own files stay."""
        from app.services import nuitka_worker

        mocker.patch.object(nuitka_worker, "_build_smoke_env", return_value={"PATH": "/usr/bin:/bin"})
        log = mocker.patch.object(nuitka_worker.task_manager, "append_log", mocker.AsyncMock())
        out = tmp_path / "dist"
        (out / "config").mkdir(parents=True)
        (out / "config" / "app.yaml").write_text("a: 1\n")
        binary = out / "main"
        binary.write_text(
            "#!/bin/sh\nmkdir -p data secrets\necho key > secrets/secrets.json\n"
            "echo db > data/app.db\necho cache > config/cache.tmp\n"
        )
        binary.chmod(0o755)

        result = await nuitka_worker._smoke_test("t", binary, out)

        assert result["status"] == "pass"
        assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*")) == ["config", "config/app.yaml", "main"]
        logged = " ".join(str(c.args[1]) for c in log.call_args_list)
        assert "data" in logged and "secrets" in logged and "config/cache.tmp" in logged

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_smk_020_a_changed_file_is_reported(self, tmp_path, mocker):
        """TC-SMK-020: a file of the output the program rewrote cannot be put back, so it is named in the log."""
        from app.services import nuitka_worker

        mocker.patch.object(nuitka_worker, "_build_smoke_env", return_value={"PATH": "/usr/bin:/bin"})
        log = mocker.patch.object(nuitka_worker.task_manager, "append_log", mocker.AsyncMock())
        (tmp_path / "settings.json").write_text("{}")
        binary = tmp_path / "main"
        binary.write_text('#!/bin/sh\necho \'{"x": 1}\' > settings.json\n')
        binary.chmod(0o755)

        await nuitka_worker._smoke_test("t", binary, tmp_path)

        assert any("settings.json" in str(c.args[1]) and "changed" in str(c.args[1]) for c in log.call_args_list)

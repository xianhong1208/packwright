"""
Tests for smoke-testing the Docker image itself.
Source: app/services/image_smoke.py, app/services/docker_worker.py (_verify_image),
app/services/nuitka_worker.py (smoke_target)

A Docker build used to run the binary on the build host with the Docker ENV,
whose container paths (MCP Gate: /app/config) do not exist there: a correct
image failed, and the image itself was never started. Now the image runs under
a unique name and is removed afterwards.
"""

import pytest

from app.schemas.task import BuildConfig
from app.services import docker_worker, image_smoke, nuitka_worker

TCP = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    "   0: 00000000:11F6 00000000:0000 0A 00000000:00000000 00:00000000 00000000 10001        0 1111 1\n"
)


class FakeDocker:
    """Answers the docker CLI calls image_smoke makes, and records them."""

    def __init__(self, *, runs: bool = True, exit_code: int = 0, logs: str = "", diff: str = "", start_ok: bool = True):
        self.calls: list[tuple[str, ...]] = []
        self.runs, self.exit_code, self.logs, self.diff, self.start_ok = runs, exit_code, logs, diff, start_ok

    async def __call__(self, *args: str, timeout: float = 60):
        self.calls.append(args)
        verb = args[0]
        if verb == "run":
            return (0, "cid\n") if self.start_ok else (125, "Error: no such image")
        if verb == "inspect":
            return 0, ("true 0" if self.runs else f"false {self.exit_code}")
        if verb == "exec" and "cat" in args:
            return 0, TCP
        if verb == "exec" and "ls" in args:
            return 0, "data/\nsecrets/\nmain\nlibs/\n"
        if verb == "diff":
            return 0, self.diff
        if verb == "logs":
            return 0, self.logs
        return 0, ""

    def names(self, verb: str) -> list[str]:
        return [c[c.index("--name") + 1] if verb == "run" else c[-1] for c in self.calls if c[0] == verb]


@pytest.fixture
def docker(mocker):
    def make(**kw):
        fake = FakeDocker(**kw)
        mocker.patch.object(image_smoke, "_docker", new=fake)
        return fake
    return make


@pytest.mark.unit
def test_tc_ismk_001_unique_container_names():
    """TC-ISMK-001: container_name — named after the repository, unique per run."""
    a = image_smoke.container_name("registry.example.com/team/mcp_gate:1.4.0")
    b = image_smoke.container_name("registry.example.com/team/mcp_gate:1.4.0")
    assert a.startswith("mcp_gate-smoke-") and b.startswith("mcp_gate-smoke-") and a != b


@pytest.mark.unit
def test_tc_ismk_002_created_dirs_from_docker_diff():
    """TC-ISMK-002: created_dirs — new top-level folders under /app; not files, hidden or deeper ones."""
    diff = "C /app\nA /app/data\nA /app/data/app.db\nA /app/app.log\nA /app/.cache\nA /app/.cache/x\nA /tmp/onefile_1\nA /tmp/onefile_1/x\nC /app/libs\nA /app/libs/new\nA /app/logs\n"
    assert image_smoke.created_dirs(diff) == ["data"]
    assert image_smoke.created_dirs(diff, existing_dirs={"logs", "libs"}) == ["data", "logs"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_ismk_003_a_running_service_passes_and_is_removed(docker):
    """TC-ISMK-003: still running after the window: pass, with its ports and new folders; the container is removed."""
    fake = docker(diff="A /app/data\nA /app/data/db\nA /app/secrets\n")

    result = await image_smoke.smoke_test_image("mcp_gate:1.4.0", window=0.2)

    assert result["status"] == "pass" and result["target"] == "image"
    assert result["listeners"] == [{"port": 4598, "address": "0.0.0.0"}]
    assert result["created_dirs"] == ["data", "secrets"]
    assert fake.names("rm") == fake.names("run") == [result["container"]]
    assert ("rm", "-f", "-v", result["container"]) in fake.calls  # its anonymous volumes too


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_ismk_004_a_failed_start_fails_with_its_output(docker):
    """TC-ISMK-004: an exit within the window is judged like the binary's, from the container's logs."""
    fake = docker(runs=False, exit_code=1, logs="Missing config file(s) in /app/config\n")

    result = await image_smoke.smoke_test_image("mcp_gate:1.4.0", window=0.2)

    assert result["status"] == "fail" and result["exit_code"] == 1
    assert "Missing config file(s) in /app/config" in result["detail"]
    assert fake.names("rm") == [result["container"]]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_ismk_005_an_image_that_does_not_start_fails_and_is_cleaned(docker):
    """TC-ISMK-005: docker run itself failing is a failure, and the name is still removed."""
    fake = docker(start_ok=False)
    result = await image_smoke.smoke_test_image("missing:1", window=0.2)
    assert result["status"] == "fail" and "did not start" in result["detail"]
    assert fake.names("rm") == [result["container"]]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_ismk_006_cancel_stops_and_removes(docker):
    """TC-ISMK-006: a cancelled build ends the test early and still removes the container."""
    fake = docker()

    async def cancelled():
        return True

    result = await image_smoke.smoke_test_image("mcp_gate:1.4.0", window=30, is_cancelled=cancelled)
    assert result["status"] == "skipped"
    assert fake.names("rm") == [result["container"]]


@pytest.mark.unit
def test_tc_ismk_007_the_image_is_tested_when_docker_is_here(mocker):
    """TC-ISMK-007: smoke_target — the image for a Docker build with Docker present; else the binary."""
    which = mocker.patch.object(nuitka_worker.shutil, "which", return_value="/usr/bin/docker")
    assert nuitka_worker.smoke_target(BuildConfig(docker_enabled=True)) == "image"
    assert nuitka_worker.smoke_target(BuildConfig(docker_enabled=False)) == "binary"
    which.return_value = None
    assert nuitka_worker.smoke_target(BuildConfig(docker_enabled=True)) == "binary"


def _quiet(mocker):
    tm = docker_worker.task_manager
    for name in ("append_log", "update_task", "set_stage"):
        mocker.patch.object(tm, name, mocker.AsyncMock())
    return (mocker.patch.object(tm, "merge_result", mocker.AsyncMock()),
            mocker.patch.object(tm, "record_config_value", mocker.AsyncMock()))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_ismk_008_image_verdict_fails_the_build(tmp_path, mocker):
    """TC-ISMK-008: run_docker_build — a failed image smoke test fails the build and is stored as the verdict."""
    (tmp_path / "dist").mkdir()
    merge, _ = _quiet(mocker)
    mocker.patch.object(docker_worker.shutil, "which", return_value="/usr/bin/docker")
    mocker.patch.object(docker_worker, "_run_docker_command", mocker.AsyncMock(return_value=True))
    mocker.patch.object(docker_worker, "smoke_test_image", mocker.AsyncMock(return_value={
        "status": "fail", "detail": "exit 1", "exit_code": 1, "target": "image", "container": "x"}))
    export = mocker.patch.object(docker_worker, "_image_size", mocker.AsyncMock(return_value=1))
    config = BuildConfig(project_type="backend_only", project_path=str(tmp_path), docker_enabled=True,
                         output_name="main", docker_volumes="")

    assert await docker_worker.run_docker_build("t1", config, db=None, precompiled=True) is False
    verdicts = [c.args[1]["verify"] for c in merge.call_args_list if "verify" in c.args[1]]
    assert verdicts and verdicts[-1]["status"] == "fail"
    export.assert_not_awaited()  # nothing is exported


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_ismk_009_found_volumes_rebuild_and_retest(tmp_path, mocker):
    """TC-ISMK-009: Volumes unset — the folders the image created become VOLUMEs, the image is
    built and tested again, the value is saved, and the port is checked inside the container."""
    (tmp_path / "dist").mkdir()
    merge, record = _quiet(mocker)
    mocker.patch.object(docker_worker.shutil, "which", return_value="/usr/bin/docker")
    dockerfiles: list[str] = []

    async def build(task_id, cmd, cwd):
        dockerfiles.append((tmp_path / "Dockerfile.generated").read_text())
        return True

    mocker.patch.object(docker_worker, "_run_docker_command", side_effect=build)
    first = {"status": "pass", "detail": "", "exit_code": None, "target": "image", "container": "a",
             "created_dirs": ["data", "secrets"], "listeners": [{"port": 4598, "address": "0.0.0.0"}]}
    second = {**first, "container": "b", "created_dirs": []}
    smoke = mocker.patch.object(docker_worker, "smoke_test_image", mocker.AsyncMock(side_effect=[first, second]))
    mocker.patch.object(docker_worker, "_image_size", mocker.AsyncMock(return_value=None))
    mocker.patch.object(docker_worker.os, "pipe", side_effect=OSError("no export in this test"))
    config = BuildConfig(project_type="backend_only", project_path=str(tmp_path), docker_enabled=True,
                         output_name="main", docker_expose_port=8000)

    assert await docker_worker.run_docker_build("t1", config, db=None, precompiled=True) is True

    assert smoke.await_count == 2 and len(dockerfiles) == 2
    assert "VOLUME" not in dockerfiles[0] and 'VOLUME ["/app/data", "/app/secrets"]' in dockerfiles[1]
    record.assert_awaited_once_with("t1", "docker_volumes", "data, secrets", None)
    patch = next(c.args[1] for c in merge.call_args_list if "verify" in c.args[1])
    assert patch["verify"]["container"] == "b" and patch["verify"]["created_dirs"] == ["data", "secrets"]
    assert patch["port_check"]["suggested"] == 4598

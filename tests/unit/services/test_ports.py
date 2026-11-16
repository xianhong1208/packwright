"""
Tests for the port check of a smoke run.
Source: app/services/ports.py, app/services/nuitka_worker.py (_smoke_test, docker_port_check)

Quick build suggested port 8000 for MCP Gate; the image exposed 8000 while the
program listened on its own SERVER_PORT, and nothing said so. The smoke test now
notes the ports the program listens on and warns, with the port to use, when the
image exposes another. It never changes the setting.
"""

import socket
import sys

import pytest

from app.schemas.task import BuildConfig
from app.services import nuitka_worker
from app.services.ports import Listener, parse_proc_net_tcp, port_check

TCP = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    "   0: 00000000:11F6 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1111 1\n"
    "   1: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 2222 1\n"
    "   2: 0100007F:11F6 0100007F:D431 01 00000000:00000000 00:00000000 00000000     0        0 3333 1\n"
)
TCP6 = (
    "  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    "   0: 00000000000000000000000001000000:1F91 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 4444 1\n"
)


@pytest.mark.unit
def test_tc_port_001_listening_sockets_are_read():
    """TC-PORT-001: parse_proc_net_tcp — LISTEN rows only, addresses decoded, filtered by inode."""
    assert parse_proc_net_tcp(TCP) == {Listener(4598, "0.0.0.0"), Listener(8080, "127.0.0.1")}
    assert parse_proc_net_tcp(TCP, {"1111", "3333"}) == {Listener(4598, "0.0.0.0")}
    assert parse_proc_net_tcp(TCP6) == {Listener(8081, "::1")}


@pytest.mark.unit
def test_tc_port_002_loopback_addresses():
    """TC-PORT-002: Listener.loopback — 127.x, ::1 and IPv4-mapped loopback; not the wildcard."""
    assert Listener(1, "127.0.0.1").loopback and Listener(1, "::1").loopback
    assert Listener(1, "::ffff:127.0.0.1").loopback
    assert not Listener(1, "0.0.0.0").loopback and not Listener(1, "::").loopback


@pytest.mark.unit
def test_tc_port_003_mismatch_suggests_the_reachable_port():
    """TC-PORT-003: port_check — a different port is reported with the lowest non-loopback one suggested."""
    result = port_check({Listener(9000, "127.0.0.1"), Listener(4598, "0.0.0.0")}, 8000)
    assert result["listening"] == [4598, 9000]
    assert result["suggested"] == 4598
    assert "listens on 4598, 9000, but the image exposes 8000" in result["message"]


@pytest.mark.unit
def test_tc_port_004_matching_or_silent_programs_say_nothing():
    """TC-PORT-004: port_check — the exposed port among them: no message; no ports at all: no check."""
    assert port_check({Listener(8000, "0.0.0.0"), Listener(9100, "0.0.0.0")}, 8000)["message"] == ""
    assert port_check(set(), 8000) is None


@pytest.mark.unit
def test_tc_port_005_loopback_only_in_a_container():
    """TC-PORT-005: port_check — in a container, the right port on 127.0.0.1 only is unreachable too."""
    result = port_check({Listener(8000, "127.0.0.1")}, 8000, container=True)
    assert result["suggested"] is None and "only on 127.0.0.1" in result["message"]
    assert port_check({Listener(8000, "127.0.0.1")}, 8000)["message"] == ""


@pytest.mark.unit
def test_tc_port_006_only_docker_builds_are_checked():
    """TC-PORT-006: docker_port_check — compares with the configured port, for Docker builds only."""
    verify = {"listeners": [{"port": 4598, "address": "0.0.0.0"}]}
    docker = BuildConfig(docker_enabled=True, docker_expose_port=8000)
    assert nuitka_worker.docker_port_check(docker, verify)["suggested"] == 4598
    assert nuitka_worker.docker_port_check(BuildConfig(docker_enabled=False), verify) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_port_007_a_real_service_port_is_seen(tmp_path, mocker):
    """TC-PORT-007: _smoke_test — the port a launched program's child opens a second in is recorded."""
    mocker.patch.object(nuitka_worker, "_SMOKE_WINDOW", 3.0)
    mocker.patch.object(nuitka_worker, "_build_smoke_env", return_value={"PATH": "/usr/bin:/bin"})
    mocker.patch.object(nuitka_worker.task_manager, "append_log", mocker.AsyncMock())
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = tmp_path / "server.py"
    server.write_text(
        "import socket, time\ntime.sleep(1)\n"
        f"s = socket.socket(); s.bind(('0.0.0.0', {port})); s.listen()\ntime.sleep(30)\n"
    )
    binary = tmp_path / "launcher"  # like a onefile launcher: the listener is its child
    binary.write_text(f"#!/bin/sh\n{sys.executable} {server}\n")
    binary.chmod(0o755)

    result = await nuitka_worker._smoke_test("t", binary, tmp_path)

    assert result["status"] == "pass"
    assert {"port": port, "address": "0.0.0.0"} in result["listeners"]

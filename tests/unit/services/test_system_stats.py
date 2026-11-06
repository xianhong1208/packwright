"""
Tests for the shared machine snapshot.
Source: app/services/system_stats.py (SystemStatsSampler)

Every open Machine or home page polls it; it used to collect from scratch per
request, sleeping 0.2 s and reading a sysfs file per core each time.
"""

import asyncio
import time

import pytest

from app.services import system_stats
from app.services.system_stats import SystemStatsSampler


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def counted(mocker):
    """Count full collections without touching the real machine."""
    def make(sampler: SystemStatsSampler):
        calls = {"n": 0}

        def fake_collect():
            # Slow enough that the other requests arrive while it runs: an
            # instant collection finishes before they start and hides a race.
            time.sleep(0.05)
            calls["n"] += 1
            return {"n": calls["n"]}

        mocker.patch.object(sampler, "collect", side_effect=fake_collect)
        return calls
    return make


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_sys_001_viewers_share_one_collection(clock, counted):
    """TC-SYS-001: requests within max_age share one snapshot, and concurrent ones
    wait for a single collection instead of each starting their own."""
    sampler = SystemStatsSampler(max_age=1.5, clock=clock, has_nvidia_smi=False)
    calls = counted(sampler)

    results = await asyncio.gather(*(sampler.get() for _ in range(5)))
    clock.now += 1.0
    later = await sampler.get()

    assert calls["n"] == 1
    assert all(r == {"n": 1} for r in results) and later == {"n": 1}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_sys_002_an_old_snapshot_is_replaced(clock, counted):
    """TC-SYS-002: once max_age has passed the next request collects again."""
    sampler = SystemStatsSampler(max_age=1.5, clock=clock, has_nvidia_smi=False)
    calls = counted(sampler)

    await sampler.get()
    clock.now += 1.6
    assert await sampler.get() == {"n": 2}
    assert calls["n"] == 2


@pytest.mark.unit
def test_tc_sys_003_core_counts_are_physical_and_logical(mocker):
    """TC-SYS-003: count_physical is the physical core count. It used to be
    psutil.cpu_count() — the logical count — so the page read "128 threads on 128 cores"."""
    mocker.patch.object(system_stats.psutil, "cpu_count", side_effect=lambda logical=True: 128 if logical else 64)
    sampler = SystemStatsSampler(has_nvidia_smi=False)

    cpu = sampler.collect()["cpu"]

    assert (cpu["count_physical"], cpu["count_logical"]) == (64, 128)


@pytest.mark.unit
def test_tc_sys_004_no_gpu_probe_without_nvidia_smi(mocker):
    """TC-SYS-004: without nvidia-smi there is nothing to probe; the probe is not run."""
    probe = mocker.patch.object(system_stats, "_gpu_info", return_value=[{"id": 0}])

    assert SystemStatsSampler(has_nvidia_smi=False).collect()["gpus"] == []
    probe.assert_not_called()
    assert SystemStatsSampler(has_nvidia_smi=True).collect()["gpus"] == [{"id": 0}]


@pytest.mark.unit
def test_tc_sys_005_frequency_is_read_sparingly(mocker, clock):
    """TC-SYS-005: cpu_freq() reads a file per core, so it is refreshed only every
    freq_max_age seconds, not on every snapshot."""
    freq = mocker.patch.object(system_stats.psutil, "cpu_freq", return_value=None)
    sampler = SystemStatsSampler(freq_max_age=10, clock=clock, has_nvidia_smi=False)

    sampler.collect()
    clock.now += 5
    sampler.collect()
    assert freq.call_count == 1
    clock.now += 6
    sampler.collect()
    assert freq.call_count == 2

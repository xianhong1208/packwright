"""One shared snapshot of the machine's load, for every page that shows it.

The Machine page polls every 2 seconds and the home page every 5, per open tab.
Each poll used to collect everything from scratch: two ``cpu_percent`` calls that
each slept 0.1 s, ``cpu_freq()`` (which reads a sysfs file per core, ~16 ms of CPU
on a 128-core host) and a GPU probe. One open Machine tab cost the server ~13x its
idle CPU, and every extra viewer added the same again.

Now one snapshot serves everyone for ``max_age`` seconds and concurrent requests
wait for a single collection. Facts that cannot change while the process runs
(core counts, maximum frequency, whether nvidia-smi exists) are read once, the
current frequency at most every ``freq_max_age`` seconds, and CPU load is read
without sleeping: psutil measures it against the previous call, which the
sampler itself made.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from collections.abc import Callable
from typing import Any

import psutil


def _gpu_info() -> list[dict]:
    """GPU load via GPUtil (which runs nvidia-smi)."""
    try:
        import GPUtil

        return [
            {
                "id": gpu.id,
                "name": gpu.name,
                "load": round(gpu.load * 100, 1),
                "memory_used": round(gpu.memoryUsed, 1),
                "memory_total": round(gpu.memoryTotal, 1),
                "memory_percent": round(gpu.memoryUsed / gpu.memoryTotal * 100, 1) if gpu.memoryTotal > 0 else 0,
                "temperature": gpu.temperature,
            }
            for gpu in GPUtil.getGPUs()
        ]
    except Exception:
        return []


class SystemStatsSampler:
    """Collects the machine snapshot at most once per ``max_age`` seconds."""

    def __init__(
        self,
        max_age: float = 1.5,
        freq_max_age: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        has_nvidia_smi: bool | None = None,
    ) -> None:
        self.max_age = max_age
        self.freq_max_age = freq_max_age
        self._clock = clock
        self._snapshot: dict[str, Any] | None = None
        self._taken_at = float("-inf")
        self._freq: Any = None
        self._freq_at = float("-inf")
        self._lock = asyncio.Lock()
        # Fixed for the life of the process.
        self._count_logical = psutil.cpu_count(logical=True) or 0
        self._count_physical = psutil.cpu_count(logical=False) or self._count_logical
        self._has_nvidia_smi = shutil.which("nvidia-smi") is not None if has_nvidia_smi is None else has_nvidia_smi
        # The first non-blocking reading is measured from this call.
        psutil.cpu_percent()
        psutil.cpu_percent(percpu=True)

    async def get(self) -> dict[str, Any]:
        """The current snapshot, collected now only if the last one is too old."""
        if self._clock() - self._taken_at < self.max_age and self._snapshot is not None:
            return self._snapshot
        async with self._lock:
            # Another request may have collected while this one waited.
            if self._clock() - self._taken_at < self.max_age and self._snapshot is not None:
                return self._snapshot
            self._snapshot = await asyncio.to_thread(self.collect)
            self._taken_at = self._clock()
            return self._snapshot

    def _cpu_freq(self) -> Any:
        if self._clock() - self._freq_at >= self.freq_max_age:
            try:
                self._freq = psutil.cpu_freq()
            except Exception:
                self._freq = None
            self._freq_at = self._clock()
        return self._freq

    def collect(self) -> dict[str, Any]:
        """Read everything once (blocking; run it off the event loop)."""
        cpu_freq = self._cpu_freq()
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")
        net_io = psutil.net_io_counters()
        return {
            "cpu": {
                "percent": psutil.cpu_percent(),
                "percent_per_core": psutil.cpu_percent(percpu=True),
                "count_physical": self._count_physical,
                "count_logical": self._count_logical,
                "frequency_current": round(cpu_freq.current, 0) if cpu_freq else None,
                "frequency_max": round(cpu_freq.max, 0) if cpu_freq and cpu_freq.max else None,
            },
            "memory": {
                "total": memory.total,
                "available": memory.available,
                "used": memory.used,
                "percent": memory.percent,
            },
            "swap": {"total": swap.total, "used": swap.used, "percent": swap.percent},
            "disk": {"total": disk.total, "used": disk.used, "free": disk.free, "percent": disk.percent},
            "network": {"bytes_sent": net_io.bytes_sent, "bytes_recv": net_io.bytes_recv},
            # No nvidia-smi on this host: there is nothing to probe, every time.
            "gpus": _gpu_info() if self._has_nvidia_smi else [],
        }


_sampler: SystemStatsSampler | None = None


def get_sampler() -> SystemStatsSampler:
    """The process-wide sampler (created on first use, inside the event loop)."""
    global _sampler
    if _sampler is None:
        _sampler = SystemStatsSampler()
    return _sampler

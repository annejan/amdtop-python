"""Dataclasses describing one collected frame of telemetry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .history import Series


@dataclass
class CpuSample:
    total_pct: float
    per_cpu_pct: list[float]
    per_core_mhz: list[int]
    avg_mhz: int | None
    temp_c: float | None
    power_w: float | None
    loadavg: tuple[float, float, float] | None
    model: str
    n_threads: int


@dataclass
class MemSample:
    total: int | None
    used: int | None
    available: int | None
    cached: int | None
    swap_total: int | None
    swap_used: int | None

    @property
    def used_pct(self) -> float | None:
        if not self.total or self.used is None:
            return None
        return 100.0 * self.used / self.total

    @property
    def swap_pct(self) -> float | None:
        if not self.swap_total or self.swap_used is None:
            return None
        return 100.0 * self.swap_used / self.swap_total


@dataclass
class IgpuSample:
    marketing: str | None
    codename: str | None
    arch: str | None
    gfx: str | None
    cu_count: int | None
    busy_pct: float | None
    mem_busy_pct: float | None
    vram_used: int | None
    vram_total: int | None
    gtt_used: int | None
    gtt_total: int | None
    sclk_mhz: int | None
    sclk_max_mhz: int | None
    fclk_mhz: int | None
    uclk_mhz: int | None
    temp_c: float | None
    power_w: float | None
    dram_read_mbps: int | None = None
    dram_write_mbps: int | None = None
    sclk_history: "Series | None" = None
    temp_history: "Series | None" = None
    power_history: "Series | None" = None
    # Per-throttler residency history in percent of each sample interval (one
    # Series or None per counter, indexed by gpu_metrics.THROTTLE_NAMES order).
    throttle_history: list = field(default_factory=list)
    # Current absolute residency accumulator per throttler (milliseconds spent
    # throttled since boot), same indexing.
    throttle_absolute: list = field(default_factory=list)

    @property
    def dram_total_mbps(self) -> int | None:
        if self.dram_read_mbps is None and self.dram_write_mbps is None:
            return None
        return (self.dram_read_mbps or 0) + (self.dram_write_mbps or 0)


@dataclass
class NpuSample:
    present: bool
    activity: list[int]
    power_w: float | None
    clk_mhz: int | None
    power_state: str | None
    fw_version: str | None
    name: str | None

    @property
    def activity_max(self) -> float | None:
        return max(self.activity) if self.activity else None

    @property
    def activity_avg(self) -> float | None:
        return sum(self.activity) / len(self.activity) if self.activity else None


@dataclass
class GpuProcess:
    pid: int
    user: str | None
    comm: str
    gpu_pct: float | None  # None when the driver exposes no per-engine busy time
    vram_bytes: int
    gtt_bytes: int
    runtime_s: float | None = None  # wall-clock age of the process, None if unknown


@dataclass
class Frame:
    host: str
    uptime_s: float | None
    cpu: CpuSample
    mem: MemSample
    igpu: IgpuSample
    npu: NpuSample
    socket_power_w: float | None = None
    gpu_procs: list[GpuProcess] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

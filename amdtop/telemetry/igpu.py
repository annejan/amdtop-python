"""Integrated GPU (Radeon 8000S / 800M) telemetry from amdgpu sysfs + gpu_metrics."""

from __future__ import annotations

import time

from .. import config
from . import sysfs
from .decode import cu_count, decode_igpu
from .gpu_metrics import THROTTLE_NAMES, GpuMetrics
from .history import MetricHistory
from .sample import IgpuSample


def throttle_pct(delta_ms: int, elapsed_s: float) -> float | None:
    """Share of ``elapsed_s`` a throttler was engaged, in percent.

    The throttle_residency accumulators count milliseconds spent throttled
    (measured: each saturates at ~1000 per second under a sustained limit).
    Returns None when the interval is unusable or the counter went backwards
    (firmware reset); clamps small timing jitter above 100%.
    """
    if elapsed_s <= 0 or delta_ms < 0:
        return None
    return min(100.0, delta_ms / (elapsed_s * 1000.0) * 100.0)


class IgpuSource:
    def __init__(self) -> None:
        # GPU identity is fixed for the life of the process; decode it once.
        self._info = decode_igpu(config.DRM_DEVICE)
        self._cu_count = cu_count(self._info.gfx)
        self._sclk_hist = MetricHistory(config.IGPU_HISTORY_WINDOW_S)
        self._temp_hist = MetricHistory(config.IGPU_HISTORY_WINDOW_S)
        self._power_hist = MetricHistory(config.IGPU_HISTORY_WINDOW_S)
        # Previous throttle accumulators and when they were read, for
        # frame-to-frame residency.
        self._throttle_prev: list[int] | None = None
        self._throttle_prev_t: float | None = None
        # One residency-% history per throttler, for per-counter trend plots.
        self._throttle_hist = [
            MetricHistory(config.IGPU_HISTORY_WINDOW_S) for _ in THROTTLE_NAMES
        ]

    def read(self, gm: GpuMetrics | None) -> IgpuSample:
        busy: float | None = None
        sclk = sclk_max = fclk = uclk = None
        temp = power = None
        dram_r = dram_w = None
        if gm is not None:
            busy = gm.gfx_activity
            sclk, sclk_max = gm.gfxclk, gm.gfx_maxfreq
            fclk, uclk = gm.fclk, gm.uclk
            temp, power = gm.temp_gfx, gm.gfx_power
            dram_r, dram_w = gm.dram_reads, gm.dram_writes

        if busy is None:
            busy = sysfs.read_int(config.GPU_BUSY)

        self._sclk_hist.record(sclk)
        self._temp_hist.record(temp)
        self._power_hist.record(power)
        width = config.IGPU_HISTORY_WIDTH

        throttle_history: list = [None] * len(THROTTLE_NAMES)
        throttle_absolute: list = [None] * len(THROTTLE_NAMES)
        if gm is not None and gm.throttle_residency:
            cur = gm.throttle_residency
            now = time.monotonic()
            prev, prev_t = self._throttle_prev, self._throttle_prev_t
            if prev is not None and prev_t is not None and len(prev) == len(cur):
                for i, (c, p) in enumerate(zip(cur, prev)):
                    pct = throttle_pct(c - p, now - prev_t)
                    if pct is not None:
                        self._throttle_hist[i].record(pct)
            self._throttle_prev, self._throttle_prev_t = cur, now
            throttle_history = [h.series(width) for h in self._throttle_hist]
            throttle_absolute = list(cur)

        return IgpuSample(
            marketing=self._info.marketing,
            codename=self._info.codename,
            arch=self._info.arch,
            gfx=self._info.gfx,
            cu_count=self._cu_count,
            busy_pct=busy,
            mem_busy_pct=sysfs.read_int(config.MEM_BUSY),
            vram_used=sysfs.read_int(config.VRAM_USED),
            vram_total=sysfs.read_int(config.VRAM_TOTAL),
            gtt_used=sysfs.read_int(config.GTT_USED),
            gtt_total=sysfs.read_int(config.GTT_TOTAL),
            sclk_mhz=sclk,
            sclk_max_mhz=sclk_max,
            fclk_mhz=fclk,
            uclk_mhz=uclk,
            temp_c=temp,
            power_w=power,
            dram_read_mbps=dram_r,
            dram_write_mbps=dram_w,
            sclk_history=self._sclk_hist.series(width),
            temp_history=self._temp_hist.series(width),
            power_history=self._power_hist.series(width),
            throttle_history=throttle_history,
            throttle_absolute=throttle_absolute,
        )

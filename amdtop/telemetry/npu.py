"""NPU (XDNA / amdxdna) telemetry.

v1 reads NPU load/power/clock from the no-root ``gpu_metrics`` IPU fields, plus
identity (power_state, firmware, name) from the accel sysfs node. The ``NpuSource``
ABC lets a future root ``DebugfsNpuSource`` add per-process attribution without any
change to the UI.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .. import config
from . import sysfs
from .gpu_metrics import GpuMetrics
from .sample import NpuSample


class NpuSource(ABC):
    @abstractmethod
    def read(self, gm: GpuMetrics | None) -> NpuSample: ...


class GpuMetricsNpuSource(NpuSource):
    """No-root NPU source backed by gpu_metrics IPU fields + accel sysfs identity."""

    def __init__(self) -> None:
        dev = config.NPU_DEVICE
        self._power_state_path = f"{dev}/power_state"
        self._name = sysfs.read_text(f"{dev}/vbnv")
        self._fw = sysfs.read_text(f"{dev}/fw_version")
        self._present = self._fw is not None or self._name is not None

    def read(self, gm: GpuMetrics | None) -> NpuSample:
        activity: list[int] = []
        power = clk = rd = wr = None
        if gm is not None:
            activity = list(gm.ipu_activity)
            power = gm.ipu_power
            clk = gm.ipuclk
            rd, wr = gm.ipu_reads, gm.ipu_writes

        return NpuSample(
            present=self._present,
            activity=activity,
            power_w=power,
            clk_mhz=clk,
            power_state=sysfs.read_text(self._power_state_path),
            fw_version=self._fw,
            name=self._name,
            dram_read_mbps=rd,
            dram_write_mbps=wr,
        )

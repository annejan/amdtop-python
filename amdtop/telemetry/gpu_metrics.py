"""Parser for the amdgpu ``gpu_metrics_v3_0`` sysfs blob (Strix Halo APU).

The 264-byte table is emitted by the SMU firmware and exposed read-only (no root)
at ``/sys/class/drm/card1/device/gpu_metrics``. It is the single golden source for
per-core CPU, iGPU (gfx), and NPU (IPU) activity/power/clocks on this platform.

The struct uses natural C alignment (padding before the u64 and some u32s), so the
format string below encodes that padding explicitly. Verified byte-exact against a
live blob: temperatures cross-check with ``sensors`` edge, socket power with PPT,
gfxclk with ``pp_dpm_sclk``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .. import config

# Sentinels the firmware writes for "not populated" fields.
_U16_INVALID = 0xFFFF
_U32_INVALID = 0xFFFFFFFF

# Names of the seven throttle_residency accumulators, in blob order.
THROTTLE_NAMES = ["prochot", "spl", "fppt", "sppt", "thm_core", "thm_gfx", "thm_soc"]

# gpu_metrics_v3_0, little-endian, natural C alignment (pad bytes marked 'x').
_FMT = (
    "<"
    "HBB"      # common_header: structure_size, format_revision, content_revision
    "HH16HH"   # temperature: gfx, soc, core[16], skin  (centi-degC)
    "HH8H16H"  # activity: gfx, vcn, ipu[8], core_c0[16]  (percent)
    "4H"       # dram_reads, dram_writes, ipu_reads, ipu_writes  (MB/s)
    "xxQ"      # (pad) system_clock_counter
    "IHxx"     # socket_power, ipu_power, (pad)          (milliwatts)
    "IIII"     # apu_power, gfx_power, dgpu_power, all_core_power  (milliwatts)
    "16H"      # core_power[16]                          (milliwatts)
    "HHH"      # sys_power, stapm_power_limit, current_stapm_power_limit
    "8H"       # gfxclk, socclk, vpeclk, ipuclk, fclk, vclk, uclk, mpipu  (MHz)
    "16H"      # current_coreclk[16]                     (MHz)
    "HH"       # current_core_maxfreq, current_gfx_maxfreq
    "xx7I"     # (pad) throttle_residency x7
    "I"        # time_filter_alphavalue
)
_SIZE = struct.calcsize(_FMT)  # 260 payload bytes; blob has 4 trailing pad bytes


def _clean16(v: int) -> int | None:
    return None if v == _U16_INVALID else v


def _clean32(v: int) -> int | None:
    return None if v == _U32_INVALID else v


@dataclass
class GpuMetrics:
    """Scaled view of one gpu_metrics_v3_0 sample.

    Temperatures are degrees C, power is watts, clocks are MHz, activity is percent.
    Fields the firmware did not populate are ``None``.
    """

    structure_size: int
    format_revision: int
    content_revision: int

    temp_gfx: float | None
    temp_soc: float | None
    temp_core: list[float | None]
    temp_skin: float | None

    gfx_activity: int | None
    vcn_activity: int | None
    ipu_activity: list[int]
    core_activity: list[int]

    dram_reads: int | None
    dram_writes: int | None
    ipu_reads: int | None  # NPU traffic counter; unit undocumented (see user guide)
    ipu_writes: int | None

    socket_power: float | None
    ipu_power: float | None
    apu_power: float | None
    gfx_power: float | None
    core_power: list[float | None]

    gfxclk: int | None
    socclk: int | None
    ipuclk: int | None
    fclk: int | None
    uclk: int | None
    coreclk: list[int | None]
    core_maxfreq: int | None
    gfx_maxfreq: int | None

    # Monotonic per-throttler residency accumulators (prochot, spl, fppt, sppt,
    # thm_core, thm_gfx, thm_soc), in milliseconds spent throttled. Measured on
    # Krackan Point: a pegged limiter adds ~1000 per second.
    throttle_residency: list[int] = field(default_factory=list)

    raw: bytes = field(default=b"", repr=False)


def parse(blob: bytes) -> GpuMetrics:
    """Parse a raw gpu_metrics_v3_0 byte string into a :class:`GpuMetrics`."""
    if len(blob) < _SIZE:
        raise ValueError(f"gpu_metrics blob too short: {len(blob)} < {_SIZE}")

    v = list(struct.unpack_from(_FMT, blob, 0))
    it = iter(v)

    def nxt():
        return next(it)

    def temp(raw: int) -> float | None:
        c = _clean16(raw)
        return None if c is None else round(c / 100.0, 2)

    def watts16(raw: int) -> float | None:
        c = _clean16(raw)
        return None if c is None else round(c / 1000.0, 3)

    def watts32(raw: int) -> float | None:
        c = _clean32(raw)
        return None if c is None else round(c / 1000.0, 3)

    structure_size, format_revision, content_revision = nxt(), nxt(), nxt()

    temp_gfx = temp(nxt())
    temp_soc = temp(nxt())
    temp_core = [temp(nxt()) for _ in range(16)]
    temp_skin = temp(nxt())

    gfx_activity = _clean16(nxt())
    vcn_activity = _clean16(nxt())
    ipu_activity = [nxt() for _ in range(8)]
    core_activity = [nxt() for _ in range(16)]

    dram_reads = _clean16(nxt())
    dram_writes = _clean16(nxt())
    ipu_reads = _clean16(nxt())
    ipu_writes = _clean16(nxt())
    nxt()  # system_clock_counter

    socket_power = watts32(nxt())
    ipu_power = watts16(nxt())
    apu_power = watts32(nxt())
    gfx_power = watts32(nxt())
    nxt()  # dgpu_power
    nxt()  # all_core_power
    core_power = [watts16(nxt()) for _ in range(16)]
    nxt()  # sys_power
    nxt()  # stapm_power_limit
    nxt()  # current_stapm_power_limit

    gfxclk = _clean16(nxt())
    socclk = _clean16(nxt())
    nxt()  # vpeclk
    ipuclk = _clean16(nxt())
    fclk = _clean16(nxt())
    nxt()  # vclk
    uclk = _clean16(nxt())
    nxt()  # mpipu
    coreclk = [_clean16(nxt()) for _ in range(16)]
    core_maxfreq = _clean16(nxt())
    gfx_maxfreq = _clean16(nxt())

    throttle_residency = [nxt() for _ in range(len(THROTTLE_NAMES))]

    # ipu_activity is a valid 0 at idle; only strip the invalid sentinel.
    ipu_activity = [a for a in ipu_activity if a != _U16_INVALID]
    core_activity = [a for a in core_activity if a != _U16_INVALID]

    return GpuMetrics(
        structure_size=structure_size,
        format_revision=format_revision,
        content_revision=content_revision,
        temp_gfx=temp_gfx,
        temp_soc=temp_soc,
        temp_core=temp_core,
        temp_skin=temp_skin,
        gfx_activity=gfx_activity,
        vcn_activity=vcn_activity,
        ipu_activity=ipu_activity,
        core_activity=core_activity,
        dram_reads=dram_reads,
        dram_writes=dram_writes,
        ipu_reads=ipu_reads,
        ipu_writes=ipu_writes,
        socket_power=socket_power,
        ipu_power=ipu_power,
        apu_power=apu_power,
        gfx_power=gfx_power,
        core_power=core_power,
        gfxclk=gfxclk,
        socclk=socclk,
        ipuclk=ipuclk,
        fclk=fclk,
        uclk=uclk,
        coreclk=coreclk,
        core_maxfreq=core_maxfreq,
        gfx_maxfreq=gfx_maxfreq,
        throttle_residency=throttle_residency,
        raw=blob,
    )


def read(path: str = config.GPU_METRICS) -> GpuMetrics | None:
    """Read and parse the live gpu_metrics blob, or ``None`` if unavailable."""
    try:
        with open(path, "rb") as fh:
            return parse(fh.read())
    except (OSError, ValueError):
        return None

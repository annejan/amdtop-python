"""Static paths, defaults, and display thresholds."""

from __future__ import annotations

import glob
import os
import re

from rich import box

from .telemetry import decode, memory

# Refresh interval bounds (seconds).
DEFAULT_INTERVAL = 1.0
MIN_INTERVAL = 0.2
MAX_INTERVAL = 10.0

_CARD_RE = re.compile(r"/card\d+$")  # exclude connector nodes like card0-DP-1


def _read(path: str) -> str | None:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def _discover_drm_device(default: str = "/sys/class/drm/card1/device") -> str:
    """Find the amdgpu render card; the index varies across APUs (card0 vs card1)."""
    for card in sorted(glob.glob("/sys/class/drm/card*")):
        if not _CARD_RE.search(card):
            continue
        dev = f"{card}/device"
        if _read(f"{dev}/vendor") == "0x1002" and os.path.exists(f"{dev}/gpu_metrics"):
            return dev
    return default


def _discover_npu_device(default: str = "/sys/class/accel/accel0/device") -> str:
    """Find the XDNA NPU accel node by its identity sysfs files."""
    for acc in sorted(glob.glob("/sys/class/accel/accel*")):
        dev = f"{acc}/device"
        if _read(f"{dev}/vbnv") or _read(f"{dev}/fw_version"):
            return dev
    return default


# sysfs locations. Auto-detected: the iGPU DRM card index and NPU accel index
# differ between machines (e.g. Strix Halo card1 vs Strix Point card0).
DRM_DEVICE = _discover_drm_device()
# PCI bus address (e.g. 0000:c5:00.0) used to match this card in DRM fdinfo.
DRM_PDEV = os.path.basename(os.path.realpath(DRM_DEVICE))
GPU_METRICS = f"{DRM_DEVICE}/gpu_metrics"
GPU_BUSY = f"{DRM_DEVICE}/gpu_busy_percent"
MEM_BUSY = f"{DRM_DEVICE}/mem_busy_percent"  # absent on some kernels/ASICs
VRAM_USED = f"{DRM_DEVICE}/mem_info_vram_used"
VRAM_TOTAL = f"{DRM_DEVICE}/mem_info_vram_total"
GTT_USED = f"{DRM_DEVICE}/mem_info_gtt_used"
GTT_TOTAL = f"{DRM_DEVICE}/mem_info_gtt_total"

NPU_DEVICE = _discover_npu_device()
# PCI address of the NPU (e.g. 0000:c5:00.1), matched against accel fdinfo.
NPU_PDEV = os.path.basename(os.path.realpath(NPU_DEVICE)) if os.path.exists(NPU_DEVICE) else None

PROC_STAT = "/proc/stat"
CPUFREQ_GLOB = "/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"

# Peak memory bandwidth (MB/s) for the % gauge. The real value is read from the
# DIMMs via SMBIOS (config varies: soldered LPDDR5X vs socketed DDR5). When it
# isn't known for this host, MEM_BW_PEAK_IS_ESTIMATE is True and the value is the
# GPU's theoretical max; the CLI treats that as a hard error (see cli.py).
_real_mem_bw = memory.cached_or_detected_mem_bw_mbps()
MEM_BW_PEAK_IS_ESTIMATE = _real_mem_bw is None
MEM_BW_PEAK_MBPS = (
    _real_mem_bw
    if _real_mem_bw is not None
    else decode.peak_mem_bw_mbps(decode.decode_igpu(DRM_DEVICE).gfx)
)

# Installed memory type (e.g. "LPDDR5", "DDR5") from SMBIOS; None if unknown.
MEM_TYPE = memory.cached_or_detected_mem_type()

# Color ramp for utilization gauges (percent breakpoints).
RAMP_GREEN_MAX = 60.0
RAMP_YELLOW_MAX = 85.0

# Which engine gets the dominant pane. Cycle order for Tab; keys 1/2/3 select.
FOCUS_ORDER = ("cpu", "igpu", "npu")
DEFAULT_FOCUS = "igpu"

# Max GPU-using processes listed in the iGPU panel (sorted by GPU % desc).
GPU_PROC_TOP_N = 5
# Max NPU-using processes listed in the NPU panel (sorted by NPU %, then memory).
NPU_PROC_TOP_N = 5

# iGPU sclk/temp trend sparklines: sliding-window span (seconds) and the fixed
# number of buckets (columns) the window is downsampled into for display. The
# plots render in two side-by-side columns, so the width is kept narrow enough
# for two (plus gutters) to fit the focus panel.
IGPU_HISTORY_WINDOW_S = 600.0
IGPU_HISTORY_WIDTH = 40
# Rows per sclk/temp/power trend plot. Three plots at this height add 3*(H+1)
# rows to the iGPU panel; the focus layout assumes a terminal tall enough
# (>= ~33 rows, true for a normal/tmux window) to show all without clipping.
IGPU_HISTORY_HEIGHT = 4
# Trend plots scale their vertical axis to the session extremes: the bottom is
# the sticky min and the top is the sticky max, both learned since process
# start (not just the 10-min window). So the plot auto-fits the run's observed
# range instead of being pinned to hard-coded lo/hi bounds.

# Which throttle_residency counters to graph as delta-per-sample trend plots.
# GPU-relevant on this APU: GFX-die thermal plus the package power family across
# time windows -- fppt (fast/burst), sppt (slow), spl (sustained/STAPM).
# Must be names from gpu_metrics.THROTTLE_NAMES.
IGPU_THROTTLE_PLOTS = ("thm_gfx", "fppt", "sppt", "spl")
# Base URL of the user guide; throttle plot labels become OSC 8 hyperlinks to the
# per-term anchor (e.g. #spl). Terminals that honor OSC 8 render them clickable;
# others show the plain label. The anchor is the counter name itself.
USER_GUIDE_URL = "https://github.com/annejan/amdtop/blob/main/docs/USER_GUIDE.md"

# Panel border glyphs. rich's default ROUNDED (╭╮╰╯) corners are absent from
# some terminal fonts and get substituted by a stand-in like "_", which eats a
# column and shifts every border. SQUARE (┌┐└┘) is universally available; set
# AMDTOP_BOX=ascii for a pure-ASCII fallback, or =rounded to restore the curves.
_BOX_STYLES = {"square": box.SQUARE, "ascii": box.ASCII, "rounded": box.ROUNDED}
PANEL_BOX = _BOX_STYLES.get(os.environ.get("AMDTOP_BOX", "square").lower(), box.SQUARE)

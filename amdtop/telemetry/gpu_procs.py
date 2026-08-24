"""Per-process iGPU usage from DRM fdinfo (/proc/<pid>/fdinfo/*).

Each DRM client exposes cumulative engine-busy nanoseconds (drm-engine-gfx,
drm-engine-compute) and current memory footprint (drm-memory-vram/gtt). GPU %
is the busy-ns delta over the wall-clock interval, so this source is stateful
(it remembers the previous per-client counters, like CpuSource).

Reading another user's fdinfo needs root; without it, only the caller's own
processes are visible (readlink/open raise OSError and are skipped silently).
"""

from __future__ import annotations

import os
import pwd
import time

from .. import config
from . import sysfs
from .sample import GpuProcess

_PROC = "/proc"
_DRI_PREFIX = "/dev/dri/"
_MEM_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}


def _parse_fdinfo(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, val = line.partition(":")
        if sep:
            out[key.strip()] = val.strip()
    return out


def _mem_bytes(val: str) -> int:
    parts = val.split()
    if not parts:
        return 0
    try:
        n = int(parts[0])
    except ValueError:
        return 0
    unit = parts[1] if len(parts) > 1 else "B"
    return n * _MEM_UNITS.get(unit, 1)


def _engine_ns(val: str) -> int:
    try:
        return int(val.split()[0])
    except (ValueError, IndexError):
        return 0


def _list_pids() -> list[int]:
    try:
        return [int(n) for n in os.listdir(_PROC) if n.isdigit()]
    except OSError:
        return []


def _comm(pid: int) -> str:
    return sysfs.read_text(f"{_PROC}/{pid}/comm") or "?"


def _user(pid: int) -> str | None:
    try:
        return pwd.getpwuid(os.stat(f"{_PROC}/{pid}").st_uid).pw_name
    except (OSError, KeyError):
        return None


_CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def _runtime_s(pid: int, uptime_s: float | None) -> float | None:
    """Wall-clock age of ``pid`` = system uptime - process start time.

    Start time is field 22 of /proc/<pid>/stat, in clock ticks since boot. The
    2nd field (comm) may contain spaces/parens, so split on the last ')'.
    """
    if uptime_s is None:
        return None
    txt = sysfs.read_text(f"{_PROC}/{pid}/stat")
    if not txt:
        return None
    try:
        fields = txt[txt.rindex(")") + 1 :].split()
        starttime_ticks = int(fields[19])  # field 22 is index 19 after comm
    except (ValueError, IndexError):
        return None
    age = uptime_s - starttime_ticks / _CLK_TCK
    return age if age >= 0 else None


def _uptime_s() -> float | None:
    txt = sysfs.read_text("/proc/uptime")
    if not txt:
        return None
    try:
        return float(txt.split()[0])
    except (ValueError, IndexError):
        return None


def _client_records(pid: int) -> dict[str, tuple[int | None, int, int]]:
    """{client_id: (engine_ns, vram_bytes, gtt_bytes)} for this card's clients.

    Dup'd fds share a drm-client-id and report identical counters, so keying by
    client-id de-duplicates them automatically. engine_ns is None when the
    driver exposes no drm-engine-* fields at all (e.g. gfx1151 amdgpu, which
    reports per-process memory but no per-engine busy time).
    """
    fd_dir = f"{_PROC}/{pid}/fd"
    try:
        fds = os.listdir(fd_dir)
    except OSError:
        return {}
    out: dict[str, tuple[int | None, int, int]] = {}
    for fd in fds:
        try:
            if not os.readlink(f"{fd_dir}/{fd}").startswith(_DRI_PREFIX):
                continue
        except OSError:
            continue
        text = sysfs.read_text(f"{_PROC}/{pid}/fdinfo/{fd}")
        if text is None:
            continue
        info = _parse_fdinfo(text)
        if info.get("drm-driver") != "amdgpu":
            continue
        if info.get("drm-pdev") != config.DRM_PDEV:
            continue
        cid = info.get("drm-client-id")
        if cid is None:
            continue
        gfx = info.get("drm-engine-gfx")
        compute = info.get("drm-engine-compute")
        if gfx is None and compute is None:
            engine: int | None = None
        else:
            engine = _engine_ns(gfx or "") + _engine_ns(compute or "")
        out[cid] = (
            engine,
            _mem_bytes(info.get("drm-memory-vram", "")),
            _mem_bytes(info.get("drm-memory-gtt", "")),
        )
    return out


class GpuProcessesSource:
    """Stateful: holds previous per-client engine-ns for delta-based GPU %."""

    def __init__(self) -> None:
        self._prev: dict[str, int] = {}
        self._prev_t = time.monotonic()

    def read(self) -> list[GpuProcess]:
        now = time.monotonic()
        dt_ns = (now - self._prev_t) * 1e9
        prev = self._prev
        cur: dict[str, int] = {}

        engine_delta: dict[int, int] = {}
        has_engine: dict[int, bool] = {}
        vram: dict[int, int] = {}
        gtt: dict[int, int] = {}
        for pid in _list_pids():
            for cid, (eng, vr, gt) in _client_records(pid).items():
                has_engine.setdefault(pid, False)
                vram[pid] = vram.get(pid, 0) + vr
                gtt[pid] = gtt.get(pid, 0) + gt
                if eng is not None:
                    has_engine[pid] = True
                    cur[cid] = eng
                    d = eng - prev.get(cid, eng)  # new client -> 0 this frame
                    engine_delta[pid] = engine_delta.get(pid, 0) + max(0, d)

        self._prev = cur
        self._prev_t = now

        uptime = _uptime_s()
        procs = [
            GpuProcess(
                pid=pid,
                user=_user(pid),
                comm=_comm(pid),
                gpu_pct=_pct(engine_delta.get(pid, 0), dt_ns)
                if has_engine.get(pid)
                else None,
                vram_bytes=vram.get(pid, 0),
                gtt_bytes=gtt.get(pid, 0),
                runtime_s=_runtime_s(pid, uptime),
            )
            for pid in vram
        ]
        procs.sort(key=lambda p: (p.gpu_pct or 0.0, p.vram_bytes), reverse=True)
        return procs[: config.GPU_PROC_TOP_N]


def _pct(delta_ns: int, dt_ns: float) -> float:
    return 0.0 if dt_ns <= 0 else 100.0 * delta_ns / dt_ns

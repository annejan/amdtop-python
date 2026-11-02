"""Per-process NPU usage from DRM fdinfo of the XDNA accel node.

amdxdna exposes one DRM client per open ``/dev/accel/accel*`` fd, with the
standard ``drm-total-memory`` key (plus driver-specific heap/internal/external
allocation keys). As of kernel 7.3 it reports no ``drm-engine-*`` busy time, so
``npu_pct`` is None; if a later driver adds engine keys, their busy-ns delta over
wall-clock time becomes the NPU %, the same way the iGPU process list works.

Like the iGPU list, other users' processes are only visible as root.
"""

from __future__ import annotations

import os
import time

from .. import config
from . import gpu_procs, sysfs
from .sample import NpuProcess

_ACCEL_PREFIX = "/dev/accel/"
_DRIVER = "amdxdna_accel_driver"


def _client_records(pid: int) -> dict[str, tuple[int | None, int]]:
    """{client_id: (engine_ns or None, memory_bytes)} for this NPU's clients."""
    root = gpu_procs._PROC
    fd_dir = f"{root}/{pid}/fd"
    try:
        fds = os.listdir(fd_dir)
    except OSError:
        return {}
    out: dict[str, tuple[int | None, int]] = {}
    for fd in fds:
        try:
            if not os.readlink(f"{fd_dir}/{fd}").startswith(_ACCEL_PREFIX):
                continue
        except OSError:
            continue
        text = sysfs.read_text(f"{root}/{pid}/fdinfo/{fd}")
        if text is None:
            continue
        info = gpu_procs._parse_fdinfo(text)
        if info.get("drm-driver") != _DRIVER:
            continue
        if config.NPU_PDEV and info.get("drm-pdev") != config.NPU_PDEV:
            continue
        cid = info.get("drm-client-id")
        if cid is None:
            continue
        engines = [v for k, v in info.items() if k.startswith("drm-engine-")]
        engine = sum(gpu_procs._engine_ns(v) for v in engines) if engines else None
        out[cid] = (engine, gpu_procs._mem_bytes(info.get("drm-total-memory", "")))
    return out


class NpuProcessesSource:
    """Stateful: holds previous per-client engine-ns for delta-based NPU %."""

    def __init__(self) -> None:
        self._prev: dict[str, int] = {}
        self._prev_t = time.monotonic()

    def read(self) -> list[NpuProcess]:
        now = time.monotonic()
        dt_ns = (now - self._prev_t) * 1e9
        prev = self._prev
        cur: dict[str, int] = {}

        delta: dict[int, int] = {}
        has_engine: dict[int, bool] = {}
        mem: dict[int, int] = {}
        for pid in gpu_procs._list_pids():
            for cid, (eng, m) in _client_records(pid).items():
                has_engine.setdefault(pid, False)
                mem[pid] = mem.get(pid, 0) + m
                if eng is not None:
                    has_engine[pid] = True
                    cur[cid] = eng
                    d = eng - prev.get(cid, eng)  # new client -> 0 this frame
                    delta[pid] = delta.get(pid, 0) + max(0, d)

        self._prev = cur
        self._prev_t = now

        uptime = gpu_procs._uptime_s()
        procs = [
            NpuProcess(
                pid=pid,
                user=gpu_procs._user(pid),
                comm=gpu_procs._comm(pid),
                npu_pct=gpu_procs._pct(delta.get(pid, 0), dt_ns)
                if has_engine.get(pid)
                else None,
                mem_bytes=mem.get(pid, 0),
                runtime_s=gpu_procs._runtime_s(pid, uptime),
            )
            for pid in mem
        ]
        procs.sort(key=lambda p: (p.npu_pct or 0.0, p.mem_bytes), reverse=True)
        return procs[: config.NPU_PROC_TOP_N]

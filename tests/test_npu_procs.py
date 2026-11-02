"""Tests for the XDNA accel-fdinfo NPU process source, using a faked /proc tree."""

import os

from rich.console import Console

from amdtop import config
from amdtop.telemetry import gpu_procs, npu_procs
from amdtop.telemetry.sample import NpuProcess, NpuSample
from amdtop.ui import panels

_PDEV = "0000:c5:00.1"
_ACCEL = "/dev/accel/accel0"


def _fdinfo(client_id, total_kib=0, driver="amdxdna_accel_driver", pdev=_PDEV, engine_ns=None):
    text = (
        "pos:\t0\n"
        f"drm-driver:\t{driver}\n"
        f"drm-client-id:\t{client_id}\n"
        f"drm-pdev:\t{pdev}\n"
        "amdxdna_accel_driver-heap-alloc:\t4636 KiB\n"
        f"drm-total-memory:\t{total_kib} KiB\n"
        "drm-shared-memory:\t0\n"
    )
    if engine_ns is not None:
        text += f"drm-engine-npu:\t{engine_ns} ns\n"
    return text


def _mkproc(proc_root, pid, comm, fds):
    d = proc_root / str(pid)
    d.mkdir()
    d.joinpath("comm").write_text(comm + "\n")
    (d / "fd").mkdir()
    (d / "fdinfo").mkdir()
    for n, (target, content) in enumerate(fds):
        os.symlink(target, d / "fd" / str(n))
        if content is not None:
            (d / "fdinfo" / str(n)).write_text(content)


class _Clock:
    def __init__(self, vals):
        self.vals = list(vals)

    def __call__(self):
        return self.vals.pop(0)


def _setup(tmp_path, monkeypatch, clock_vals=(100.0, 100.0, 101.0)):
    proc = tmp_path / "proc"
    proc.mkdir()
    monkeypatch.setattr(gpu_procs, "_PROC", str(proc))
    monkeypatch.setattr(config, "NPU_PDEV", _PDEV)
    monkeypatch.setattr(npu_procs.time, "monotonic", _Clock(clock_vals))
    return proc


def test_lists_npu_client_memory_without_engine_time(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch)
    _mkproc(proc, 2828, "flm-real", [(_ACCEL, _fdinfo(31, total_kib=6153652))])
    r = npu_procs.NpuProcessesSource().read()
    assert len(r) == 1
    assert r[0].pid == 2828 and r[0].comm == "flm-real"
    assert r[0].mem_bytes == 6153652 * 1024
    assert r[0].npu_pct is None  # kernel 7.3 amdxdna has no drm-engine-* keys


def test_ignores_dri_fds_other_drivers_and_other_pdevs(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch)
    _mkproc(proc, 10, "game", [("/dev/dri/renderD128", _fdinfo(1, total_kib=100))])
    _mkproc(proc, 11, "other", [(_ACCEL, _fdinfo(2, total_kib=100, driver="ivpu"))])
    _mkproc(proc, 12, "npu2", [(_ACCEL, _fdinfo(3, total_kib=100, pdev="0000:01:00.0"))])
    _mkproc(proc, 13, "socket", [("socket:[123]", None)])
    assert npu_procs.NpuProcessesSource().read() == []


def test_dup_fds_with_same_client_id_counted_once(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch)
    info = _fdinfo(7, total_kib=1024)
    _mkproc(proc, 20, "app", [(_ACCEL, info), (_ACCEL, info)])
    assert npu_procs.NpuProcessesSource().read()[0].mem_bytes == 1024 * 1024


def test_engine_keys_become_busy_percent(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch)
    _mkproc(proc, 30, "infer", [(_ACCEL, _fdinfo(5, total_kib=1, engine_ns=0))])
    src = npu_procs.NpuProcessesSource()
    assert src.read()[0].npu_pct == 0.0  # first frame primes
    proc.joinpath("30", "fdinfo", "0").write_text(_fdinfo(5, total_kib=1, engine_ns=250_000_000))
    assert src.read()[0].npu_pct == 25.0


def _npu():
    return NpuSample(present=True, activity=[80] * 8, power_w=1.5, clk_mhz=1778,
                     power_state="D0", name="NPU Krackan 1", fw_version="1.1.2.64")


def _text(renderable, width=100):
    c = Console(width=width, record=True, color_system=None)
    c.print(renderable)
    return c.export_text()


def test_npu_panels_list_processes():
    procs = [NpuProcess(2828, "annejan", "flm-real", None, 6 << 30, 3600.0),
             NpuProcess(2900, "annejan", "whisper", None, 1 << 30, 60.0)]
    full = _text(panels.render_npu(_npu(), procs))
    assert "flm-real" in full and "whisper" in full and "MEM" in full
    compact = _text(panels.render_npu_compact(_npu(), procs), width=40)
    assert "flm-real 6G  +1" in compact


def test_npu_panel_shows_npu_memory_traffic():
    n = _npu()
    n.dram_read_mbps, n.dram_write_mbps = 8346, 2773
    assert "mem R 8.3  W 2.8 GB/s" in _text(panels.render_npu(n))

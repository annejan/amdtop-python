"""Tests for the DRM-fdinfo GPU process source, using a faked /proc tree."""

import os

from amdtop import config
from amdtop.telemetry import gpu_procs

_PDEV = "0000:c5:00.0"


def _fdinfo(
    client_id,
    gfx_ns=0,
    compute_ns=0,
    vram_kib=0,
    gtt_kib=0,
    driver="amdgpu",
    pdev=_PDEV,
):
    return (
        "pos:\t0\n"
        f"drm-driver:\t{driver}\n"
        f"drm-pdev:\t{pdev}\n"
        f"drm-client-id:\t{client_id}\n"
        f"drm-engine-gfx:\t{gfx_ns} ns\n"
        f"drm-engine-compute:\t{compute_ns} ns\n"
        f"drm-memory-vram:\t{vram_kib} KiB\n"
        f"drm-memory-gtt:\t{gtt_kib} KiB\n"
    )


def _mkproc(proc_root, pid, comm, fds, make_fd_dir=True):
    """fds: list of (symlink_target, fdinfo_text_or_None)."""
    d = proc_root / str(pid)
    d.mkdir()
    d.joinpath("comm").write_text(comm + "\n")
    if not make_fd_dir:
        return
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


def _setup(tmp_path, monkeypatch, clock_vals):
    proc = tmp_path / "proc"
    proc.mkdir()
    monkeypatch.setattr(gpu_procs, "_PROC", str(proc))
    monkeypatch.setattr(config, "DRM_PDEV", _PDEV)
    monkeypatch.setattr(gpu_procs.time, "monotonic", _Clock(clock_vals))
    return proc


def test_pct_is_engine_delta_over_wall(tmp_path, monkeypatch):
    # init@100, read1@100 (dt=0, primes), read2@101 (dt=1s).
    proc = _setup(tmp_path, monkeypatch, [100.0, 100.0, 101.0])
    render = "/dev/dri/renderD128"
    _mkproc(proc, 4821, "llama", [(render, _fdinfo(1, gfx_ns=0))])
    src = gpu_procs.GpuProcessesSource()

    assert src.read()[0].gpu_pct == 0.0  # first frame primes, no delta yet

    proc.joinpath("4821", "fdinfo", "0").write_text(_fdinfo(1, gfx_ns=500_000_000))
    r = src.read()
    assert r[0].pid == 4821
    assert r[0].comm == "llama"
    assert r[0].gpu_pct == 50.0  # 0.5s busy over 1s wall


def test_combined_gfx_plus_compute(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch, [0.0, 0.0, 1.0])
    render = "/dev/dri/renderD128"
    _mkproc(proc, 10, "vllm", [(render, _fdinfo(7, gfx_ns=0, compute_ns=0))])
    src = gpu_procs.GpuProcessesSource()
    src.read()
    proc.joinpath("10", "fdinfo", "0").write_text(
        _fdinfo(7, gfx_ns=200_000_000, compute_ns=300_000_000)
    )
    assert src.read()[0].gpu_pct == 50.0  # (0.2 + 0.3)s over 1s


def test_dedup_by_client_id(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch, [0.0, 0.0, 1.0])
    render = "/dev/dri/renderD128"
    # Two fds, SAME client-id, identical counters (dup'd fd) -> counted once.
    _mkproc(
        proc,
        20,
        "app",
        [(render, _fdinfo(3, gfx_ns=0)), (render, _fdinfo(3, gfx_ns=0))],
    )
    src = gpu_procs.GpuProcessesSource()
    src.read()
    for fd in ("0", "1"):
        proc.joinpath("20", "fdinfo", fd).write_text(_fdinfo(3, gfx_ns=500_000_000))
    assert src.read()[0].gpu_pct == 50.0  # not 100


def test_driver_and_pdev_filter(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch, [0.0, 0.0])
    render = "/dev/dri/renderD128"
    _mkproc(
        proc,
        30,
        "mixed",
        [
            (render, _fdinfo(1, gfx_ns=9, driver="xe")),  # wrong driver
            (render, _fdinfo(2, gfx_ns=9, pdev="0000:aa:00.0")),  # wrong card
            ("/dev/null", None),  # non-DRI fd, skipped before fdinfo
        ],
    )
    src = gpu_procs.GpuProcessesSource()
    assert src.read() == []


def test_vram_gtt_aggregated_across_clients(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch, [0.0, 0.0])
    render = "/dev/dri/renderD128"
    _mkproc(
        proc,
        40,
        "big",
        [
            (render, _fdinfo(1, vram_kib=1000, gtt_kib=10)),
            (render, _fdinfo(2, vram_kib=2000, gtt_kib=20)),
        ],
    )
    src = gpu_procs.GpuProcessesSource()
    r = src.read()
    assert r[0].vram_bytes == 3000 * 1024
    assert r[0].gtt_bytes == 30 * 1024


def _fdinfo_no_engine(client_id, vram_kib=0, gtt_kib=0, pdev=_PDEV):
    # gfx1151 amdgpu: memory fields present, NO drm-engine-* lines.
    return (
        "pos:\t0\n"
        "drm-driver:\tamdgpu\n"
        f"drm-pdev:\t{pdev}\n"
        f"drm-client-id:\t{client_id}\n"
        f"drm-memory-vram:\t{vram_kib} KiB\n"
        f"drm-memory-gtt:\t{gtt_kib} KiB\n"
    )


def test_no_engine_fields_lists_proc_with_none_pct(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch, [0.0, 0.0])
    render = "/dev/dri/renderD128"
    _mkproc(proc, 60, "llama", [(render, _fdinfo_no_engine(1, vram_kib=3000))])
    src = gpu_procs.GpuProcessesSource()
    r = src.read()
    assert r[0].pid == 60
    assert r[0].gpu_pct is None  # driver exposes no engine time
    assert r[0].vram_bytes == 3000 * 1024


def test_missing_fd_dir_skipped(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch, [0.0, 0.0])
    _mkproc(proc, 50, "noperm", [], make_fd_dir=False)  # listdir(fd) -> OSError
    src = gpu_procs.GpuProcessesSource()
    assert src.read() == []


def _stat_line(starttime_ticks, comm="llama (bench)"):
    # /proc/<pid>/stat: "pid (comm) state ppid ... starttime ...". comm may hold
    # spaces/parens, so field 22 (starttime) is index 19 after the last ')'.
    fields = ["0"] * 22
    fields[21] = str(starttime_ticks)  # 1-based field 22
    tail = " ".join(fields[3:])  # fields after comm+state (we only need index 19)
    return f"7 ({comm}) R {tail}"


def test_runtime_is_uptime_minus_starttime(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch, [0.0, 0.0])
    monkeypatch.setattr(gpu_procs, "_CLK_TCK", 100)
    (proc / "7").mkdir()
    (proc / "7" / "stat").write_text(_stat_line(500_000))  # 5000s since boot
    assert gpu_procs._runtime_s(7, uptime_s=8000.0) == 3000.0  # 8000 - 5000


def test_runtime_none_when_uptime_unknown(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch, [0.0, 0.0])
    (proc / "7").mkdir()
    (proc / "7" / "stat").write_text(_stat_line(100))
    assert gpu_procs._runtime_s(7, uptime_s=None) is None


def test_runtime_comm_with_spaces_and_parens(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch, [0.0, 0.0])
    monkeypatch.setattr(gpu_procs, "_CLK_TCK", 100)
    (proc / "9").mkdir()
    (proc / "9" / "stat").write_text(_stat_line(200_000, comm="weird ) name"))
    assert gpu_procs._runtime_s(9, uptime_s=5000.0) == 3000.0  # 5000 - 2000

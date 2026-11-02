from rich.console import Console

from amdtop.telemetry import gpu_metrics
from amdtop.telemetry.history import Series
from amdtop.telemetry.sample import IgpuSample
from amdtop.ui import panels


def _series(lo: float, hi: float, n: int = 40) -> Series:
    pts = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    return Series(points=pts, cur=pts[-1], min=lo, max=hi)


def _igpu() -> IgpuSample:
    names = gpu_metrics.THROTTLE_NAMES
    thr = [_series(0, 300) for _ in names]
    absv = [123456 for _ in names]
    return IgpuSample(
        marketing="Radeon 860M", codename="Krackan Point", arch="RDNA 3.5",
        gfx="gfx1152", cu_count=8, busy_pct=10.0, mem_busy_pct=None,
        vram_used=2 << 30, vram_total=4 << 30, gtt_used=200 << 20, gtt_total=14 << 30,
        sclk_mhz=1350, sclk_max_mhz=2900, fclk_mhz=None, uclk_mhz=None,
        temp_c=62.0, power_w=4.0,
        sclk_history=_series(600, 2900), temp_history=_series(40, 95),
        power_history=_series(1, 54),
        throttle_history=thr, throttle_absolute=absv,
    )


def _render(width: int) -> list[str]:
    console = Console(width=width, record=True, color_system=None)
    console.print(panels.render_igpu(_igpu()))
    return console.export_text().splitlines()


def test_narrow_igpu_panel_uses_compact_trends_without_overflow():
    lines = _render(80)
    text = "\n".join(lines)
    assert "trends · 10m" in text
    assert "…" not in text
    assert all(len(l) <= 80 for l in lines)
    # one row per metric: sclk, temp, power + four throttle counters
    for label in ("sclk", "temp", "power", "thm_gfx", "fppt", "sppt", "spl"):
        assert sum(1 for l in lines if l.lstrip("│ ").startswith(label)) == 1


def test_very_narrow_panel_trims_sparkline_instead_of_wrapping():
    lines = _render(50)
    assert "…" not in "\n".join(lines)
    assert all(len(l) <= 50 for l in lines)
    assert sum(1 for l in lines if l.lstrip("│ ").startswith("sclk")) == 1


def test_wide_igpu_panel_keeps_two_column_bar_plots():
    text = "\n".join(_render(160))
    assert "trends · 10m" not in text
    assert "…" not in text
    assert "min 600  max 2900  · 10m" in text


def test_throttle_plots_show_residency_percent():
    text = "\n".join(_render(160))
    assert "300 %" in text  # cur of the synthetic series
    assert "peak 300%" in text
    assert "total 2m" in text  # 123456 ms accumulator
    assert "(+" not in text  # no raw accumulator deltas any more


def test_compact_throttle_rows_show_percent():
    lines = [l for l in _render(80) if l.lstrip("│ ").startswith("spl")]
    assert len(lines) == 1
    assert "300 %" in lines[0] and "peak 300%" in lines[0]


def _with_dram(g, rd=37000, wr=5000):
    g.dram_read_mbps, g.dram_write_mbps = rd, wr
    return g


def test_igpu_panel_shows_dram_traffic_as_share_of_peak(monkeypatch):
    from amdtop import config
    monkeypatch.setattr(config, "MEM_BW_PEAK_MBPS", 84000.0)
    c = Console(width=100, record=True, color_system=None)
    c.print(panels.render_igpu(_with_dram(_igpu())))
    text = c.export_text()
    assert "dram" in text and "50%" in text and "R 37.0  W 5.0 GB/s" in text


def test_compact_igpu_dram_fits_sidebar(monkeypatch):
    from amdtop import config
    monkeypatch.setattr(config, "MEM_BW_PEAK_MBPS", 84000.0)
    c = Console(width=40, record=True, color_system=None)
    c.print(panels.render_igpu_compact(_with_dram(_igpu())))
    lines = c.export_text().splitlines()
    dram = [l for l in lines if "dram" in l]
    assert len(dram) == 1 and "42.0 GB/s" in dram[0]
    assert not any(l.strip("│ ") == "GB/s" for l in lines)  # no wrapped tail


def test_igpu_panel_without_dram_counters_has_no_dram_row():
    c = Console(width=100, record=True, color_system=None)
    c.print(panels.render_igpu(_igpu()))
    assert "dram" not in c.export_text()

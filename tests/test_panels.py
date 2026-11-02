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

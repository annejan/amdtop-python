"""Rich renderables for the header and the CPU / iGPU / NPU panels."""

from __future__ import annotations

import datetime as _dt
import itertools

from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .. import config
from ..telemetry import gpu_metrics
from ..telemetry.sample import (
    CpuSample,
    Frame,
    GpuProcess,
    IgpuSample,
    MemSample,
    NpuSample,
)
from . import gauges


def _fmt_uptime(s: float | None) -> str:
    if s is None:
        return "?"
    s = int(s)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return (f"{d}d " if d else "") + f"{h:02d}:{m:02d}"


_FOCUS_LABELS = {"cpu": "CPU", "igpu": "iGPU", "npu": "NPU"}


def render_header(frame: Frame, interval: float, focus: str = "cpu") -> Panel:
    now = _dt.datetime.now().strftime("%H:%M:%S")
    left = Text()
    left.append(" amdtop ", style="bold reverse")
    left.append(f" {frame.host}", style="bold cyan")
    if frame.igpu.codename:
        left.append(f" ({frame.igpu.codename})", style="bold green")
    left.append(f"  up {_fmt_uptime(frame.uptime_s)}", style="dim")
    if frame.socket_power_w is not None:
        left.append(f"   socket {frame.socket_power_w:.1f} W", style="magenta")

    right = Text()
    right.append("focus ")
    for i, key in enumerate(("cpu", "igpu", "npu"), start=1):
        style = "bold reverse cyan" if key == focus else "dim"
        right.append(f" {i}:{_FOCUS_LABELS[key]} ", style=style)
    hint = "  ^v k kill" if focus == "igpu" else ""
    right.append(f"   {interval:.1f}s  q quit  +/- rate{hint}  {now}", style="dim")

    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")
    grid.add_row(left, right)
    return Panel(grid, box=config.PANEL_BOX, style="blue", padding=(0, 1))


def _core_grid(cpu: CpuSample, columns: int = 4) -> Table:
    n = cpu.n_threads
    rows = (n + columns - 1) // columns
    grid = Table.grid(expand=True, padding=(0, 1))
    for _ in range(columns):
        grid.add_column(justify="left")
    cells: list[Text] = []
    for i in range(n):
        pct = cpu.per_cpu_pct[i]
        cell = Text()
        cell.append(f"{i:2d}", style="dim")
        cell.append("[")
        cell.append_text(gauges.meter(pct, 6))
        cell.append("]")
        cell.append(f"{pct:3.0f}%", style=gauges.ramp_color(pct))
        cells.append(cell)
    for r in range(rows):
        row = [cells[r + c * rows] for c in range(columns) if r + c * rows < n]
        row += [Text("")] * (columns - len(row))
        grid.add_row(*row)
    return grid


def render_cpu(cpu: CpuSample) -> Panel:
    body = Table.grid(expand=True)
    body.add_column()

    summary = Text()
    summary.append_text(gauges.labeled_meter("all", cpu.total_pct, 24))
    body.add_row(summary)

    stats = Text()
    if cpu.avg_mhz is not None:
        stats.append(f"avg {cpu.avg_mhz} MHz   ", style="cyan")
    if cpu.temp_c is not None:
        stats.append(f"{cpu.temp_c:.0f}°C   ", style="yellow")
    if cpu.power_w is not None:
        stats.append(f"{cpu.power_w:.1f} W   ", style="magenta")
    if cpu.loadavg is not None:
        stats.append("load %.2f %.2f %.2f" % cpu.loadavg, style="dim")
    body.add_row(stats)
    body.add_row(Text())
    body.add_row(_core_grid(cpu))

    title = f"CPU · {cpu.model}"
    return Panel(body, box=config.PANEL_BOX, title=title, title_align="left", border_style="green")


def _mem_row(label: str, used: int | None, total: int | None, width: int = 20) -> Text:
    if used is None or total is None or total == 0:
        return gauges.labeled_meter(label, None, width)
    pct = 100.0 * used / total
    suffix = f"{gauges.fmt_bytes(used)}/{gauges.fmt_bytes(total)}"
    return gauges.labeled_meter(label, pct, width, suffix, label_w=4)


def render_mem(m: MemSample, width: int = 28) -> Panel:
    body = Table.grid(expand=True)
    body.add_column()
    body.add_row(_mem_row("ram", m.used, m.total, width=width))
    body.add_row(_mem_row("swap", m.swap_used, m.swap_total, width=width))

    stats = Text()
    if m.available is not None:
        stats.append(f"avail {gauges.fmt_bytes(m.available)}   ", style="green")
    if m.cached is not None:
        stats.append(f"cached {gauges.fmt_bytes(m.cached)}", style="dim")
    body.add_row(stats)

    return Panel(body, box=config.PANEL_BOX, title="Memory", title_align="left", border_style="yellow")


def _fmt_dur(s: float | None) -> str:
    """Compact process age: ``45s``, ``12m``, ``3h04``, ``2d05`` (<= 5 chars)."""
    if s is None:
        return "?"
    s = int(s)
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h{m:02d}"
    d, h = divmod(h, 24)
    return f"{d}d{h:02d}"


def _proc_rows(
    procs: list[GpuProcess], body: Table, width: int = 48, selected: int | None = None
) -> None:
    header = Text(
        f"{'PID':>8} {'USER':<8} {'COMMAND':<12} {'GPU':>4} {'VRAM':>6} {'TIME':>5}",
        style="dim",
    )
    body.add_row(header)
    body.add_row(Text("─" * width, style="dim"))
    for i, p in enumerate(procs):
        marker = ">" if i == selected else " "
        pct = "  —" if p.gpu_pct is None else f"{p.gpu_pct:3.0f}%"
        text = (
            f"{marker}{p.pid:>7} {(p.user or '?')[:8]:<8} "
            f"{p.comm[:12]:<12} {pct} {gauges.fmt_bytes(p.vram_bytes):>6} "
            f"{_fmt_dur(p.runtime_s):>5}"
        )
        if i == selected:
            # One uniform style so the whole row reads as a single color rather
            # than reverse-video over each field's individual color.
            body.add_row(Text(text, style="reverse cyan"))
            continue
        line = Text()
        line.append(f"{marker}", style="bold cyan")
        line.append(f"{p.pid:>7} ")
        line.append(f"{(p.user or '?')[:8]:<8} ", style="cyan")
        line.append(f"{p.comm[:12]:<12} ", style="white")
        if p.gpu_pct is None:
            line.append(f"{'—':>4}", style="dim")
        else:
            line.append(f"{p.gpu_pct:3.0f}%", style=gauges.ramp_color(p.gpu_pct))
        line.append(f" {gauges.fmt_bytes(p.vram_bytes):>6}", style="magenta")
        line.append(f" {_fmt_dur(p.runtime_s):>5}", style="yellow")
        body.add_row(line)


# Throttlers split by cause: thermal (thm_*) vs power/electrical (the rest).
_THROTTLE_THERMAL = {"thm_core", "thm_gfx", "thm_soc"}


def _plot_block(spec, *, win: str, label_w: int, gutter_w: int, height: int) -> list[Text]:
    """Render one trend plot (header + gutter + bars) as a list of Text lines."""
    label, series, unit, color, fmt = spec[:5]
    absv = spec[5] if len(spec) > 5 else None
    lo, hi = series.min, series.max
    head = Text()
    if absv is not None:
        # Throttle counter: label links to the user guide (OSC 8), and the value
        # shows the absolute accumulator plus the plotted per-sample delta. Link
        # only the keyword itself so the underline doesn't extend into padding.
        link = f"{config.USER_GUIDE_URL}#{label}"
        head.append(label, style=f"bold link {link}")
        head.append(" " * (label_w - len(label) + 1))
        delta = "n/a" if series.cur is None else f"{series.cur:+.0f}"
        head.append(f"{absv:>10} ({delta})  ", style=color)
    else:
        head.append(f"{label:<{label_w}} ", style="bold")
        cur = "n/a" if series.cur is None else fmt.format(series.cur)
        head.append(f"{cur:>5} {unit}  ", style=color)
    if lo is not None and hi is not None:
        head.append(f"min {fmt.format(lo)}  max {fmt.format(hi)}", style="dim")
    head.append(f"  · {win}", style="dim")
    out = [head]
    lines = gauges.plot(series.points, height, lo=lo, hi=hi, color=color)
    # y-axis gutter: max label on the top row, min on the bottom, blank between.
    for i, line in enumerate(lines):
        if i == 0 and hi is not None:
            tick = fmt.format(hi)
        elif i == len(lines) - 1 and lo is not None:
            tick = fmt.format(lo)
        else:
            tick = ""
        row = Text(f"{tick:>{gutter_w}} ", style="dim")
        row.append_text(line)
        out.append(row)
    return out


def _trend_rows(body: Table, g: IgpuSample) -> None:
    window_m = config.IGPU_HISTORY_WINDOW_S / 60.0
    win = f"{window_m:.0f}m" if window_m == int(window_m) else f"{window_m:.1f}m"

    thr = {}
    if g.throttle_history:
        idx = {n: i for i, n in enumerate(gpu_metrics.THROTTLE_NAMES)}
        for name in config.IGPU_THROTTLE_PLOTS:
            i = idx.get(name)
            if i is not None and i < len(g.throttle_history):
                color = "red" if name in _THROTTLE_THERMAL else "magenta"
                absv = None
                if i < len(g.throttle_absolute):
                    absv = g.throttle_absolute[i]
                thr[name] = (name, g.throttle_history[i], "d", color, "{:.0f}", absv)

    # Two columns. Left: the analog trends (clock, thermal) plus GFX-die thermal
    # throttle. Right: the package-power family stacked by time window --
    # power draw over fast/slow/sustained (fppt/sppt/spl) throttle deltas.
    col1 = [
        ("sclk", g.sclk_history, "MHz", "cyan", "{:.0f}"),
        ("temp", g.temp_history, "°C", "yellow", "{:.0f}"),
        thr.get("thm_gfx"),
    ]
    col2 = [
        ("power", g.power_history, "W", "magenta", "{:.0f}"),
        thr.get("fppt"),
        thr.get("sppt"),
        thr.get("spl"),
    ]

    all_specs = [s for s in col1 + col2 if s is not None]
    if not all_specs:
        return
    label_w = max(len(s[0]) for s in all_specs)
    # Shared vertical scale is each plot's session extremes (sticky min..max).
    # Gutter width is shared so every plot's bars start at the same column.
    gutter_w = max(
        (
            len(s[4].format(v))
            for s in all_specs
            if s[1] is not None and s[1].min is not None
            for v in (s[1].min, s[1].max)
        ),
        default=1,
    )
    body.add_row(_TrendPlots(col1, col2, win=win, label_w=label_w, gutter_w=gutter_w,
                             height=config.IGPU_HISTORY_HEIGHT))


def _spark_row(spec, *, label_w: int, value_w: int, spark_w: int) -> Text:
    """One-line trend: label, current value, sparkline tail, session range."""
    label, series, unit, color, fmt = spec[:5]
    is_throttle = len(spec) > 5
    row = Text()
    if is_throttle:
        link = f"{config.USER_GUIDE_URL}#{label}"
        row.append(label, style=f"bold link {link}")
        row.append(" " * (label_w - len(label) + 1))
        val = "n/a" if series.cur is None else f"{series.cur:+.0f}"
    else:
        row.append(f"{label:<{label_w}} ", style="bold")
        val = "n/a" if series.cur is None else f"{fmt.format(series.cur)} {unit}"
    row.append(f"{val:>{value_w}} ", style=color)
    if spark_w > 0:
        row.append_text(gauges.sparkline(series.points[-spark_w:], lo=series.min,
                                         hi=series.max, color=color))
    if series.min is not None and series.max is not None:
        row.append(f" {fmt.format(series.min)}..{fmt.format(series.max)}", style="dim")
    return row


class _TrendPlots:
    """Trend plots that adapt to the width they are given at render time.

    When there is room, render two columns of multi-row bar plots. Otherwise
    (e.g. the iGPU pane in the live view on a ~120-column terminal) fall back to
    one sparkline row per metric, trimmed to the newest points that fit, so
    nothing wraps or gets cut off with an ellipsis.
    """

    _GRID_PAD = 3

    def __init__(self, col1, col2, *, win: str, label_w: int, gutter_w: int,
                 height: int) -> None:
        self.col1 = col1
        self.col2 = col2
        self.win = win
        self.label_w = label_w
        self.gutter_w = gutter_w
        self.height = height

    def _block(self, spec) -> list[Text]:
        if not spec or spec[1] is None:
            return [Text()]
        return _plot_block(spec, win=self.win, label_w=self.label_w,
                           gutter_w=self.gutter_w, height=self.height)

    def _grid(self) -> tuple[Table, int]:
        """Two-column bar-plot grid and the width it needs without wrapping."""
        grid = Table.grid(padding=(0, self._GRID_PAD))
        grid.add_column(no_wrap=True)
        grid.add_column(no_wrap=True)
        widths = [0, 0]
        for a, b in itertools.zip_longest(self.col1, self.col2):
            left, right = self._block(a), self._block(b)
            n = max(len(left), len(right))
            left += [Text()] * (n - len(left))
            right += [Text()] * (n - len(right))
            for l, r in zip(left, right):
                widths[0] = max(widths[0], l.cell_len)
                widths[1] = max(widths[1], r.cell_len)
                grid.add_row(l, r)
        return grid, widths[0] + self._GRID_PAD + widths[1]

    def _compact(self, max_width: int) -> Table:
        # Analog trends first, then the throttle counters.
        specs = [s for s in self.col1[:2] + self.col2[:1] + self.col1[2:] + self.col2[1:]
                 if s is not None and s[1] is not None]
        value_w = 9
        ranges = max((len(f" {s[4].format(s[1].min)}..{s[4].format(s[1].max)}")
                      for s in specs if s[1].min is not None), default=0)
        fixed = self.label_w + 1 + value_w + 1 + ranges
        n_points = max((len(s[1].points) for s in specs), default=0)
        spark_w = max(0, min(n_points, max_width - fixed))
        grid = Table.grid()
        grid.add_column(no_wrap=True, overflow="crop")
        grid.add_row(Text(f"trends · {self.win}", style="dim"))
        for spec in specs:
            grid.add_row(_spark_row(spec, label_w=self.label_w, value_w=value_w,
                                    spark_w=spark_w))
        return grid

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        grid, need = self._grid()
        yield grid if need <= options.max_width else self._compact(options.max_width)

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement(1, options.max_width)


def render_igpu(
    g: IgpuSample,
    procs: list[GpuProcess] | None = None,
    selected: int | None = None,
    confirm_pid: int | None = None,
    status: str | None = None,
) -> Panel:
    body = Table.grid(expand=True)
    body.add_column()

    # Meters in two columns: activity (gpu/mem) left, memory (vram/gtt) right,
    # so the four bars take two rows instead of four.
    meters = Table.grid(padding=(0, 3))
    meters.add_column()
    meters.add_column()
    left = [gauges.labeled_meter("gpu", g.busy_pct, 16)]
    if g.mem_busy_pct is not None:
        left.append(gauges.labeled_meter("mem", g.mem_busy_pct, 16))
    right = [
        _mem_row("vram", g.vram_used, g.vram_total, width=16),
        _mem_row("gtt", g.gtt_used, g.gtt_total, width=16),
    ]
    for i in range(max(len(left), len(right))):
        l = left[i] if i < len(left) else Text()
        r = right[i] if i < len(right) else Text()
        meters.add_row(l, r)
    body.add_row(meters)
    body.add_row(Text())
    _trend_rows(body, g)
    if procs:
        _proc_rows(procs, body, selected=selected)
        if confirm_pid is not None:
            comm = next((p.comm for p in procs if p.pid == confirm_pid), "?")
            prompt = Text()
            prompt.append(f" kill {confirm_pid} ({comm})?  y/N ", style="bold reverse red")
            body.add_row(prompt)
        elif status:
            body.add_row(Text(status, style="dim"))

    name = g.marketing or "iGPU"
    title = f"iGPU · {name}"
    if g.cu_count:
        title += f" · {g.cu_count} CU"
    if g.arch:
        title += f" · {g.arch}"
    if g.gfx:
        title += f" · {g.gfx}"
    peak_gbps = config.MEM_BW_PEAK_MBPS / 1000.0
    tilde = "~" if config.MEM_BW_PEAK_IS_ESTIMATE else ""
    mem = f"{config.MEM_TYPE} " if config.MEM_TYPE else ""
    title += f" · {mem}{tilde}{peak_gbps:.0f} GB/s"
    return Panel(body, box=config.PANEL_BOX, title=title, title_align="left", border_style="magenta")


def render_cpu_compact(cpu: CpuSample) -> Panel:
    body = Table.grid(expand=True)
    body.add_column()
    body.add_row(gauges.labeled_meter("all", cpu.total_pct, 10))
    stats = Text()
    if cpu.avg_mhz is not None:
        stats.append(f"{cpu.avg_mhz} MHz  ", style="cyan")
    if cpu.temp_c is not None:
        stats.append(f"{cpu.temp_c:.0f}°C  ", style="yellow")
    if cpu.power_w is not None:
        stats.append(f"{cpu.power_w:.1f} W", style="magenta")
    body.add_row(stats)
    return Panel(body, box=config.PANEL_BOX, title="CPU", title_align="left", border_style="green")


def render_igpu_compact(g: IgpuSample) -> Panel:
    body = Table.grid(expand=True)
    body.add_column()
    body.add_row(gauges.labeled_meter("busy", g.busy_pct, 10))
    body.add_row(_mem_row("vram", g.vram_used, g.vram_total, width=10))
    body.add_row(_mem_row("gtt", g.gtt_used, g.gtt_total, width=10))
    stats = Text()
    if g.sclk_mhz is not None:
        stats.append(f"{g.sclk_mhz} MHz  ", style="cyan")
    if g.temp_c is not None:
        stats.append(f"{g.temp_c:.0f}°C  ", style="yellow")
    if g.power_w is not None:
        stats.append(f"{g.power_w:.1f} W", style="magenta")
    body.add_row(stats)
    name = g.marketing or "iGPU"
    return Panel(body, box=config.PANEL_BOX, title=f"iGPU · {name}", title_align="left", border_style="magenta")


def render_npu_compact(n: NpuSample) -> Panel:
    body = Table.grid(expand=True)
    body.add_column()
    if not n.present:
        body.add_row(Text("not detected", style="dim"))
        return Panel(body, box=config.PANEL_BOX, title="NPU", title_align="left", border_style="cyan")
    body.add_row(gauges.labeled_meter("busy", n.activity_max, 10))
    stats = Text()
    if n.clk_mhz is not None:
        stats.append(f"{n.clk_mhz} MHz  ", style="cyan")
    if n.power_w is not None:
        stats.append(f"{n.power_w:.2f} W  ", style="magenta")
    if n.power_state:
        stats.append(n.power_state, style="green" if n.power_state == "D0" else "dim")
    body.add_row(stats)
    return Panel(body, box=config.PANEL_BOX, title="NPU · XDNA", title_align="left", border_style="cyan")


def render_npu(n: NpuSample) -> Panel:
    body = Table.grid(expand=True)
    body.add_column()

    if not n.present:
        body.add_row(Text("NPU not detected", style="dim"))
        return Panel(body, box=config.PANEL_BOX, title="NPU", title_align="left", border_style="cyan")

    head = gauges.labeled_meter("busy", n.activity_max, 24)
    body.add_row(head)
    body.add_row(Text())

    for i, a in enumerate(n.activity):
        body.add_row(gauges.labeled_meter(f"col{i}", float(a), 16, label_w=5))
    if not n.activity:
        body.add_row(Text("activity: n/a", style="dim"))

    body.add_row(Text())
    stats = Text()
    if n.clk_mhz is not None:
        stats.append(f"clk {n.clk_mhz} MHz   ", style="cyan")
    if n.power_w is not None:
        stats.append(f"{n.power_w:.2f} W   ", style="magenta")
    if n.power_state:
        stats.append(f"{n.power_state}", style="green" if n.power_state == "D0" else "dim")
    body.add_row(stats)
    ident = Text(f"{n.name or 'npu'}  fw {n.fw_version or '?'}", style="dim")
    body.add_row(ident)

    return Panel(body, box=config.PANEL_BOX, title="NPU · XDNA", title_align="left", border_style="cyan")

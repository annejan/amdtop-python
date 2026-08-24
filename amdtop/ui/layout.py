"""Compose the header + CPU / iGPU / NPU panels into one screen renderable."""

from __future__ import annotations

from rich.console import Group
from rich.layout import Layout

from ..telemetry.sample import Frame
from . import panels


from .. import config

_FULL = {
    "cpu": lambda f, **kw: panels.render_cpu(f.cpu),
    "igpu": lambda f, **kw: panels.render_igpu(f.igpu, f.gpu_procs, **kw),
    "npu": lambda f, **kw: panels.render_npu(f.npu),
}
_COMPACT = {
    "cpu": lambda f: panels.render_cpu_compact(f.cpu),
    "igpu": lambda f: panels.render_igpu_compact(f.igpu),
    "npu": lambda f: panels.render_npu_compact(f.npu),
}


def render(
    frame: Frame,
    interval: float,
    focus: str = config.DEFAULT_FOCUS,
    selected: int = 0,
    confirm_pid: int | None = None,
    status: str | None = None,
) -> Layout:
    kw = {}
    if focus == "igpu":
        kw = {"selected": selected, "confirm_pid": confirm_pid, "status": status}
    root = Layout()
    root.split_column(
        Layout(panels.render_header(frame, interval, focus), name="header", size=3),
        Layout(name="body"),
    )
    root["body"].split_row(
        Layout(_FULL[focus](frame, **kw), name="left", ratio=2),
        Layout(name="side", ratio=1),
    )
    others = [k for k in config.FOCUS_ORDER if k != focus]
    root["body"]["side"].split_column(
        Layout(_COMPACT[others[0]](frame), name="side0", size=7),
        Layout(_COMPACT[others[1]](frame), name="side1", size=7),
        Layout(panels.render_mem(frame.mem, width=10), name="mem"),
    )
    return root


def render_static(frame: Frame, interval: float) -> Group:
    """Flat top-to-bottom rendering for --once / non-fullscreen output."""
    return Group(
        panels.render_header(frame, interval),
        panels.render_cpu(frame.cpu),
        panels.render_mem(frame.mem),
        panels.render_igpu(frame.igpu, frame.gpu_procs),
        panels.render_npu(frame.npu),
    )

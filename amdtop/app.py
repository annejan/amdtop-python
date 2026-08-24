"""Live loop: collect a frame, render it, handle keys, repeat."""

from __future__ import annotations

import os
import select
import signal
import sys
import termios
import time
import tty
from contextlib import contextmanager

from rich.console import Console
from rich.live import Live

from . import config
from .telemetry.collector import Collector
from .ui import layout


@contextmanager
def _raw_stdin():
    """Put stdin in cbreak mode for single-key reads; no-op if not a TTY."""
    if not sys.stdin.isatty():
        yield None
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield fd
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _wait_key(timeout: float) -> str | None:
    """Block up to ``timeout`` s for one keypress; return it or None.

    Escape sequences (arrow keys arrive as ``\\x1b[A`` / ``\\x1b[B``) are drained
    as a unit: after an ESC we grab the rest of the sequence with a zero-timeout
    read so callers see the whole ``\\x1b[A`` instead of a bare ESC.
    """
    if not sys.stdin.isatty():
        time.sleep(timeout)
        return None
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if not r:
        return None
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        r, _, _ = select.select([sys.stdin], [], [], 0)
        while r:
            ch += sys.stdin.read(1)
            r, _, _ = select.select([sys.stdin], [], [], 0)
    return ch


def _kill(pid: int) -> str:
    """SIGKILL ``pid``; return a short status string describing the outcome."""
    try:
        os.kill(pid, signal.SIGKILL)
    except PermissionError:
        return f"kill {pid}: permission denied"
    except ProcessLookupError:
        return f"kill {pid}: no such process"
    except OSError as e:
        return f"kill {pid}: {e.strerror or 'error'}"
    return f"killed {pid}"


def _adjust(interval: float, faster: bool) -> float:
    interval = interval / 1.5 if faster else interval * 1.5
    return max(config.MIN_INTERVAL, min(config.MAX_INTERVAL, interval))


def run_once(interval: float, prime: float = 0.3) -> None:
    """Print a single snapshot (primes CPU deltas with a short sleep first)."""
    collector = Collector()
    collector.collect()
    time.sleep(prime)
    frame = collector.collect()
    Console().print(layout.render_static(frame, interval))


def _live_console() -> Console:
    """Console for the full-screen loop.

    Inside tmux, the alternate screen's last row is unusable, so a layout sized
    to the full terminal height overflows by one row and every panel border
    lands one row too low. Pinning the height one row short fixes the alignment;
    width stays auto-detected so horizontal resizes still reflow.
    """
    console = Console()
    if os.environ.get("TMUX"):
        console = Console(height=max(1, console.size.height - 1))
    return console


def run(interval: float = config.DEFAULT_INTERVAL) -> None:
    collector = Collector()
    collector.collect()  # prime CPU deltas
    console = _live_console()
    focus = config.DEFAULT_FOCUS
    selected = 0  # index into the iGPU proc list (clamped each frame)
    confirm_pid: int | None = None  # awaiting y/N to kill this pid
    status: str | None = None  # transient result of the last kill
    with _raw_stdin(), Live(
        console=console, screen=True, auto_refresh=False, transient=True
    ) as live:
        while True:
            frame = collector.collect()
            procs = frame.gpu_procs
            # The list is re-sorted every collect, so we track a position, not a
            # pid; clamp it to the current row count.
            selected = max(0, min(selected, len(procs) - 1)) if procs else 0
            live.update(
                layout.render(
                    frame, interval, focus, selected, confirm_pid, status
                ),
                refresh=True,
            )
            status = None  # only show a kill result for a single frame
            key = _wait_key(interval)
            if confirm_pid is not None:  # pinned kill prompt; wait for a keypress
                if key is None:
                    continue  # no key yet -> keep the prompt up, re-render
                if key in ("y", "Y"):
                    status = _kill(confirm_pid)
                confirm_pid = None
                continue
            if key in ("q", "Q", "\x03"):  # q or Ctrl-C
                break
            if key in ("+", "="):
                interval = _adjust(interval, faster=True)
            elif key == "-":
                interval = _adjust(interval, faster=False)
            elif key in ("1", "2", "3"):
                focus = config.FOCUS_ORDER[int(key) - 1]
            elif key == "\t":
                focus = config.FOCUS_ORDER[
                    (config.FOCUS_ORDER.index(focus) + 1) % len(config.FOCUS_ORDER)
                ]
            elif focus == "igpu" and procs:  # process selection + kill
                if key == "\x1b[A":
                    selected = max(0, selected - 1)
                elif key == "\x1b[B":
                    selected = min(len(procs) - 1, selected + 1)
                elif key in ("k", "K"):
                    confirm_pid = procs[selected].pid

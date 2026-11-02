"""Command-line entry point for amdtop."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__, app, config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="amdtop",
        description="btop-style CPU/iGPU/NPU monitor for AMD Ryzen AI APUs.",
    )
    parser.add_argument(
        "-i", "--interval", type=float, default=config.DEFAULT_INTERVAL,
        metavar="SEC", help="refresh interval in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "-1", "--once", action="store_true",
        help="print a single snapshot and exit",
    )
    parser.add_argument(
        "--no-strict", action="store_true",
        help="run with an estimated memory bandwidth peak instead of erroring "
             "when the real per-host value is unknown",
    )
    parser.add_argument("-V", "--version", action="version",
                        version=f"amdtop {__version__}")
    args = parser.parse_args(argv)

    if config.MEM_BW_PEAK_IS_ESTIMATE and not args.no_strict:
        print(
            "error: memory bandwidth peak is unknown for this host "
            "(no cached SMBIOS value).\n"
            "Prime it once -- this reads your DIMMs' type and speed via "
            "`sudo dmidecode -t 17`, so you may be prompted for your sudo "
            "password:\n"
            "    python -m amdtop.telemetry.memory\n"
            "Don't need the real peak? Run with --no-strict to use an "
            "estimated value.",
            file=sys.stderr,
        )
        return 1

    if os.geteuid() != 0:
        print(
            "note: only your own GPU processes are listed -- reading other "
            "users' /proc fdinfo needs root.\n"
            "Run `sudo amdtop` to see every user's GPU processes; otherwise "
            "this is safe to ignore.",
            file=sys.stderr,
        )

    interval = max(config.MIN_INTERVAL, min(config.MAX_INTERVAL, args.interval))
    try:
        if args.once:
            app.run_once(interval)
        else:
            app.run(interval)
    except KeyboardInterrupt:
        pass
    return 0

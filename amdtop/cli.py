"""Command-line entry point for amdtop."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__, app, config
from .telemetry import memory


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
        help="start with an estimated memory bandwidth peak when the real "
             "per-host value is unknown (the memory gauge may be inaccurate)",
    )
    parser.add_argument(
        "--prime-memory", action="store_true",
        help="read the real memory bandwidth peak from SMBIOS (runs "
             "`sudo dmidecode -t 17`), cache it for later runs, and exit",
    )
    parser.add_argument("-V", "--version", action="version",
                        version=f"amdtop {__version__}")
    args = parser.parse_args(argv)

    if args.prime_memory:
        return memory.prime_cache()

    if config.MEM_BW_PEAK_IS_ESTIMATE and not args.no_strict:
        est = config.MEM_BW_PEAK_MBPS / 1000.0
        cache = memory.cache_dir()
        home = os.path.expanduser("~")
        if cache.startswith(home + os.sep):
            cache = "~" + cache[len(home):]
        print(
            "error: amdtop does not know the peak memory bandwidth of this "
            "machine.\n"
            "\n"
            "The iGPU memory gauge shows RAM traffic as a percentage of that "
            "peak. The peak\n"
            "depends on the installed memory (soldered LPDDR5X or socketed "
            "DDR5), and only\n"
            "SMBIOS reports it. Reading SMBIOS needs root.\n"
            "\n"
            f"To read it once and cache it in {cache}, run:\n"
            "    amdtop --prime-memory\n"
            "This runs `sudo dmidecode -t 17`, so sudo may ask for your "
            "password.\n"
            "\n"
            f"To start now with an estimate of ~{est:.0f} GB/s instead, run:\n"
            "    amdtop --no-strict\n"
            "The estimate can be far from the real value, so the memory gauge "
            "can be wrong.",
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

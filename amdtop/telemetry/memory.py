"""System RAM / swap telemetry from /proc/meminfo."""

from __future__ import annotations

import os
import pwd
import socket
import subprocess

from .sample import MemSample

_MEMINFO = "/proc/meminfo"


def _cache_home() -> str:
    """Real user's home, even under sudo (so a root-primed cache is found later)."""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            return pwd.getpwnam(sudo_user).pw_dir
        except KeyError:
            pass
    return os.path.expanduser("~")


# Peak memory bandwidth can't be derived from the GPU alone: the same APU ships
# with soldered LPDDR5X (wide bus) or socketed DDR5 (narrower, slower), so it
# must be read from the actual DIMMs via SMBIOS. dmidecode needs root, so a
# successful detection is cached for later no-root runs. The home dir is often
# NFS-shared across hosts, so the cache is keyed by hostname to avoid collisions.
_MEM_BW_CACHE = os.path.join(
    _cache_home(), ".cache", "amdtop", f"mem_bw_mbps.{socket.gethostname()}"
)
_MEM_TYPE_CACHE = os.path.join(
    _cache_home(), ".cache", "amdtop", f"mem_type.{socket.gethostname()}"
)


def cache_dir() -> str:
    """Directory holding the per-host SMBIOS caches."""
    return os.path.dirname(_MEM_BW_CACHE)


def _first_int(val: str | None) -> int | None:
    if not val:
        return None
    try:
        return int(val.split()[0])
    except (ValueError, IndexError):
        return None


def _parse_dmidecode_mem_type(text: str) -> str | None:
    """Return the memory type (e.g. 'LPDDR5', 'DDR5') of the first populated module."""
    cur: dict[str, str] = {}

    def type_of(d: dict[str, str]) -> str | None:
        if not _first_int(d.get("Size")):  # unpopulated slot
            return None
        t = (d.get("Type") or "").strip()
        if not t or t.lower() in ("unknown", "other", "none"):
            return None
        return t

    for line in text.splitlines():
        s = line.strip()
        if s == "Memory Device":
            found = type_of(cur)
            if found:
                return found
            cur = {}
            continue
        key, sep, val = s.partition(":")
        if sep:
            cur[key.strip()] = val.strip()
    return type_of(cur)


def _parse_dmidecode_mem_bw(text: str) -> float | None:
    """Sum data-width x configured-speed / 8 over populated modules -> MB/s."""
    total = 0.0
    cur: dict[str, str] = {}

    def flush() -> None:
        nonlocal total
        if _first_int(cur.get("Size")):  # populated (not "No Module Installed")
            width = _first_int(cur.get("Data Width") or cur.get("Total Width"))
            mts = _first_int(cur.get("Configured Memory Speed") or cur.get("Speed"))
            if width and mts:
                total += width * mts / 8.0

    for line in text.splitlines():
        s = line.strip()
        if s == "Memory Device":
            flush()
            cur = {}
            continue
        key, sep, val = s.partition(":")
        if sep:
            cur[key.strip()] = val.strip()
    flush()
    return total or None


def _run_dmidecode_t17(allow_sudo: bool = False) -> str | None:
    """Return the raw ``dmidecode -t 17`` (Memory Device) text, or None.

    Runs dmidecode directly when already root. Otherwise, if ``allow_sudo`` is
    set, escalates only dmidecode via ``sudo`` (may prompt for a password) so the
    calling user still owns any cache it writes -- important on root_squash NFS
    homes where a root process cannot write the user's cache.
    """
    if os.geteuid() == 0:
        cmd = ["dmidecode", "-t", "17"]
        timeout: float | None = 5
    elif allow_sudo:
        cmd = ["sudo", "dmidecode", "-t", "17"]
        timeout = 120  # allow time for an interactive password prompt
    else:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def detect_mem_bw_mbps(allow_sudo: bool = False) -> float | None:
    """Read peak memory bandwidth from SMBIOS via dmidecode; None if unavailable."""
    text = _run_dmidecode_t17(allow_sudo)
    return _parse_dmidecode_mem_bw(text) if text is not None else None


def detect_mem_type(allow_sudo: bool = False) -> str | None:
    """Read the installed memory type from SMBIOS via dmidecode; None if unavailable."""
    text = _run_dmidecode_t17(allow_sudo)
    return _parse_dmidecode_mem_type(text) if text is not None else None


def _read_cache() -> float | None:
    try:
        with open(_MEM_BW_CACHE) as fh:
            v = float(fh.read().strip())
        return v if v > 0 else None
    except (OSError, ValueError):
        return None


def _write_cache(v: float) -> bool:
    try:
        os.makedirs(os.path.dirname(_MEM_BW_CACHE), exist_ok=True)
        with open(_MEM_BW_CACHE, "w") as fh:
            fh.write(str(v))
        return True
    except OSError:
        return False


def cached_or_detected_mem_bw_mbps() -> float | None:
    """Real DIMM-derived peak from cache, or SMBIOS if already root; else None.

    Never prompts for a password here (no sudo) -- that would hang the TUI on
    startup. Priming via sudo is an explicit step (see the module ``__main__``).
    """
    cached = _read_cache()
    if cached is not None:
        return cached
    detected = detect_mem_bw_mbps()
    if detected is not None and _write_cache(detected):
        return detected
    return None


def mem_bw_mbps(fallback: float) -> float:
    """Real DIMM-derived peak if known, else the given fallback."""
    real = cached_or_detected_mem_bw_mbps()
    return real if real is not None else fallback


def _read_type_cache() -> str | None:
    try:
        with open(_MEM_TYPE_CACHE) as fh:
            v = fh.read().strip()
        return v or None
    except OSError:
        return None


def _write_type_cache(v: str) -> bool:
    try:
        os.makedirs(os.path.dirname(_MEM_TYPE_CACHE), exist_ok=True)
        with open(_MEM_TYPE_CACHE, "w") as fh:
            fh.write(v)
        return True
    except OSError:
        return False


def cached_or_detected_mem_type() -> str | None:
    """Real DIMM memory type from cache, or SMBIOS if already root; else None.

    Never prompts for a password here (no sudo) -- that would hang the TUI on
    startup. Priming via sudo is an explicit step (see the module ``__main__``).
    """
    cached = _read_type_cache()
    if cached is not None:
        return cached
    detected = detect_mem_type()
    if detected is not None and _write_type_cache(detected):
        return detected
    return None


def _read_meminfo() -> dict[str, int]:
    """Return /proc/meminfo as {key: bytes}."""
    out: dict[str, int] = {}
    try:
        with open(_MEMINFO) as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if parts:
                    # values are in kB
                    out[key] = int(parts[0]) * 1024
    except OSError:
        pass
    return out


class MemSource:
    def read(self) -> MemSample:
        m = _read_meminfo()
        total = m.get("MemTotal")
        available = m.get("MemAvailable")
        cached = m.get("Cached")
        swap_total = m.get("SwapTotal")
        swap_free = m.get("SwapFree")

        used = None if total is None or available is None else total - available
        swap_used = (
            None
            if swap_total is None or swap_free is None
            else swap_total - swap_free
        )
        return MemSample(
            total=total,
            used=used,
            available=available,
            cached=cached,
            swap_total=swap_total,
            swap_used=swap_used,
        )


def prime_cache() -> int:
    """Read SMBIOS via ``sudo dmidecode`` and cache bandwidth/type; return exit code.

    Run this as yourself (NOT under sudo) -- it escalates only dmidecode via sudo
    (you may be prompted for a password), and writes the cache as you, so it
    works on root_squash NFS homes.
    """
    import sys

    if os.geteuid() != 0:
        print(
            "amdtop needs to read your DIMMs' type and speed from SMBIOS to show "
            "the real peak memory bandwidth.\n"
            "This runs `sudo dmidecode -t 17`, so you may be prompted for your "
            "sudo password next.\n"
            "Don't need it? Skip this and run `amdtop --no-strict` to use an "
            "estimated peak instead.\n",
            file=sys.stderr,
        )

    text = _run_dmidecode_t17(allow_sudo=True)
    if text is None:
        print("could not read SMBIOS memory info via dmidecode.", file=sys.stderr)
        return 1
    bw = _parse_dmidecode_mem_bw(text)
    mem_type = _parse_dmidecode_mem_type(text)
    if bw is None:
        print("could not parse memory bandwidth from dmidecode.", file=sys.stderr)
        return 1
    if not _write_cache(bw):
        print(f"could not write cache to {_MEM_BW_CACHE}", file=sys.stderr)
        return 1
    print(
        f"memory bandwidth peak: {bw / 1000:.1f} GB/s ({bw:.0f} MB/s)\n"
        f"cached at {_MEM_BW_CACHE}"
    )
    if mem_type and _write_type_cache(mem_type):
        print(f"memory type: {mem_type}\ncached at {_MEM_TYPE_CACHE}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(prime_cache())

# amdtop

A [btop](https://github.com/aristocratos/btop)-style terminal monitor for **AMD Ryzen AI** APUs
(Strix Halo, Strix Point, Krackan Point) that shows the **CPU, integrated GPU, and NPU side by side** in
one live-refreshing view.

![amdtop iGPU view with 10-minute sclk/temp trend plots](docs/amdtop-igpu.png)

## Why

Standard tools show one engine at a time (`btop`/`htop` for CPU, `amdgpu_top`/`radeontop` for
the GPU, and the NPU is largely invisible). On these APUs all three compute engines share
one power/thermal/memory budget, so watching them together is what actually tells you where a
workload is bottlenecked. `amdtop` puts CPU, iGPU, NPU, and system memory on a single screen.

## Features

- **CPU** — per-thread utilization bars, per-core clocks, package power, Tctl temperature, load average.
- **iGPU** — busy %, unified VRAM/GTT usage, sclk/fclk/uclk, edge temperature, GPU power, plus
  **10-minute sclk & temperature trend plots**. PCI-ID decode surfaces the codename
  (e.g. **Strix Halo**, **Krackan Point**) and architecture (e.g. **RDNA 3.5 · gfx1151**).
- **NPU (XDNA)** — per-column activity, IPU power and clock, power state, firmware version — all
  **without root**, read from the amdgpu `gpu_metrics` table.
- **Memory** — RAM and swap usage, available, cached.
- Live refresh with adjustable rate; single-snapshot mode for scripting.

## Requirements

- An AMD Ryzen AI APU with an RDNA 3.5 iGPU and an XDNA NPU (see [Tested hardware](#tested-hardware))
  on Linux with the `amdgpu` and `amdxdna` drivers loaded.
- Python 3.10+ and [`rich`](https://github.com/Textualize/rich).
- No root required — all telemetry comes from read-only `sysfs` / `/proc`.

## Install

```bash
pipx install .          # or: pipx install -e . to track a git checkout
```

Or with plain pip in a virtualenv:

```bash
pip install -e .        # provides the `amdtop` command
```

Or run straight from the source tree with `python -m amdtop`.

## Usage

```bash
amdtop                  # live dashboard (default 1.0s refresh)
amdtop -i 0.5           # refresh every 0.5s
amdtop --once           # print a single snapshot and exit
amdtop --prime-memory   # one-time: read real memory bandwidth via sudo dmidecode
amdtop --version
```

On first run amdtop stops with an error until it knows the peak bandwidth of your RAM.
The iGPU memory gauge needs it, and only SMBIOS reports it (reading it needs root). The
same APU ships with soldered LPDDR5X or socketed DDR5, so the GPU model alone is not
enough: on a Krackan Point laptop with DDR5 the GPU-based estimate is ~128 GB/s, the real
value is 90 GB/s. Run `amdtop --prime-memory` once to read and cache the real value in
`~/.cache/amdtop/`, or `amdtop --no-strict` to start with the estimate (marked `~`).

In the live view: `q` quits, `+` / `-` speed up / slow down the refresh, and
`1` / `2` / `3` (or `Tab` to cycle) promote CPU, iGPU, or NPU to the dominant
pane while the other two collapse to compact summary rows.

## How it works

The heart of the tool is the amdgpu **`gpu_metrics_v3_0`** table exposed read-only at
`/sys/class/drm/card*/device/gpu_metrics`. On these APUs this single 264-byte blob reports
per-core CPU activity, iGPU (gfx) activity, and **NPU (IPU) activity/power/clock** — so no
privileged helper is needed for NPU visibility. The remaining data comes from `/proc/stat`,
`cpufreq`, `k10temp`, `/proc/meminfo`, and amdgpu memory sysfs.

```
amdtop/
  telemetry/
    gpu_metrics.py   parse the gpu_metrics_v3_0 blob (the golden source)
    cpu.py           /proc/stat deltas, cpufreq, k10temp, package power
    igpu.py          amdgpu sysfs + gpu_metrics
    memory.py        /proc/meminfo
    npu.py           NpuSource ABC + no-root GpuMetricsNpuSource
    decode.py        PCI-ID -> codename / RDNA arch / gfx target
    collector.py     reads gpu_metrics once, fans out to all sources
  ui/                Rich gauges, panels, layout
  app.py / cli.py    live loop + CLI
```

The NPU backend is behind an `NpuSource` interface, so a future root `debugfs` source can add
per-process NPU attribution without touching the UI.

## Development

```bash
pip install pytest
pytest
```

## Tested hardware

| APU | CPU | iGPU | NPU | Memory | Status |
|---|---|---|---|---|---|
| Strix Halo | Ryzen AI MAX+ 395 | Radeon 8060S (gfx1151) | XDNA 2 | LPDDR5X | verified: field offsets, scales, PCI IDs |
| Krackan Point | Ryzen AI 7 PRO 350 | Radeon 860M (gfx1152, 8 CU) | XDNA 2, 8 columns | socketed DDR5 | verified: all panels, NPU activity under load (kernel 7.3) |

Strix Point (gfx1150) and Phoenix (gfx1103) are in the decode table but have not been
tested. If you run amdtop on one of them, please open an issue with the output of
`amdtop --once`.

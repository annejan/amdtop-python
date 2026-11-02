# amdtop User Guide

This guide explains the metrics `amdtop` displays, with an emphasis on the terms
that are not self-explanatory. On a Ryzen AI APU (Strix Halo, Strix Point, Krackan Point) the CPU, integrated GPU, and
NPU all share one power, thermal, and memory budget, so most of these numbers are
about understanding which shared limit a workload is hitting.

All data comes from the world-readable amdgpu `gpu_metrics` sysfs table (no root
required) plus standard `/proc` and `/sys` interfaces.

## Contents

- [iGPU metrics](#igpu-metrics)
- [Throttle counters](#throttle-counters)
  - [thm_gfx](#thm_gfx)
  - [fppt](#fppt)
  - [sppt](#sppt)
  - [spl](#spl)
- [Reading the trend plots](#reading-the-trend-plots)

## iGPU metrics

- **gpu** - graphics engine busy percent (share of time the GFX block was active).
- **mem** - memory-controller busy percent.
- **vram** - unified video memory currently allocated out of the total carved for
  the iGPU.
- **gtt** - GTT (graphics translation table) memory: system RAM mapped for GPU use.
- **sclk** - GFX shader/engine clock in MHz. This is the headline "how fast is the
  GPU running" number.
- **temp** - GFX-die edge temperature in degrees C.
- **power** - GFX-rail power draw in watts (the GPU's own power, separate from the
  CPU cores).

## Throttle counters

The firmware exposes seven monotonic "throttle residency" accumulators, one per
throttler. Each counts the milliseconds that throttler has been engaged since boot.
`amdtop` turns the change between two samples into a **residency percentage**: the
share of the last interval during which that limit was holding the chip back. `0%`
means the limit was never hit; `100%` means it was in force the whole time.

Each plot header shows the current residency, the `peak` within the session, and the
`total` time spent throttled since boot, for example `spl 100 %  peak 100%  total 1m`.

On this APU the CPU and GPU share a single package power budget, so a heavy GPU
workload is frequently clamped by the package power limits (fppt/sppt/spl) rather
than by the GPU's own thermal limit. The power limits differ only by the time
window they average over: fast, slow, and sustained.

### thm_gfx

GFX thermal throttle. Engages when the graphics die itself reaches its temperature
ceiling. This is the most GPU-specific throttle signal: if `thm_gfx` residency is
climbing, the GPU is being held back by heat, and better cooling would help. If it
is flat while the power throttles are active, the workload is power-limited rather
than thermal-limited.

### fppt

Fast Package Power Tracking. The shortest-window package power limit
(milliseconds). It catches the initial burst at the very start of a load spike and
then releases as the slower limits take over. Rarely the steady-state limiter, but
useful for seeing how aggressively a workload ramps.

### sppt

Slow Package Power Tracking. A seconds-scale sliding-average package power limit.
It governs the transition from "just started boosting" to steady state: it lets the
package run above the sustained number briefly by draining budget, then reels it
back down. Rising `sppt` residency means the boost window is closing.

### spl

Sustained Power Limit (also called STAPM, Skin-Temperature-Aware Power Management).
The long-term, steady-state package power ceiling (tens of seconds to minutes). It
is the "forever" number a workload settles to once the short-term boost budget is
spent. Because it is skin-temperature aware, the value depends on chassis cooling.
If `spl` residency is pegged during a sustained run, you have hit the permanent
power floor: more boost budget will not help, only a higher configured power limit
or shedding CPU load (since the budget is shared) will.

The package power family across time windows, shortest to longest:
`fppt` (burst) -> `sppt` (slow) -> `spl` (sustained).

## Reading the trend plots

Each plot is a fixed-width, 10-minute sliding window downsampled into buckets; each
bucket shows the peak value in its time slot. The vertical scale auto-fits the
session extremes (the sticky min and max learned since `amdtop` started), so the
bars grow to fill the plot as the run's true range emerges. The plot header shows
the current value plus that session `min` and `max`.

For the throttle plots the plotted quantity is the residency percentage per sample,
on a fixed `0..100%` scale, so a bar appears only when that throttler was engaged
during the interval and a full-height bar means it was engaged for the whole interval.

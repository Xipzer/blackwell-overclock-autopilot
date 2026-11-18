# Blackwell OC Autopilot

Finds the highest stable clock at each voltage of an NVIDIA RTX 50 card's V/F curve, one point at a time, on
Windows with MSI Afterburner. It is the Blackwell edition of
[OC Autopilot](https://github.com/Xipzer/overclock-autopilot).

**Status: per-voltage search, 3D validation harness and VBIOS override workflow all used end to end on one RTX 5090
Founders Edition (water-cooled).** Results are in
[blackwell-field-notes](https://github.com/Xipzer/blackwell-field-notes). Short version:

| Voltage | Compute limit (lock) | 3D limit (FurMark, real clock) | Max curve (Profile 1) |
|---|---|---|---|
| 900 mV | 2,497 MHz | 2,332 MHz | 2,332 MHz |
| 950 mV | 3,030 MHz | 3,000 MHz | 3,015 MHz |
| 1000 mV | 3,195 MHz | 3,120 MHz | 3,120 MHz |
| 1050 mV | 3,300 MHz | 3,240 MHz | 3,240 MHz |
| 1100 mV | 3,382 MHz (voltage ceiling) | 3,277 MHz | flat 3,247 MHz from ~1,075 mV |

- Compute limits sit 30 to 110 MHz above what 3D survives. A steady heavy load (FurMark) also overstates the 3D limit,
  because a hot core drops temperature bins and never runs the clock it was given.
- The max curve passes warm runs (Time Spy Extreme graphics up to 28,223 at 700 W, Steel Nomad Stress Test 99.2 %),
  but hangs at random in one heavy scene of Time Spy Extreme Graphics Test 2, more often with a cold core. Clock
  caps at 3,060 or 3,090 MHz passed 13 of 13 cold runs at 600 W in a window but hung at 700 W; lowering single curve regions, less memory
  overclock, the stock VBIOS and a raised MSVDD voltage floor did not stop it. See
  [docs/VALIDATION.md](docs/VALIDATION.md).
- 700 W without flashing works through a VBIOS override ([docs/VBIOS.md](docs/VBIOS.md)), but Time Spy peaks
  at about 592 W, so power was not the limit.
- Lowering the whole curve 45 or 60 MHz at every voltage, or per voltage band, stopped the GT2 hang (12 of 12 and
  11 of 11). But those runs, like every harness run before 18 Nov 16:23 UTC, were not really fullscreen: 3DMark
  had fallen back to a 3840x2160 window, a lighter load. The `tse` harness now forces borderless fullscreen
  (`is_borderless: true`, native-size swapchain), which held on every run, and records the real window mode per run.
  See [Known quirks](#known-quirks).
- **Final (18 Nov evening, borderless fullscreen):** per-band margin never stopped the hangs; they kept landing at
  3,045 to 3,090 MHz whatever the voltage, a heavy-load clock wall. A **soft cap in the curve** fixed it: every
  point up to 1,060 mV held flat at a cap, points above untouched (`python -m bwoc curve --softcap 3090`). Cap
  3,090 = 6 clean, 1 hang in 7 (Profile 1, max); cap 3,075 = 6 of 6 (Profile 2); no fps cost (about 173 in GT2).
  Forcing Resizable BAR for 3DMark (+1.2 %) and XBAR +400 brought GT2 to 176.6 fps. See
  [docs/METHOD.md](docs/METHOD.md#the-soft-cap-what-finally-worked).
- **Validated score (3DMark app, 18 Nov):** Time Spy Extreme 24,961 overall, graphics 29,265 (up from 28,223 on the
  old hang-prone curve, +3.7 %, now stable), CPU 13,615. Rank 92 of about 3,270 results for i9-14900KS + RTX 5090,
  on a daily profile with no hardware mods. See
  [blackwell-field-notes Results](https://github.com/Xipzer/blackwell-field-notes#results).
- **Voltage lever (18 Nov, 20:00 UTC):** mVolt+ runtime voltage offsets are ignored on driver 621.24, but raising
  the NVVDD REL floor in the override image (`nvvdd_rel_equation_min_mv` 900 -> 1150) lifts the core voltage limit
  from 1,120 to 1,170 mV. With the curve top ramped to +255 at 1,170 mV, light loads run 3,360 to 3,382 MHz instead
  of about 3,180; heavy loads never use it (at or under 1.02 V). GT2 179.0 fps in one run (was 176.6). See
  [docs/VBIOS.md](docs/VBIOS.md#voltage-lever-raising-the-core-voltage-limit).

Not built yet: writing a per-point curve from the results and the isolated re-test are still done by hand, and the
3D (FurMark) search is not in this repo yet. See [docs/METHOD.md](docs/METHOD.md).

> **Warning.** The search pushes the GPU until it fails, on purpose. Expect driver hangs and blue screens
> (DPC_WATCHDOG_VIOLATION, 0x133), one per voltage. Save and close your work first. Use at your own risk.

## Known quirks

The full list with remedies and public sources is in
[blackwell-field-notes QUIRKS.md](https://github.com/Xipzer/blackwell-field-notes/blob/main/QUIRKS.md). The ones
this tool handles or depends on:

| Quirk | What the tool does / what you do |
|---|---|
| A direct 3DMark launch runs in a 3840x2160 window, not fullscreen (exclusive fullscreen held only for the first run after boot) | `tse` writes `is_windowed: false`, `is_borderless: true`, `swapchain_resolution` = display size; reads the window each run (`0x94000000` = borderless fullscreen, `0x14CF0000` = window) and warns |
| A monitor on the Intel iGPU costs about 5.5 % (cross-adapter copy); HWiNFO hides it | you: all monitors on the NVIDIA card, iGPU off in Windows and BIOS |
| DXGI LUID changes every boot | looked up and written per launch |
| A driver reset wipes curve, memory offset, cap and XBAR offset | `--profile` and `--cap` re-applied after every failure; re-send `abwp XBARCLK_off N` yourself |
| Afterburner polls at 1 s by default; global settings in `Profiles\MSIAfterburner.cfg` | you: `HwPollPeriod=100` there while logging |
| Afterburner shared memory goes stale after an Afterburner restart | `mahmlog.ps1` checks signature and timestamp, reopens |
| Voltage slider and `NVVDD_off_Vrel` ignored on driver 621.x | you: mVolt+ offsets were ignored too (621.24); raise `nvvdd_rel_equation_min_mv` in the image instead (docs/VBIOS.md, voltage lever) |
| HWiNFO free cannot log from the command line; old Intel iGPU drivers crash it | you: shared memory (`SensorsSM=1`); `oneAPI=0` or a newer Intel driver |
| Two harnesses at once give nonsense fps | preflight refuses to start when the GPU is busy |
| 8 runs prove little | `--rate`; use 1 run to screen, 3 to keep, 10 to 12 for the final pass |
| Per-band offsets can make the curve non-monotonic and pin hangs on the wrong band | `abcurve.monotonic()` caps each point at the lowest clock above it; `--softcap` output is monotonic |
| With one GPU (iGPU off), Afterburner drops the `GPU1 ` prefix (core voltage = `GPU voltage`) | `mahmlog.ps1` and `mahm1.ps1` fall back to the plain names |
| 3DMark Time Spy does not use Resizable BAR by default | you: NVIDIA Profile Inspector, "3DMark TimeSpy" profile, `rBAR - Enable` (0x000F00BA) = 1 (+1.2 % GT2 here) |
| XBAR offset is not stored in a profile | you: a logon task running `MSIAfterburner.exe /wpXBARCLK_off,400` (or `abwp XBARCLK_off 400`) |

## How it works, short

1. Read the factory V/F curve from an Afterburner profile slot.
2. Write an offset to a spare slot (the work slot) and apply it.
3. Pin the clock with `nvidia-smi -lgc F,F`, so the driver runs exactly the point under test.
4. Run `gpucheck` (a CUDA FP32 checksum check with pulsed load) for 60 s, and watch for driver resets.
5. Raise the clock in 30 MHz steps, then 15 MHz near the edge, until the first failure.
6. After a crash, a logon task resumes the search and records that step as the voltage's first failure.

Full method, rules and lessons: [docs/METHOD.md](docs/METHOD.md).

## Needs

- Windows 10 or 11, an RTX 50 card, MSI Afterburner (4.6.7 Beta 2 and Beta 5 tested; set `HwPollPeriod=100` in
  `Profiles\MSIAfterburner.cfg` for 100 ms telemetry; Beta 5's "out of warranty" mode, `OEM=3`, for XBAR, SYS and
  aux voltage telemetry and the `abwp` / `abreport` helper commands).
- For clean 3D results: every monitor on the NVIDIA card, iGPU disabled (see Known quirks).
- Python 3.10 or newer, on Windows or in WSL.
- The CUDA toolkit to build `gpucheck` and `ramp` (`gpucheck/build.sh`, or `nvcc -O2 -o gpucheck.exe gpucheck.cu`).
- For trials: 3DMark (Time Spy). For the VBIOS workflow: nvflash, Vix Editor and Vix Loader (see docs/VBIOS.md).
- In Afterburner: save your factory or daily curve to a slot (the source slot), keep a known stable slot (the safe
  slot), and enable the voltage graph in Settings, Monitoring (needed for light mode).

## Setup

1. Copy `bwoc.example.ini` to `bwoc.ini` and edit it. Every key is explained in the file.
2. If Python runs unelevated or in WSL, use `elevated.mode = helper` and register the helper and the clock cap
   from an administrator PowerShell:

   ```
   .\tools\install-tasks.ps1 -ProfileFile 'C:\Program Files (x86)\MSI Afterburner\Profiles\VEN_10DE&DEV_....cfg' -CapMax 3330
   ```

3. Check the readings: `python -m bwoc telemetry`.
4. For Time Spy trials: fill in `[3dmark]` and copy the workload files (see
   [docs/VALIDATION.md](docs/VALIDATION.md)).

## Commands

| Command | What it does |
|---|---|
| `python -m bwoc sweep --volts 1050,1000,950 [--mode heavy\|light] [--start 1000:420,950:450]` | per-voltage search (crashes the GPU on purpose) |
| `python -m bwoc sweep ... --resume` | continue after a crash (use from a logon task) |
| `python -m bwoc curve [--profile N]` | show a profile's V/F curve |
| `python -m bwoc curve --offset 300 --apply` | write one offset to every point of the work slot and apply it |
| `python -m bwoc curve --softcap 3090 [--below 1060] [--apply]` | soft cap: the source curve with every point at or under `--below` mV held to at most the cap, points above untouched, written to the work slot |
| `python -m bwoc cap 3330` / `cap --reset` | set or remove the clock cap |
| `python -m bwoc profile N` | apply an Afterburner slot |
| `python -m bwoc telemetry` | one line of live clock, voltage, power and load |
| `python -m bwoc tse --runs 8 [--profile N] [--cap MHz] [--rate]` | N direct 3DMark test launches (Time Spy Extreme GT2 by default), hang noticed in about 2 s |
| `python -m bwoc hangscan telemetry.csv` | find the heavy-scene hang signature in a 100 ms telemetry log |

Use `--mode heavy` (3 blocks per SM) up to about 1050 mV and `--mode light` (1 block per SM) for the top of the
curve, which the card only runs at light load.

## Tools

| File | What it does |
|---|---|
| `tools/helper.ps1` | elevated helper: clock lock and cap, profile write and apply, `abwp` (Afterburner `/wp` writes such as `XBARCLK_off`), `abreport` (extended report), plus `romsave`, `vix*` and `pclick` |
| `tools/install-tasks.ps1` | logon tasks for the helper and the clock cap |
| `tools/mahm1.ps1` | one sample of Afterburner's live data |
| `tools/mahmlog.ps1` | Afterburner's live data to CSV every 100 ms, flushed per line (survives a hard hang); reopens the shared memory after an Afterburner restart; logs XBAR, SYS and aux voltage when Afterburner publishes them; handles names with and without the `GPU1 ` prefix |
| `tools/luid.ps1` | lists DXGI adapters and their LUIDs (3DMark workloads need the current one; it changes every boot) |
| `tools/winrect.ps1` | rectangle and window style of a running test window (tells borderless fullscreen from the fallback window) |
| `tools/screen.ps1` | the primary display's native size (default `swapchain_resolution`) |
| `tools/awake.ps1` | keeps the displays awake (3DMark aborts if a display sleeps) |
| `tools/romdump.ps1` | NvAPI VBIOS image, read-only; truncated on the 5090, for a look only |
| `tools/vbios.py` | offline VBIOS check, field list, edit with a full field diff, image diff (Vix Editor command line) |
| `gpucheck/gpucheck.cu` | CUDA FP32 checksum check with pulsed load (the search's load) |
| `gpucheck/ramp.cu` | CUDA light-to-full load ramp with checksums (did not reproduce the 3D hang) |

## Tips from the 5090 run

- Validate with the real 3D workload, cold and warm, not only with the search's load. Log at 100 ms while you do.
- Check that the 3D workload really runs fullscreen on one display, with no monitor on the iGPU. Our fallback window
  rendered 18 % fewer frames than fullscreen, so its hang rates understated the load.
- Count runs: 16 clean runs only rule out hang rates above about 17 %, 60 above 5 %.
- Start each voltage near its extrapolated edge (`--start`). Each edge costs a crash.
- The clock nvidia-smi reports sits 15 to 23 MHz under any lock. The tool allows 30 MHz.
- Measure the real top voltage first (`telemetry` at light load). Our card never went past 1.120 V, so points
  above it are never used.
- If several voltages fail at the same offset, re-test with only the point under test raised.
- A clock cap (`nvidia-smi -lgc 210,MAX`) only helps if it sits under the clocks where the card fails. A driver
  reset clears it, so re-apply it after every reset. A soft cap written into the curve (`curve --softcap`) needs
  no background tool and survives resets once the profile is applied again.
- If hangs land on the same clock whatever the voltage, stop adding margin per voltage: it is a clock wall. Find
  it with a soft cap ladder (15 MHz steps, 3 runs each) and keep the top of the curve.
- Check the GPU is idle and the displays will stay awake before an unattended run.

## The suite

| Repo | What it is |
|---|---|
| [overclock-autopilot](https://github.com/Xipzer/overclock-autopilot) | Generic core: test engine, safety rails, run ledger |
| [raptor-lake-overclock-autopilot](https://github.com/Xipzer/raptor-lake-overclock-autopilot) | Intel 13th and 14th gen CPU and DDR5 edition |
| [blackwell-overclock-autopilot](https://github.com/Xipzer/blackwell-overclock-autopilot) (this one) | NVIDIA RTX 50 edition |
| [raptor-lake-field-notes](https://github.com/Xipzer/raptor-lake-field-notes) | Data and lessons from the Raptor Lake campaign |
| [blackwell-field-notes](https://github.com/Xipzer/blackwell-field-notes) | Data and lessons from the RTX 5090 tuning |
| [blackout-tray](https://github.com/Xipzer/blackout-tray) | Tray app for fans, RGB and screens, plus a GPU clock cap that follows the coolant temperature |

## Licence

PolyForm Noncommercial 1.0.0. See [LICENSE.md](LICENSE.md).

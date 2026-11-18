# Validation: Time Spy trials, the hang signature, telemetry

The per-voltage search ([METHOD.md](METHOD.md)) finds what each point survives under a steady load. Real 3D work
failed 30 to 110 MHz lower on the RTX 5090, and its failure was a different kind: a hang in one heavy scene of
Time Spy Extreme Graphics Test 2. This page covers the tools built to test that case without clicking, and what they
found. The full story and the numbers are in [blackwell-field-notes](https://github.com/Xipzer/blackwell-field-notes).

## Direct 3DMark launches (`python -m bwoc tse`)

3DMark starts each graphics test as its own process, `3DMarkTimeSpy.exe --in <workload.json> --out <result.json>`.
With a copy of the workload file you can start one test directly, as often as you like, with no 3DMark window.

Getting the workload files, once:

1. Start a normal run of the test (for example a Time Spy Extreme custom run with only Graphics Test 2).
2. While it runs, read the test process's command line, in PowerShell:
   `Get-CimInstance Win32_Process -Filter "Name='3DMarkTimeSpy.exe'" | Select-Object -Expand CommandLine`
3. Copy the file given after `--in` to `workload_dir` as `gt2.json` (and the same for `gt1.json`). The tool
   rewrites four keys before every launch: `dxgi_adapter_luid` (the current one), `is_windowed` (`false`),
   `is_borderless` (`[3dmark] borderless`, default `true`) and `swapchain_resolution` (`[3dmark] swapchain`, default
   the primary display's native size). See "Display mode" below for why all four matter.
4. Set `[3dmark] exe` to the test binary (`...\3DMark\dlc\time-spy-test\bin\x64\3DMarkTimeSpy.exe` for Time Spy).

What the tool handles:

| Problem | What happens | Handling |
|---|---|---|
| The run is not fullscreen | a copied workload can say `"is_windowed": true`; with `"is_windowed": false` alone, 3DMark went fullscreen only on the first run after a boot and then fell back to a 3840x2160 window across monitors (about 141 fps against 172 in GT2) | `is_windowed: false`, `is_borderless: true` and a native-size `swapchain_resolution` are written before each launch; the window is read once per run (`tools/winrect.ps1`) and each result records `mode` (`borderless`, `windowed`, ...) with a warning when it was not fullscreen |
| The DXGI adapter LUID changes on every boot | 3DMark refuses the launch: "No DXGI adapter with given luid found". It looks like a failed run | `tools/luid.ps1` lists the adapters; the LUID is written into the workload before each launch |
| A hang takes minutes to notice | waiting for the process to end cost up to 150 s per hang | every 2 s one PowerShell call checks the process and the System log (event 4101, any nvlddmkm event) |
| A launch that never ran | locked drive, stale LUID, sleeping display: no result and no reset | not counted; relaunched up to `trial.relaunch` times |
| A driver reset drops the settings | the curve, the memory offset and the clock cap are gone after a reset | `--profile N --cap MHz` are re-applied before the trial and after every failure |
| The GPU is already busy | a trial started on top of someone's benchmark | preflight refuses to start above 20 % load |

```
python -m bwoc tse --runs 8 --profile 1 --cap 3090            # gate: stops at the first hang
python -m bwoc tse --runs 8 --profile 1 --rate --label p1     # measures the hang rate over all 8 runs
python -m bwoc tse --tests gt1,gt2 --runs 4                   # both tests, back to back
```

A run passes when the process exits by itself, 3DMark wrote a result, and no driver reset was logged.

Back-to-back direct launches are harsher than full 3DMark runs. On the 5090 the same setup hung 5 times in 8 direct
GT2 runs (windowed; 3 in 8 with `is_windowed: false`, which also ended up in a window) while full app runs (with
demo, loading and the CPU test between graphics tests) passed. Use the harness to compare settings with each other,
not to predict how often a full run fails.

## Display mode: check it, do not assume it

A direct launch does not reliably run the way the workload asks. What we measured on the 5090, four monitors, GT2,
window read about 30 s into each run with `GetWindowRect` and `GetWindowLong(GWL_STYLE)`:

| Workload settings | Window | GT2 fps |
|---|---|---|
| `is_windowed: true` (as copied) | ordinary window across monitors | about 149 |
| `is_windowed: false` (exclusive fullscreen) | first run after a boot fullscreen; every later run an ordinary 3840x2160 window at 0,0 to 3856,2199, style `0x14CF0000` | 172.5, then 141.0 |
| `is_windowed: true`, `is_borderless: true`, 1920x1080 swapchain | ordinary window, `0x14CF0000` | 140.4 |
| **`is_windowed: false`, `is_borderless: true`, 1920x1080 swapchain** | **0,0 to 1920,1080, style `0x94000000`, every run** | **171.8, 171.8, 172.0** |

Style `0x14CF0000` has `WS_CAPTION` (`0x00C00000`): a normal window. `0x94000000` is `WS_POPUP | WS_VISIBLE |
WS_CLIPSIBLINGS`: borderless and display-sized. The harness calls a run `windowed` when the caption bit is set and
`borderless` when there is no caption and the size equals the swapchain.

Why it matters: the fallback window is a lighter load. PresentMon showed the GPU idle about 13 % of each frame
(GPU busy 6.07 ms of 7.09 ms) and HWiNFO's "Performance Limit - Utilization" flag stayed on. Hang rates measured in
it understate the load and overstate the margin, and its fps only compare within one session.

A second display adapter matters too: with one monitor on the Intel iGPU, the fallback window ran about 5.5 % slower
(152.7 to 153.1 fps against 161.3 to 162.0 with the iGPU disabled), and HWiNFO running hid most of that. Put every
monitor on the NVIDIA card and disable the iGPU in Windows and the BIOS before measuring. Details, sources and a
clean measurement checklist: [blackwell-field-notes QUIRKS.md](https://github.com/Xipzer/blackwell-field-notes/blob/main/QUIRKS.md).

## Displays must stay awake

3DMark aborts with `window_focus_lost: Display resolution changed` if a display goes to sleep. For unattended trials
run `tools/awake.ps1` (keeps the system and displays awake until `awake.stop` appears or `-Hours` pass). Dimming the
screens over DDC is fine; sleep is not.

## Telemetry at 100 ms (`tools/mahmlog.ps1`)

nvidia-smi does not report core voltage and its 1 s sampling misses the event. `tools/mahmlog.ps1` reads
Afterburner's shared memory every 100 ms and writes `time,clock,voltage,power,usage,temp,xbar,sys,auxv,mem`,
flushing each line, so the log survives a hard hang up to the last sample.

```
powershell -ExecutionPolicy Bypass -File tools\mahmlog.ps1 -Out C:\bwoc\telemetry.csv
```

Three things to get right, all found the hard way on 18 Nov:

- **Afterburner's own polling period.** Afterburner reads the hardware every `HwPollPeriod` ms, and the default is
  1000. A 100 ms log then repeats each 1 s value ten times. Set `HwPollPeriod=100` in `Profiles\MSIAfterburner.cfg`.
  The global settings live in that file, not in the `MSIAfterburner.cfg` next to the exe (that one still read 1000
  after the change). On the 5090 every "100 ms" log before 18 Nov was really 1 s data.
- **Afterburner restarts.** If Afterburner restarts while a logger holds `MAHMSharedMemory` open, the new instance
  does not publish into the old mapping: the logger keeps reading frozen values (the signature at offset 0 becomes
  `0xDEAD`, or the timestamp at offset 20 stops moving). On the 5090 this left two whole series of `is_windowed: false` runs
  with a flat log, including the hang with a 3,090 MHz cap. The logger now checks the signature and the timestamp
  and reopens the mapping when either goes stale (`-StaleSeconds`, default 5).
- **Extra rails.** Afterburner 4.6.7 Beta 5 with the "out of warranty" voltage control option (`OEM=3` in
  `Profiles\MSIAfterburner.cfg`) adds the crossbar clock (XBAR), the system clock and the aux voltage (MSVDD) to the
  shared memory. The logger writes them in `xbar`, `sys` and `auxv`; the columns stay empty without that option.
  With only one GPU in the system (iGPU disabled) Afterburner drops the `GPU1 ` prefix from every name
  (`Core clock`, `GPU voltage`, `Crossbar clock`, ...); the core voltage is then `GPU voltage`, not `Voltage`. The
  logger tries the prefixed name first and falls back to the plain one. Newly named graphs may need ticking in the
  Monitoring tab before Afterburner publishes them.
  The same mode allows low-level writes (helper command `abwp`, for example `abwp XBARCLK_off 300`) and an extended
  report (helper command `abreport NAME`: SPEEDO, IDDQ, Vrel and Vop per rail, clock domains, V/F points). Driver
  621.x ignores `NVVDD_off_Vrel` and `MSVDD_off_Vrel` like it ignores the voltage slider.

**XBAR offset on the 5090** (Profile 1 curve, cap 3,090 MHz, fallback window): +0 = 2,415 MHz under load, 153.7 to
154.0 fps; +100 = 2,505, 155.8; +200 = 2,602, 156.9; +300 = 2,707 MHz (0.91 x core, about the 0.90 ratio ceiling),
157.8 fps (+2.6 %). A driver reset or restart clears it; re-apply it with the curve.

**HWiNFO.** Only HWiNFO Pro can start and stop a sensor log from the command line. On the free version, set
`SensorsSM=1` in `HWiNFO64.INI` and read the shared memory (`Global\HWiNFO_SENS_SM2`) yourself. Sensor indices move
between HWiNFO restarts, so look values up by name on every poll. Other keys we used: `oneAPI=0` (avoids a crash with
old Intel iGPU drivers), `PresentMon`, `NvmlSupport` (no fps effect either way). Useful values: GPU effective clock
(matched the requested clock at the median under GT2 load), crossbar and system domain clocks, MSVDD output voltage,
and the five Performance Limit flags (Power, Thermal, Reliability Voltage, Max Operating Voltage, Utilization).

For the clock limit reasons (power cap, thermal, reliability voltage), log nvidia-smi alongside it:

```
nvidia-smi --query-gpu=timestamp,clocks.gr,power.draw,power.limit,temperature.gpu,clocks_event_reasons.active,clocks_event_reasons.sw_power_cap,clocks_event_reasons.hw_slowdown,clocks_event_reasons.sw_thermal_slowdown --format=csv -lms 1000 -f limits.csv
```

## The hang signature (`python -m bwoc hangscan`)

Every Time Spy hang on the 5090 had the same shape in the 100 ms log:

1. A heavy scene: 2,990 to 3,150 MHz at 985 to 1,050 mV, 410 to 600 W.
2. Within one sample, power collapses to 120 to 155 W while usage stays at 98 to 100 %. The GPU has stopped mid-frame.
3. Because power fell, the clock jumps to the top of the curve (3,120 to 3,270 MHz). This jump looks like a light-load
   boost crash but it is a symptom: the GPU had already hung.
4. A driver reset (event 4101, nvlddmkm event 14 "PF FLR") 2 to 15 s later, or a full Windows freeze.

With true 100 ms polling (after the `HwPollPeriod` fix above) one more step shows up between 1 and 2: the readings
freeze for a few samples. One hang (cap 3,060 MHz, 700 W, `is_windowed: false`, 18 Nov):

| Time (UTC) | Clock | Voltage | Power | Usage | Core | XBAR | SYS | Aux |
|---|---|---|---|---|---|---|---|---|
| 09:39:06.328 | 2,932 | 0.960 V | 528.7 W | 100 % | 47 C | 2,407 | 2,437 | 1.040 V |
| 09:39:06.438 to .765 | 2,932 | 0.960 V | 427.2 W (same value, 4 samples) | 100 % | 47 C | 2,407 | 2,437 | 1.040 V |
| 09:39:06.873 | 3,052 | 0.975 V | 116.0 W | 100 % | 36 C | 2,475 | 2,520 | 1.055 V |

The harness saw the driver reset about 20 s after the freeze. XBAR, SYS and the aux voltage were steady right up
to the hang, with no dip or spike before it, so they gave no trigger signature.

A normal scene change or loading screen drops usage together with power, so it does not match. The scanner flags a
sample over `--heavy-w` (400 W) followed within `--window` (3 s) by at least `--min-low` (1 s) of samples under
`--low-w` (200 W) at `--busy-pct` (95 %) usage or more:

```
python -m bwoc hangscan telemetry.csv > hangs.csv
```

On the 5090's log of 17 and 18 Nov it found every logged Time Spy hang but one: a windowed hard freeze, logged at
1 s polling, whose last heavy sample was only about 310 W (under `--heavy-w`). Its false positives were runs of the CUDA
load-ramp test (`gpucheck/ramp.cu`), which holds the GPU at 100 % usage and 170 W on purpose. Check flagged times
against what was running.

## Re-tests with `is_windowed: false` (18 Nov)

Every harness hang rate before 18 Nov 09:00 UTC was measured windowed. These re-runs asked for fullscreen but, as
found later that day, ran in the 3840x2160 fallback window (see "Display mode" above). They compare with each other,
not with real fullscreen (Profile 1 curve, 700 W limit, memory +3000, GT2 direct launches):

| Setup | Result | GT2 fps (passing runs) |
|---|---|---|
| Profile 1 as is | 3 hangs in 8 runs (windowed: 5 in 8) | 154.5 to 156.3 |
| Cap 3,090 MHz (`-lgc 210,3090`) | hung on run 4 of 12 | 167.1 to 167.9 |
| Cap 3,060 MHz | hung on run 9 of 12 (real 2,932 MHz at 960 mV, about 530 W, 47 C) | 152.4 to 153.6 |
| Whole curve 30 MHz lower at every voltage, no cap | hung on run 6 of 12 | 154.8 to 155.4 |
| Whole curve 60 MHz lower at every voltage, no cap | **clean 12 of 12** | 153.6 to 155.1 |
| Whole curve 45 MHz lower at every voltage, no cap | **clean 12 of 12** | 154.1 to 155.3 |
| Whole curve 45 MHz lower, XBAR +300 | **clean 12 of 12** | 157.8 to 167.2 |
| Per voltage band vs Profile 1 (up to 980 mV +15, 981 to 1,005 -30, 1,006 to 1,030 -75, 1,031 to 1,060 -45), XBAR +300 | clean 11 of 11 (4 hangs on the way, all at 1,010 to 1,035 mV and 3,052 to 3,105 MHz) | 158.7 to 160.0 |

Repeated in borderless fullscreen with the fixed harness: see the next section. Run counts: 1 run to screen a step, 3 to keep it,
10 to 12 only for the final pass. 16 clean runs bound the hang rate under about 17 % and 60 clean runs under 5 %
(95 %, one-sided: 1 - 0.05^(1/n)); 8 runs cannot tell 5 hangs in 8 from 3.

The fps "states" (about 155 in most sessions, 167 to 173 in a few, 137 to 141 later) were the display path, not
the GPU: the fallback window, the iGPU monitor and HWiNFO's polling of the iGPU. Core clocks were the same in all
of them.

## Borderless fullscreen results (18 Nov evening)

Fixed harness (`is_windowed: false`, `is_borderless: true`, swapchain 1920x1080), 700 W, memory +3000, XBAR +300:

| Setup | Result | GT2 fps |
|---|---|---|
| Per band vs Profile 1, two passes (the second monotonic), 1,006 to 1,030 mV band from -60 down to -120 | kept hanging at 3,045 to 3,090 MHz, 1,000 to 1,020 mV | 171.6 to 174.0 |
| Soft cap 3,045 / 3,060 / 3,075 / 3,090 MHz up to 1,060 mV | clean 3 of 3 each | 172.7 to 173.5 |
| Soft cap 3,105 | hung on run 2 | 173.5 |
| Soft cap 3,090, final pass | 1 hang, 3 clean (6 clean, 1 hang in 7 overall) | 172.9 to 173.3 |
| Soft cap 3,075, final pass | 3 of 3 (6 of 6 overall) | 171.9 to 173.4 |
| Soft cap 3,090, ReBAR forced for 3DMark | 3 of 3 | 175.4 to 175.9 |
| same, XBAR +400 / +500 | clean (1 run / 4 runs) | 176.6 / 176.4 to 176.9 |

ReBAR A/B on the same profile: 173.5 and 173.0 default, 175.5 and 175.3 forced, 173.1 off again. XBAR under load:
+300 = 2,647 MHz, +400 = 2,737, +500 = 2,775 (about 0.9 x core, the ceiling). Method and reading:
[METHOD.md](METHOD.md#the-soft-cap-what-finally-worked).

## What did not reproduce the hang

Each of these was run at a setting that hung Time Spy GT2, and passed:

| Load | Result |
|---|---|
| FurMark 2 (Vulkan), steady, any window size | pass; FurMark also overstates the limits (see METHOD.md) |
| FurMark load steps: light vsync FurMark plus heavy 2560x1440 FurMark every ~6 s | 40 load steps, no crash |
| `gpucheck/ramp.cu`: light compute, stepped ramp to full, back | 23 cycles, 0 errors, no reset |
| OCCT 3D Adaptive (Variable and Switch) | 19 + 10 min clean, but it only drove the card to 2,700 to 3,020 MHz, under the hang zone |
| 3DMark Steel Nomad Stress Test, 20 loops | 99.2 % stability, no reset |

So keep a real 3D workload that reaches the hang clocks in the test plan.

## OCCT GUI automation, notes

OCCT has no command line for its GPU tests, and it runs elevated, so posted window messages do not reach it. What
worked:

- The elevated helper's `pclick PROC X Y`: it brings the largest window of process PROC to the front and does a real
  mouse click (SetCursorPos and mouse_event) at X,Y pixels from the window's top-left corner.
- Coordinates depend on the OCCT version, window size and display scaling. Take a screenshot of the window, read the
  positions of: Stability test, 3D Adaptive, the mode (Variable or Switch), the duration, and Start. Keep the window
  size fixed between runs.
- Watch the System log for driver resets while it runs (the same check as the Time Spy harness) and take a
  screenshot at the end for OCCT's verdict.
- Do not move the mouse or use the PC while the clicks run. Check the GPU is idle first.
- OCCT's 3D Adaptive on the 5090 never went past about 3,020 MHz, so it could not test the clocks where Time Spy hung.

## Practical gotchas

- **BitLocker**: after some restarts the second drive (with the 3DMark library) stayed locked, so every launch
  failed without running. The harness preflight checks the exe path; unlock the drive first.
- **The DXGI LUID changes every boot** (above).
- **`nvidia-smi -lgc F,F` does not hold F on Blackwell** under a heavy 3D load: the card ran about 100 MHz under a
  min=max lock and temperature bins move it further. Use `-lgc 210,CAP` as a ceiling only.
- **A driver reset clears the cap and offsets.** Re-apply after every failure (the harness does) and in normal use
  (a logon task plus a task on event 4101, or a tray app that re-sends the cap every minute).
- **`pkill -f PATTERN` can kill your own shell** when the pattern is also in that shell's command line. Match the
  exact process name instead.
- **Check that the GPU is idle** before starting any test; an unattended test once collided with a benchmark.
- **One harness at a time.** Two scripts launching 3DMark together gave about 90 fps runs that mean nothing.
- **Check the window and the adapter** (see "Display mode"): one monitor on the iGPU or a fallback window changes
  the load more than most curve changes do.

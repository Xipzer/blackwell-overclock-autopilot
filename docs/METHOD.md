# Method

How the search works, why it works that way, and what we learned building it on an RTX 5090.
Results from that card are in [blackwell-field-notes](https://github.com/Xipzer/blackwell-field-notes).

## The idea: test one V/F point at a time

An NVIDIA card picks its clock from a voltage/frequency curve. Afterburner lets you add an offset to each
point. A normal overclock adds one offset to the whole curve and hopes every point holds. That hides the real
question: how far can each voltage go?

To test one point:

1. Write the same offset O to every point of the work profile and apply it. The point at voltage V now asks for
   F = base(V) + O, where base(V) is the factory clock at V (read from the source profile).
2. Lock the clock with `nvidia-smi -lgc F,F`. The driver now runs the lowest voltage that gives F on the
   current curve, which is V.
3. Run a load that the card can hold at that point, check its results, and watch for driver resets.

A uniform offset is used, not a single raised point, so the curve stays monotonic and the driver has no reason to
choose a different point.

## Isolating one point

A uniform offset has one weakness: a failure could come from another part of the curve, not from V. On the 5090 the
edges at 900, 950 and 1000 mV all came at +510, which looked like that. The check: give the offset only to V and the
points above it, keep every point below at a known safe offset (+300 here), and re-test the failing step. The curve
stays monotonic as long as the offset under test is higher than the safe one.

On the 5090 both re-tests failed again at +510 (1000 mV: PC went down; 950 mV: 5 driver resets, recovered), so the
edges were real silicon limits. The tool does not do this yet; it was done by hand.

## The check: gpucheck

`gpucheck/gpucheck.cu` runs deterministic FP32 FMA chains on every SM. Each launch sums a hash of each block's
result. The first launch is the reference; every later launch must match it bit for bit (same inputs, same order).
Any difference is an error.

- Usage: `gpucheck <seconds> <blocks_per_sm> <busy_ms> <idle_ms>`.
- Output: a line every 5 s, then `RESULT errors=N launches=M`. A CUDA error prints `errors=-1` and exits.
- The load is pulsed (busy, then idle), so the clock sees load changes like a game does.
- Heavy mode uses 3 blocks per SM, 2000/400 ms. Full load (more blocks) hit the 600 W power limit and the card
  dropped under the lock, so the point was not really tested.
- Light mode uses 1 block per SM, 1500/600 ms. Under heavy load the 5090 held its voltage near 1.05 V (power,
  current and reliability limits), but at light load it runs the top of the curve, up to about 1.12 V. Those
  points can only be tested with a light load.

## Pass, fail, not reached

| Outcome | Rule |
|---|---|
| Pass | `RESULT errors=0`, no event 4101 or nvlddmkm event in the System log during the step, and the card ran the lock |
| Fail | checksum error, CUDA error, driver reset, or the PC went down during the step |
| Not reached | no error, but the highest clock seen was more than 30 MHz under the lock, or (light mode) the median voltage was more than 20 mV under V |

"Not reached" is not a result: the card was held back by a limit, so the point was not tested. The search stops
that voltage there.

The 30 MHz tolerance matters: the clock reported by nvidia-smi sits 15 to 23 MHz under any `-lgc` lock. Our first
pass used 8 MHz, and called every step "not reached".

## Steps

- Measure the real top voltage first. With the voltage slider at +100 % the 5090 held at most 1.115 to 1.120 V under
  any load (1.125 V only near idle). Points above that are never used, so searching them gives only "not reached".
- Start near the expected edge. On the 5090 the edge offset rose by about +30 MHz for each 50 mV lower, so after
  the first voltage, each next one can start about 60 to 90 MHz under its extrapolated edge (`--start`).
- 60 s per step was enough on the 5090: every failure came within the step.
- +30 MHz per step, then +15 MHz once the offset passes `fine_above`. Each failure costs a reboot, so the steps
  near the edge are small and each voltage is allowed one failure.
- `--bracket` retries one fine step above the last pass after a failure. Off by default because it costs a
  second crash.
- The driver accepts up to +1000 MHz per point; larger offsets are refused before they are written.

## Crash resume

Before each step a marker file (`state/vf-running-<mode>.json`) is written with the voltage, the clock, and the
last pass. It is removed when the step ends. If the program starts and the marker is there, the step was running
when the PC went down, so it is that voltage's first failure. Start the sweep with `--resume` from a logon task:
it waits `boot_delay` seconds (Afterburner and the helper need to start), records the failure, and carries on.

Disk checks after each crash were tried and dropped: a GPU fault cannot change data in RAM or on disk, and the
exposure is the same as a power cut, which NTFS journaling covers. Every check we did came back clean.

## After a failure and at the end

1. Apply `safe_profile` (a slot you know is stable).
2. Lock the clock to `cap.min_mhz,cap.max_mhz`.
3. At the end: `nvidia-smi -rgc`, apply `final_profile` (or the source slot), then the cap again.

## Result on the RTX 5090

| Voltage | Highest clean | First fail | Offset clean / fail | Load |
|---|---|---|---|---|
| 900 mV | 2,497 | 2,512 | +495 / +510 | heavy |
| 950 mV | 3,030 | 3,045 | +495 / +510 | heavy |
| 1000 mV | 3,195 | 3,225 | +480 / +510 | heavy |
| 1050 mV | 3,300 | 3,330 | +450 / +480 | heavy |
| 1100 mV | 3,382 | none (voltage ceiling) | +435 / - | light |

Clocks are lock targets in MHz. Most edges ended in a driver hang and a 0x133 bugcheck; one ended in driver resets
that recovered. Full data: [blackwell-field-notes](https://github.com/Xipzer/blackwell-field-notes).

## From limits to a curve

Done by hand for now:

1. Each tested point gets its clean offset minus 45 MHz (3 bins). Points in between are interpolated.
2. Points under the lowest tested voltage keep a known safe offset.
3. Points above the real top voltage do not matter; give them the top point's offset.
4. Cap the clock (`nvidia-smi -lgc 210,MAX`) at or under the highest clean top clock.
5. Validate: a benchmark, a stress test, and a run with hot water (45 C on the 5090).

On the 5090 this gave +450 at 900 and 950 mV, +435 at 1000, +405 at 1050, +390 at 1100 to 1125, +300 below
880 mV, a 3,330 MHz cap, and 15,678 in Steel Nomad (+2.6 % over a +180 uniform offset). The stress test and the hot
run are pending.

## Transient boost spikes and the clock cap

With a large offset, light-load moments (menus, alt-tab, loading screens) let the card jump to the top of the
curve, around 3,200 MHz on the 5090, a point no game load ever runs and nothing had tested. That crashed the
driver. The fix: `nvidia-smi -lgc 210,<cap>` keeps the full idle range but cuts off the top. It needs admin
rights and does not survive a reboot, so `tools/install-tasks.ps1 -CapMax N` adds a logon task.

After the per-voltage search the 5090's top ran 3,315 to 3,352 MHz with 0 errors, and the old spike crash did not
come back (the card runs cooler on water now), so its cap went up to 3,330.

A matching public report: https://rog-forum.asus.com/t5/gaming-notebooks/rtx-5090-laptop-gpu-hang-and-video-tdr-failure-regression/td-p/1157396/page/2

## Afterburner details

- Profiles live in `Profiles\VEN_10DE&DEV_xxxx&...cfg`, one file per card, under Program Files. Writing needs
  admin rights, hence the staged copy and the helper.
- `VFCurve=` is hex: a 12-byte header (uint32 format, uint32 point count, uint32 zero), then per point three
  little-endian floats (voltage mV, base MHz, offset MHz), then zero padding (1,688 bytes on the 5090 for 127
  points). The tool keeps the padding.
- `CoreClkBoost` and `MemClkBoost` are in kHz (`3000000` = +3000 MHz).
- `MSIAfterburner.exe -Profile5` applies slot 5 to a running Afterburner.
- The core voltage appears in Afterburner's shared memory (`MAHMSharedMemory`) only after enabling the voltage
  graph in Settings, Monitoring. nvidia-smi does not report voltage.
- Only the work slot is written. Your other slots are never touched.

## Elevated actions

Four actions need admin rights: `-lgc`, `-rgc`, writing the profile file, and applying a profile (Afterburner
runs elevated). `bwoc/elevated.py` puts them behind one interface:

- `mode = direct`: Python on Windows, started as administrator, does them itself.
- `mode = helper`: Python runs unelevated (or in WSL) and writes one line to `helper_dir/cmd.txt`;
  `tools/helper.ps1`, running elevated, executes it and writes `ack.txt` (`ok ...` or `error ...`). It accepts
  only `lgc MIN MAX`, `rgc`, `abwrite`, `abprof N` and `quit`, with checked arguments, and exits after 12 hours.

## Lessons

1. Check the tool before believing a ceiling. Our first "ceiling" was a tolerance bug.
2. Heavy load hides the top of the curve. The card will not run its highest voltages under a full load.
3. A uniform offset gave similar edge offsets (+450 to +510) at every voltage tested, because the factory curve
   already follows the silicon's slope. Raise only the point under test to prove an edge is that point's own.
4. Most edges ended in a hang and a 0x133 bugcheck, not a clean driver reset. Plan for reboots.
5. Measure the real top voltage before searching above it, and read the live voltage from Afterburner.
6. Files written just before a crash can be lost, as with a power cut. Commit and sync before each step.
7. A clock that passes a compute check is not the whole story: the transient boost to the top of the curve is
   what crashed in normal use.

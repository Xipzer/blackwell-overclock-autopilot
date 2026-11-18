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

## Compute limits are not 3D limits

A curve built from these compute limits (each point at its clean limit minus 45 MHz) crashed Time Spy Extreme at
once. Bisecting by voltage region in Time Spy showed the 3D limits 30 to 75 MHz under the compute limits (1000 mV:
+480 in compute, +405 in 3D). The compute check alone cannot set a 3D curve.

## The 3D search (FurMark) and why it overstates limits

The same per-point method with FurMark 2 (Vulkan, artifact scanner on) as the load: the offset only at and above
the voltage under test (+300 below), the clock locked, 30 to 60 s per step, the live voltage read from Afterburner,
and a watchdog that kills FurMark if it hangs after a driver reset. Two lessons cost most of a day:

- **A heavy steady load overstates the limit.** Under a full FurMark load the core is hot, and the driver drops
  temperature bins of about 15 MHz each, so a step "at 3,150 MHz" really ran at 3,060 to 3,100 MHz. FurMark passed
  1000 mV at +435 while Time Spy crashed at +420 with 3,150 to 3,172 MHz real. The search now shrinks the FurMark
  window (lighter load, cooler core) until the real clock is within 50 MHz of the lock, and records the real clock.
  Limits are kept in real MHz, not offsets.
- **Temperature bins move the whole curve.** A cold core (water 22 to 27 C) runs one or two bins higher at every
  voltage than a warm one. A curve tuned warm can fail cold. Tune or at least validate at the coldest condition
  the card will see.
- **A driver reset drops the curve and the lock**, and the next step then runs at stock settings and looks like a
  pass. A step whose median voltage is more than 20 mV over the target now counts as a failure (settings lost).

Offsets written into Afterburner's profile file are applied as written, at any temperature; the temperature
dependence comes from the driver's bins on top. Afterburner's curve editor works on the clocks shown at the
current temperature, so a curve dragged into shape warm gives different offsets from one dragged cold. Write
curves to the profile file (as this tool does), not through the editor.

FurMark 3D limits on the 5090 (real clocks, everyday water): 850 mV 1,800; 875 mV 2,122; 900 mV 2,332;
950 mV 3,000; 1000 mV 3,120; 1025 mV 3,157 to 3,202; 1050 mV 3,240; 1075 mV 3,247; 1100 mV 3,277.

## From limits to a curve

1. Each point gets the highest real clock the 3D search proved at that voltage. Points in between are
   interpolated; a point never gets less clock than a lower voltage.
2. Flatten the top: above the voltage where the clock stops rising, keep it flat, so the curve caps itself.
3. Validate with the real workload, cold and warm: Time Spy Extreme (or its GT2 alone, with the trial harness, see
   [VALIDATION.md](VALIDATION.md)), the Steel Nomad Stress Test, and a hot run.
4. Every crash: read the 100 ms telemetry before changing anything (`python -m bwoc hangscan`).

The 5090's max curve (Profile 1): 950 mV 3,015, 1000 mV 3,120, 1025 mV 3,202, 1050 mV 3,240, flat 3,247 from about
1,075 mV, memory +3000. Warm it passed 3 Time Spy Extreme runs and the Steel Nomad Stress Test (99.2 %). Cold, it
hangs in one heavy scene of Time Spy GT2; see the field notes.

## Clock caps

`nvidia-smi -lgc 210,<cap>` keeps the idle range and cuts off the top. It needs admin rights, does not survive a
reboot, and a driver reset clears it, so `tools/install-tasks.ps1 -CapMax N` adds a logon task, and a task on event
4101 (or a tray app that re-sends it every minute) puts it back after a reset.

What a cap can and cannot do: it only limits clocks above it. On the 5090, caps at 3,202 and 3,232 MHz did nothing
for the GT2 hang, because heavy scenes never reach those clocks. Caps at 3,060 and 3,090 MHz held heavy scenes under
the hang zone and passed 13 of 13 cold GT2 runs at 600 W.

`-lgc F,F` (min = max) does not hold F on Blackwell under a heavy 3D load: the card ran about 100 MHz under it.

The earlier "transient boost crash" (menus, alt-tab, light-load moments at the top of the curve) was most likely
the same heavy-scene hang seen from the wrong end: when the GPU hangs, power falls and the clock jumps to the top,
so the log shows a high clock at light load right before the reset.

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
  Optional extras, used by hand: `romsave`, `vixload`, `vixunload`, `vixverify`, `vixstatus` (see
  [VBIOS.md](VBIOS.md)) and `pclick PROC X Y` (see [VALIDATION.md](VALIDATION.md)).

## Lessons

1. Check the tool before believing a ceiling. Our first "ceiling" was a tolerance bug.
2. Heavy load hides the top of the curve. The card will not run its highest voltages under a full load.
3. A uniform offset gave similar edge offsets (+450 to +510) at every voltage tested, because the factory curve
   already follows the silicon's slope. Raise only the point under test to prove an edge is that point's own.
4. Most edges ended in a hang and a 0x133 bugcheck, not a clean driver reset. Plan for reboots.
5. Measure the real top voltage before searching above it, and read the live voltage from Afterburner.
6. Files written just before a crash can be lost, as with a power cut. Commit and sync before each step.
7. A clock that passes a compute check is not the whole story. 3D limits sat 30 to 110 MHz lower.
8. Log at 100 ms before tuning by crash. The clock jump before a reset is a symptom; the 100 ms log shows the GPU
   hung in a heavy phase first.
9. Run the controlled test before changing the curve: the same setting, the same condition, N runs. Lowering the
   1000 to 1025 mV points by 15 or 30 MHz did not stop the hang, and the whole curve minus 30 MHz most likely hung
   on its fifth run; that only became clear with repeated runs and the 100 ms log.
10. Every step changed only one thing, and every result is in the journal with its conditions (water temperature,
    driver state, VBIOS). Cold and warm runs are different tests.

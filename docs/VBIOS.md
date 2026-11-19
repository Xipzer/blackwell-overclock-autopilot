# A higher power limit without flashing: VBIOS override

The RTX 5090 Founders Edition stops at 600 W. Panchovix's
[Vix Editor](https://github.com/Panchovix/nvidia-vbios-vix-editor) edits a copy of the card's VBIOS, and the
[Windows Vix Loader](https://github.com/Panchovix/nvidia-windows-vbios-vix-loader) hands that copy to the NVIDIA
driver through a registry override (value `vbios` in the GPU's display class key). The card's flash chip is never
written. Unloading the override and restarting gives the stock VBIOS back.

> **Risk.** You run firmware values NVIDIA did not ship. 700 W through one 12V-2x6 connector is about 9.7 A per
> pin if it all comes through the connector, above the 9.2 to 9.5 A per-pin rating; 600 W is already 88 % of a
> 9.5 A rating (sources in the field notes). Check that the plug is fully seated, never bend the cable near the
> plug, and watch connector temperature or per-pin current if you can. Use at your own risk.

## Steps

All editing is offline. The only steps that touch the card are the read-only dump and the load.

1. **Dump the full image, read-only.** `nvflash --save card.rom` (nvflash 5.867 used; helper command `romsave`).
   Do not use NvAPI_GPU_GetVbiosImage (`tools/romdump.ps1`) for editing: on the 5090 it returned 458,240 bytes
   instead of the full 1,961,983, and the editor rejects it. Keep this file safe; it is your stock image.
2. **Check it:** `tools/vbios.py check card.rom` (size, SHA-256, the editor's integrity check, a warning on a
   truncated dump).
3. **List the fields:** `tools/vbios.py fields card.rom -o fields.json` (136 fields on the 5090 image 98.02.2E.00.03).
4. **Edit, offline:** `tools/vbios.py edit card.rom card-700w.rom --set power_max_w=700`. The editor runs in a
   private network namespace (`unshare -rn`), refuses a source whose SHA-256 changed, and the script then diffs all
   fields of the two images and stops if any field changed that you did not ask for and the editor did not list as
   linked. It also prints how many bytes differ (226 to 230 bytes on the 5090 for the edits below).
5. **Load:** copy the image to the helper folder as `vbios-override.rom`, then helper command `vixload`
   (`vbios-loader load --gpu 0 FILE`). It applies after a Windows restart.
6. **Verify after the restart:** `vixverify` compares the VBIOS the driver runs with the stored override, byte for
   byte, and `nvidia-smi --query-gpu=power.max_limit --format=csv` should show the new limit (700.00 W).
7. **Undo:** `vixunload`, restart, and check `power.max_limit` is back at 600 W.

Verify the editor and loader downloads against the release SHA256SUMS. The loader is open source; it writes only the
`vbios` value and a `VixLoaderPreviousEnableGpuFirmware` backup value in the GPU's driver key.

## What the fields do on the 5090 (measured on one card)

| Edit | Result |
|---|---|
| `power_max_w` 600 -> 700 | `power.max_limit` 700 W; Afterburner's power slider goes to 121 %. Time Spy Extreme graphics 28,223, best on this curve. But Time Spy Extreme peaked at about 592 W: the curve and the hang, not the power limit, set the result |
| `nvvdd_rel_equation_max_mv` / `msvdd_rel_equation_max_mv` 1110 -> 1150 (and the linked `*_rel_max_mv`) | nothing measurable. The reliability (REL) voltage is computed per chip. Afterburner's extended report (helper `abreport`) shows NVVDD Vrel 1,120 mV and MSVDD Vrel 1,070 mV (with a -50 mV MSVDD offset) on this card; the highest load voltage we saw, 1.115 to 1.120 V, matches the NVVDD figure. An earlier version of this page said the core REL was about 1,070 mV, which mixed up the rails |
| `msvdd_rel_equation_min_mv` 900 -> 1100 (the MSVDD REL floor) | Time Spy GT2 hang rate 4 in 9 runs (one of them a full Windows freeze) against 5 in 8 without it. Not a fix |
| `runtime_voltage_offsets` 0 -> 1 | loads fine, but mVolt+ v0.50.13 NVVDD offsets (`--nvvdd-offsets 0,25,25`) were still ignored on driver 621.24: success reported, `rail_offsets_ignored_by_driver: true`, `nvvdd_max` stayed 1,120 mV |
| `nvvdd_rel_equation_min_mv` 900 -> 1150 (the NVVDD REL floor; only field changed, 101 bytes) | **works.** After the restart mVolt+ `--status` reads `nvvdd_max` 1,170 mV (REL 1,150 plus the ALT +20 step), was 1,120. Under load the core tops out at about 1.135 V read (about 1.145 V set, the REL limit; ALT +20 unused). With the curve top ramped from 3,247 MHz at 1,070 mV to +255 at 1,170 mV, a light 720p GT1 load runs 3,360 to 3,382 MHz instead of 3,172 to 3,195 (4 of 4 clean; +315 hung at 3,457 MHz). **But heavy loads climb too**: Fire Strike Ultra ran 3,180 to 3,217 MHz at 1.065 to 1.08 V, on the old 1,065 to 1,070 mV step, and two driver resets followed; the 179.0 fps GT2 run from that curve is withdrawn. With the soft cap extended to 1,100 mV: GT2 176.6, 176.1, 176.2 fps clean, Fire Strike Ultra graphics 37,457 (+1.3 %) |

Background, from the editor's documentation and changelog:

- The REL floor (`*_rel_equation_min_mv`) is the field that raises the REL voltage; the ceiling does not. The chip
  computes its own Vrel (1,120 mV on ours) and the REL equation floor and ceiling clamp it, so a floor above the
  computed value sets the limit (our reading, confirmed by the 1,170 mV result above).
- On driver 621.01 and newer, RTX 50 cards ignore NVVDD and MSVDD runtime voltage offsets: the driver accepts them
  and reports success, but nothing changes. Afterburner's voltage slider is a no-op there. The editor's
  `runtime_voltage_offsets=1` adds hooks so a runtime tool can apply offsets again; on our card with driver 621.24
  and mVolt+ v0.50.13 they were still ignored, so use the static REL floor.

## Voltage lever: raising the core voltage limit

What worked on the 5090 FE (18 Nov 2026):

1. Start from the image you run now (for us the 700 W image with `runtime_voltage_offsets=1`).
2. `tools/vbios.py edit current.rom current-rel1150.rom --set nvvdd_rel_equation_min_mv=1150` and check that the
   diff lists only that field.
3. Load it (`vixload`), restart, `vixverify`, and read the limit back (mVolt+ `--status`, `nvvdd_max_mv`; or watch
   the highest voltage under a light load). Do not trust a tool's "success" without reading it back.
4. **Extend the soft cap first.** A higher voltage limit moves heavy loads up the curve too, so any clock step that
   heavy loads could not reach before becomes reachable. Hold every point up to where heavy loads can now go at the
   heavy-load wall (here 1,100 mV at 3,090 MHz), then ramp the top above it.
5. Search the top with a light load that actually sits there (Time Spy Extreme GT1 at 720p, about 250 W). A 720p
   load is CPU bound, so compare clocks, not fps. Then re-test heavy loads (GT2, Fire Strike Ultra) and log their
   voltage: if they run above the cap's last point, extend the cap.
6. Rollback: load the previous image again and restart.

Our ladder (18 Nov, cap only up to 1,060 mV, ramp from 3,247 MHz at 1,070 mV to 3,247 + D at 1,170 mV): D = +60,
+105, +150, +195, +255 clean (3,255 to 3,382 MHz read), +315 hung at 3,457 MHz / 1.145 V. Saved as Profile 1 +255,
Profile 2 +195.

What went wrong (19 Nov): 4K TSE GT1 had stayed at or under 1.02 V, so we assumed heavy loads would not use the new
top. Fire Strike Ultra then ran heavy scenes at 3,180 to 3,217 MHz and 1.065 to 1.08 V, on the step from 3,090 to
3,247 MHz at 1,065 to 1,070 mV. Two driver resets followed at about 610 to 620 W (last heavy samples 3,030 to
3,052 MHz at 1.03 to 1.045 V, then the power collapse). The 179.0 fps GT2 result on that curve came from the same
step and is withdrawn.

Current shape (19 Nov): points up to 1,100 mV capped at 3,090 MHz (Profile 1) / 3,075 (Profile 2),
straight ramp from 1,100 to 1,150 mV (3,090 -> 3,440 / 3,075 -> 3,380), flat above. TSE GT2 3 of 3 clean (176.6,
176.1, 176.2 fps, max 1.085 V, heavy load held at the wall), light 720p clean at 1.135 V, validated Fire Strike Ultra
34,409 overall / 37,457 graphics (+1.3 % over 36,975). Details:
[blackwell-field-notes, Voltage lever](https://github.com/Xipzer/blackwell-field-notes#voltage-lever) and Q28.

A driver reset wipes memory +3000 and the XBAR offset; re-apply both before trusting a score (Fire Strike Ultra
graphics 33,184 with both lost, 36,538 without XBAR, 37,457 with both).
- MSVDD feeds the fabric (XBAR and SYS clocks); XBAR runs at about 0.90 x the core clock. NVIDIA lowered the MSVDD
  REL by 50 mV from driver 572.60, which is why the MSVDD floor was worth a test.

## Gotchas

- **BitLocker**: a restart for the override can leave a second BitLocker drive locked. Anything installed there
  (3DMark) will not start until it is unlocked.
- **Check after driver updates.** The override lives in the driver's registry key; a clean reinstall may drop it
  (not tested). Check `power.max_limit` after every driver change.
- **A crash during a test is not a reason to blame the override by default.** On the 5090 the same hang came back
  on the stock VBIOS at 600 W.

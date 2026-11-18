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
| `nvvdd_rel_equation_max_mv` / `msvdd_rel_equation_max_mv` 1110 -> 1150 (and the linked `*_rel_max_mv`) | nothing measurable. The reliability (REL) voltage is computed per chip; on this card it sits near 1,070 mV, under the old 1,110 ceiling, so a higher ceiling changes nothing |
| `msvdd_rel_equation_min_mv` 900 -> 1100 (the MSVDD REL floor) | Time Spy GT2 hang rate 4 in 9 runs (one of them a full Windows freeze) against 5 in 8 without it. Not a fix |

Background, from the editor's documentation and changelog:

- The REL floor (`*_rel_equation_min_mv`) is the field that raises the REL voltage; the ceiling does not.
- On driver 621.01 and newer, RTX 50 cards ignore NVVDD and MSVDD runtime voltage offsets: the driver accepts them
  and reports success, but nothing changes. Afterburner's voltage slider is a no-op there. The editor's
  `runtime_voltage_offsets=1` adds hooks so a runtime tool can apply offsets again.
- MSVDD feeds the fabric (XBAR and SYS clocks); XBAR runs at about 0.90 x the core clock. NVIDIA lowered the MSVDD
  REL by 50 mV from driver 572.60, which is why the MSVDD floor was worth a test.

## Gotchas

- **BitLocker**: a restart for the override can leave a second BitLocker drive locked. Anything installed there
  (3DMark) will not start until it is unlocked.
- **Check after driver updates.** The override lives in the driver's registry key; a clean reinstall may drop it
  (not tested). Check `power.max_limit` after every driver change.
- **A crash during a test is not a reason to blame the override by default.** On the 5090 the same hang came back
  on the stock VBIOS at 600 W.

# Logs MSI Afterburner's live data to a CSV every -IntervalMs (default 100 ms) until -StopFile appears or -Hours pass.
# Columns: time,clock,voltage,power,usage,temp,xbar,sys,auxv,mem (clocks MHz, voltages V, power W, usage %, temperature C).
# xbar, sys and auxv (crossbar clock, system clock, aux/MSVDD voltage) stay empty unless Afterburner publishes them
# (4.6.7 Beta 5 with the "out of warranty" voltage control option, OEM=3 in Profiles\MSIAfterburner.cfg).
# Each line is flushed at once, so the log survives a hard hang or a power cycle up to the last sample.
# Feed the file to "python -m bwoc hangscan" to find the hang signature.
# Needs Afterburner running with the voltage, power, usage and temperature graphs enabled (Settings, Monitoring).
# Afterburner polls the hardware every HwPollPeriod ms (default 1000); set HwPollPeriod=100 in
# Profiles\MSIAfterburner.cfg, or a 100 ms log only repeats each 1 s value ten times.
# If Afterburner restarts, the old shared memory is marked dead (signature 0xDEAD) or its timestamp stops moving;
# the log then reopens MAHMSharedMemory instead of writing stale values.
# GPU1 is the first card; use -Gpu 2 for a second one.
param(
    [string]$Out = (Join-Path $PSScriptRoot 'telemetry.csv'),
    [int]$IntervalMs = 100,
    [int]$Gpu = 1,
    [double]$Hours = 24,
    [string]$StopFile = (Join-Path $PSScriptRoot 'telemetry.stop'),
    [double]$StaleSeconds = 5
)
$MAHM = 0x4D41484D
$new = -not (Test-Path $Out)
$w = New-Object System.IO.StreamWriter($Out, $true); $w.AutoFlush = $true
if ($new) { $w.WriteLine('time,clock,voltage,power,usage,temp,xbar,sys,auxv,mem') }
$g = "GPU$Gpu"
$end = (Get-Date).AddHours($Hours)
$m = $null; $v = $null; $lastT = $null; $seen = Get-Date

function Close-View { if ($script:v) { $script:v.Dispose() }; if ($script:m) { $script:m.Dispose() }; $script:v = $null; $script:m = $null }

while ((Get-Date) -lt $end -and -not (Test-Path $StopFile)) {
    if ($v -eq $null -or $v.ReadUInt32(0) -ne $MAHM) {
        Close-View
        try { $m = [System.IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting('MAHMSharedMemory'); $v = $m.CreateViewAccessor() }
        catch { Start-Sleep 1; continue }
        if ($v.ReadUInt32(0) -ne $MAHM) { Close-View; Start-Sleep 1; continue }
        $lastT = $null; $seen = Get-Date
    }
    $t = $v.ReadInt32(20)
    if ($t -ne $lastT) { $lastT = $t; $seen = Get-Date }
    elseif (((Get-Date) - $seen).TotalSeconds -gt $StaleSeconds) { Close-View; Start-Sleep 3; continue }
    $hs = $v.ReadUInt32(8); $ne = $v.ReadUInt32(12); $es = $v.ReadUInt32(16)
    $r = @{}
    for ($i = 0; $i -lt $ne; $i++) {
        $o = $hs + $i * $es; $b = New-Object byte[] 260; [void]$v.ReadArray($o, $b, 0, 260)
        $r[([Text.Encoding]::ASCII.GetString($b)).Split([char]0)[0]] = $v.ReadSingle($o + 1300)
    }
    $w.WriteLine(('{0},{1},{2:F3},{3:F1},{4},{5},{6},{7},{8:F3},{9}' -f (Get-Date -Format 'HH:mm:ss.fff'), $r["$g core clock"],
        $r["$g voltage"], $r["$g power"], $r["$g usage"], $r["$g temperature"], $r["$g crossbar clock"],
        $r["$g system clock"], $r["$g aux voltage"], $r["$g memory clock"]))
    Start-Sleep -Milliseconds $IntervalMs
}
Close-View
$w.Close()

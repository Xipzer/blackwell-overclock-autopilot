# Logs MSI Afterburner's live data to a CSV every -IntervalMs (default 100 ms) until -StopFile appears or -Hours pass.
# Columns: time,clock,voltage,power,usage,temp (clock MHz, voltage V, power W, usage %, temperature C).
# Each line is flushed at once, so the log survives a hard hang or a power cycle up to the last 100 ms.
# Feed the file to "python -m bwoc hangscan" to find the hang signature.
# Needs Afterburner running with the voltage, power, usage and temperature graphs enabled (Settings, Monitoring).
# GPU1 is the first card; use -Gpu 2 for a second one.
param(
    [string]$Out = (Join-Path $PSScriptRoot 'telemetry.csv'),
    [int]$IntervalMs = 100,
    [int]$Gpu = 1,
    [double]$Hours = 24,
    [string]$StopFile = (Join-Path $PSScriptRoot 'telemetry.stop')
)
$m = [System.IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting('MAHMSharedMemory')
$v = $m.CreateViewAccessor(); $hs = $v.ReadUInt32(8); $ne = $v.ReadUInt32(12); $es = $v.ReadUInt32(16)
$new = -not (Test-Path $Out)
$w = New-Object System.IO.StreamWriter($Out, $true); $w.AutoFlush = $true
if ($new) { $w.WriteLine('time,clock,voltage,power,usage,temp') }
$g = "GPU$Gpu"
$end = (Get-Date).AddHours($Hours)
while ((Get-Date) -lt $end -and -not (Test-Path $StopFile)) {
    $r = @{}
    for ($i = 0; $i -lt $ne; $i++) {
        $o = $hs + $i * $es; $b = New-Object byte[] 260; [void]$v.ReadArray($o, $b, 0, 260)
        $r[([Text.Encoding]::ASCII.GetString($b)).Split([char]0)[0]] = $v.ReadSingle($o + 1300)
    }
    $w.WriteLine(('{0},{1},{2:F3},{3:F1},{4},{5}' -f (Get-Date -Format 'HH:mm:ss.fff'), $r["$g core clock"], $r["$g voltage"],
        $r["$g power"], $r["$g usage"], $r["$g temperature"]))
    Start-Sleep -Milliseconds $IntervalMs
}
$w.Close()

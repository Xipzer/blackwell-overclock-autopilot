# Elevated helper for Blackwell OC Autopilot (elevated.mode = helper).
# Run it as administrator, for example from a scheduled task with "Run with highest privileges"
# (see install-tasks.ps1). It polls cmd.txt in its own folder, runs one fixed command, and writes ack.txt.
# It accepts only these commands, with checked arguments:
#   lgc MIN MAX   nvidia-smi -lgc MIN,MAX      (MHz, MAX <= 3600)
#   rgc           nvidia-smi -rgc
#   abwrite       copy ab-stage.cfg (this folder) over the Afterburner profile file given as -ProfileFile
#   abprof N      MSIAfterburner.exe -ProfileN (N = 1..5)
#   quit          exit
# It exits on its own after -Hours hours.
param(
    [Parameter(Mandatory = $true)][string]$ProfileFile,
    [string]$Afterburner = 'C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe',
    [string]$NvidiaSmi = 'C:\Windows\System32\nvidia-smi.exe',
    [double]$Hours = 12
)
$dir = $PSScriptRoot
$cmdFile = Join-Path $dir 'cmd.txt'
$ackFile = Join-Path $dir 'ack.txt'
$stage = Join-Path $dir 'ab-stage.cfg'
$end = (Get-Date).AddHours($Hours)

while ((Get-Date) -lt $end) {
    if (Test-Path $cmdFile) {
        $c = (Get-Content $cmdFile -Raw).Trim()
        Remove-Item $cmdFile -Force
        $a = $c -split '\s+'
        $msg = 'ok'
        try {
            switch ($a[0]) {
                'lgc' {
                    if ($a.Count -ge 3 -and $a[1] -match '^\d{3,4}$' -and $a[2] -match '^\d{3,4}$' -and [int]$a[2] -le 3600 -and [int]$a[1] -le [int]$a[2]) {
                        $out = (& $NvidiaSmi -lgc ($a[1] + ',' + $a[2]) 2>&1) -join ' '
                        $msg = $(if ($LASTEXITCODE -eq 0) { 'ok ' } else { 'error ' }) + $out
                    } else { $msg = 'error bad lgc' }
                }
                'rgc' {
                    $out = (& $NvidiaSmi -rgc 2>&1) -join ' '
                    $msg = $(if ($LASTEXITCODE -eq 0) { 'ok ' } else { 'error ' }) + $out
                }
                'abwrite' { Copy-Item $stage $ProfileFile -Force }
                'abprof' {
                    if ($a.Count -ge 2 -and $a[1] -match '^[1-5]$') { Start-Process -FilePath $Afterburner -ArgumentList ('-Profile' + $a[1]) }
                    else { $msg = 'error bad abprof' }
                }
                'quit' { 'ok quit' | Out-File $ackFile -Encoding ascii; exit }
                default { $msg = 'error unknown ' + $c }
            }
        } catch { $msg = 'error ' + $_.Exception.Message }
        Start-Sleep -Milliseconds 500
        $msg | Out-File $ackFile -Encoding ascii
    }
    Start-Sleep -Milliseconds 500
}

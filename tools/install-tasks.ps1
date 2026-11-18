# Creates two scheduled tasks for the current user. Run once from an administrator PowerShell.
#   "BWOC helper": starts tools\helper.ps1 elevated, on demand and at logon (set elevated.helper_task to its name).
#   "BWOC clock cap": runs nvidia-smi -lgc MIN,MAX at logon, because a clock lock does not survive a reboot.
# Example:
#   .\install-tasks.ps1 -ProfileFile 'C:\Program Files (x86)\MSI Afterburner\Profiles\VEN_10DE&DEV_2B85&....cfg' -CapMax 3180
# Remove with: Unregister-ScheduledTask -TaskName 'BWOC helper'; Unregister-ScheduledTask -TaskName 'BWOC clock cap'
param(
    [Parameter(Mandatory = $true)][string]$ProfileFile,
    [int]$CapMin = 210,
    [int]$CapMax = 0,
    [string]$NvidiaSmi = 'C:\Windows\System32\nvidia-smi.exe',
    # Optional, for the VBIOS commands of the helper (romsave, vixload, vixunload, vixverify, vixstatus).
    [string]$NvFlash = '',
    [string]$VixLoader = ''
)
$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 13)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user

$helper = Join-Path $PSScriptRoot 'helper.ps1'
$act = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ("-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$helper`" -ProfileFile `"$ProfileFile`"" +
    $(if ($NvFlash) { " -NvFlash `"$NvFlash`"" } else { '' }) + $(if ($VixLoader) { " -VixLoader `"$VixLoader`"" } else { '' }))
Register-ScheduledTask -TaskName 'BWOC helper' -Action $act -Trigger $logon -Principal $principal -Settings $settings -Force | Out-Null
Write-Output 'Registered: BWOC helper'

if ($CapMax -gt 0) {
    $capAct = New-ScheduledTaskAction -Execute $NvidiaSmi -Argument "-lgc $CapMin,$CapMax"
    $delayed = New-ScheduledTaskTrigger -AtLogOn -User $user
    $delayed.Delay = 'PT30S'
    Register-ScheduledTask -TaskName 'BWOC clock cap' -Action $capAct -Trigger $delayed -Principal $principal -Settings $settings -Force | Out-Null
    Write-Output "Registered: BWOC clock cap ($CapMin-$CapMax MHz at logon)"
}

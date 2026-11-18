# Keeps the system and the displays awake until -StopFile appears or -Hours pass.
# 3DMark aborts a run with "window_focus_lost: Display resolution changed" when a display goes to sleep, which
# looks like a failed run in an unattended trial. Turning the screens dark with DDC brightness is fine; sleep is not.
param(
    [double]$Hours = 9,
    [string]$StopFile = (Join-Path $PSScriptRoot 'awake.stop')
)
Add-Type -Name P -Namespace K -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
$end = (Get-Date).AddHours($Hours)
# ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED, renewed every 30 s
while ((Get-Date) -lt $end -and -not (Test-Path $StopFile)) { [void][K.P]::SetThreadExecutionState(0x80000003); Start-Sleep 30 }
[void][K.P]::SetThreadExecutionState(0x80000000)

# Elevated helper for Blackwell OC Autopilot (elevated.mode = helper).
# Run it as administrator, for example from a scheduled task with "Run with highest privileges"
# (see install-tasks.ps1). It polls cmd.txt in its own folder, runs one fixed command, and writes ack.txt.
# It accepts only these commands, with checked arguments:
#   lgc MIN MAX   nvidia-smi -lgc MIN,MAX      (MHz, MAX <= 3600)
#   rgc           nvidia-smi -rgc
#   abwrite       copy ab-stage.cfg (this folder) over the Afterburner profile file given as -ProfileFile
#   abprof N      MSIAfterburner.exe -ProfileN (N = 1..5)
#   abwp NAME V   MSIAfterburner.exe /wpNAME,V, a low-level write; needs Afterburner 4.6.7 Beta 5 or later in
#                 "out of warranty" mode (OEM=3). NAME: XBARCLK_off, SYSCLK_off, NVVDD_off_Vrel, MSVDD_off_Vrel.
#                 Example: abwp XBARCLK_off 300 (+300 MHz crossbar clock). A driver reset or reboot clears it.
#                 Driver 621.x ignores the two _off_Vrel voltage writes (see docs/VALIDATION.md).
#   abreport NAME MSIAfterburner.exe /wpMAKEREPORT,8,<this folder>\NAME.txt: the extended report (SPEEDO, IDDQ,
#                 Vrel/Vop per rail, clock domains, V/F points). Read-only. Same mode requirement as abwp.
#   romsave       nvflash --save vbios-full-<time>.rom (this folder); read-only, needs -NvFlash
#   vixload       vbios-loader load --gpu 0 vbios-override.rom (this folder); applies after a restart, needs -VixLoader
#   vixunload     vbios-loader unload --gpu 0; applies after a restart
#   vixverify     vbios-loader verify --gpu 0 (the running VBIOS against the stored override, byte for byte)
#   vixstatus     vbios-loader status
#   pclick P X Y  a real left click at X,Y (pixels from the top-left of process P's largest window), for elevated
#                 GUI apps that ignore posted messages (OCCT); see docs/VALIDATION.md
#   quit          exit
# It exits on its own after -Hours hours.
param(
    [Parameter(Mandatory = $true)][string]$ProfileFile,
    [string]$Afterburner = 'C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe',
    [string]$NvidiaSmi = 'C:\Windows\System32\nvidia-smi.exe',
    [string]$NvFlash = '',
    [string]$VixLoader = '',
    [double]$Hours = 12
)
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class Clk {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] static extern void mouse_event(uint f, int x, int y, uint d, IntPtr e);
  public static IntPtr Biggest(uint want) {
    IntPtr best = IntPtr.Zero; long area = 0;
    EnumWindows((h, l) => { uint pid; GetWindowThreadProcessId(h, out pid); if (pid != want) return true;
      RECT r; GetWindowRect(h, out r); long a = (long)(r.R - r.L) * (r.B - r.T); if (a > area) { area = a; best = h; } return true; }, IntPtr.Zero);
    return best;
  }
  public static void Click(IntPtr w, int x, int y) {
    RECT r; GetWindowRect(w, out r); SetForegroundWindow(w); System.Threading.Thread.Sleep(200);
    SetCursorPos(r.L + x, r.T + y); System.Threading.Thread.Sleep(50);
    mouse_event(2, 0, 0, 0, IntPtr.Zero); System.Threading.Thread.Sleep(50); mouse_event(4, 0, 0, 0, IntPtr.Zero);
  }
}
'@
function Tool([string]$exe, [string[]]$argv) {
    if (-not $exe -or -not (Test-Path -LiteralPath $exe)) { return 'error tool not set or missing: ' + $exe }
    $out = (& $exe @argv 2>&1) -join ' | '
    return $(if ($LASTEXITCODE -eq 0) { 'ok ' } else { 'error ' }) + $out
}
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
                'abwp' {
                    if ($a.Count -ge 3 -and $a[1] -match '^(XBARCLK_off|SYSCLK_off|NVVDD_off_Vrel|MSVDD_off_Vrel)$' -and $a[2] -match '^[-+]?\d{1,4}$') {
                        Start-Process -FilePath $Afterburner -ArgumentList ('/wp' + $a[1] + ',' + $a[2])
                    } else { $msg = 'error bad abwp' }
                }
                'abreport' {
                    if ($a.Count -ge 2 -and $a[1] -match '^[\w-]+$') {
                        Start-Process -FilePath $Afterburner -ArgumentList ('/wpMAKEREPORT,8,' + (Join-Path $dir ($a[1] + '.txt')))
                    } else { $msg = 'error bad abreport' }
                }
                'romsave' { $msg = Tool $NvFlash @('--save', (Join-Path $dir ('vbios-full-' + (Get-Date -f yyyyMMdd-HHmmss) + '.rom'))) }
                'vixload' { $msg = Tool $VixLoader @('load', '--gpu', '0', (Join-Path $dir 'vbios-override.rom')) }
                'vixunload' { $msg = Tool $VixLoader @('unload', '--gpu', '0') }
                'vixverify' { $msg = Tool $VixLoader @('verify', '--gpu', '0') }
                'vixstatus' { $msg = Tool $VixLoader @('status') }
                'pclick' {
                    if ($a.Count -ge 4 -and $a[1] -match '^[\w-]+$' -and $a[2] -match '^\d{1,4}$' -and $a[3] -match '^\d{1,4}$') {
                        $p = Get-Process $a[1] -ErrorAction SilentlyContinue | Select-Object -First 1
                        $h = if ($p) { [Clk]::Biggest([uint32]$p.Id) } else { [IntPtr]::Zero }
                        if ($h -ne [IntPtr]::Zero) { [Clk]::Click($h, [int]$a[2], [int]$a[3]) } else { $msg = 'error no window' }
                    } else { $msg = 'error bad pclick' }
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

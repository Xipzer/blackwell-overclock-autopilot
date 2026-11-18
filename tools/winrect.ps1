# Prints the main window of a running process as "rect L,T -> R,B style 0xSTYLE", or "no window".
# Used by the Time Spy harness to check that a run is really fullscreen on one display:
#   style 0x94000000 (WS_POPUP, no caption) with the swapchain size = borderless fullscreen (wanted)
#   style 0x14CF0000 (caption, sizing frame) = an ordinary window, often 3840x2160 across several monitors
param([string]$Name = '3DMarkTimeSpy')
Add-Type @"
using System; using System.Runtime.InteropServices;
public class WR { public struct RECT { public int L, T, R, B; }
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr h, int i); }
"@
[void][WR]::SetProcessDPIAware()
$p = Get-Process $Name -ErrorAction SilentlyContinue | ? { $_.MainWindowHandle -ne [IntPtr]::Zero } | select -First 1
if ($p) {
    $r = New-Object WR+RECT
    [void][WR]::GetWindowRect($p.MainWindowHandle, [ref]$r)
    'rect {0},{1} -> {2},{3} style 0x{4:X8}' -f $r.L, $r.T, $r.R, $r.B, [WR]::GetWindowLong($p.MainWindowHandle, -16)
} else { 'no window' }

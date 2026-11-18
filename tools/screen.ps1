# Prints the primary display's native size as "WIDTHxHEIGHT" (DPI-aware, so 150 % scaling does not shrink it).
# The Time Spy harness writes this into the workload's swapchain_resolution when [3dmark] swapchain is empty.
Add-Type @"
using System; using System.Runtime.InteropServices;
public class SC { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i); }
"@
[void][SC]::SetProcessDPIAware()
'{0}x{1}' -f [SC]::GetSystemMetrics(0), [SC]::GetSystemMetrics(1)

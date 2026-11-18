# Read-only: saves the VBIOS image the driver reports through NvAPI_GPU_GetVbiosImage, for a quick look only.
# On an RTX 5090 this returned 458,240 bytes, while the real image is 1,961,983 bytes: the NvAPI image is
# truncated and VBIOS editors reject it. For editing, dump the full image with "nvflash --save" instead
# (helper.ps1 command romsave). See docs/VBIOS.md.
param([string]$Out = (Join-Path $PSScriptRoot 'vbios-nvapi.rom'), [int]$Gpu = 0)
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class NvRom {
  [DllImport("nvapi64.dll", EntryPoint="nvapi_QueryInterface")] static extern IntPtr Q(uint id);
  delegate int Init(); delegate int Enum([Out] IntPtr[] h, out uint n);
  [StructLayout(LayoutKind.Sequential)] struct IMG { public uint version; public uint size; public IntPtr buffer; }
  delegate int Get(IntPtr gpu, ref IMG img);
  public static byte[] Read(int gpu) {
    var init = (Init)Marshal.GetDelegateForFunctionPointer(Q(0x0150E828), typeof(Init)); int r = init(); if (r != 0) throw new Exception("init " + r);
    var en = (Enum)Marshal.GetDelegateForFunctionPointer(Q(0xE5AC921F), typeof(Enum)); var h = new IntPtr[64]; uint n; r = en(h, out n); if (r != 0) throw new Exception("enum " + r);
    var get = (Get)Marshal.GetDelegateForFunctionPointer(Q(0xFC13EE11), typeof(Get));
    var img = new IMG(); img.version = 0x00020010; img.size = 0xFA000; img.buffer = Marshal.AllocHGlobal(0xFA000);
    r = get(h[gpu], ref img); if (r != 0) throw new Exception("get " + r);
    var b = new byte[img.size]; Marshal.Copy(img.buffer, b, 0, (int)img.size); return b; } }
'@
$b = [NvRom]::Read($Gpu); [IO.File]::WriteAllBytes($Out, $b); "saved $($b.Length) bytes to $Out"

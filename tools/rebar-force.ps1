# Force Resizable BAR (rBAR - Enable 0x000F00BA = 1) on the driver profiles that own the 3DMark executables, via NVAPI DRS.
# Run elevated. NPI .nip imports fail silently for these because the executables belong to predefined profiles.
$log = Join-Path $PSScriptRoot 'rebar-force.txt'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class Drs {
  [DllImport("nvapi64.dll", EntryPoint = "nvapi_QueryInterface", CallingConvention = CallingConvention.Cdecl)]
  static extern IntPtr QI(uint id);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int F0();
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int F1(out IntPtr h);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int FH(IntPtr h);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int FFind(IntPtr h, [MarshalAs(UnmanagedType.LPWStr)] string app, out IntPtr prof, IntPtr appBuf);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int FInfo(IntPtr h, IntPtr prof, IntPtr buf);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int FSet(IntPtr h, IntPtr prof, IntPtr buf);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int FGet(IntPtr h, IntPtr prof, uint id, IntPtr buf);
  static T D<T>(uint id) { return (T)(object)Marshal.GetDelegateForFunctionPointer(QI(id), typeof(T)); }
  public static string Run(string[] exes, uint settingId, uint value) {
    var sb = new StringBuilder();
    sb.AppendLine("init " + D<F0>(0x0150E828)());
    IntPtr s; sb.AppendLine("session " + D<F1>(0x0694D52E)(out s));
    sb.AppendLine("load " + D<FH>(0x375DBD6B)(s));
    foreach (var exe in exes) {
      int appSize = 4 + 4 + 4 * 4096 + 4;
      IntPtr app = Marshal.AllocHGlobal(appSize); for (int i = 0; i < appSize; i++) Marshal.WriteByte(app, i, 0);
      Marshal.WriteInt32(app, 0, appSize | (3 << 16));
      IntPtr prof; int r = D<FFind>(0xEEE566B2)(s, exe, out prof, app);
      if (r != 0) { sb.AppendLine(exe + " find " + r); continue; }
      int pSize = 4 + 4096 + 4 * 4;
      IntPtr pi = Marshal.AllocHGlobal(pSize); for (int i = 0; i < pSize; i++) Marshal.WriteByte(pi, i, 0);
      Marshal.WriteInt32(pi, 0, pSize | (1 << 16));
      int ri = D<FInfo>(0x61CD6FD6)(s, prof, pi);
      string name = Marshal.PtrToStringUni(new IntPtr(pi.ToInt64() + 4));
      int sSize = 4 + 4096 + 4 * 5 + 4100 + 4100;
      IntPtr st = Marshal.AllocHGlobal(sSize); for (int i = 0; i < sSize; i++) Marshal.WriteByte(st, i, 0);
      Marshal.WriteInt32(st, 0, sSize | (1 << 16));
      int rg = D<FGet>(0x73BF8338)(s, prof, settingId, st);
      uint before = rg == 0 ? (uint)Marshal.ReadInt32(st, 4 + 4096 + 20 + 4100) : 0xFFFFFFFF;
      for (int i = 0; i < sSize; i++) Marshal.WriteByte(st, i, 0);
      Marshal.WriteInt32(st, 0, sSize | (1 << 16));
      Marshal.WriteInt32(st, 4 + 4096, (int)settingId);
      Marshal.WriteInt32(st, 4 + 4096 + 20 + 4100, (int)value);
      int rs = D<FSet>(0x577DD202)(s, prof, st);
      sb.AppendLine(exe + " -> profile '" + name + "' info " + ri + " get " + rg + " before " + before + " set " + rs);
    }
    sb.AppendLine("save " + D<FH>(0xFCBC7E14)(s));
    sb.AppendLine("destroy " + D<FH>(0xDAD9CFF8)(s));
    return sb.ToString();
  }
}
'@
try {
  [Drs]::Run(@('3DMarkICFWorkload.exe', '3DMarkICFDemo.exe', '3DMarkPortRoyal.exe', '3DMarkSteelNomad.exe', '3DMarkTimeSpy.exe'), 0x000F00BA, 1) | Out-File $log -Encoding utf8
} catch { $_ | Out-String | Out-File $log -Encoding utf8 }
'done' | Out-File $log -Append -Encoding utf8

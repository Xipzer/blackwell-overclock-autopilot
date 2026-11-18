# Lists every DXGI adapter as "LuidLow,LuidHigh,Description", one per line. No admin rights needed.
# 3DMark workload files name the GPU by this LUID, and it changes on every boot, so look it up before each session.
Add-Type @'
using System; using System.Runtime.InteropServices;
[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct DESC1 {
 [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string Description; public uint VendorId, DeviceId, SubSysId, Revision;
 public UIntPtr Ded, DedSys, Shared; public uint LuidLow; public int LuidHigh; public uint Flags; }
[ComImport, Guid("29038f61-3839-4626-91fd-086879011a05"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] public interface IAdapter1 {
 void SetPrivateData(); void SetPrivateDataInterface(); void GetPrivateData(); void GetParent();
 void EnumOutputs(); void GetDesc(); void CheckInterfaceSupport(); [PreserveSig] int GetDesc1(out DESC1 d); }
[ComImport, Guid("770aae78-f26f-4dba-a829-253c83d1b387"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] public interface IFactory1 {
 void SetPrivateData(); void SetPrivateDataInterface(); void GetPrivateData(); void GetParent();
 void EnumAdapters(); void MakeWindowAssociation(); void GetWindowAssociation(); void CreateSwapChain(); void CreateSoftwareAdapter();
 [PreserveSig] int EnumAdapters1(uint i, out IAdapter1 a); }
public static class X { [DllImport("dxgi.dll")] static extern int CreateDXGIFactory1(ref Guid g, out IFactory1 f);
 public static string List() { var g = new Guid("770aae78-f26f-4dba-a829-253c83d1b387"); IFactory1 f; CreateDXGIFactory1(ref g, out f);
  var s = ""; for (uint i = 0; ; i++) { IAdapter1 a; if (f.EnumAdapters1(i, out a) != 0) break; DESC1 d; a.GetDesc1(out d); s += d.LuidLow + "," + d.LuidHigh + "," + d.Description + "\n"; } return s; } }
'@
[X]::List()

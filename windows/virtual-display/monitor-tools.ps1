#requires -Version 7.0
param([switch]$List)
$ErrorActionPreference = 'Stop'
$VirtualDisplayRoot = $PSScriptRoot
$DisplayBaselinePath = Join-Path $VirtualDisplayRoot 'baseline-display.json'
$DisplayTargetPath = Join-Path $VirtualDisplayRoot 'display-target.json'

if (-not ('CodexVirtualDisplay.Native' -as [type])) {
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;

namespace CodexVirtualDisplay {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct DisplayDevice {
        public uint cb;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string DeviceName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceString;
        public uint StateFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceID;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceKey;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct DevMode {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmDeviceName;
        public ushort dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra;
        public uint dmFields;
        public int dmPositionX, dmPositionY;
        public uint dmDisplayOrientation, dmDisplayFixedOutput;
        public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmFormName;
        public ushort dmLogPixels;
        public uint dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency;
        public uint dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2, dmPanningWidth, dmPanningHeight;
    }
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct OutputDesc {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string DeviceName;
        public Rect DesktopCoordinates;
        [MarshalAs(UnmanagedType.Bool)] public bool AttachedToDesktop;
        public uint Rotation;
        public IntPtr Monitor;
    }
    public class MonitorRecord { public string DeviceName, DeviceString, DeviceID; public uint StateFlags; }
    public class DisplayRecord {
        public string DeviceName, DeviceString, DeviceID, DeviceKey;
        public uint StateFlags;
        public bool Attached, Primary, HasCurrentMode;
        public int Left, Top, Width, Height, Frequency, BitsPerPixel, Orientation;
        public string ModeBase64;
        public MonitorRecord[] Monitors;
    }
    public class OutputRecord { public string DeviceName; public int Left, Top, Width, Height, CaptureIndex; }
    [StructLayout(LayoutKind.Sequential)]
    public struct DeviceInfoData { public uint cbSize; public Guid ClassGuid; public uint DevInst; public IntPtr Reserved; }
    public class PnpRecord {
        public string Name, PNPDeviceID, Manufacturer, Status;
        public string[] HardwareID;
        public uint StatusFlags, ProblemCode;
    }
    public static class Native {
        const int Current=-1, NotFound=unchecked((int)0x887A0002);
        const uint Position=0x20, Orientation=0x80, Bits=0x40000, Width=0x80000, Height=0x100000, Frequency=0x400000;
        [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        [return:MarshalAs(UnmanagedType.Bool)] static extern bool EnumDisplayDevicesW(string device, uint index, ref DisplayDevice info, uint flags);
        [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        [return:MarshalAs(UnmanagedType.Bool)] static extern bool EnumDisplaySettingsExW(string device, int index, ref DevMode mode, uint flags);
        [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int ChangeDisplaySettingsExW(string device, ref DevMode mode, IntPtr hwnd, uint flags, IntPtr param);
        [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
        [DllImport("dxgi.dll")] static extern int CreateDXGIFactory1(ref Guid iid, out IntPtr factory);
        [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr SetupDiGetClassDevsW(ref Guid classGuid, string enumerator, IntPtr hwnd, uint flags);
        [DllImport("setupapi.dll", SetLastError=true)]
        [return:MarshalAs(UnmanagedType.Bool)] static extern bool SetupDiEnumDeviceInfo(IntPtr set, uint index, ref DeviceInfoData data);
        [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        [return:MarshalAs(UnmanagedType.Bool)] static extern bool SetupDiGetDeviceRegistryPropertyW(IntPtr set, ref DeviceInfoData data, uint property, out uint type, byte[] buffer, uint bufferSize, out uint required);
        [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        [return:MarshalAs(UnmanagedType.Bool)] static extern bool SetupDiGetDeviceInstanceIdW(IntPtr set, ref DeviceInfoData data, StringBuilder instanceId, uint size, out uint required);
        [DllImport("setupapi.dll", SetLastError=true)]
        [return:MarshalAs(UnmanagedType.Bool)] static extern bool SetupDiDestroyDeviceInfoList(IntPtr set);
        [DllImport("cfgmgr32.dll")] static extern uint CM_Get_DevNode_Status(out uint status, out uint problem, uint devInst, uint flags);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int EnumChild(IntPtr self, uint index, out IntPtr child);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetDesc(IntPtr self, out OutputDesc desc);
        static T Slot<T>(IntPtr obj, int index) where T:Delegate { return Marshal.GetDelegateForFunctionPointer<T>(Marshal.ReadIntPtr(Marshal.ReadIntPtr(obj), index*IntPtr.Size)); }
        static DisplayDevice NewDevice() { return new DisplayDevice { cb=(uint)Marshal.SizeOf<DisplayDevice>() }; }
        static DevMode NewMode() { return new DevMode { dmSize=(ushort)Marshal.SizeOf<DevMode>() }; }
        static string Encode(DevMode mode) {
            int size=Marshal.SizeOf<DevMode>(); IntPtr ptr=Marshal.AllocHGlobal(size);
            try { Marshal.StructureToPtr(mode,ptr,false); byte[] bytes=new byte[size]; Marshal.Copy(ptr,bytes,0,size); return Convert.ToBase64String(bytes); }
            finally { Marshal.FreeHGlobal(ptr); }
        }
        static DevMode Decode(string encoded) {
            byte[] bytes=Convert.FromBase64String(encoded);
            if(bytes.Length!=Marshal.SizeOf<DevMode>()) throw new Exception("Unexpected saved DEVMODE size.");
            IntPtr ptr=Marshal.AllocHGlobal(bytes.Length);
            try { Marshal.Copy(bytes,0,ptr,bytes.Length); return Marshal.PtrToStructure<DevMode>(ptr); }
            finally { Marshal.FreeHGlobal(ptr); }
        }
        static string[] DeviceStrings(IntPtr set, ref DeviceInfoData data, uint property) {
            uint type, required;
            bool found=SetupDiGetDeviceRegistryPropertyW(set,ref data,property,out type,null,0,out required);
            if(!found) {
                int error=Marshal.GetLastWin32Error();
                if(error==13) return Array.Empty<string>(); // Optional property absent.
                if(error!=122) throw new Win32Exception(error,"Native display device property size query failed.");
            }
            if(required==0) return Array.Empty<string>();
            if(required>1048576) throw new Exception("Unexpected display device property size.");
            byte[] bytes=new byte[required];
            if(!SetupDiGetDeviceRegistryPropertyW(set,ref data,property,out type,bytes,(uint)bytes.Length,out required)) throw new Win32Exception(Marshal.GetLastWin32Error(),"Native display device property query failed.");
            if(type!=1 && type!=7) throw new Exception("Unexpected display device property type.");
            return Encoding.Unicode.GetString(bytes,0,(int)required).Split(new[]{'\0'},StringSplitOptions.RemoveEmptyEntries);
        }
        public static PnpRecord[] PnpDevices() {
            Guid displayClass=new Guid("4d36e968-e325-11ce-bfc1-08002be10318");
            IntPtr set=SetupDiGetClassDevsW(ref displayClass,null,IntPtr.Zero,2); // DIGCF_PRESENT only.
            if(set==new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error(),"Native display device enumeration failed.");
            try {
                var result=new List<PnpRecord>();
                for(uint index=0;index<256;index++) {
                    var data=new DeviceInfoData { cbSize=(uint)Marshal.SizeOf<DeviceInfoData>() };
                    if(!SetupDiEnumDeviceInfo(set,index,ref data)) {
                        int error=Marshal.GetLastWin32Error();
                        if(error==259) return result.ToArray();
                        throw new Win32Exception(error,"Native display device iteration failed.");
                    }
                    var instanceId=new StringBuilder(4096); uint needed;
                    if(!SetupDiGetDeviceInstanceIdW(set,ref data,instanceId,(uint)instanceId.Capacity,out needed)) throw new Win32Exception(Marshal.GetLastWin32Error(),"Native display instance ID query failed.");
                    string name=DeviceStrings(set,ref data,12).FirstOrDefault();
                    if(String.IsNullOrEmpty(name)) name=DeviceStrings(set,ref data,0).FirstOrDefault();
                    string manufacturer=DeviceStrings(set,ref data,11).FirstOrDefault();
                    string[] hardwareIds=DeviceStrings(set,ref data,1);
                    uint flags,problem; uint cr=CM_Get_DevNode_Status(out flags,out problem,data.DevInst,0);
                    if(cr!=0) throw new Exception("Native display devnode status query failed (CM code "+cr+").");
                    bool healthy=(flags&8)!=0 && (flags&0x400)==0; // DN_STARTED and no DN_HAS_PROBLEM.
                    result.Add(new PnpRecord { Name=name,PNPDeviceID=instanceId.ToString(),Manufacturer=manufacturer,HardwareID=hardwareIds,Status=healthy?"OK":"NotStartedOrProblem",StatusFlags=flags,ProblemCode=(flags&0x400)!=0?problem:0 });
                }
                throw new Exception("Unexpected number of present display devices.");
            } finally { SetupDiDestroyDeviceInfoList(set); }
        }
        public static DisplayRecord[] Displays() {
            IntPtr prior=SetThreadDpiAwarenessContext(new IntPtr(-4));
            try {
                var result=new List<DisplayRecord>();
                for(uint i=0;i<64;i++) {
                    var device=NewDevice(); if(!EnumDisplayDevicesW(null,i,ref device,0)) return result.ToArray();
                    var monitors=new List<MonitorRecord>();
                    for(uint j=0;j<64;j++) {
                        var monitor=NewDevice(); if(!EnumDisplayDevicesW(device.DeviceName,j,ref monitor,0)) break;
                        monitors.Add(new MonitorRecord { DeviceName=monitor.DeviceName,DeviceString=monitor.DeviceString,DeviceID=monitor.DeviceID,StateFlags=monitor.StateFlags });
                    }
                    var mode=NewMode(); bool hasMode=EnumDisplaySettingsExW(device.DeviceName,Current,ref mode,0);
                    result.Add(new DisplayRecord { DeviceName=device.DeviceName, DeviceString=device.DeviceString,DeviceID=device.DeviceID,DeviceKey=device.DeviceKey,StateFlags=device.StateFlags,
                        Attached=(device.StateFlags&1)!=0,Primary=(device.StateFlags&4)!=0,HasCurrentMode=hasMode,
                        Left=mode.dmPositionX,Top=mode.dmPositionY,Width=(int)mode.dmPelsWidth,Height=(int)mode.dmPelsHeight,Frequency=(int)mode.dmDisplayFrequency,BitsPerPixel=(int)mode.dmBitsPerPel,Orientation=(int)mode.dmDisplayOrientation,
                        ModeBase64=hasMode?Encode(mode):null,Monitors=monitors.ToArray() });
                }
                throw new Exception("Unexpected number of GDI display devices.");
            } finally { if(prior!=IntPtr.Zero) SetThreadDpiAwarenessContext(prior); }
        }
        public static OutputRecord[] Outputs() {
            IntPtr prior=SetThreadDpiAwarenessContext(new IntPtr(-4)); IntPtr factory=IntPtr.Zero;
            try {
                Guid iid=new Guid("770aae78-f26f-4dba-a829-253c83d1b387");
                Marshal.ThrowExceptionForHR(CreateDXGIFactory1(ref iid,out factory));
                var result=new List<OutputRecord>(); var enumAdapters=Slot<EnumChild>(factory,12);
                for(uint a=0;a<64;a++) {
                    IntPtr adapter; int hr=enumAdapters(factory,a,out adapter); if(hr==NotFound) break; Marshal.ThrowExceptionForHR(hr);
                    try {
                        var enumOutputs=Slot<EnumChild>(adapter,7);
                        for(uint o=0;o<64;o++) {
                            IntPtr output; hr=enumOutputs(adapter,o,out output); if(hr==NotFound) break; Marshal.ThrowExceptionForHR(hr);
                            try {
                                OutputDesc desc; Marshal.ThrowExceptionForHR(Slot<GetDesc>(output,7)(output,out desc));
                                if(desc.AttachedToDesktop) result.Add(new OutputRecord { DeviceName=desc.DeviceName,Left=desc.DesktopCoordinates.Left,Top=desc.DesktopCoordinates.Top,Width=desc.DesktopCoordinates.Right-desc.DesktopCoordinates.Left,Height=desc.DesktopCoordinates.Bottom-desc.DesktopCoordinates.Top });
                            } finally { Marshal.Release(output); }
                        }
                    } finally { Marshal.Release(adapter); }
                }
                var sorted=result.OrderBy(d=>d.Left!=0||d.Top!=0).ThenBy(d=>d.Top).ThenBy(d=>d.Left).ToArray();
                if(sorted.Select(d=>d.DeviceName).Distinct(StringComparer.OrdinalIgnoreCase).Count()!=sorted.Length) throw new Exception("Duplicate DXGI output names.");
                for(int i=0;i<sorted.Length;i++) sorted[i].CaptureIndex=i;
                return sorted;
            } finally { if(factory!=IntPtr.Zero) Marshal.Release(factory); if(prior!=IntPtr.Zero) SetThreadDpiAwarenessContext(prior); }
        }
        static DevMode RequestedMode(string device,int x,int y,int width,int height,int frequency) {
            for(int i=0;i<4096;i++) {
                var mode=NewMode(); if(!EnumDisplaySettingsExW(device,i,ref mode,0)) break;
                if(mode.dmPelsWidth==(uint)width && mode.dmPelsHeight==(uint)height && mode.dmDisplayFrequency==(uint)frequency && mode.dmBitsPerPel==32 && mode.dmDisplayOrientation==0) {
                    mode.dmPositionX=x; mode.dmPositionY=y; mode.dmFields=Position|Orientation|Bits|Width|Height|Frequency; return mode;
                }
            }
            throw new Exception("Requested 32-bit landscape virtual display mode is not advertised by its driver.");
        }
        public static int TestMode(string device,int x,int y,int width,int height,int frequency) { var mode=RequestedMode(device,x,y,width,height,frequency); return ChangeDisplaySettingsExW(device,ref mode,IntPtr.Zero,2,IntPtr.Zero); }
        public static int ApplyMode(string device,int x,int y,int width,int height,int frequency) { var mode=RequestedMode(device,x,y,width,height,frequency); return ChangeDisplaySettingsExW(device,ref mode,IntPtr.Zero,1,IntPtr.Zero); }
        public static int RestoreMode(string device,string savedMode,bool wasAttached,bool wasPrimary) {
            var mode=String.IsNullOrEmpty(savedMode)?NewMode():Decode(savedMode);
            if(!wasAttached) { mode.dmFields=Position|Width|Height; mode.dmPelsWidth=0; mode.dmPelsHeight=0; }
            return ChangeDisplaySettingsExW(device,ref mode,IntPtr.Zero,1u|(wasAttached&&wasPrimary?0x10u:0u),IntPtr.Zero);
        }
    }
}
'@
}

function Get-DisplayInventory {
	[pscustomobject]@{capturedUtc=[DateTime]::UtcNow.ToString('o'); devices=@([CodexVirtualDisplay.Native]::Displays()); outputs=@([CodexVirtualDisplay.Native]::Outputs())}
}


function Test-VirtualDisplayRecord($Device) {
	return $Device.DeviceString -eq 'Virtual Display Driver' -and $Device.DeviceID -eq 'Root\MttVDD'
}

function Assert-PhysicalDisplayUnchanged($Inventory, $Baseline) {
	$physical = @($Inventory.devices | Where-Object DeviceName -eq $Baseline.physical.DeviceName)
	if ($physical.Count -ne 1) { throw 'The exact baseline physical display is missing or ambiguous.' }
	$physical = $physical[0]
	foreach ($field in @('DeviceName','DeviceString','DeviceID','DeviceKey','Attached','Primary','Left','Top','Width','Height','Frequency','BitsPerPixel','Orientation')) {
		if ($physical.$field -ne $Baseline.physical.$field) { throw ('Physical display changed: ' + $field + '. Run setup again only after reviewing the new layout.') }
	}
	$beforeIds = (@($Baseline.physical.Monitors | ForEach-Object DeviceID | Sort-Object) -join '|')
	$afterIds = (@($physical.Monitors | ForEach-Object DeviceID | Sort-Object) -join '|')
	if ($beforeIds -ne $afterIds) { throw 'Physical panel monitor identity changed.' }
	$physicalOutput = @($Inventory.outputs | Where-Object DeviceName -eq $physical.DeviceName)
	if ($physicalOutput.Count -ne 1 -or $physicalOutput[0].CaptureIndex -ne 0) { throw 'Physical display is no longer the unique primary DXGI capture output.' }
	foreach ($field in @('Left','Top','Width','Height')) { if ($physicalOutput[0].$field -ne $physical.$field) { throw 'Physical GDI and DXGI geometry disagree.' } }
	return $physical
}

# Read-only registration: the user installs the signed VDD and extends its screen
# in Windows Display Settings first. No driver/device/mode changes occur here.
function Get-RegistrationSnapshot {
	$inventory = Get-DisplayInventory
	$pnpDevices = @([CodexVirtualDisplay.Native]::PnpDevices())
	$physical = @($inventory.devices | Where-Object { $_.Attached -and $_.Primary -and -not (Test-VirtualDisplayRecord $_) })
	$virtual = @($inventory.devices | Where-Object { Test-VirtualDisplayRecord $_ })
	$virtualPnp = @($pnpDevices | Where-Object { $_.Name -eq 'Virtual Display Driver' -and $_.Manufacturer -eq 'MikeTheTech' -and $_.HardwareID -contains 'Root\MttVDD' -and $_.Status -eq 'OK' })
	if ($physical.Count -ne 1 -or $virtual.Count -ne 1 -or $virtualPnp.Count -ne 1) { throw 'Install the official signed MikeTheTech Virtual Display Driver, then extend one virtual monitor beside one physical primary display.' }
	$physical = $physical[0]; $virtual = $virtual[0]
	if ($physical.Left -ne 0 -or $physical.Top -ne 0 -or $physical.Width -le 0 -or $physical.Height -le 0) { throw 'Supported layout requires a physical primary display at desktop origin.' }
	if (@($inventory.devices | Where-Object Attached).Count -ne 2 -or $inventory.outputs.Count -ne 2) { throw 'Supported layout requires exactly one physical display and one active virtual display.' }
	if (-not $virtual.Attached -or $virtual.Primary -or $virtual.Left -ne $physical.Width -or $virtual.Top -ne 0 -or $virtual.Width -ne 1920 -or $virtual.Height -ne 1080 -or $virtual.Frequency -ne 60 -or $virtual.BitsPerPixel -ne 32 -or $virtual.Orientation -ne 0) { throw 'In Windows Display Settings, extend the virtual monitor directly right of the physical primary at 1920x1080, 60 Hz, landscape (32-bit).' }
	$knownIds = @($inventory.devices | ForEach-Object DeviceID | Sort-Object -Unique)
	$unknownPnp = @($pnpDevices | Where-Object { @($_.HardwareID | Where-Object { $_ -in $knownIds }).Count -eq 0 })
	if ($unknownPnp.Count -gt 0) { throw 'An unrecognized display adapter is present; this layout is unsupported.' }
	$baseline = [pscustomobject]@{schemaVersion=2; capturedUtc=$inventory.capturedUtc; physical=$physical; inventoryDeviceIds=$knownIds; pnpDeviceIds=@($pnpDevices | ForEach-Object PNPDeviceID | Sort-Object)}
	$null = Assert-PhysicalDisplayUnchanged $inventory $baseline
	$output = @($inventory.outputs | Where-Object DeviceName -eq $virtual.DeviceName)
	if ($output.Count -ne 1 -or $output[0].CaptureIndex -ne 1) { throw 'Virtual DXGI output must be capture index 1; refusing physical-display fallback.' }
	foreach ($field in @('Left','Top','Width','Height')) { if ($output[0].$field -ne $virtual.$field) { throw 'Virtual GDI and DXGI geometry disagree.' } }
	$monitorIds = @($virtual.Monitors | ForEach-Object DeviceID | Sort-Object)
	if ($monitorIds.Count -eq 0 -or [string]::IsNullOrWhiteSpace(($monitorIds -join ''))) { throw 'Virtual monitor identity is unavailable.' }
	$target = [pscustomobject]@{schemaVersion=1;configuredUtc=$inventory.capturedUtc;deviceName=$virtual.DeviceName;deviceId=$virtual.DeviceID;deviceString=$virtual.DeviceString;pnpInstanceId=$virtualPnp[0].PNPDeviceID;monitorDeviceIds=$monitorIds;captureIndex=1;geometry=[pscustomobject]@{left=$virtual.Left;top=$virtual.Top;width=$virtual.Width;height=$virtual.Height;frequency=$virtual.Frequency;bitsPerPixel=$virtual.BitsPerPixel;orientation=$virtual.Orientation}}
	return [pscustomobject]@{baseline=$baseline;target=$target}
}

function Read-PhysicalBaseline {
	if (-not (Test-Path -LiteralPath $DisplayBaselinePath)) { throw 'Display baseline is missing. Run scripts/setup.ps1 first.' }
	$baseline = Get-Content -LiteralPath $DisplayBaselinePath -Raw | ConvertFrom-Json
	if ($baseline.schemaVersion -ne 2 -or -not $baseline.physical.Primary -or $baseline.physical.Width -le 0 -or $baseline.physical.Height -le 0 -or $baseline.physical.Left -ne 0 -or $baseline.physical.Top -ne 0 -or @($baseline.pnpDeviceIds).Count -eq 0) { throw 'Display baseline is invalid.' }
	return $baseline
}

function Get-ValidatedDisplayLayout {
	$baseline = Read-PhysicalBaseline
	$inventory = Get-DisplayInventory
	$physical = Assert-PhysicalDisplayUnchanged $inventory $baseline
	$currentIds = (@($inventory.devices | ForEach-Object DeviceID | Sort-Object -Unique) -join '|')
	if ($currentIds -ne (@($baseline.inventoryDeviceIds | Sort-Object -Unique) -join '|')) { throw 'Display adapter/output inventory changed; refusing to guess a capture target.' }
	$pnpDevices = @([CodexVirtualDisplay.Native]::PnpDevices())
	if ((@($pnpDevices | ForEach-Object PNPDeviceID | Sort-Object) -join '|') -ne (@($baseline.pnpDeviceIds | Sort-Object) -join '|')) { throw 'Display PnP inventory changed.' }
	$virtualPnp = @($pnpDevices | Where-Object { $_.Name -eq 'Virtual Display Driver' -and $_.Manufacturer -eq 'MikeTheTech' -and $_.HardwareID -contains 'Root\MttVDD' -and $_.Status -eq 'OK' })
	if ($virtualPnp.Count -ne 1) { throw 'Expected exactly one healthy MikeTheTech Root\MttVDD virtual display driver.' }
	$virtual = @($inventory.devices | Where-Object { Test-VirtualDisplayRecord $_ })
	if ($virtual.Count -ne 1 -or $virtual[0].Primary) { throw 'Expected exactly one non-primary GDI virtual display output.' }
	return [pscustomobject]@{baseline=$baseline; inventory=$inventory; physical=$physical; virtual=$virtual[0]; virtualPnpInstanceId=$virtualPnp[0].PNPDeviceID}
}

function Assert-VirtualDisplayTarget {
	if (-not (Test-Path -LiteralPath $DisplayTargetPath)) { throw 'Virtual display target is missing. Run scripts/setup.ps1 first.' }
	$target = Get-Content -LiteralPath $DisplayTargetPath -Raw | ConvertFrom-Json
	if ($target.schemaVersion -ne 1 -or $target.deviceId -ne 'Root\MttVDD' -or $target.deviceString -ne 'Virtual Display Driver' -or $target.captureIndex -ne 1 -or $target.geometry.width -ne 1920 -or $target.geometry.height -ne 1080 -or $target.geometry.frequency -ne 60) { throw 'Saved virtual target has unexpected identity, capture index or mode.' }
	$layout = Get-ValidatedDisplayLayout
	$virtual = $layout.virtual
	if (-not $virtual.Attached -or $virtual.DeviceName -ne $target.deviceName -or $virtual.DeviceID -ne $target.deviceId -or $layout.virtualPnpInstanceId -ne $target.pnpInstanceId) { throw 'Saved virtual display target is no longer the active driver output.' }
	if (@($layout.inventory.devices | Where-Object Attached).Count -ne 2 -or $layout.inventory.outputs.Count -ne 2) { throw 'Virtual streaming requires exactly the baseline physical display and one virtual output.' }
	if ($target.geometry.left -ne ([int]$layout.physical.Left + [int]$layout.physical.Width) -or $target.geometry.top -ne $layout.physical.Top) { throw 'Virtual display is not directly right of the preserved physical display.' }
	foreach ($pair in @(@('Left','left'),@('Top','top'),@('Width','width'),@('Height','height'),@('Frequency','frequency'),@('BitsPerPixel','bitsPerPixel'),@('Orientation','orientation'))) {
		if ($virtual.($pair[0]) -ne $target.geometry.($pair[1])) { throw ('Virtual display mode changed: ' + $pair[0]) }
	}
	$monitorIds = (@($virtual.Monitors | ForEach-Object DeviceID | Sort-Object) -join '|')
	if ([string]::IsNullOrEmpty($monitorIds) -or $monitorIds -ne (@($target.monitorDeviceIds | Sort-Object) -join '|')) { throw 'Virtual monitor identity changed or disappeared.' }
	$output = @($layout.inventory.outputs | Where-Object DeviceName -eq $target.deviceName)
	if ($output.Count -ne 1 -or $output[0].CaptureIndex -ne $target.captureIndex) { throw 'DXGI output ordering changed; refusing possible physical-display fallback.' }
	foreach ($field in @('Left','Top','Width','Height')) { if ($output[0].$field -ne $virtual.$field) { throw 'Virtual GDI and DXGI geometry disagree.' } }
	return [pscustomobject]@{target=$target; layout=$layout; output=$output[0]}
}

if ($List) { Get-DisplayInventory | ConvertTo-Json -Depth 10 }

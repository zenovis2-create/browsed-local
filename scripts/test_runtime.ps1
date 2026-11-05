#requires -Version 7.0
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'Native monitor/runtime checks require Windows.' }
$repoRoot = Split-Path -Parent $PSScriptRoot
$serverRoot = Join-Path $repoRoot 'windows'
$parseCount = 0
Get-ChildItem -LiteralPath $repoRoot -Filter '*.ps1' -File -Recurse | ForEach-Object {
	$tokens=$null; $errors=$null
	$null=[Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$tokens,[ref]$errors)
	if ($errors.Count -gt 0) { throw ('PowerShell parse failure: ' + $_.Name) }
	$parseCount++
}
. (Join-Path $serverRoot 'common.ps1') -AllowUnconfigured
. (Join-Path $serverRoot 'virtual-display\monitor-tools.ps1')
function Assert-True([bool]$Value,[string]$Message) { if (-not $Value) { throw $Message } }
function Assert-Rejected([scriptblock]$Call,[string]$Message) {
	$rejected=$false
	try { & $Call | Out-Null } catch { $rejected=$true }
	Assert-True $rejected $Message
}
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('browsed-local-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
	$physical = [pscustomobject]@{DeviceName='physical-test';DeviceString='Physical panel';DeviceID='physical-id';DeviceKey='physical-key';Attached=$true;Primary=$true;Left=0;Top=0;Width=2560;Height=1440;Frequency=120;BitsPerPixel=32;Orientation=0;Monitors=@([pscustomobject]@{DeviceID='physical-monitor'})}
	$virtual = [pscustomobject]@{DeviceName='virtual-test';DeviceString='Virtual Display Driver';DeviceID='Root\MttVDD';Attached=$true;Primary=$false;Left=2560;Top=0;Width=1920;Height=1080;Frequency=60;BitsPerPixel=32;Orientation=0;Monitors=@([pscustomobject]@{DeviceID='virtual-monitor'})}
	$physicalOutput = [pscustomobject]@{DeviceName='physical-test';CaptureIndex=0;Left=0;Top=0;Width=2560;Height=1440}
	$virtualOutput = [pscustomobject]@{DeviceName='virtual-test';CaptureIndex=1;Left=2560;Top=0;Width=1920;Height=1080}
	$inventory = [pscustomobject]@{devices=@($physical,$virtual);outputs=@($physicalOutput,$virtualOutput)}
	$baseline = [pscustomobject]@{physical=($physical | ConvertTo-Json -Depth 5 | ConvertFrom-Json)}
	$null = Assert-PhysicalDisplayUnchanged $inventory $baseline
	$physical.Width=1920
	Assert-Rejected { Assert-PhysicalDisplayUnchanged $inventory $baseline } 'Changed physical resolution must be rejected.'
	$physical.Width=2560
	$layout = [pscustomobject]@{physical=$physical;virtual=$virtual;inventory=$inventory;virtualPnpInstanceId='test-instance'}
	function Get-ValidatedDisplayLayout { return $layout }
	$DisplayTargetPath = Join-Path $tempRoot 'display-target.json'
	$target = [ordered]@{schemaVersion=1;deviceName='virtual-test';deviceId='Root\MttVDD';deviceString='Virtual Display Driver';pnpInstanceId='test-instance';captureIndex=1;monitorDeviceIds=@('virtual-monitor');geometry=@{left=2560;top=0;width=1920;height=1080;frequency=60;bitsPerPixel=32;orientation=0}}
	$target | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $DisplayTargetPath
	$null = Assert-VirtualDisplayTarget
	$virtualOutput.CaptureIndex=0
	Assert-Rejected { Assert-VirtualDisplayTarget } 'Reordered virtual output must be rejected.'
	$virtualOutput.CaptureIndex=1
	$virtual.Width=1280
	Assert-Rejected { Assert-VirtualDisplayTarget } 'Changed virtual mode must be rejected.'
	$virtual.Width=1920
	$virtual.Monitors[0].DeviceID='different-monitor'
	Assert-Rejected { Assert-VirtualDisplayTarget } 'Changed virtual monitor identity must be rejected.'
	$virtual.Monitors[0].DeviceID='virtual-monitor'
	$StatePath = Join-Path $tempRoot 'stream-state.json'
	$StreamExecutable = (Get-Process -Id $PID).Path
	$state = [ordered]@{executable=$StreamExecutable;port=16901;streamPid=$PID;streamStartedUtc=(Get-Process -Id $PID).StartTime.ToUniversalTime().ToString('o')}
	$state | ConvertTo-Json | Set-Content -LiteralPath $StatePath
	# Mock only socket inspection. No listener is opened, adopted, or terminated.
	function Get-NetTCPConnection { [pscustomobject]@{OwningProcess=$PID;LocalAddress='127.0.0.1'} }
	Assert-True ((Get-OwnedStream).Process.Id -eq $PID) 'Exact live PID should be recognized.'
	$state.streamStartedUtc=[DateTime]::UtcNow.AddDays(-7).ToString('o')
	$state | ConvertTo-Json | Set-Content -LiteralPath $StatePath
	Assert-Rejected { Get-OwnedStream } 'Recycled or stale PID timestamp must be rejected.'
	$state.streamStartedUtc=(Get-Process -Id $PID).StartTime.ToUniversalTime().ToString('o')
	$state | ConvertTo-Json | Set-Content -LiteralPath $StatePath
	function Get-NetTCPConnection { [pscustomobject]@{OwningProcess=$PID;LocalAddress='0.0.0.0'} }
	Assert-Rejected { Get-OwnedStream } 'Nonloopback listener must be rejected.'
	function Get-NetTCPConnection { [pscustomobject]@{OwningProcess=($PID+1);LocalAddress='127.0.0.1'} }
	Assert-Rejected { Get-OwnedStream } 'Foreign listener owner must be rejected.'
	[ordered]@{status='passed';powershellFilesParsed=$parseCount;runtimeCases=10;serverStarted=$false;displaySettingsChanged=$false} | ConvertTo-Json
} finally {
	# Unique test directory is verified before recursive cleanup.
	$resolved=[IO.Path]::GetFullPath($tempRoot)
	if ([IO.Path]::GetDirectoryName($resolved) -ne [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar) -or [IO.Path]::GetFileName($resolved) -notlike 'browsed-local-test-*') { throw 'Unexpected test cleanup path.' }
	Remove-Item -LiteralPath $resolved -Recurse -Force
}

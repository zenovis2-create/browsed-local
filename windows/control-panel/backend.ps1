#requires -Version 7.0
param([ValidateSet('status','start','stop')][string]$Action='status',[string]$ResultFile='')
$ErrorActionPreference = 'Stop'
$ControlRoot = $PSScriptRoot
$ServerRoot = Split-Path -Parent $ControlRoot
$ResolvedResultFile = $null

function New-ControlResult([string]$State,[string]$Code,[Nullable[int]]$ProcessId=$null) {
	[pscustomobject]@{state=$State;code=$Code;pid=$ProcessId;endpoint='http://127.0.0.1:16901/';checkedUtc=[DateTime]::UtcNow.ToString('o')}
}

function Get-LightServerStatus {
	try { $owned = Get-OwnedStream } catch { return (New-ControlResult 'error' 'ownership_check_failed') }
	if ($null -eq $owned) {
		try { $listeners = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object Port -eq 16901) }
		catch { return (New-ControlResult 'error' 'listener_inspection_failed') }
		if ($listeners.Count -gt 0) { return (New-ControlResult 'error' 'port_conflict') }
		return (New-ControlResult 'off' 'stopped')
	}
	if ($owned.Listeners.Count -eq 0) { return (New-ControlResult 'error' 'owned_not_listening' $owned.Process.Id) }
	try { $captureTarget = (Assert-VirtualDisplayTarget).target }
	catch { return (New-ControlResult 'error' 'invalid_launch_state' $owned.Process.Id) }
	if ($owned.State.displayMode -ne 'virtual-only' -or $owned.State.captureDeviceName -ne $captureTarget.deviceName -or $owned.State.captureIndex -ne $captureTarget.captureIndex -or $owned.State.captureArgument -ne ('--display=' + $captureTarget.captureIndex)) {
		return (New-ControlResult 'error' 'invalid_launch_state' $owned.Process.Id)
	}
	foreach ($field in @('left','top','width','height','frequency','bitsPerPixel','orientation')) {
		if ($owned.State.captureGeometry.$field -ne $captureTarget.geometry.$field) { return (New-ControlResult 'error' 'invalid_launch_state' $owned.Process.Id) }
	}
	$client = [Net.Http.HttpClient]::new()
	$client.Timeout = [TimeSpan]::FromSeconds(3)
	try {
		$health = $client.GetAsync('http://127.0.0.1:16901/healthz').GetAwaiter().GetResult()
		$login = $client.GetAsync('http://127.0.0.1:16901/').GetAwaiter().GetResult()
		if ([int]$health.StatusCode -ne 200 -or [int]$login.StatusCode -ne 401) { return (New-ControlResult 'error' 'health_failed' $owned.Process.Id) }
		return (New-ControlResult 'on' 'ready' $owned.Process.Id)
	} catch { return (New-ControlResult 'error' 'health_failed' $owned.Process.Id) }
	finally { $client.Dispose() }
}

try {
	if (-not [string]::IsNullOrWhiteSpace($ResultFile)) {
		$candidate = [IO.Path]::GetFullPath($ResultFile)
		$allowedRoot = [IO.Path]::GetFullPath($ControlRoot) + [IO.Path]::DirectorySeparatorChar
		if (-not $candidate.StartsWith($allowedRoot,[StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetExtension($candidate) -ne '.json' -or -not [IO.Directory]::Exists([IO.Path]::GetDirectoryName($candidate))) { throw 'Invalid local result path.' }
		$ResolvedResultFile = $candidate
	}
	. (Join-Path $ServerRoot 'common.ps1')
	. (Join-Path $ServerRoot 'virtual-display\monitor-tools.ps1')
	if ($Action -eq 'status') {
		$result = Get-LightServerStatus
	} elseif ($Action -eq 'start') {
		$before = Get-LightServerStatus
		if ($before.state -eq 'on') { $result = New-ControlResult 'on' 'already_on' $before.pid }
		elseif ($before.state -ne 'off') { $result = $before }
		else {
			# Static absolute script paths only; no shell text or credential arguments.
			& (Join-Path $ServerRoot 'start.ps1') | Out-Null
			$result = Get-LightServerStatus
		}
	} else {
		# HTTP health may be broken, but stopping still requires exact owned PID/path/time.
		try { $owned = Get-OwnedStream } catch { $owned = $null; $result = New-ControlResult 'error' 'ownership_check_failed' }
		if ($null -eq $result) {
			if ($null -eq $owned) {
				$result = Get-LightServerStatus
				if ($result.state -eq 'off') { $result = New-ControlResult 'off' 'already_off' }
			} else {
				& (Join-Path $ServerRoot 'stop.ps1') | Out-Null
				$result = Get-LightServerStatus
			}
		}
	}
} catch {
	# Never serialize exception text, process arguments, credentials or response bodies.
	$result = New-ControlResult 'error' 'action_failed'
}
$json = $result | ConvertTo-Json -Compress
if ($ResolvedResultFile) {
	# WriteAllText closes the result before this parent exits. Long-lived stream
	# descendants must not keep a GUI PIPE open or serve as its result transport.
	try { [IO.File]::WriteAllText($ResolvedResultFile,$json,[Text.UTF8Encoding]::new($false)) }
	catch { exit 1 }
} else {
	$json
}
if ($result.state -eq 'error') { exit 1 }

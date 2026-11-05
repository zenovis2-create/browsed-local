#requires -Version 7.0
. (Join-Path $PSScriptRoot 'common.ps1')
. (Join-Path $PSScriptRoot 'virtual-display\monitor-tools.ps1')
$process = $null
try {
	# Voxl falls back to physical index 0 when a requested index is invalid.
	# Require an exact current virtual GDI + DXGI target before launching it.
	$displayVerification = Assert-VirtualDisplayTarget
	$captureTarget = $displayVerification.target
	if ((Get-FileHash -LiteralPath $StreamExecutable -Algorithm SHA256).Hash -ne $StreamExecutableHash) { throw 'Voxl executable changed before launch.' }
	$credential = Read-StreamCredentials
	$info = [Diagnostics.ProcessStartInfo]::new()
	$info.FileName = $StreamExecutable
	$info.WorkingDirectory = Split-Path -Parent $StreamExecutable
	$info.UseShellExecute = $false
	$info.CreateNoWindow = $true
	$info.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
	$info.RedirectStandardOutput = $true
	$info.RedirectStandardError = $true
	foreach ($argument in @('--addr=127.0.0.1', '--port=16901', ('--display=' + $captureTarget.captureIndex), '--title=browsed-local', ('--files-root=' + (Join-Path $StreamRoot 'shared')), '--audio-enabled=false', '--microphone-enabled=false', '--enable-clipboard=false')) {
		$info.ArgumentList.Add($argument)
	}
	$info.Environment['VOXL_PASSWORD'] = $credential.password
	$process = [Diagnostics.Process]::new()
	$process.StartInfo = $info
	if (-not $process.Start()) { throw 'Windows stream process did not start.' }
	# Startup output contains a login token. Drain both pipes to /dev/null-equivalent,
	# never a console or a log, while this supervisor retains their handles.
	$stdoutDrain = $process.StandardOutput.BaseStream.CopyToAsync([IO.Stream]::Null)
	$stderrDrain = $process.StandardError.BaseStream.CopyToAsync([IO.Stream]::Null)
	Write-StreamState ([ordered]@{executable=$StreamExecutable; port=$StreamPort; streamPid=$process.Id; streamStartedUtc=$process.StartTime.ToUniversalTime().ToString('o'); supervisorPid=$PID; supervisorStartedUtc=(Get-Process -Id $PID).StartTime.ToUniversalTime().ToString('o'); displayMode='virtual-only'; captureDeviceName=$captureTarget.deviceName; captureIndex=$captureTarget.captureIndex; captureArgument=('--display=' + $captureTarget.captureIndex); captureGeometry=$captureTarget.geometry; virtualTargetFile=$DisplayTargetPath})
	while (-not $process.WaitForExit(2000)) {
		try {
			$currentDisplay = Assert-VirtualDisplayTarget
			if ($currentDisplay.target.deviceName -ne $captureTarget.deviceName -or $currentDisplay.target.captureIndex -ne $captureTarget.captureIndex) { throw 'Virtual capture target changed.' }
		} catch {
			# Stop only this owned child when topology/identity changes; never adopt
			# a newly indexed physical output or restart with a fallback display.
			if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
			throw 'Virtual display became unavailable or changed; the owned stream was stopped.'
		}
	}
	$stdoutDrain.GetAwaiter().GetResult()
	$stderrDrain.GetAwaiter().GetResult()
	exit $process.ExitCode
} catch {
	# A state-write or watchdog failure must not orphan a capturing child. This
	# Process object belongs only to the child launched by this supervisor.
	if ($null -ne $process) {
		try { if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit(5000) | Out-Null } } catch { }
	}
	# Avoid serializing exceptions containing request details or environment values.
	@{status='failed'; stage='supervisor'; timestamp=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $StreamRoot 'last-supervisor-error.json')
	exit 1
}

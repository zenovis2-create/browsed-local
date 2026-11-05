#requires -Version 7.0
. (Join-Path $PSScriptRoot 'common.ps1')
$mutex = [Threading.Mutex]::new($false, 'Local\BrowsedLocalWindows16901')
if (-not $mutex.WaitOne(10000)) { throw 'Another Windows stream startup is in progress.' }
try {
	$existing = Get-OwnedStream
	if ($null -ne $existing -and $existing.Listeners.Count -gt 0) {
		& (Join-Path $StreamRoot 'status.ps1')
		return
	}
	if ($null -ne $existing) { throw 'Owned stream is running without a ready listener; inspect status before restarting.' }
	if (@(Get-NetTCPConnection -State Listen -LocalPort $StreamPort -ErrorAction SilentlyContinue).Count -gt 0) { throw 'Port 16901 is occupied by another process; refusing to adopt it.' }
	if ((Get-FileHash -LiteralPath $StreamExecutable -Algorithm SHA256).Hash -ne $StreamExecutableHash) { throw 'Existing Voxl binary changed; review the update before starting.' }
	. (Join-Path $StreamRoot 'virtual-display\monitor-tools.ps1')
	$null = Assert-VirtualDisplayTarget
	New-Item -ItemType Directory -Path (Join-Path $StreamRoot 'shared') -Force | Out-Null
	if (-not (Test-Path -LiteralPath $CredentialPath)) {
		$bytes = [byte[]]::new(32)
		[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
		$tempCredential = Join-Path $StreamRoot ('credential-' + [guid]::NewGuid().ToString('N') + '.tmp')
		try {
			[IO.File]::WriteAllText($tempCredential, '')
			Protect-LocalFile $tempCredential
			[ordered]@{host='127.0.0.1'; port=$StreamPort; username='codex'; password=[Convert]::ToBase64String($bytes); createdUtc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $tempCredential -Encoding utf8
			[IO.File]::Move($tempCredential, $CredentialPath, $false)
		} finally { if (Test-Path -LiteralPath $tempCredential) { Remove-Item -LiteralPath $tempCredential } }
	}
	$null = Read-StreamCredentials
	$info = [Diagnostics.ProcessStartInfo]::new()
	$info.FileName = (Get-Process -Id $PID).Path
	$info.UseShellExecute = $false
	$info.CreateNoWindow = $true
	$info.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
	foreach ($argument in @('-NoLogo', '-NoProfile', '-NonInteractive', '-File', (Join-Path $StreamRoot 'run-stream.ps1'))) { $info.ArgumentList.Add($argument) }
	$supervisor = [Diagnostics.Process]::Start($info)
	$ready = $false
	for ($attempt = 0; $attempt -lt 40; $attempt++) {
		Start-Sleep -Milliseconds 250
		$owned = Get-OwnedStream
		if ($null -ne $owned -and $owned.Listeners.Count -gt 0) { $ready=$true; break }
		if ($supervisor.HasExited) { break }
	}
	if (-not $ready) { throw 'Windows stream did not become ready within 10 seconds; inspect last-supervisor-error.json.' }
	& (Join-Path $StreamRoot 'status.ps1')
} finally {
	$mutex.ReleaseMutex()
	$mutex.Dispose()
}

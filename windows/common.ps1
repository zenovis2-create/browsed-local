#requires -Version 7.0
param([switch]$AllowUnconfigured)
$ErrorActionPreference = 'Stop'
$StreamRoot = $PSScriptRoot
$ConfigPath = Join-Path $StreamRoot 'config.json'
$StreamExecutable = $null
$StreamExecutableHash = $null
if (Test-Path -LiteralPath $ConfigPath) {
	$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
	if ($config.schemaVersion -ne 1 -or -not [IO.Path]::IsPathFullyQualified([string]$config.executable) -or $config.executableSha256 -notmatch '^[0-9A-Fa-f]{64}$') { throw 'Local config is invalid. Run scripts/setup.ps1 again after reviewing the executable.' }
	$StreamExecutable = [IO.Path]::GetFullPath([string]$config.executable)
	$StreamExecutableHash = [string]$config.executableSha256
} elseif (-not $AllowUnconfigured) {
	throw 'Local config is missing. Run scripts/setup.ps1 -VoxlPath <reviewed voxl.exe> first.'
}
$StreamPort = 16901
$CredentialPath = Join-Path $StreamRoot 'credentials.json'
$StatePath = Join-Path $StreamRoot 'stream-state.json'

function Protect-LocalFile([string]$Path) {
	$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
	$acl = [Security.AccessControl.FileSecurity]::new()
	$acl.SetOwner($ownerSid)
	$acl.SetAccessRuleProtection($true, $false)
	foreach ($sid in @($ownerSid, [Security.Principal.SecurityIdentifier]::new('S-1-5-18'), [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))) {
		$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'Allow'))
	}
	Set-Acl -LiteralPath $Path -AclObject $acl
}

function Write-StreamState($Value) {
	$tempPath = Join-Path $StreamRoot ('state-' + [guid]::NewGuid().ToString('N') + '.tmp')
	$Value | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $tempPath -Encoding utf8
	[IO.File]::Move($tempPath, $StatePath, $true)
}

function Read-StreamCredentials {
	$credential = Get-Content -LiteralPath $CredentialPath -Raw | ConvertFrom-Json
	if ($credential.host -ne '127.0.0.1' -or [int]$credential.port -ne $StreamPort -or [string]::IsNullOrWhiteSpace($credential.password)) {
		throw 'Windows stream credential file has unexpected endpoint or missing password.'
	}
	return $credential
}

function Get-OwnedStream {
	if (-not (Test-Path -LiteralPath $StatePath)) { return $null }
	$state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
	if ($state.executable -ne $StreamExecutable -or [int]$state.port -ne $StreamPort) { throw 'Stream state does not belong to this Windows endpoint.' }
	$process = Get-Process -Id ([int]$state.streamPid) -ErrorAction SilentlyContinue
	if ($null -eq $process) { return $null }
	if ($process.Path -ne $StreamExecutable) { throw 'Stored PID now belongs to a different executable; refusing action.' }
	# PowerShell 7.5+ ConvertFrom-Json materializes ISO timestamps as DateTime;
	# calling Parse(object) would stringify that using the local timezone.
	$startedUtc = if ($state.streamStartedUtc -is [DateTime]) { $state.streamStartedUtc.ToUniversalTime() } else { [DateTimeOffset]::Parse([string]$state.streamStartedUtc).UtcDateTime }
	if ([Math]::Abs(($process.StartTime.ToUniversalTime() - $startedUtc).TotalSeconds) -gt 1) { throw 'Stored PID start time changed; refusing action.' }
	$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $StreamPort -ErrorAction SilentlyContinue)
	if ($listeners.Count -gt 0) {
		foreach ($listener in $listeners) {
			if ($listener.OwningProcess -ne $process.Id -or $listener.LocalAddress -notin @('127.0.0.1', '::1')) { throw 'Windows stream listener ownership or bind scope is unexpected.' }
		}
	}
	return [pscustomobject]@{State=$state; Process=$process; Listeners=$listeners}
}

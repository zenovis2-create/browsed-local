#requires -Version 7.0
param(
	[Parameter(Mandatory)][string]$VoxlPath,
	[switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'browsed-local currently supports Windows only.' }
$serverRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'windows'
. (Join-Path $serverRoot 'common.ps1') -AllowUnconfigured
. (Join-Path $serverRoot 'virtual-display\monitor-tools.ps1')
$executable = Get-Item -LiteralPath $VoxlPath
if ($executable.PSIsContainer -or $executable.Extension -ne '.exe') { throw 'VoxlPath must identify the reviewed Voxl Windows executable.' }
$hash = (Get-FileHash -LiteralPath $executable.FullName -Algorithm SHA256).Hash
$snapshot = Get-RegistrationSnapshot
$config = [ordered]@{schemaVersion=1;executable=$executable.FullName;executableSha256=$hash}
if ($CheckOnly) {
	[ordered]@{status='prerequisites-ready';changesApplied=$false;captureIndex=$snapshot.target.captureIndex;virtualWidth=$snapshot.target.geometry.width;virtualHeight=$snapshot.target.geometry.height;configExists=(Test-Path -LiteralPath $ConfigPath)} | ConvertTo-Json
	return
}
# A clone has its own state; never overwrite a configured or running installation.
# To register a changed layout, stop this installation first and archive only its
# config.json, stream-state.json, virtual-display/baseline-display.json and
# virtual-display/display-target.json. Keep credentials.json to retain password.
foreach ($path in @($ConfigPath,$DisplayBaselinePath,$DisplayTargetPath,$StatePath)) {
	if (Test-Path -LiteralPath $path) { throw 'This copy already has local configuration/state. Use -CheckOnly, or stop and archive its local configuration before registering again.' }
}
$created = [Collections.Generic.List[string]]::new()
try {
	foreach ($entry in @(@($DisplayBaselinePath,$snapshot.baseline),@($DisplayTargetPath,$snapshot.target),@($ConfigPath,$config))) {
		$path = [string]$entry[0]
		# CreateNew is atomic and refuses a concurrent setup overwriting local state.
		$stream = [IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
		$created.Add($path)
		try {
			$bytes = [Text.UTF8Encoding]::new($false).GetBytes(($entry[1] | ConvertTo-Json -Depth 12))
			$stream.Write($bytes,0,$bytes.Length)
		} finally { $stream.Dispose() }
	}
	$null = Assert-VirtualDisplayTarget
	[ordered]@{status='configured';changesApplied=$true;displayChangesApplied=$false;captureIndex=$snapshot.target.captureIndex;credentialsCreated=$false;serverStarted=$false} | ConvertTo-Json
} catch {
	# Only files created by this failed invocation are removed. Never touch driver,
	# monitor settings, another installation, or an unrelated listener.
	foreach ($path in $created) { Remove-Item -LiteralPath $path -ErrorAction SilentlyContinue }
	throw
}

#requires -Version 7.0
<#
Starts the pointer overlay and the window guard (both optional, both safe to start twice:
a second copy exits immediately). They wait up to 30 s for the virtual monitor to appear.

  -NoOverlay / -NoGuard   skip one of them
  -DryRunGuard            guard only logs what it would move (windows/logs/window-guard.log)
  -IgnoreTitle <text>     never move windows whose title contains <text> (the stream viewer's page title)
  -Pythonw <path>         use this pythonw.exe instead of the one found next to `python` on PATH
#>
param([switch]$NoOverlay, [switch]$NoGuard, [switch]$DryRunGuard, [string[]]$IgnoreTitle = @(), [string]$Pythonw = '')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'helpers.ps1')
if ([string]::IsNullOrWhiteSpace($Pythonw)) { $pythonw = Resolve-Pythonw } else { $pythonw = [IO.Path]::GetFullPath($Pythonw); if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { throw '-Pythonw does not exist.' } }
$running = @(Get-VScreenHelpers)

function Start-Helper([string]$Script, [string[]]$ExtraArguments) {
	if ($running | Where-Object { $_.script -eq $Script }) { return ($running | Where-Object { $_.script -eq $Script } | Select-Object -First 1).pid }
	$argumentList = (@('-B', (Join-Path $HelperRoot $Script), '--wait', '30') + $ExtraArguments) | ForEach-Object { Quote-Argument $_ }
	$process = Start-Process -FilePath $pythonw -ArgumentList $argumentList -WindowStyle Hidden -PassThru
	return $process.Id
}

$overlayPid = $null; $guardPid = $null
if (-not $NoOverlay) { $overlayPid = Start-Helper 'cursor_overlay.py' @() }
if (-not $NoGuard) {
	$guardArguments = @()
	if ($DryRunGuard) { $guardArguments += '--dry-run' }
	foreach ($title in $IgnoreTitle) { $guardArguments += @('--ignore-title', $title) }
	$guardPid = Start-Helper 'window_guard.py' $guardArguments
}
[ordered]@{ overlayPid = $overlayPid; guardPid = $guardPid } | ConvertTo-Json

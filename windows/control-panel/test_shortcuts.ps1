#requires -Version 7.0
# Uses an isolated temp folder; never changes Desktop or Start-menu shortcuts.
$ErrorActionPreference = 'Stop'
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('browsed-local-shortcut-test-' + [guid]::NewGuid().ToString('N'))
$linkPath = Join-Path $fixture 'browsed-local.lnk'
try {
	New-Item -ItemType Directory -Path $fixture | Out-Null
	$installer = Join-Path $PSScriptRoot 'install-shortcuts.ps1'
	& $installer -Destination @($fixture) -WhatIf | Out-Null
	if (Test-Path -LiteralPath $linkPath) { throw 'WhatIf unexpectedly created a shortcut.' }
	$first = & $installer -Destination @($fixture) | ConvertFrom-Json
	if ($first.status -ne 'created' -or -not (Test-Path -LiteralPath $linkPath)) { throw 'Shortcut was not created.' }
	$again = & $installer -Destination @($fixture) | ConvertFrom-Json
	if ($again.status -ne 'already-correct') { throw 'Shortcut creation is not idempotent.' }
	$shell = New-Object -ComObject WScript.Shell
	$link = $shell.CreateShortcut($linkPath)
	if ($link.Arguments -ne ('"' + (Join-Path $PSScriptRoot 'virtual_screen_control.pyw') + '"') -or $link.WorkingDirectory -ne $PSScriptRoot) { throw 'Shortcut target does not match this package.' }
	$link.Arguments = 'unrelated-fixture'
	$link.Save()
	$refused = $false
	try { & $installer -Destination @($fixture) | Out-Null } catch { $refused = $true }
	if (-not $refused -or $shell.CreateShortcut($linkPath).Arguments -ne 'unrelated-fixture') { throw 'An unrelated shortcut was overwritten.' }
	'PASS: WhatIf, shortcut target, idempotency and unrelated-shortcut refusal.'
} finally {
	# Both exact paths were created here; no recursive deletion is needed.
	if (Test-Path -LiteralPath $linkPath) { Remove-Item -LiteralPath $linkPath }
	if (Test-Path -LiteralPath $fixture) { Remove-Item -LiteralPath $fixture }
}

#requires -Version 7.0
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source

foreach ($script in Get-ChildItem -LiteralPath $root -Filter '*.ps1' -Recurse -File) {
	$tokens = $null; $errors = $null
	$null = [Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$errors)
	if ($errors.Count) { throw ('PowerShell parse failed: ' + $script.Name) }
}
'PASS: PowerShell syntax'

Push-Location (Join-Path $root 'windows/control-panel')
try {
	& $python -B -m unittest test_control_model.py test_gui_smoke.py
	if ($LASTEXITCODE -ne 0) { throw 'GUI/model tests failed.' }
	& $python -B test_result_transport.py
	if ($LASTEXITCODE -ne 0) { throw 'Inherited-handle regression failed.' }
	& (Join-Path $PWD 'test_shortcuts.ps1')
} finally { Pop-Location }

& $python -B (Join-Path $PSScriptRoot 'test_package_hygiene.py')
if ($LASTEXITCODE -ne 0) { throw 'Package hygiene failed.' }
Push-Location (Join-Path $root 'windows/vscreen')
try {
	& $python -B -m unittest test_sprites test_monitors test_guard_logic test_input
	if ($LASTEXITCODE -ne 0) { throw 'vscreen tests failed.' }
} finally { Pop-Location }
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'test_runtime.ps1')) {
	& (Join-Path $PSScriptRoot 'test_runtime.ps1')
}
'PASS: browsed-local verification'

#requires -Version 7.0
# Stops the pointer overlay and window guard started from this checkout. Nothing else is touched.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'helpers.ps1')
$stopped = @()
foreach ($helper in @(Get-VScreenHelpers)) {
	try { Stop-Process -Id $helper.pid -Force -ErrorAction Stop; $stopped += $helper.script } catch { }
}
[ordered]@{ stopped = $stopped } | ConvertTo-Json

#requires -Version 7.0
# Regression checks for the helper launcher (pure functions only; nothing is started or stopped).
$ErrorActionPreference = 'Stop'
. (Join-Path (Join-Path (Split-Path -Parent $PSScriptRoot) 'windows') 'helpers.ps1')
function Assert-Equal($Actual, $Expected, [string]$Message) { if ($Actual -ne $Expected) { throw "$Message (got [$Actual], wanted [$Expected])" } }

# A title with spaces must reach the helper as ONE argument (this once split into three and the helper exited silently).
Assert-Equal (Quote-Argument 'zenovis — Windows') '"zenovis — Windows"' 'spaces are quoted'
Assert-Equal (Quote-Argument '--wait') '--wait' 'plain arguments are left alone'
Assert-Equal (Quote-Argument 'C:\Program Files\x.py') '"C:\Program Files\x.py"' 'paths with spaces are quoted'
Assert-Equal (Quote-Argument 'say "hi"') '"say \"hi\""' 'embedded quotes are escaped'

# Process discovery returns only this checkout's helper scripts and never throws when none are running.
$found = @(Get-VScreenHelpers)
foreach ($helper in $found) { if ($helper.script -notin @('cursor_overlay.py', 'window_guard.py')) { throw 'unexpected helper match' } }
'PASS: helper launcher helpers'


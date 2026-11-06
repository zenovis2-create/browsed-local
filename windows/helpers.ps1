#requires -Version 7.0
# Shared by start-helpers.ps1 / stop-helpers.ps1 / status.
# The helpers are two small background Python programs next to the stream server:
#   cursor_overlay.py  paints the mouse pointer, click ripples and a wheel badge onto the virtual monitor
#   window_guard.py    moves windows launched from the virtual monitor onto it
$HelperRoot = Join-Path $PSScriptRoot 'vscreen'
$HelperScripts = @('cursor_overlay.py', 'window_guard.py')

function Get-VScreenHelpers {
	# Match on the exact script path under this checkout so unrelated Python processes are never touched.
	$escaped = [regex]::Escape($HelperRoot)
	Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
		Where-Object { $_.CommandLine -match ($escaped + '[\\/](cursor_overlay|window_guard)\.py') } |
		ForEach-Object {
			[pscustomobject]@{ pid = [int]$_.ProcessId; script = ([regex]::Match($_.CommandLine, '(cursor_overlay|window_guard)\.py').Value) }
		}
}

function Resolve-Pythonw {
	$python = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
	if ($null -ne $python) {
		$detected = & $python.Source -c 'import sys; from pathlib import Path; print(Path(sys.executable).with_name("pythonw.exe"))' 2>$null
		if ($LASTEXITCODE -eq 0 -and @($detected).Count -eq 1 -and (Test-Path -LiteralPath ([string]$detected) -PathType Leaf)) { return [string]$detected }
	}
	$direct = Get-Command pythonw -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
	if ($null -ne $direct) { return $direct.Source }
	# Registered installs (python.org installer): newest version first. PATH may hold only a wrapper.
	foreach ($hive in @('HKCU:', 'HKLM:')) {
		$core = Join-Path $hive 'Software\Python\PythonCore'
		if (-not (Test-Path -LiteralPath $core)) { continue }
		foreach ($version in (Get-ChildItem -LiteralPath $core | Sort-Object { [version]($_.PSChildName -replace '-.*$', '') } -Descending -ErrorAction SilentlyContinue)) {
			$install = (Get-ItemProperty -LiteralPath (Join-Path $version.PSPath 'InstallPath') -ErrorAction SilentlyContinue).'(default)'
			if ($install) { $candidate = Join-Path $install 'pythonw.exe'; if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate } }
		}
	}
	throw 'pythonw.exe was not found; install Python 3.10+ (the GUI needs it too).'
}

# Start-Process joins -ArgumentList with plain spaces, so anything containing a space must be quoted
# here, or "zenovis — Windows" arrives as three arguments and the helper exits silently (no console).
function Quote-Argument([string]$Value) {
	if ($Value -match '[\s"]') { return '"' + ($Value -replace '"', '\"') + '"' }
	return $Value
}

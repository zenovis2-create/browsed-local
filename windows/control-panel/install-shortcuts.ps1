#requires -Version 7.0
[CmdletBinding(SupportsShouldProcess)]
param([string]$Pythonw='', [string[]]$Destination=@())
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'virtual_screen_control.pyw'
if ([string]::IsNullOrWhiteSpace($Pythonw)) {
	$python = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
	if ($null -eq $python) { throw 'Python 3.10+ with Tk must be installed and available on PATH, or pass -Pythonw.' }
	$detected = & $python.Source -c 'import sys; from pathlib import Path; print(Path(sys.executable).with_name("pythonw.exe"))'
	if ($LASTEXITCODE -ne 0 -or @($detected).Count -ne 1) { throw 'Could not locate pythonw.exe. Pass -Pythonw explicitly.' }
	$Pythonw = [string]$detected
}
$Pythonw = [IO.Path]::GetFullPath($Pythonw)
if (-not (Test-Path -LiteralPath $Pythonw -PathType Leaf) -or -not (Test-Path -LiteralPath $script -PathType Leaf)) { throw 'Python windowed executable or controller script is missing.' }
if ($Destination.Count -eq 0) { $Destination = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) }
$shell = New-Object -ComObject WScript.Shell
$results = foreach ($folder in $Destination) {
	if (-not (Test-Path -LiteralPath $folder -PathType Container)) { throw 'Shortcut destination must be an existing directory.' }
	$linkPath = Join-Path $folder 'browsed-local.lnk'
	$arguments = '"' + $script + '"'
	if (Test-Path -LiteralPath $linkPath) {
		$existing = $shell.CreateShortcut($linkPath)
		if ($existing.TargetPath -ne $Pythonw -or $existing.Arguments -ne $arguments -or $existing.WorkingDirectory -ne $PSScriptRoot) { throw ('Refusing to overwrite an unrelated shortcut: ' + $linkPath) }
		[pscustomobject]@{path=$linkPath;status='already-correct'}
		continue
	}
	if ($PSCmdlet.ShouldProcess($linkPath, 'Create browsed-local GUI shortcut')) {
		$link = $shell.CreateShortcut($linkPath)
		$link.TargetPath = $Pythonw
		$link.Arguments = $arguments
		$link.WorkingDirectory = $PSScriptRoot
		$link.Description = 'browsed-local 가상 화면 서버 켜기·끄기'
		$link.IconLocation = (Join-Path $env:WINDIR 'System32\shell32.dll') + ',16'
		$link.WindowStyle = 1
		$link.Save()
		[pscustomobject]@{path=$linkPath;status='created'}
	}
}
$results | ConvertTo-Json

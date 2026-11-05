#requires -Version 7.0
param([string]$OutputDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist'))
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'verify.ps1')

# Package only committed Git blobs. Untracked credentials, state and local edits
# cannot leak into the release, even when the working directory has been used.
$dirty = @(& git -C $root status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $dirty.Count) { throw 'Commit reviewed source changes before packaging.' }
$files = @(& git -C $root ls-files)
if ($LASTEXITCODE -ne 0 -or $files.Count -eq 0) { throw 'No committed source inventory.' }
foreach ($file in $files) {
	if ($file -match '(?i)(^|/)(credentials|config|stream-state|baseline-display|display-target|last-supervisor-error)\.json$|(^|/)credential-[^/]+\.tmp$|\.(exe|dll|msi|lnk|zip|png)$|(^|/)shared/') { throw 'Release inventory includes local data or a binary.' }
}
$output = [IO.Path]::GetFullPath($OutputDirectory)
$null = New-Item -ItemType Directory -Path $output -Force
$archive = Join-Path $output 'browsed-local-0.1.0.zip'
if (Test-Path -LiteralPath $archive) { throw 'Release archive already exists; choose a new output directory.' }
& git -C $root archive --format=zip --prefix=browsed-local/ ('--output=' + $archive) HEAD
if ($LASTEXITCODE -ne 0) { throw 'Git archive failed.' }
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($archive + '.sha256'), ($hash + '  ' + [IO.Path]::GetFileName($archive) + "`n"), [Text.UTF8Encoding]::new($false))
[pscustomobject]@{archive=$archive;sha256=$hash;sourceCommit=(& git -C $root rev-parse HEAD)} | ConvertTo-Json

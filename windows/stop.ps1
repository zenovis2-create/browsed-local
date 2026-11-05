#requires -Version 7.0
. (Join-Path $PSScriptRoot 'common.ps1')
$owned = Get-OwnedStream
if ($null -eq $owned) {
	@{endpoint='127.0.0.1:16901'; status='stopped'} | ConvertTo-Json
	return
}
# Get-OwnedStream validates executable path and creation time, guarding recycled PIDs.
Stop-Process -Id $owned.Process.Id
$null = $owned.Process.WaitForExit(5000)
if (@(Get-NetTCPConnection -State Listen -LocalPort $StreamPort -ErrorAction SilentlyContinue).Count -gt 0) { throw 'Port 16901 is still listening after stopping the owned stream.' }
@{endpoint='127.0.0.1:16901'; status='stopped'; stoppedPid=$owned.Process.Id} | ConvertTo-Json

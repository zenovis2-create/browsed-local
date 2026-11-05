#requires -Version 7.0
. (Join-Path $PSScriptRoot 'common.ps1')
. (Join-Path $PSScriptRoot 'virtual-display\monitor-tools.ps1')
$displayVerification = Assert-VirtualDisplayTarget
$captureTarget = $displayVerification.target
$owned = Get-OwnedStream
if ($null -eq $owned -or $owned.Listeners.Count -eq 0) { throw 'Owned Windows stream is not running with a verified loopback listener.' }
if ((Get-FileHash -LiteralPath $StreamExecutable -Algorithm SHA256).Hash -ne $StreamExecutableHash) { throw 'Voxl binary changed since the approved stream setup.' }
if ($owned.State.displayMode -ne 'virtual-only' -or $owned.State.captureDeviceName -ne $captureTarget.deviceName -or $owned.State.captureIndex -ne $captureTarget.captureIndex) { throw 'Running Windows stream predates the current virtual-only target. Configure the display, then explicitly stop/start only port 16901.' }
foreach ($field in @('left','top','width','height','frequency','bitsPerPixel','orientation')) {
	if ($owned.State.captureGeometry.$field -ne $captureTarget.geometry.$field) { throw 'Running stream was launched for a different virtual-display geometry.' }
}
if ($owned.State.captureArgument -ne ('--display=' + $captureTarget.captureIndex)) { throw 'Owned stream launch state does not record the exact validated virtual-display argument.' }
$credential = Read-StreamCredentials
$client = [Net.Http.HttpClient]::new()
$client.Timeout = [TimeSpan]::FromSeconds(15)
try {
	$baseUrl = 'http://127.0.0.1:16901'
	$unauthenticated = $client.GetAsync($baseUrl + '/').GetAwaiter().GetResult()
	if ([int]$unauthenticated.StatusCode -ne 401) { throw 'Unauthenticated root did not return 401.' }
	$client.DefaultRequestHeaders.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $credential.password)
	$authenticated = $client.GetAsync($baseUrl + '/').GetAwaiter().GetResult()
	if ([int]$authenticated.StatusCode -ne 200) { throw 'Authenticated root did not return 200.' }
	$html = $authenticated.Content.ReadAsStringAsync().GetAwaiter().GetResult()
	$title = [regex]::Match($html, '(?is)<title>(.*?)</title>').Groups[1].Value
	if ($title -notmatch 'browsed-local') { throw 'Authenticated page title does not match the owned Windows stream.' }
	$screenshot = $client.GetAsync($baseUrl + '/screenshot').GetAwaiter().GetResult()
	if ([int]$screenshot.StatusCode -ne 200) { throw 'Authenticated screenshot endpoint did not return 200.' }
	$imageBytes = $screenshot.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
	if ($imageBytes.Length -lt 24 -or [Convert]::ToHexString($imageBytes[0..7]) -ne '89504E470D0A1A0A') { throw 'Screenshot response was not a valid PNG header.' }
	$width = [uint32]$imageBytes[16] * 16777216 + [uint32]$imageBytes[17] * 65536 + [uint32]$imageBytes[18] * 256 + [uint32]$imageBytes[19]
	$height = [uint32]$imageBytes[20] * 16777216 + [uint32]$imageBytes[21] * 65536 + [uint32]$imageBytes[22] * 256 + [uint32]$imageBytes[23]
	if ($width -ne 1920 -or $height -ne 1080 -or $width -ne $captureTarget.geometry.width -or $height -ne $captureTarget.geometry.height) { throw 'Screenshot dimensions do not match the required 1920x1080 virtual monitor; refusing to report ready.' }
	$finalDisplay = Assert-VirtualDisplayTarget
	if ($finalDisplay.target.deviceName -ne $captureTarget.deviceName -or $finalDisplay.target.captureIndex -ne $captureTarget.captureIndex) { throw 'Display target changed during screenshot verification.' }
	[ordered]@{endpoint=$baseUrl; status='ready'; displayMode='virtual-only'; captureDeviceName=$captureTarget.deviceName; captureIndex=$captureTarget.captureIndex; physicalUnchanged=$true; pid=$owned.Process.Id; sessionId=$owned.Process.SessionId; listeners=@($owned.Listeners | ForEach-Object {$_.LocalAddress}); unauthenticatedStatus=401; authenticatedStatus=200; title=$title; screenshotStatus=200; screenshotWidth=$width; screenshotHeight=$height; screenshotBytes=$imageBytes.Length; credentialFile=$CredentialPath; checkedUtc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Depth 4
} finally {
	$client.Dispose()
}

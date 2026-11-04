# Run after extracting the complete Windows distribution.
# This script has not been executed on the Linux build machine.
$ErrorActionPreference = 'Stop'
$Package = $PSScriptRoot
$Hashes = Get-Content -LiteralPath (Join-Path $Package 'SHA256.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($Item in $Hashes.PSObject.Properties) {
    $File = Join-Path $Package $Item.Name
    $Actual = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Item.Value) { throw "SHA256 mismatch: $($Item.Name)" }
}
& (Join-Path $Package 'runtime\python.exe') -B -E -s (Join-Path $Package 'windows_smoke.py')
if ($LASTEXITCODE -ne 0) { throw "Bundled Python / engine smoke test failed: $LASTEXITCODE" }
$Launch = Start-Process -FilePath (Join-Path $Package 'Bbolprom.exe') -ArgumentList '--self-test' -PassThru
if (-not $Launch.WaitForExit(60000)) {
    Stop-Process -Id $Launch.Id -Force
    throw 'Native launcher / local HTTP health self-test timed out'
}
if ($Launch.ExitCode -ne 0) { throw "Native launcher / local HTTP health self-test failed: $($Launch.ExitCode)" }
Write-Output 'Verified bundled runtime, engine, native launcher and local HTTP health. Browser UI/real PT/live API are separate tests.' 

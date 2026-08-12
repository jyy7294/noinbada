$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
& "$ProjectRoot\.venv\Scripts\python.exe" -m trzip.hourly_cli collect
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "먼저 scripts\install-hourly-task.ps1을 실행해 주세요."
}
Set-Location $ProjectRoot
& $Python -m trzip.x_web_collector --setup
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

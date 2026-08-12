$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "먼저 scripts\install-hourly-task.ps1을 실행해 주세요."
}
Set-Location $ProjectRoot
Write-Host "X 로그인과 대한민국 트렌드 10개 이상을 최대 10분간 자동 확인합니다. Enter 입력은 필요하지 않습니다."
& $Python -m trzip.x_web_collector --setup --setup-timeout-seconds 600
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

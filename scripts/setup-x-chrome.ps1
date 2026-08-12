param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ProfileName = "",
    [int]$TimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExtensionRoot = Join-Path $ProjectRoot "chrome-extension\trzip-x-current-session"
$Chrome = Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"
$LocalStatePath = Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data\Local State"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "먼저 scripts\install-hourly-task.ps1을 실행해 주세요."
}
if (-not (Test-Path -LiteralPath (Join-Path $ExtensionRoot "manifest.json"))) {
    throw "X Chrome 확장 폴더를 찾을 수 없습니다: $ExtensionRoot"
}
if (-not (Test-Path -LiteralPath $Chrome)) {
    throw "Google Chrome 실행 파일을 찾을 수 없습니다: $Chrome"
}
if (-not (Test-Path -LiteralPath $LocalStatePath)) {
    throw "Chrome Local State를 찾을 수 없습니다. Chrome 프로필이 먼저 생성되어야 합니다."
}

# Only non-secret profile metadata is read. Cookies, storage, and passwords are
# never inspected, copied, or passed to the collector.
$LocalState = Get-Content -LiteralPath $LocalStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
$ProfileEntry = if ($ProfileName) {
    $LocalState.profile.info_cache.PSObject.Properties |
        Where-Object { [string]$_.Value.name -ieq $ProfileName } |
        Select-Object -First 1
} else {
    $LastUsedDirectory = [string]$LocalState.profile.last_used
    $LocalState.profile.info_cache.PSObject.Properties |
        Where-Object { [string]$_.Name -eq $LastUsedDirectory } |
        Select-Object -First 1
}
if (-not $ProfileEntry) {
    $KnownProfiles = @(
        $LocalState.profile.info_cache.PSObject.Properties |
            ForEach-Object { [string]$_.Value.name }
    ) -join ", "
    $Requested = if ($ProfileName) { "표시 이름 '$ProfileName'" } else { "Chrome의 마지막 사용 프로필" }
    throw "$Requested 을(를) 찾을 수 없습니다. 확인된 프로필: $KnownProfiles"
}
$ProfileDirectory = [string]$ProfileEntry.Name
$ResolvedProfileName = [string]$ProfileEntry.Value.name

Write-Host "Chrome 대상 프로필: $ResolvedProfileName ($ProfileDirectory)"
Write-Host "쿠키를 복사하지 않고 이 프로필 내부의 확장 프로그램이 X 순위만 저장합니다."
Write-Host "기존 Chrome 창이나 탭은 종료하지 않습니다."
Write-Host ""
Write-Host "1) 열린 chrome://extensions 화면에서 '개발자 모드'를 켭니다."
Write-Host "2) '압축해제된 확장 프로그램을 로드합니다'를 누릅니다."
Write-Host "3) 함께 열린 폴더를 선택합니다: $ExtensionRoot"
Write-Host "4) 설치 직후 자동 수집됩니다. 확장 배지가 30이면 성공입니다."

Start-Process -FilePath explorer.exe -ArgumentList @($ExtensionRoot) | Out-Null
Start-Process -FilePath $Chrome -ArgumentList @(
    "--profile-directory=$ProfileDirectory",
    "chrome://extensions"
) | Out-Null

Set-Location $ProjectRoot
& $Python -m trzip.x_web_collector --setup --setup-timeout-seconds ([Math]::Max(1, $TimeoutSeconds))
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "X 현재 세션 연결 확인 완료: 한국 실시간 순위 1~30위가 로컬 inbox에 저장됐습니다."

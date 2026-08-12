param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "TRZIP X Google Hourly Collector",
    [switch]$ReplaceDifferentProjectRoot
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$RuntimeRoot = if ($env:TRZIP_RUNTIME_ROOT) {
    [IO.Path]::GetFullPath($env:TRZIP_RUNTIME_ROOT)
} else {
    [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "TRZIP"))
}
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LiveDataRoot = Join-Path $RuntimeRoot "live-data"

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".git"))) {
    throw "ProjectRoot is not a Git worktree: $ProjectRoot"
}
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
if (-not (Test-Path -LiteralPath $Python)) {
    py -3.13 -m venv (Join-Path $ProjectRoot ".venv")
}
& $Python -m pip install -e "$ProjectRoot"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }

if (-not (Test-Path -LiteralPath (Join-Path $LiveDataRoot ".git"))) {
    # A runtime clone may have been created with --single-branch main. Fetch
    # the publication branch into an explicit remote-tracking ref so worktree
    # creation is deterministic in both full and single-branch clones.
    & git -C $ProjectRoot fetch origin "+refs/heads/live-data:refs/remotes/origin/live-data"
    if ($LASTEXITCODE -ne 0) { throw "Cannot fetch origin/live-data" }
    & git -C $ProjectRoot show-ref --verify --quiet refs/heads/live-data
    if ($LASTEXITCODE -eq 0) {
        & git -C $ProjectRoot worktree add $LiveDataRoot live-data
    } else {
        & git -C $ProjectRoot worktree add -b live-data $LiveDataRoot origin/live-data
    }
    if ($LASTEXITCODE -ne 0) { throw "Cannot create live-data worktree" }
}

$Now = Get-Date
$NextHour = $Now.Date.AddHours($Now.Hour + 1)
$Script = Join-Path $ProjectRoot "scripts\collect-hourly.ps1"
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    $ExistingArguments = [string]$ExistingTask.Actions[0].Arguments
    $ExpectedScriptArgument = "-File `"$Script`""
    $ExpectedRootArgument = "-ProjectRoot `"$ProjectRoot`""
    $AlreadyExact = $ExistingTask.Actions[0].Execute -ieq "powershell.exe" -and
        $ExistingArguments.Contains($ExpectedScriptArgument) -and
        $ExistingArguments.Contains($ExpectedRootArgument)
    if (-not $AlreadyExact -and -not $ReplaceDifferentProjectRoot) {
        throw @"
예약 작업 '$TaskName'이 다른 프로젝트를 가리키고 있어 자동으로 덮어쓰지 않았습니다.
현재: $ExistingArguments
교체하려면 이 스크립트를 -ReplaceDifferentProjectRoot와 함께 다시 실행하세요.
"@
    }
}
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Script`" -ProjectRoot `"$ProjectRoot`"" `
    -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $NextHour `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "매시 00분 현재 로그인 Chrome의 X 한국 실시간 + Google Trends KR 수집, 검증, live-data 게시" `
    -Force | Out-Null

$Task = Get-ScheduledTask -TaskName $TaskName
$RegisteredScript = $Task.Actions[0].Arguments
if (-not $RegisteredScript.Contains("-File `"$Script`"") -or
    -not $RegisteredScript.Contains("-ProjectRoot `"$ProjectRoot`"")) {
    throw "Scheduled task path verification failed: $RegisteredScript"
}
$RegisteredTrigger = @($Task.Triggers)[0]
if ($RegisteredTrigger.Repetition.Interval -ne "PT1H") {
    throw "Scheduled task hourly trigger verification failed: $($RegisteredTrigger.Repetition.Interval)"
}
$Task | Select-Object TaskName,State,@{N="Execute";E={$_.Actions[0].Execute}},@{N="Arguments";E={$_.Actions[0].Arguments}}

Write-Host ""
Write-Host "예약 작업은 수집 -> 정규화 -> 검증 -> live-data 게시 전체 파이프라인을 실행합니다."
Write-Host "X는 현재 로그인된 Chrome 프로필 안의 확장 프로그램이 매시 순위 1~30위를 먼저 저장해야 합니다."
Write-Host "최초 1회 설정: powershell -ExecutionPolicy Bypass -File scripts\setup-x-chrome.ps1"

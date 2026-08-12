param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "TRZIP X Google Hourly Collector"
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
    -Description "매시 00분 로컬 Chrome X 한국 실시간 + Google Trends KR 수집, 검증, live-data 게시" `
    -Force | Out-Null

$Task = Get-ScheduledTask -TaskName $TaskName
$RegisteredScript = $Task.Actions[0].Arguments
if ($RegisteredScript -notlike "*$Script*") {
    throw "Scheduled task path verification failed: $RegisteredScript"
}
$Task | Select-Object TaskName,State,@{N="Execute";E={$_.Actions[0].Execute}},@{N="Arguments";E={$_.Actions[0].Arguments}}

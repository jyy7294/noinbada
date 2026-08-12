param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
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

# The supported scheduler is the Codex desktop automation. Keep an old
# Windows task from creating a duplicate snapshot if it still exists.
$LegacyTask = Get-ScheduledTask -TaskName "TRZIP X Google Hourly Collector" -ErrorAction SilentlyContinue
if ($LegacyTask -and $LegacyTask.State -ne "Disabled") {
    Disable-ScheduledTask -TaskName $LegacyTask.TaskName | Out-Null
}

[ordered]@{
    status = "ready"
    runtime_root = $RuntimeRoot
    live_data_ready = (Test-Path -LiteralPath (Join-Path $LiveDataRoot ".git"))
    scheduler = "codex_hourly_automation"
    legacy_windows_task_disabled = [bool]$LegacyTask
} | ConvertTo-Json -Compress

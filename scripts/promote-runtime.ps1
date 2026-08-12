param(
    [string]$RuntimeCheckout = (Join-Path $env:USERPROFILE "Documents\Codex\noinbada-runtime"),
    [string]$ExpectedSha = "",
    [string]$TaskName = "TRZIP X Google Hourly Collector"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RuntimeCheckout = [IO.Path]::GetFullPath($RuntimeCheckout)
$Mutex = [Threading.Mutex]::new($false, "Global\TRZIP-NOINBADA-HOURLY-V1")
$HasMutex = $false

try {
    $now = Get-Date
    if ($now.Minute -ge 58 -or $now.Minute -le 1) {
        throw "Runtime promotion is blocked near the hourly collection boundary. Retry after minute 01."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $RuntimeCheckout ".git"))) {
        throw "Runtime checkout is not a Git worktree."
    }
    $dirty = @(& git -C $RuntimeCheckout status --porcelain --untracked-files=all)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
        throw "Runtime checkout has local changes; refusing to overwrite it."
    }
    $branch = (& git -C $RuntimeCheckout branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -ne "main") {
        throw "Runtime checkout must be on main."
    }
    $HasMutex = $Mutex.WaitOne(0)
    if (-not $HasMutex) {
        throw "Hourly collection is active; retry runtime promotion after it finishes."
    }

    & git -C $RuntimeCheckout fetch origin `
        "+refs/heads/main:refs/remotes/origin/main" --quiet
    if ($LASTEXITCODE -ne 0) { throw "Failed to fetch origin/main." }
    & git -C $RuntimeCheckout merge --ff-only origin/main
    if ($LASTEXITCODE -ne 0) { throw "Runtime checkout cannot fast-forward to origin/main." }

    $runtimeSha = (& git -C $RuntimeCheckout rev-parse HEAD).Trim()
    $remoteSha = (& git -C $RuntimeCheckout rev-parse origin/main).Trim()
    if ($runtimeSha -ne $remoteSha) { throw "Runtime and origin/main SHA differ." }
    if ($ExpectedSha -and $runtimeSha -ne $ExpectedSha) {
        throw "Runtime SHA does not match the checkpoint SHA."
    }

    $python = Join-Path $RuntimeCheckout ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Runtime Python environment is missing."
    }
    & $python -m pip install -e $RuntimeCheckout --quiet
    if ($LASTEXITCODE -ne 0) { throw "Runtime dependency refresh failed." }

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $script = Join-Path $RuntimeCheckout "scripts\collect-hourly.ps1"
    $arguments = [string]$task.Actions[0].Arguments
    if (-not $arguments.Contains("-File `"$script`"") -or
        -not $arguments.Contains("-ProjectRoot `"$RuntimeCheckout`"")) {
        throw "Scheduled task does not target the promoted runtime checkout."
    }

    [ordered]@{
        status = "promoted"
        branch = "main"
        sha = $runtimeSha
        scheduler = $TaskName
        scheduler_target_verified = $true
    } | ConvertTo-Json -Compress
} finally {
    if ($HasMutex) { $Mutex.ReleaseMutex() }
    $Mutex.Dispose()
}

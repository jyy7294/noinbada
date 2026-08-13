param(
    [string]$RuntimeCheckout = (Join-Path $env:USERPROFILE "Documents\Codex\noinbada-runtime"),
    [string]$ExpectedSha = "",
    [string]$AutomationConfig = (Join-Path $env:USERPROFILE ".codex\automations\trzip\automation.toml")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RuntimeCheckout = [IO.Path]::GetFullPath($RuntimeCheckout)
$AutomationConfig = [IO.Path]::GetFullPath($AutomationConfig)
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
    # Keep the promoted runtime independently auditable.  The hourly process only
    # needs production dependencies, but checkpoint/runtime verification also
    # requires the repository's schema and test dependencies on every machine.
    & $python -m pip install -e "$RuntimeCheckout[dev]" --quiet
    if ($LASTEXITCODE -ne 0) { throw "Runtime dependency refresh failed." }

    & $python -c "import jsonschema, pytest" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime verification dependencies are unavailable after refresh."
    }

    if (-not (Test-Path -LiteralPath $AutomationConfig -PathType Leaf)) {
        throw "Codex hourly automation config is missing."
    }
    $automationText = [IO.File]::ReadAllText($AutomationConfig, [Text.Encoding]::UTF8)
    if ($automationText -notmatch '(?m)^\s*status\s*=\s*"ACTIVE"\s*$') {
        throw "Codex hourly automation is not ACTIVE."
    }
    if ($automationText -notmatch '(?m)^\s*rrule\s*=\s*"FREQ=HOURLY;INTERVAL=1;BYMINUTE=0"\s*$') {
        throw "Codex hourly automation schedule is not the required top-of-hour rule."
    }
    $runtimePathCandidates = @(
        $RuntimeCheckout,
        $RuntimeCheckout.Replace('\', '/'),
        $RuntimeCheckout.Replace('\', '\\')
    )
    $targetsRuntime = $false
    foreach ($candidate in $runtimePathCandidates) {
        if ($automationText.Contains($candidate)) {
            $targetsRuntime = $true
            break
        }
    }
    if (-not $targetsRuntime) {
        throw "Codex hourly automation does not target the promoted runtime checkout."
    }

    [ordered]@{
        status = "promoted"
        branch = "main"
        sha = $runtimeSha
        scheduler = "codex_hourly_automation"
        automation_config = "%USERPROFILE%\.codex\automations\trzip\automation.toml"
        scheduler_target_verified = $true
    } | ConvertTo-Json -Compress
} finally {
    if ($HasMutex) { $Mutex.ReleaseMutex() }
    $Mutex.Dispose()
}

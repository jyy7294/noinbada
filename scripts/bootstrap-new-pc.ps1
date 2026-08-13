param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TargetThreadId = "",
    [string]$CodexHome = (Join-Path $env:USERPROFILE ".codex"),
    [switch]$SkipTests,
    [switch]$ForceAutomation
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)

foreach ($Command in @("git", "py")) {
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "Required command is missing: $Command"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".git"))) {
    throw "Run this script from a cloned Git repository."
}

$Branch = (& git -C $ProjectRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $Branch -ne "main") {
    throw "Portable setup must start from the main branch."
}
& git -C $ProjectRoot fetch origin "+refs/heads/main:refs/remotes/origin/main" --quiet
if ($LASTEXITCODE -ne 0) { throw "Cannot fetch origin/main." }
$LocalSha = (& git -C $ProjectRoot rev-parse HEAD).Trim()
$RemoteSha = (& git -C $ProjectRoot rev-parse origin/main).Trim()
if ($LocalSha -ne $RemoteSha) {
    throw "Local main is not the current origin/main. Fast-forward it before setup."
}

& (Join-Path $PSScriptRoot "setup-local-runtime.ps1") -ProjectRoot $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw "Runtime setup failed." }

$AutomationStatus = "needs_target_thread_id"
if ($TargetThreadId) {
    $Arguments = @(
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "install-codex-automation.ps1"),
        "-TargetThreadId", $TargetThreadId,
        "-ProjectRoot", $ProjectRoot,
        "-CodexHome", $CodexHome
    )
    if ($ForceAutomation) { $Arguments += "-Force" }
    & powershell @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Codex automation installation failed." }
    $AutomationStatus = "installed"
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$TestStatus = "skipped"
if (-not $SkipTests) {
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Repository validation failed." }
    $TestStatus = "passed"
}

$RuntimeRoot = if ($env:TRZIP_RUNTIME_ROOT) {
    [IO.Path]::GetFullPath($env:TRZIP_RUNTIME_ROOT)
} else {
    [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "TRZIP"))
}
$LiveDataRoot = Join-Path $RuntimeRoot "live-data"
$GitHubCredentialStatus = if (Get-Command gh -ErrorAction SilentlyContinue) {
    & gh auth status 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { "authenticated" } else { "needs_gh_auth_login" }
} else {
    "git_credential_required_for_push"
}

[ordered]@{
    status = if ($AutomationStatus -eq "installed") { "ready_for_browser_login_check" } else { "needs_target_thread_id" }
    code_sha = $LocalSha
    branch = $Branch
    python = $Python
    tests = $TestStatus
    runtime_root = $RuntimeRoot
    live_data_worktree = (Test-Path -LiteralPath (Join-Path $LiveDataRoot ".git"))
    automation = $AutomationStatus
    github_credentials = $GitHubCredentialStatus
    remaining_human_checks = @(
        "Open Codex Desktop and keep the target task available.",
        "Sign in to X in the current Chrome profile and verify the Korea trending page.",
        "Run scripts\collect-hourly.ps1 once and then scripts\audit-runtime.py."
    )
} | ConvertTo-Json -Depth 4

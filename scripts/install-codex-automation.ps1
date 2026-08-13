param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F-]{20,}$')]
    [string]$TargetThreadId,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CodexHome = (Join-Path $env:USERPROFILE ".codex"),
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function ConvertTo-TomlString([string]$Value) {
    return $Value.Replace('\', '\\').Replace('"', '\"').Replace("`r", '').Replace("`n", '\n')
}

$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$CodexHome = [IO.Path]::GetFullPath($CodexHome)
$ConfigDirectory = Join-Path $CodexHome "automations\trzip"
$ConfigPath = Join-Path $ConfigDirectory "automation.toml"
$InboxPath = if ($env:TRZIP_X_INBOX) {
    [IO.Path]::GetFullPath($env:TRZIP_X_INBOX)
} else {
    Join-Path $env:USERPROFILE "Downloads\TRZIP\x-current-session.json"
}
$PromptTemplatePath = Join-Path $ProjectRoot "config\codex-automation\trzip-prompt.ko.txt"

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".git"))) {
    throw "ProjectRoot is not a Git worktree: $ProjectRoot"
}
if ((Test-Path -LiteralPath $ConfigPath) -and -not $Force) {
    throw "Automation already exists. Re-run with -Force only after reviewing the existing automation."
}
if (-not (Test-Path -LiteralPath $PromptTemplatePath -PathType Leaf)) {
    throw "Automation prompt template is missing: $PromptTemplatePath"
}
$Prompt = [IO.File]::ReadAllText($PromptTemplatePath, [Text.Encoding]::UTF8).Trim()
$Prompt = $Prompt.Replace("{{X_INBOX}}", $InboxPath).Replace("{{PROJECT_ROOT}}", $ProjectRoot)

$Toml = @"
version = 1
id = "trzip"
kind = "heartbeat"
name = "TRZIP hourly X and Google collection"
prompt = "$(ConvertTo-TomlString $Prompt)"
status = "ACTIVE"
rrule = "FREQ=HOURLY;INTERVAL=1;BYMINUTE=0"
notification_policy = "failed_runs_only"
target_thread_id = "$(ConvertTo-TomlString $TargetThreadId)"
"@

New-Item -ItemType Directory -Force -Path $ConfigDirectory | Out-Null
$TemporaryPath = "$ConfigPath.tmp"
[IO.File]::WriteAllText($TemporaryPath, $Toml + "`n", [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $TemporaryPath -Destination $ConfigPath -Force

[ordered]@{
    status = "installed"
    automation_id = "trzip"
    config = $ConfigPath
    schedule = "FREQ=HOURLY;INTERVAL=1;BYMINUTE=0"
    project_root = $ProjectRoot
    target_thread_id = $TargetThreadId
} | ConvertTo-Json -Compress

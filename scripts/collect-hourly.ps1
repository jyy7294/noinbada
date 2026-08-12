param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$RuntimeRoot = if ($env:TRZIP_RUNTIME_ROOT) {
    [IO.Path]::GetFullPath($env:TRZIP_RUNTIME_ROOT)
} else {
    [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "TRZIP"))
}
$PublicationRoot = Join-Path $RuntimeRoot "publication"
$DatabasePath = Join-Path $RuntimeRoot "data\trzip-hourly.sqlite3"
$LiveDataRoot = Join-Path $RuntimeRoot "live-data"
$LogRoot = Join-Path $RuntimeRoot "logs"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RunId = [guid]::NewGuid().ToString("N")
$StartedAt = [DateTimeOffset]::UtcNow
$Mutex = [Threading.Mutex]::new($false, "Global\TRZIP-NOINBADA-HOURLY-V1")
$HasMutex = $false

function Write-RunLog {
    param([string]$Phase, [string]$Status, [string]$Detail = "")
    New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
    $record = [ordered]@{
        run_id = $RunId
        at = [DateTimeOffset]::UtcNow.ToString("o")
        phase = $Phase
        status = $Status
        detail = $Detail
    }
    Add-Content -LiteralPath (Join-Path $LogRoot ("hourly-{0}.jsonl" -f (Get-Date -Format "yyyy-MM-dd"))) `
        -Value ($record | ConvertTo-Json -Compress)
}

function Assert-ChildPath {
    param([string]$Parent, [string]$Child)
    $resolvedParent = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $resolvedChild = [IO.Path]::GetFullPath($Child).TrimEnd('\') + '\'
    if (-not $resolvedChild.StartsWith($resolvedParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe path outside runtime root: $resolvedChild"
    }
}

function Get-RelativeChildPath {
    param([string]$Parent, [string]$Child)
    $resolvedParent = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $resolvedChild = [IO.Path]::GetFullPath($Child)
    if (-not $resolvedChild.StartsWith($resolvedParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe child path outside parent: $resolvedChild"
    }
    return $resolvedChild.Substring($resolvedParent.Length)
}

function Sync-PublicDirectory {
    param([string]$Name)
    $Source = Join-Path $PublicationRoot $Name
    $Destination = Join-Path $LiveDataRoot $Name
    Assert-ChildPath -Parent $RuntimeRoot -Child $Destination
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $sourceRelative = @{}
    foreach ($item in Get-ChildItem -LiteralPath $Source -Recurse -File) {
        $relative = Get-RelativeChildPath -Parent $Source -Child $item.FullName
        $sourceRelative[$relative] = $true
        $target = Join-Path $Destination $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath $item.FullName -Destination $target -Force
    }
    foreach ($item in Get-ChildItem -LiteralPath $Destination -Recurse -File) {
        $relative = Get-RelativeChildPath -Parent $Destination -Child $item.FullName
        if (-not $sourceRelative.ContainsKey($relative)) {
            Remove-Item -LiteralPath $item.FullName -Force
        }
    }
}

try {
    $HasMutex = $Mutex.WaitOne(0)
    if (-not $HasMutex) {
        Write-RunLog -Phase "lock" -Status "skipped" -Detail "another hourly run is active"
        exit 0
    }
    Write-RunLog -Phase "start" -Status "running" -Detail $ProjectRoot
    if (-not (Test-Path -LiteralPath $Python)) { throw "Python environment missing: $Python" }
    if (-not (Test-Path -LiteralPath (Join-Path $LiveDataRoot ".git"))) {
        throw "live-data worktree missing; run scripts\install-hourly-task.ps1"
    }
    New-Item -ItemType Directory -Force -Path $PublicationRoot,(Split-Path -Parent $DatabasePath) | Out-Null

    Set-Location $ProjectRoot
    # Raw ledger and published daily aggregates are retained indefinitely by
    # default. Pruning requires an explicit positive --retention-days value.
    & $Python -m trzip.local_pipeline --output $PublicationRoot --database $DatabasePath
    if ($LASTEXITCODE -ne 0) { throw "local pipeline exited with code $LASTEXITCODE" }
    Write-RunLog -Phase "pipeline" -Status "ok"

    $DirtyBefore = @(& git -C $LiveDataRoot status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw "live-data worktree is not readable" }
    if ($DirtyBefore.Count -gt 0) {
        $DirtyPaths = @(
            @(& git -C $LiveDataRoot diff --name-only)
            @(& git -C $LiveDataRoot diff --cached --name-only)
            @(& git -C $LiveDataRoot ls-files --others --exclude-standard)
        ) | Sort-Object -Unique
        $ForbiddenDirtyPaths = @($DirtyPaths | Where-Object {
            $_ -notmatch '^(latest|observations|monitoring)/'
        })
        if ($ForbiddenDirtyPaths.Count -gt 0) {
            throw "live-data worktree has non-publication changes; refusing to overwrite: $($ForbiddenDirtyPaths -join ', ')"
        }
        Write-RunLog -Phase "recovery" -Status "continuing" `
            -Detail "recovering allowed publication files from an interrupted prior run"
    }
    & git -C $LiveDataRoot fetch origin live-data --quiet
    if ($LASTEXITCODE -ne 0) { throw "failed to fetch origin/live-data" }
    $local = (& git -C $LiveDataRoot rev-parse HEAD).Trim()
    $remote = (& git -C $LiveDataRoot rev-parse origin/live-data).Trim()
    $base = (& git -C $LiveDataRoot merge-base HEAD origin/live-data).Trim()
    if ($local -eq $base -and $local -ne $remote) {
        & git -C $LiveDataRoot merge --ff-only origin/live-data
        if ($LASTEXITCODE -ne 0) { throw "failed to fast-forward live-data" }
    } elseif ($local -ne $remote -and $remote -ne $base) {
        throw "live-data diverged from origin; refusing force push"
    }

    foreach ($name in "latest","observations","monitoring") {
        Sync-PublicDirectory -Name $name
    }
    & git -C $LiveDataRoot add -- latest observations monitoring
    if ($LASTEXITCODE -ne 0) { throw "failed to stage publication files" }
    $StagedPaths = @(& git -C $LiveDataRoot diff --cached --name-only)
    if ($LASTEXITCODE -ne 0) { throw "failed to inspect staged publication files" }
    $ForbiddenPaths = @($StagedPaths | Where-Object {
        $_ -notmatch '^(latest|observations|monitoring)/'
    })
    if ($ForbiddenPaths.Count -gt 0) {
        & git -C $LiveDataRoot restore --staged -- $ForbiddenPaths
        throw "publication attempted to stage forbidden paths: $($ForbiddenPaths -join ', ')"
    }
    & git -C $LiveDataRoot diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-RunLog -Phase "publish" -Status "unchanged"
        exit 0
    }
    $commitStamp = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:00Z")
    & git -C $LiveDataRoot -c user.name="trzip-local-collector" `
        -c user.email="trzip-local-collector@users.noreply.github.com" `
        commit -m "data: laptop hourly collection $commitStamp"
    if ($LASTEXITCODE -ne 0) { throw "failed to commit live data" }
    & git -C $LiveDataRoot push origin live-data
    if ($LASTEXITCODE -ne 0) { throw "failed to push live-data; local commit retained for retry" }
    $commit = (& git -C $LiveDataRoot rev-parse --short HEAD).Trim()
    Write-RunLog -Phase "publish" -Status "ok" -Detail $commit
} catch {
    Write-RunLog -Phase "failed" -Status "error" -Detail $_.Exception.Message
    Write-Error $_
    exit 1
} finally {
    if ($HasMutex) { $Mutex.ReleaseMutex() }
    $Mutex.Dispose()
    Get-ChildItem -LiteralPath $LogRoot -Filter "hourly-*.jsonl" -File -ErrorAction SilentlyContinue |
        Where-Object LastWriteTime -lt (Get-Date).AddDays(-30) |
        Remove-Item -Force
}

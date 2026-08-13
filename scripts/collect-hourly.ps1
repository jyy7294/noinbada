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
        throw "live-data worktree missing; run scripts\setup-local-runtime.ps1"
    }
    New-Item -ItemType Directory -Force -Path $PublicationRoot,(Split-Path -Parent $DatabasePath) | Out-Null

    Set-Location $ProjectRoot
    # Raw ledger and published daily aggregates are retained indefinitely by
    # default. Pruning requires an explicit positive --retention-days value.
    & $Python -m trzip.local_pipeline --output $PublicationRoot --database $DatabasePath
    if ($LASTEXITCODE -ne 0) { throw "local pipeline exited with code $LASTEXITCODE" }
    & $Python -c "from pathlib import Path; from trzip.publication_pipeline import validate_frontend_delivery; validate_frontend_delivery(Path(r'$PublicationRoot'))"
    if ($LASTEXITCODE -ne 0) { throw "frontend delivery manifest validation failed" }
    Write-RunLog -Phase "pipeline" -Status "ok"

    $PublicationStatusPath = Join-Path $PublicationRoot "latest\status.json"
    try {
        $PublicationStatus = Get-Content -LiteralPath $PublicationStatusPath -Raw | ConvertFrom-Json
    } catch {
        throw "publication status is missing or invalid"
    }
    if ($PublicationStatus.publishable -ne $true) {
        $SourceDetail = "x={0} google={1}" -f `
            $PublicationStatus.source_status.x,$PublicationStatus.source_status.google_trends
        Write-RunLog -Phase "publish" -Status "local_only" `
            -Detail "same-hour X+Google gate not met; $SourceDetail"
        exit 0
    }

    # Audit the exact publication and SQLite ledger that are about to be
    # published. History maturity may remain provisional, but both ranking
    # sources must be observed for this hour before remote publication.
    $AuditScript = Join-Path $ProjectRoot "scripts\audit-runtime.py"
    $AuditOutput = @(& $Python $AuditScript --runtime-root $RuntimeRoot --json 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "runtime quality audit failed; publication was not pushed"
    }
    try {
        $Audit = ($AuditOutput -join [Environment]::NewLine) | ConvertFrom-Json
    } catch {
        throw "runtime quality audit returned invalid JSON"
    }
    $AuditDetail = "status={0} failures={1} blockers={2} warnings={3}" -f `
        $Audit.status,$Audit.failures.Count,$Audit.blockers.Count,$Audit.warnings.Count
    Write-RunLog -Phase "audit" -Status $Audit.status -Detail $AuditDetail

    # The complete product contract must pass before any latest publication can
    # replace the remote. Remote verification and the immutable receipt happen
    # later, after the exact bytes are pushed and independently resolved.
    $PreflightOutput = Join-Path $PublicationRoot "monitoring\publication_preflight.json"
    & $Python -m trzip.result_quality --database $DatabasePath `
        --end $PublicationStatus.observed_at --preflight `
        --intelligence (Join-Path $PublicationRoot "latest\intelligence.json") `
        --output $PreflightOutput | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $Preflight = Get-Content -LiteralPath $PreflightOutput -Raw -Encoding utf8 | ConvertFrom-Json
        $SourceRows = "x={0} google={1}" -f `
            $Preflight.source_gate.sources.x.row_count, `
            $Preflight.source_gate.sources.google_trends.row_count
        throw "publication preflight failed before remote push; $SourceRows; failures=$($Preflight.contract.failures -join ',')"
    }
    Write-RunLog -Phase "preflight" -Status "ok" `
        -Detail "source-v2 and frontend-v2 contracts passed before remote publication"

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
    # Refresh the remote-tracking ref explicitly. `git fetch origin live-data`
    # updates FETCH_HEAD only on some worktree configurations, leaving
    # origin/live-data stale even when the remote branch is current.
    & git -C $LiveDataRoot fetch origin `
        "+refs/heads/live-data:refs/remotes/origin/live-data" --quiet
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
    $PublicationChanged = $LASTEXITCODE -ne 0
    $commitStamp = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:00Z")
    if (-not $PublicationChanged) {
        Write-RunLog -Phase "publish" -Status "unchanged"
    } else {
        & git -C $LiveDataRoot -c user.name="trzip-local-collector" `
            -c user.email="trzip-local-collector@users.noreply.github.com" `
            commit -m "data: laptop hourly collection $commitStamp"
        if ($LASTEXITCODE -ne 0) { throw "failed to commit live data" }
        & git -C $LiveDataRoot push origin "HEAD:refs/heads/live-data"
        if ($LASTEXITCODE -ne 0) { throw "failed to push live-data; local commit retained for retry" }
    }
    $localPublished = (& git -C $LiveDataRoot rev-parse HEAD).Trim()
    $remoteLine = @(& git -C $LiveDataRoot ls-remote origin refs/heads/live-data)
    if ($LASTEXITCODE -ne 0 -or $remoteLine.Count -ne 1) {
        throw "failed to verify remote live-data after push; local commit retained"
    }
    $remotePublished = ($remoteLine[0] -split '\s+')[0].Trim()
    if ($remotePublished -ne $localPublished) {
        throw "remote live-data verification mismatch: local=$localPublished remote=$remotePublished"
    }
    $RemoteManifestText = (@(
        & git -C $LiveDataRoot show "${remotePublished}:latest/manifest.json"
    ) -join [Environment]::NewLine)
    if ($LASTEXITCODE -ne 0) {
        throw "failed to read manifest from verified remote commit"
    }
    try {
        $RemoteManifest = $RemoteManifestText | ConvertFrom-Json
    } catch {
        throw "verified remote commit contains an invalid manifest"
    }
    if (
        $RemoteManifest.publication_id -ne $PublicationStatus.publication_id -or
        $RemoteManifest.observed_at -ne $PublicationStatus.observed_at
    ) {
        throw "remote manifest does not match the current hourly publication"
    }
    $RemoteManifestBlob = (& git -C $LiveDataRoot rev-parse "${remotePublished}:latest/manifest.json").Trim()
    if ($LASTEXITCODE -ne 0 -or $RemoteManifestBlob -notmatch '^[0-9a-f]{40,64}$') {
        throw "failed to resolve manifest blob from verified remote commit"
    }
    $LocalManifestPath = Join-Path $PublicationRoot "latest\manifest.json"
    $LocalManifestBlob = (& git -C $LiveDataRoot hash-object `
        --path=latest/manifest.json $LocalManifestPath).Trim()
    if ($LASTEXITCODE -ne 0 -or $LocalManifestBlob -ne $RemoteManifestBlob) {
        throw "local publication manifest bytes do not match the verified remote object"
    }
    # Count an hour only after the exact publication has passed runtime audit
    # and its remote SHA has been independently verified.
    $QualityOutput = Join-Path $PublicationRoot "monitoring\result_quality.json"
    & $Python -m trzip.result_quality --database $DatabasePath `
        --end $PublicationStatus.observed_at --count 8 --output $QualityOutput `
        --record-publication --publication-id $PublicationStatus.publication_id `
        --remote-sha $remotePublished `
        --intelligence (Join-Path $PublicationRoot "latest\intelligence.json") `
        --manifest $LocalManifestPath `
        --remote-manifest-blob $RemoteManifestBlob | Out-Null
    $QualityExitCode = $LASTEXITCODE
    if ($QualityExitCode -notin @(0,1)) {
        throw "result quality gate failed to execute; exit=$QualityExitCode"
    }
    $Quality = Get-Content -LiteralPath $QualityOutput -Raw -Encoding utf8 | ConvertFrom-Json
    $QualityStatus = if ($Quality.passed -eq $true) { "complete" } else { "in_progress" }
    $QualityDetail = "streak={0}/8 remaining={1}" -f `
        $Quality.current_consecutive_success_count,$Quality.remaining_success_hours
    Write-RunLog -Phase "result_quality" -Status $QualityStatus -Detail $QualityDetail
    Sync-PublicDirectory -Name "monitoring"
    & git -C $LiveDataRoot add -- monitoring
    & git -C $LiveDataRoot diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        & git -C $LiveDataRoot -c user.name="trzip-local-collector" `
            -c user.email="trzip-local-collector@users.noreply.github.com" `
            commit -m "data: record verified hourly result $commitStamp"
        if ($LASTEXITCODE -ne 0) { throw "failed to attach verified monitoring result" }
        & git -C $LiveDataRoot push origin "HEAD:refs/heads/live-data"
        if ($LASTEXITCODE -ne 0) { throw "failed to publish verified monitoring result" }
        $localPublished = (& git -C $LiveDataRoot rev-parse HEAD).Trim()
        $remotePublished = ((@(& git -C $LiveDataRoot ls-remote origin refs/heads/live-data))[0] -split '\s+')[0].Trim()
        if ($remotePublished -ne $localPublished) { throw "monitoring remote verification mismatch" }
    }
    $commit = (& git -C $LiveDataRoot rev-parse --short HEAD).Trim()
    Write-RunLog -Phase "publish" -Status "ok" -Detail "$commit remote_verified=true"
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

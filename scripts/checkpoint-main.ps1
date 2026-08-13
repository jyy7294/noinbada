param(
    [Parameter(Mandatory = $true)]
    [string[]]$IncludePath,
    [Parameter(Mandatory = $true)]
    [string]$Message,
    [Parameter(Mandatory = $true)]
    [string]$Objective,
    [string[]]$Completed = @(),
    [string[]]$NextAction = @(),
    [string[]]$Blocker = @(),
    [string[]]$KnownLimitation = @(),
    [switch]$SkipRuntimePromotion
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$StateRelative = "CURRENT_STATE.json"
$StatePath = Join-Path $ProjectRoot $StateRelative
$StateSchema = Join-Path $ProjectRoot "schemas\current-state-v1.schema.json"
$TemporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("trzip-checkpoint-" + [guid]::NewGuid().ToString("N"))
$Committed = $false
$StateExisted = Test-Path -LiteralPath $StatePath
$StateBefore = if ($StateExisted) { [IO.File]::ReadAllBytes($StatePath) } else { $null }

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& git -C $ProjectRoot @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return @($output | Where-Object { $_ -notmatch '^warning: in the working copy of ' })
}

function Normalize-RelativePath {
    param([string]$Value)
    $candidate = $Value.Trim().Replace("\", "/")
    if (-not $candidate -or $candidate -eq "." -or
        $candidate.IndexOfAny([char[]]"*?[]") -ge 0 -or
        [IO.Path]::IsPathRooted($candidate) -or $candidate.EndsWith("/")) {
        throw "Only explicit repository file paths are allowed: $Value"
    }
    $full = [IO.Path]::GetFullPath((Join-Path $ProjectRoot $candidate))
    $prefix = $ProjectRoot.TrimEnd("\") + "\"
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes the repository: $Value"
    }
    if (Test-Path -LiteralPath $full -PathType Container) {
        throw "Directory-wide checkpoint paths are forbidden: $Value"
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        & git -C $ProjectRoot ls-files --error-unmatch -- $candidate 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Checkpoint path does not exist and is not tracked: $Value" }
    }
    return $candidate
}

function Get-DirtyPaths {
    $paths = @(
        @(Invoke-Git diff --name-only)
        @(Invoke-Git ls-files --others --exclude-standard)
    ) | ForEach-Object { ([string]$_).Trim().Replace("\", "/") } |
        Where-Object { $_ } | Sort-Object -Unique
    return @($paths)
}

function Add-GitPathsInBatches {
    param(
        [Parameter(Mandatory = $true)][string[]]$Paths,
        [int]$BatchSize = 40
    )
    if ($BatchSize -lt 1) { throw "BatchSize must be positive." }
    for ($offset = 0; $offset -lt $Paths.Count; $offset += $BatchSize) {
        $last = [Math]::Min($offset + $BatchSize - 1, $Paths.Count - 1)
        $batch = @($Paths[$offset..$last])
        Invoke-Git add -- @batch | Out-Null
    }
}

function Restore-GitPathsInBatches {
    param(
        [Parameter(Mandatory = $true)][string[]]$Paths,
        [int]$BatchSize = 40
    )
    if ($BatchSize -lt 1) { throw "BatchSize must be positive." }
    for ($offset = 0; $offset -lt $Paths.Count; $offset += $BatchSize) {
        $last = [Math]::Min($offset + $BatchSize - 1, $Paths.Count - 1)
        $batch = @($Paths[$offset..$last])
        & git -C $ProjectRoot restore --staged -- @batch 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not restore the staged checkpoint batch."
        }
    }
}

function Assert-OnlyAllowedDirtyPaths {
    param([string[]]$Allowed)
    $unexpected = @(Get-DirtyPaths | Where-Object { $_ -notin $Allowed })
    if ($unexpected.Count -gt 0) {
        throw "Unrelated working-tree changes exist: $($unexpected -join ', ')"
    }
}

function Test-ExportedTreeSecrets {
    param([string]$Root)
    $secretPatterns = @(
        'tmcp_live_[A-Za-z0-9]{20,}',
        'github_pat_[A-Za-z0-9_]{40,}',
        'gho_[A-Za-z0-9]{30,}',
        'sk-[A-Za-z0-9]{32,}',
        'Bearer\s+[A-Za-z0-9._-]{24,}'
    )
    $localPathPattern = '(?i)[A-Za-z]:[\\/]+Users[\\/]+lch68(?:[\\/]|$)'
    $extensions = @('.py', '.ps1', '.md', '.json', '.js', '.html', '.toml', '.txt', '.yml', '.yaml')
    foreach ($file in Get-ChildItem -LiteralPath $Root -Recurse -File) {
        if ($file.Extension.ToLowerInvariant() -notin $extensions -and $file.Name -notin @('.env.example', '.gitignore', '.gitattributes', '.editorconfig')) {
            continue
        }
        $text = [IO.File]::ReadAllText($file.FullName)
        foreach ($pattern in $secretPatterns) {
            if ($text -match $pattern) { throw "Secret-like value found in staged tree: $($file.Name)" }
        }
        if ($text -match $localPathPattern) {
            throw "User-specific absolute path found in staged tree: $($file.Name)"
        }
    }
}

try {
    if (-not (Test-Path -LiteralPath $Python)) { throw "Repository Python environment is missing." }
    if (([string](Invoke-Git branch --show-current)).Trim() -ne "main") {
        throw "Verified checkpoints must start on main."
    }
    $existingStaged = @(Invoke-Git diff --cached --name-only)
    if ($existingStaged.Count -gt 0) { throw "The index already contains staged files." }

    $normalized = @($IncludePath | ForEach-Object { Normalize-RelativePath $_ } | Sort-Object -Unique)
    if ($normalized.Count -eq 0) { throw "At least one explicit checkpoint path is required." }
    $allowed = @($normalized + $StateRelative | Sort-Object -Unique)
    Assert-OnlyAllowedDirtyPaths -Allowed $allowed

    Invoke-Git fetch origin "+refs/heads/main:refs/remotes/origin/main" --quiet | Out-Null
    $baseSha = ([string](Invoke-Git rev-parse HEAD)).Trim()
    $remoteBaseSha = ([string](Invoke-Git rev-parse origin/main)).Trim()
    if ($baseSha -ne $remoteBaseSha) {
        throw "Local main is not equal to origin/main. Integrate the remote change and revalidate."
    }

    # Windows limits native-process command-line length. Generated delivery
    # bundles can contain hundreds of explicit files, so preserve the strict
    # allowlist while staging it in bounded batches.
    Add-GitPathsInBatches -Paths $normalized
    # Do not let rename detection hide the deleted side of a regenerated
    # immutable bundle; every requested path must be accounted for explicitly.
    $staged = @(Invoke-Git diff --cached --no-renames --name-only | ForEach-Object { $_.Trim().Replace("\", "/") })
    $missing = @($normalized | Where-Object { $_ -notin $staged -and $_ -ne $StateRelative })
    if ($missing.Count -gt 0) { throw "Requested paths had no staged change: $($missing -join ', ')" }

    New-Item -ItemType Directory -Path $TemporaryRoot | Out-Null
    $exportPrefix = $TemporaryRoot.TrimEnd("\") + "\"
    Invoke-Git checkout-index --all --force "--prefix=$exportPrefix" | Out-Null

    Push-Location $TemporaryRoot
    try {
        $pytestOutput = @(& $Python -m pytest -q 2>&1)
        if ($LASTEXITCODE -ne 0) { throw "pytest failed: $($pytestOutput -join [Environment]::NewLine)" }
        $pytestSummaries = @(
            $pytestOutput | Where-Object { [string]$_ -match '^\s*\d+\s+passed(?:\s|,|$)' }
        )
        if ($pytestSummaries.Count -eq 0) { throw "Could not read the pytest pass count." }
        $pytestSummary = [string]$pytestSummaries[-1]
        if ($pytestSummary -notmatch '^\s*(\d+)\s+passed(?:\s|,|$)') {
            throw "Could not read the final pytest pass count."
        }
        $pytestCount = [int]$Matches[1]

        & $Python -m compileall -q src tests
        if ($LASTEXITCODE -ne 0) { throw "Python compileall failed." }

        foreach ($script in Get-ChildItem -LiteralPath (Join-Path $TemporaryRoot "scripts") -Filter "*.ps1" -File) {
            $tokens = $null
            $parseErrors = $null
            [System.Management.Automation.Language.Parser]::ParseFile(
                $script.FullName, [ref]$tokens, [ref]$parseErrors
            ) | Out-Null
            if ($parseErrors.Count -gt 0) {
                throw "PowerShell parse failed for $($script.Name): $($parseErrors[0].Message)"
            }
        }
        Test-ExportedTreeSecrets -Root $TemporaryRoot
    } finally {
        Pop-Location
    }

    & git -C $ProjectRoot diff --cached --check
    if ($LASTEXITCODE -ne 0) { throw "Staged diff check failed." }

    $digests = [ordered]@{}
    foreach ($path in $normalized) {
        if ($path -eq $StateRelative) { continue }
        $exported = Join-Path $TemporaryRoot $path
        $digests[$path] = if (Test-Path -LiteralPath $exported -PathType Leaf) {
            (Get-FileHash -LiteralPath $exported -Algorithm SHA256).Hash.ToLowerInvariant()
        } else {
            "deleted"
        }
    }
    $changedPaths = @($normalized + $StateRelative | Sort-Object -Unique)
    $state = [ordered]@{
        schema_version = "trzip-current-state-v1"
        updated_at = [DateTimeOffset]::UtcNow.ToString("o")
        project = [ordered]@{
            repository = "jyy7294/noinbada"
            code_branch = "main"
            data_branch = "live-data"
        }
        checkpoint = [ordered]@{
            describes_commit = "self"
            base_remote_main_sha = $baseSha
            validation_target = "staged_tree"
            changed_paths = $changedPaths
            changed_file_digests = $digests
            commit_message = $Message
            validation_status = "passed"
        }
        validation = [ordered]@{
            pytest = [ordered]@{ status = "passed"; count = $pytestCount }
            compileall = [ordered]@{ status = "passed" }
            powershell_parse = [ordered]@{ status = "passed" }
            diff_check = [ordered]@{ status = "passed" }
            secret_scan = [ordered]@{ status = "passed" }
            local_path_scan = [ordered]@{ status = "passed" }
            state_schema = [ordered]@{ status = "passed" }
        }
        handoff = [ordered]@{
            objective = $Objective
            completed = @($Completed)
            next_actions = @($NextAction)
            blockers = @($Blocker)
            known_limitations = @($KnownLimitation)
        }
        runtime_contract = [ordered]@{
            checkout = "%USERPROFILE%\Documents\Codex\noinbada-runtime"
            runtime_root = "%LOCALAPPDATA%\TRZIP"
            scheduler = "codex_hourly_automation"
            required_branch = "main"
        }
        live_state_pointer = [ordered]@{
            branch = "live-data"
            status_file = "latest/status.json"
            run_history_file = "monitoring/run_history.json"
        }
    }
    [IO.File]::WriteAllText(
        $StatePath,
        (($state | ConvertTo-Json -Depth 12) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
    Invoke-Git add -- $StateRelative | Out-Null
    & $Python -c "import json,sys,jsonschema; jsonschema.Draft202012Validator(json.load(open(sys.argv[2],encoding='utf-8'))).validate(json.load(open(sys.argv[1],encoding='utf-8')))" $StatePath $StateSchema
    if ($LASTEXITCODE -ne 0) { throw "CURRENT_STATE schema validation failed." }
    & git -C $ProjectRoot diff --cached --check
    if ($LASTEXITCODE -ne 0) { throw "Final staged diff check failed." }
    Assert-OnlyAllowedDirtyPaths -Allowed $allowed

    $remoteLine = @(& git -C $ProjectRoot ls-remote origin refs/heads/main)
    if ($LASTEXITCODE -ne 0 -or $remoteLine.Count -ne 1) { throw "Cannot verify remote main." }
    $remoteNow = ($remoteLine[0] -split '\s+')[0].Trim()
    if ($remoteNow -ne $remoteBaseSha) {
        throw "origin/main changed during validation. Review and re-run the full checkpoint."
    }

    Invoke-Git commit -m $Message | Out-Null
    $Committed = $true
    $localSha = ([string](Invoke-Git rev-parse HEAD)).Trim()
    Invoke-Git push origin "HEAD:refs/heads/main" | Out-Null
    $publishedLine = @(& git -C $ProjectRoot ls-remote origin refs/heads/main)
    if ($LASTEXITCODE -ne 0 -or $publishedLine.Count -ne 1) { throw "Cannot verify pushed main." }
    $publishedSha = ($publishedLine[0] -split '\s+')[0].Trim()
    if ($publishedSha -ne $localSha) { throw "Remote main SHA does not match the local checkpoint." }

    $promotion = $null
    if (-not $SkipRuntimePromotion) {
        $promotion = & (Join-Path $PSScriptRoot "promote-runtime.ps1") -ExpectedSha $localSha
        if ($LASTEXITCODE -ne 0) { throw "Code is on main, but runtime promotion failed." }
    }
    [ordered]@{
        status = "published"
        main_sha = $localSha
        remote_verified = $true
        tests_passed = $pytestCount
        runtime_promotion = if ($SkipRuntimePromotion) { "skipped" } else { "verified" }
        promotion_detail = $promotion
    } | ConvertTo-Json -Depth 6
} catch {
    $originalError = $_
    if (-not $Committed) {
        # Rename detection can collapse a generated bundle replacement into
        # fewer paths. Re-read the index until both additions and the formerly
        # paired deletions are fully unstaged.
        while ($true) {
            $actualStaged = @(& git -C $ProjectRoot diff --cached --no-renames --name-only 2>$null)
            if ($actualStaged.Count -eq 0) { break }
            Restore-GitPathsInBatches -Paths $actualStaged
        }
        if ($StateExisted) {
            [IO.File]::WriteAllBytes($StatePath, $StateBefore)
        } elseif (Test-Path -LiteralPath $StatePath) {
            Remove-Item -LiteralPath $StatePath -Force
        }
    }
    throw $originalError
} finally {
    if (Test-Path -LiteralPath $TemporaryRoot) {
        $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd("\") + "\"
        $resolvedTemporary = [IO.Path]::GetFullPath($TemporaryRoot).TrimEnd("\") + "\"
        if ($resolvedTemporary.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $TemporaryRoot -Recurse -Force
        }
    }
}

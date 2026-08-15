[CmdletBinding()]
param(
    [double]$DurationHours = 24,
    [int]$IntervalSeconds = 60,
    [string]$BaseUrl = 'http://127.0.0.1:8765',
    [string]$SessionToken = '',
    [string]$OutputDir = 'output\verification\LLMWIKI-013\soak',
    [string]$SqlitePath = '',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputDir)) { [System.IO.Path]::GetFullPath($OutputDir) } else { [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDir)) }
$allowedRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'output\verification\LLMWIKI-013'))
if (-not $resolvedOutput.StartsWith($allowedRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) { Write-Error 'OUTPUT_DIR_OUTSIDE_LLMWIKI_013'; exit 2 }
if ($DurationHours -le 0 -or $IntervalSeconds -le 0) { Write-Error 'INVALID_SOAK_DURATION_OR_INTERVAL'; exit 2 }
if ($Force -and $DurationHours -ge 24) { Write-Error 'SOAK_FORCE_IS_DEBUG_ONLY'; exit 2 }
if ((Test-Path -LiteralPath $resolvedOutput) -and -not $Force) {
    $existing = @(Get-ChildItem -LiteralPath $resolvedOutput -Force -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0) { Write-Error 'OUTPUT_DIR_NOT_EMPTY_USE_FORCE_FOR_DEBUG_ONLY'; exit 2 }
}

$BaseUrl = $BaseUrl.TrimEnd('/')
$token = if ($SessionToken) { $SessionToken } elseif ($env:AGENT_PET_SESSION_TOKEN) { $env:AGENT_PET_SESSION_TOKEN } else { '' }
$headers = if ($token) { @{ Authorization = "Bearer $token"; Accept = 'application/json' } } else { @{ Accept = 'application/json' } }
$resolvedSqlite = if ($SqlitePath) { [System.IO.Path]::GetFullPath($SqlitePath) } elseif ($env:AGENT_PET_SQLITE_PATH) { [System.IO.Path]::GetFullPath($env:AGENT_PET_SQLITE_PATH) } else { '' }
$python = Get-Command python -ErrorAction SilentlyContinue
try {
    $baseUri = [Uri]$BaseUrl
    $backendPort = $baseUri.Port
}
catch {
    Write-Error 'INVALID_SOAK_BASE_URL'
    exit 2
}

function Write-JsonLine {
    param([Parameter(Mandatory = $true)][object]$Value)
    Add-Content -LiteralPath (Join-Path $resolvedOutput 'samples.jsonl') -Value ($Value | ConvertTo-Json -Compress -Depth 10) -Encoding UTF8
}

function Invoke-Json {
    param([Parameter(Mandatory = $true)][string]$Path)
    return Invoke-RestMethod -Method Get -Uri "$BaseUrl$Path" -Headers $headers -TimeoutSec ([Math]::Max(5, $IntervalSeconds))
}

function Get-SidecarProcess {
    $connection = Get-NetTCPConnection -LocalPort $backendPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $connection) { return $null }
    return Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
}

function Test-InteractiveLogin {
    $sessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
    if ($sessionId -le 0) { return $false }
    return $null -ne (Get-Process -Name explorer -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -eq $sessionId } | Select-Object -First 1)
}

function Invoke-DatabaseSnapshot {
    param([Parameter(Mandatory = $true)][string]$Since)
    if ($null -eq $python) { throw 'SOAK_PYTHON_NOT_FOUND' }
    Push-Location (Join-Path $repoRoot 'apps\backend')
    try {
        $raw = & $python.Source -m app.evals.soak_snapshot --database $resolvedSqlite --since $Since 2>&1
        if ($LASTEXITCODE -ne 0) { throw "SOAK_SQLITE_SNAPSHOT_FAILED:$($raw -join ' ')" }
        $line = @($raw | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) | Select-Object -Last 1
        if ($null -eq $line) { throw 'SOAK_SQLITE_SNAPSHOT_EMPTY' }
        return ($line | ConvertFrom-Json)
    }
    finally { Pop-Location }
}

if (-not $token) {
    [Console]::Error.WriteLine('SOAK_SESSION_TOKEN_REQUIRED')
    exit 2
}
if (-not $resolvedSqlite -or -not (Test-Path -LiteralPath $resolvedSqlite -PathType Leaf)) {
    [Console]::Error.WriteLine('SOAK_SQLITE_BACKUP_PREREQUISITE_MISSING')
    exit 2
}
if ($null -eq $python) {
    [Console]::Error.WriteLine('SOAK_PYTHON_NOT_FOUND')
    exit 2
}
if (-not (Test-InteractiveLogin)) {
    [Console]::Error.WriteLine('SOAK_INTERACTIVE_LOGIN_REQUIRED')
    exit 2
}

try {
    New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null
    if ($Force) {
        foreach ($name in @('samples.jsonl', 'soak-report.json', 'soak-report.md', 'database-pre-soak.sqlite3')) {
            $path = Join-Path $resolvedOutput $name
            if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force }
        }
    }

    try { $health = Invoke-Json '/api/health' } catch { throw 'SOAK_PREREQUISITE:SOAK_HEALTH_NOT_AVAILABLE' }
    if ($health.status -notin @('ok', 'degraded')) { throw 'SOAK_PREREQUISITE:SOAK_HEALTH_NOT_AVAILABLE' }
    try { $diagnostics = Invoke-Json '/api/diagnostics/export' } catch { throw 'SOAK_PREREQUISITE:SOAK_DIAGNOSTICS_NOT_AVAILABLE' }
    if ($diagnostics.database.reachable -ne $true -or $diagnostics.database.quick_check -ne 'ok') { throw 'SOAK_PREREQUISITE:SOAK_DATABASE_NOT_HEALTHY' }
    $process = Get-SidecarProcess
    if ($null -eq $process) { throw 'SOAK_PREREQUISITE:SOAK_SIDECAR_IDENTITY_NOT_FOUND' }

    $backupPath = Join-Path $resolvedOutput 'database-pre-soak.sqlite3'
    Push-Location (Join-Path $repoRoot 'apps\backend')
    try {
        & $python.Source -c "from app.services.memory_graph_migration import backup_sqlite_database; backup_sqlite_database(r'$resolvedSqlite', r'$backupPath')"
        if ($LASTEXITCODE -ne 0) { throw 'SOAK_PREREQUISITE:SOAK_DATABASE_BACKUP_FAILED' }
    }
    finally { Pop-Location }

    $samplesPath = Join-Path $resolvedOutput 'samples.jsonl'
    if (Test-Path -LiteralPath $samplesPath) { Remove-Item -LiteralPath $samplesPath -Force }
    $started = Get-Date
    $deadline = $started.AddHours($DurationHours)
    $since = $started.ToUniversalTime().ToString('o')
    $initialPid = [int]$process.Id
    $lastPid = $initialPid
    $restartCount = 0
    $healthFailures = 0
    $sampleCount = 0
    $readyCount = 0
    $unreadySince = $null
    $lastSampleAt = $started
    while ((Get-Date) -lt $deadline) {
        $sampleAt = Get-Date
        try {
            $health = Invoke-Json '/api/health'
            $diagnostics = Invoke-Json '/api/diagnostics/export'
            $impact = $null
            try { $impact = Invoke-Json '/api/metrics/local-impact?window_days=7' } catch { $impact = $null }
            $currentProcess = Get-SidecarProcess
            $currentPid = if ($null -ne $currentProcess) { [int]$currentProcess.Id } else { $null }
            $newRecoveryDurations = @()
            $pidChanged = $null -ne $currentPid -and $currentPid -ne $lastPid
            if ($pidChanged) {
                $restartCount++
                if ($null -eq $unreadySince) {
                    $restartRecovery = [Math]::Max(0, ($sampleAt - $lastSampleAt).TotalSeconds)
                    $newRecoveryDurations += $restartRecovery
                }
                $lastPid = $currentPid
            }
            $snapshot = Invoke-DatabaseSnapshot -Since $since
            $isReady = $health.status -eq 'ok' -and $diagnostics.database.quick_check -eq 'ok' -and $null -ne $currentProcess
            if (-not $isReady) {
                if ($null -eq $unreadySince) { $unreadySince = $sampleAt }
                $healthFailures++
            }
            elseif ($null -ne $unreadySince) {
                $duration = ($sampleAt - $unreadySince).TotalSeconds
                $newRecoveryDurations += $duration
                $unreadySince = $null
            }
            $sample = [ordered]@{
                timestamp = $sampleAt.ToUniversalTime().ToString('o')
                health = $health.status
                ready = $isReady
                sidecar_pid = $currentPid
                restart_count = $restartCount
                memory_bytes = if ($null -ne $currentProcess) { [int64]$currentProcess.WorkingSet64 } else { $null }
                handle_count = if ($null -ne $currentProcess) { [int]$currentProcess.HandleCount } else { $null }
                cpu_seconds = if ($null -ne $currentProcess) { [double]$currentProcess.CPU } else { $null }
                database_quick_check = $diagnostics.database.quick_check
                metric_sample_size = if ($null -ne $impact) { $impact.sample_size } else { $null }
                metric_evidence_status = if ($null -ne $impact) { $impact.evidence_status } else { 'unavailable' }
                sqlite_snapshot = $snapshot
                recovery_durations_seconds = $newRecoveryDurations
            }
            Write-JsonLine $sample
            $sampleCount++
            if ($isReady) { $readyCount++ }
            $lastSampleAt = $sampleAt
        }
        catch {
            $healthFailures++
            if ($null -eq $unreadySince) { $unreadySince = $sampleAt }
            $sample = [ordered]@{
                timestamp = $sampleAt.ToUniversalTime().ToString('o')
                health = 'error'
                ready = $false
                error_code = 'probe_failed'
                restart_count = $restartCount
                sqlite_snapshot = $null
                recovery_durations_seconds = @()
            }
            Write-JsonLine $sample
            $sampleCount++
            $lastSampleAt = $sampleAt
        }
        $remaining = ($deadline - (Get-Date)).TotalSeconds
        if ($remaining -gt 0) { Start-Sleep -Seconds ([Math]::Min($IntervalSeconds, [Math]::Ceiling($remaining))) }
    }

    $completed = Get-Date
    $durationSeconds = ($completed - $started).TotalSeconds
    $reportPath = Join-Path $resolvedOutput 'soak-report.json'
    Push-Location (Join-Path $repoRoot 'apps\backend')
    try {
        & $python.Source -m app.evals.soak_report --samples $samplesPath --duration-hours $DurationHours --interval-seconds $IntervalSeconds --observed-duration-seconds $durationSeconds --out $reportPath 2>&1 | Out-Null
    }
    finally { Pop-Location }
    $evaluatorExit = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) { throw 'SOAK_REPORT_GENERATION_FAILED' }
    $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $report | Add-Member -NotePropertyName health_failure_count -NotePropertyValue $healthFailures -Force
    $report | Add-Member -NotePropertyName restart_count -NotePropertyValue $restartCount -Force
    $report | Add-Member -NotePropertyName initial_sidecar_pid -NotePropertyValue $initialPid -Force
    $report | Add-Member -NotePropertyName database_backup_present -NotePropertyValue (Test-Path -LiteralPath $backupPath -PathType Leaf) -Force
    $report | Add-Member -NotePropertyName ready_sample_count -NotePropertyValue $readyCount -Force
    $report | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    $status = [string]$report.status
    @(
        '# Agent Pet soak report',
        '',
        "- status: **$status**",
        "- requested duration hours: $DurationHours",
        "- observed duration seconds: $([Math]::Round($durationSeconds, 2))",
        "- samples: $sampleCount",
        "- health failures: $healthFailures",
        "- ready ratio: $($report.ready_ratio)",
        "- recovery p95 seconds: $($report.recovery_p95_seconds)",
        "- generation lag p95 seconds: $($report.generation_lag_p95_seconds)",
        "- RSS growth percent: $($report.resource_growth_percent.memory_bytes)",
        "- handle growth percent: $($report.resource_growth_percent.handle_count)",
        "- evidence status: $($report.evidence_status)",
        '',
        'A short debug window is mechanism evidence only and cannot substitute for a real 24-hour record.',
        '',
        'Threshold details:',
        (($report.checks | ConvertTo-Json -Depth 12))
    ) | Set-Content -LiteralPath (Join-Path $resolvedOutput 'soak-report.md') -Encoding UTF8
    if ($evaluatorExit -ne 0 -and $status -notin @('debug_failed', 'failed')) { exit 1 }
    if ($status -in @('passed', 'debug_passed')) { exit 0 }
    exit 1
}
catch {
    Write-Error $_.Exception.Message
    if ([string]$_.Exception.Message -like 'SOAK_PREREQUISITE:*') { exit 2 }
    exit 1
}

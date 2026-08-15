[CmdletBinding()]
param(
    [string]$OutputDir = "output\verification\LLMWIKI-002",
    [int]$Port = 0,
    [ValidateRange(10, 120)][int]$StartupTimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "llmwiki-sidecar-harness.ps1")

$resolvedOutput = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDir))
$allowedOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "output"))
if (-not $resolvedOutput.StartsWith($allowedOutputRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must stay under the repository output directory."
}

function Assert-Journey {
    param([bool]$Condition, [string]$Code)
    if (-not $Condition) {
        throw $Code
    }
}

function Write-JsonEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][object]$Value
    )
    Write-LlmWikiUtf8NoBom -Path (Join-Path $resolvedOutput $Name) -Value (($Value | ConvertTo-Json -Depth 50) + "`n")
}

function ConvertFrom-Sse {
    param([AllowEmptyString()][string]$Raw)

    $events = [System.Collections.Generic.List[object]]::new()
    $eventName = ""
    foreach ($line in ($Raw -split "`r?`n")) {
        if ($line.StartsWith("event: ")) {
            $eventName = $line.Substring(7).Trim()
            continue
        }
        if (-not $line.StartsWith("data: ")) {
            continue
        }
        $payload = $null
        try {
            $payload = $line.Substring(6) | ConvertFrom-Json
        }
        catch {
            $payload = [ordered]@{ parse_error = "invalid_sse_json" }
        }
        $events.Add([ordered]@{ event = $eventName; data = $payload })
    }
    return @($events)
}

function Invoke-ActionApi {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST", "PUT")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body
    )
    return Invoke-LlmWikiApi -Method $Method -BaseUrl $baseUrl -SessionToken $sessionToken -Path $Path -Body $Body -TimeoutSeconds 45
}

function Invoke-ChatJourney {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Message
    )

    $accepted = Invoke-ActionApi -Method POST -Path "/api/chat" -Body ([ordered]@{ message = $Message })
    Assert-Journey ($accepted.status -eq 200 -and $null -ne $accepted.body) "CHAT_ACCEPT_FAILED_$Name"
    $stream = Invoke-ActionApi -Method GET -Path ([string]$accepted.body.stream_url)
    Assert-Journey ($stream.status -eq 200) "CHAT_STREAM_FAILED_$Name"
    $events = @(ConvertFrom-Sse -Raw ([string]$stream.raw))
    Assert-Journey (@($events | Where-Object { $_.event -eq "done" }).Count -eq 1) "CHAT_DONE_MISSING_$Name"
    $evidence = [ordered]@{
        conversation_id = [string]$accepted.body.conversation_id
        message_id = [string]$accepted.body.message_id
        agent_run_id = [string]$accepted.body.agent_run_id
        events = $events
    }
    Write-JsonEvidence -Name ("sse-{0}.json" -f $Name) -Value $evidence
    return $evidence
}

function Get-PendingCheckpoint {
    param([Parameter(Mandatory = $true)][string]$RunId)
    $pending = Invoke-ActionApi -Method GET -Path "/api/checkpoints/pending"
    Assert-Journey ($pending.status -eq 200) "CHECKPOINT_LIST_FAILED"
    $matches = @($pending.body | Where-Object { [string]$_.run_id -eq $RunId })
    Assert-Journey ($matches.Count -eq 1) "CHECKPOINT_COUNT_INVALID"
    return $matches[0]
}

function Quote-SqliteText {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Invoke-ReadOnlySqliteJson {
    param([Parameter(Mandatory = $true)][string]$Sql)

    $lines = @(& $sqliteCommand -readonly -json $databasePath $Sql 2>&1)
    Assert-Journey ($LASTEXITCODE -eq 0) "SQLITE_READ_FAILED"
    $raw = ($lines -join "`n").Trim()
    if (-not $raw) {
        return @()
    }
    return @($raw | ConvertFrom-Json)
}

function Get-CheckpointEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$CheckpointId
    )

    $quoted = Quote-SqliteText $CheckpointId
    $rows = @(Invoke-ReadOnlySqliteJson -Sql "SELECT checkpoint_id, run_id, status, action_proposal_id, idempotency_key, terminal_receipt_ref, state_json FROM agent_checkpoints WHERE checkpoint_id = $quoted;")
    Assert-Journey ($rows.Count -eq 1) "CHECKPOINT_ROW_MISSING_$Name"
    $state = [string]$rows[0].state_json | ConvertFrom-Json
    $evidence = [ordered]@{
        checkpoint_id = [string]$rows[0].checkpoint_id
        run_id = [string]$rows[0].run_id
        status = [string]$rows[0].status
        action_proposal_id = [string]$rows[0].action_proposal_id
        idempotency_key = [string]$rows[0].idempotency_key
        terminal_receipt_ref = if ($rows[0].terminal_receipt_ref) { [string]$rows[0].terminal_receipt_ref } else { $null }
        state = $state
    }
    Write-JsonEvidence -Name ("checkpoint-{0}.json" -f $Name) -Value $evidence
    return $evidence
}

function Get-ActionEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$IdempotencyKey
    )

    $quoted = Quote-SqliteText $IdempotencyKey
    $rows = @(Invoke-ReadOnlySqliteJson -Sql "SELECT id, action_type, status, idempotency_key, target_paths_json, metadata_json, error FROM agent_actions WHERE idempotency_key = $quoted ORDER BY rowid;")
    $actions = @(
        foreach ($row in $rows) {
            [ordered]@{
                id = [string]$row.id
                action_type = [string]$row.action_type
                status = [string]$row.status
                idempotency_key = [string]$row.idempotency_key
                target_paths = @([string]$row.target_paths_json | ConvertFrom-Json)
                metadata = [string]$row.metadata_json | ConvertFrom-Json
                error = if ($row.error) { [string]$row.error } else { $null }
            }
        }
    )
    $evidence = [ordered]@{ count = $actions.Count; actions = $actions }
    Write-JsonEvidence -Name ("actions-{0}.json" -f $Name) -Value $evidence
    return $evidence
}

function Invoke-CheckpointDecision {
    param(
        [Parameter(Mandatory = $true)][object]$Checkpoint,
        [Parameter(Mandatory = $true)][object]$StoredCheckpoint,
        [Parameter(Mandatory = $true)][ValidateSet("approved", "rejected")][string]$Decision
    )

    return Invoke-ActionApi -Method POST -Path ("/api/checkpoints/{0}/decision" -f [uri]::EscapeDataString([string]$Checkpoint.checkpoint_id)) -Body ([ordered]@{
        decision_id = [string]$Checkpoint.decision_id
        decision = $Decision
        policy_version = [string]$StoredCheckpoint.state.policy_decision.policy_version
    })
}

function Stop-And-CaptureSidecar {
    param(
        [System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($null -eq $Process) {
        return
    }
    Stop-LlmWikiIsolatedSidecar -Process $Process
    try {
        Write-LlmWikiUtf8NoBom -Path (Join-Path $resolvedOutput ("sidecar-{0}.stdout.log" -f $Label)) -Value (Read-LlmWikiSidecarLog -Process $Process -Stream stdout -AdditionalSecrets @($modelKey))
        Write-LlmWikiUtf8NoBom -Path (Join-Path $resolvedOutput ("sidecar-{0}.stderr.log" -f $Label)) -Value (Read-LlmWikiSidecarLog -Process $Process -Stream stderr -AdditionalSecrets @($modelKey))
    }
    finally {
        try { $Process.Dispose() } catch { }
    }
}

function Start-ModelStub {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][int]$Port
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Python
    $startInfo.Arguments = '"{0}" --host 127.0.0.1 --port {1}' -f (Join-Path $PSScriptRoot "llmwiki-model-stub.py"), $Port
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "MODEL_STUB_START_FAILED"
    }
    $process | Add-Member -NotePropertyName LlmWikiStdoutTask -NotePropertyValue ($process.StandardOutput.ReadToEndAsync()) -Force
    $process | Add-Member -NotePropertyName LlmWikiStderrTask -NotePropertyValue ($process.StandardError.ReadToEndAsync()) -Force
    return $process
}

function Wait-ModelStub {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [int]$TimeoutSeconds = 15
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri "$BaseUrl/health" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                return $true
            }
        }
        catch {
        }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

function Stop-And-CaptureModelStub {
    param([System.Diagnostics.Process]$Process)

    if ($null -eq $Process) {
        return
    }
    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        [void]$Process.WaitForExit(5000)
    }
    $stdout = if ($Process.LlmWikiStdoutTask) { [string]$Process.LlmWikiStdoutTask.GetAwaiter().GetResult() } else { "" }
    $stderr = if ($Process.LlmWikiStderrTask) { [string]$Process.LlmWikiStderrTask.GetAwaiter().GetResult() } else { "" }
    Write-LlmWikiUtf8NoBom -Path (Join-Path $resolvedOutput "model-stub.stdout.log") -Value $stdout
    Write-LlmWikiUtf8NoBom -Path (Join-Path $resolvedOutput "model-stub.stderr.log") -Value $stderr
    $Process.Dispose()
}

function ConvertTo-SanitizedHarnessLog {
    param([AllowEmptyCollection()][object[]]$Lines)

    $content = (@($Lines | ForEach-Object { [string]$_ }) -join "`n")
    $redactions = @(
        [ordered]@{ value = $resolvedOutput; replacement = "<action-output>" },
        [ordered]@{ value = $repoRoot; replacement = "<repo>" },
        [ordered]@{ value = [System.IO.Path]::GetTempPath().TrimEnd("\", "/"); replacement = "<temp>" },
        [ordered]@{ value = [Environment]::GetFolderPath("UserProfile"); replacement = "<user-profile>" }
    )
    foreach ($redaction in $redactions) {
        if ([string]::IsNullOrWhiteSpace([string]$redaction.value)) {
            continue
        }
        $content = $content -replace [regex]::Escape([string]$redaction.value), [string]$redaction.replacement
    }
    return $content.TrimEnd() + "`n"
}

function New-CrashRecoveryEvidence {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("Passed", "Failed", "Partial")][string]$Status,
        [Parameter(Mandatory = $true)][string]$ReasonCode,
        [Parameter(Mandatory = $true)][string]$ObservedState,
        [AllowNull()][object]$DuplicateEffects,
        [Parameter(Mandatory = $true)][int]$HarnessExitCode,
        [AllowNull()][object]$SourceReport,
        [AllowNull()][object]$SourceScenario,
        [Parameter(Mandatory = $true)][hashtable]$Checks
    )

    return [ordered]@{
        scenario = "effect_after_commit_before_receipt_recovery"
        source_scenario = "effect_after_claim_before_receipt"
        status = $Status
        reason_code = $ReasonCode
        observed_state = $ObservedState
        duplicate_effects = $DuplicateEffects
        evidence = @("fault-harness/backend-fault-scenarios.json", "fault-harness.log")
        details = [ordered]@{
            harness_exit_code = $HarnessExitCode
            source_schema_version = if ($null -ne $SourceReport) { [string]$SourceReport.schema_version } else { $null }
            source_report_status = if ($null -ne $SourceReport) { [string]$SourceReport.status } else { $null }
            source_status = if ($null -ne $SourceScenario) { [string]$SourceScenario.status } else { $null }
            source_reason_code = if ($null -ne $SourceScenario) { [string]$SourceScenario.reason_code } else { $null }
            strict_checks = $Checks
        }
    }
}

function Invoke-CrashRecoveryFaultHarness {
    param(
        [Parameter(Mandatory = $true)][string]$BackendDir,
        [Parameter(Mandatory = $true)][string]$OutputDir,
        [Parameter(Mandatory = $true)][string]$Python
    )

    $harnessDir = Join-Path $OutputDir "fault-harness"
    $reportPath = Join-Path $harnessDir "backend-fault-scenarios.json"
    $logPath = Join-Path $OutputDir "fault-harness.log"
    New-Item -ItemType Directory -Force -Path $harnessDir | Out-Null
    if (Test-Path -LiteralPath $reportPath -PathType Leaf) {
        Remove-Item -LiteralPath $reportPath -Force
    }

    $lines = @()
    $exitCode = 1
    Push-Location $BackendDir
    try {
        $lines = @(& $Python -m app.evals.llmwiki_fault_scenarios --output-dir $harnessDir 2>&1)
        $exitCode = $LASTEXITCODE
    }
    catch {
        $lines = @([string]$_.Exception.Message)
    }
    finally {
        Pop-Location
    }
    $logLines = @("exit_code=$exitCode") + $lines
    Write-LlmWikiUtf8NoBom -Path $logPath -Value (ConvertTo-SanitizedHarnessLog -Lines $logLines)

    $emptyChecks = @{
        source_schema_v1 = $false
        source_scenario_passed = $false
        child_exit_code_86 = $false
        receipt_verified = $false
        authoritative_state_recovered = $false
        same_receipt_on_retry = $false
        exactly_one_action_row = $false
        marker_count_one = $false
        duplicate_effects_zero = $false
        preferred_reason_code = $false
    }
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        return New-CrashRecoveryEvidence -Status "Partial" -ReasonCode "fault_harness_report_missing" -ObservedState "The subprocess fault harness did not produce a structured report." -DuplicateEffects $null -HarnessExitCode $exitCode -SourceReport $null -SourceScenario $null -Checks $emptyChecks
    }

    try {
        $sourceReport = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return New-CrashRecoveryEvidence -Status "Partial" -ReasonCode "fault_harness_report_malformed" -ObservedState "The subprocess fault harness report could not be parsed as JSON." -DuplicateEffects $null -HarnessExitCode $exitCode -SourceReport $null -SourceScenario $null -Checks $emptyChecks
    }

    $matches = @($sourceReport.scenarios | Where-Object { [string]$_.scenario -eq "effect_after_claim_before_receipt" })
    if ($matches.Count -ne 1) {
        $reasonCode = if ($matches.Count -eq 0) { "fault_harness_scenario_missing" } else { "fault_harness_scenario_ambiguous" }
        return New-CrashRecoveryEvidence -Status "Partial" -ReasonCode $reasonCode -ObservedState "The subprocess fault report did not contain exactly one target crash-recovery scenario." -DuplicateEffects $null -HarnessExitCode $exitCode -SourceReport $sourceReport -SourceScenario $null -Checks $emptyChecks
    }

    $sourceScenario = $matches[0]
    $observedState = [string]$sourceScenario.observed_state
    $duplicateEffects = $sourceScenario.duplicate_effects
    $checks = @{
        source_schema_v1 = [string]$sourceReport.schema_version -eq "llmwiki-fault-scenarios.v1"
        source_scenario_passed = [string]$sourceScenario.status -eq "Passed"
        child_exit_code_86 = [string]$sourceScenario.details.child_exit_code -eq "86"
        receipt_verified = [string]$sourceScenario.details.receipt.status -eq "verified"
        authoritative_state_recovered = (
            $sourceScenario.details.receipt.result.recovered_from_authoritative_state -is [bool] -and
            $sourceScenario.details.receipt.result.recovered_from_authoritative_state
        )
        same_receipt_on_retry = (
            $sourceScenario.details.same_receipt_on_retry -is [bool] -and
            $sourceScenario.details.same_receipt_on_retry
        )
        exactly_one_action_row = [regex]::IsMatch($observedState, "(?:^|,\s*)action_rows=1(?:\s*,|$)")
        marker_count_one = [string]$sourceScenario.details.receipt.result.marker_count -eq "1"
        duplicate_effects_zero = $null -ne $duplicateEffects -and [string]$duplicateEffects -eq "0"
        preferred_reason_code = [string]$sourceScenario.reason_code -eq "receipt_replayed_without_duplicate_effect"
    }
    $strictlyPassed = (
        $checks.source_schema_v1 -and
        $checks.source_scenario_passed -and
        $checks.child_exit_code_86 -and
        $checks.receipt_verified -and
        $checks.authoritative_state_recovered -and
        $checks.same_receipt_on_retry -and
        $checks.exactly_one_action_row -and
        $checks.marker_count_one -and
        $checks.duplicate_effects_zero
    )
    if ($strictlyPassed) {
        return New-CrashRecoveryEvidence -Status "Passed" -ReasonCode ([string]$sourceScenario.reason_code) -ObservedState $observedState -DuplicateEffects $duplicateEffects -HarnessExitCode $exitCode -SourceReport $sourceReport -SourceScenario $sourceScenario -Checks $checks
    }
    if ([string]$sourceScenario.status -eq "Failed") {
        $reasonCode = if ([string]::IsNullOrWhiteSpace([string]$sourceScenario.reason_code)) { "crash_recovery_scenario_failed" } else { [string]$sourceScenario.reason_code }
        return New-CrashRecoveryEvidence -Status "Failed" -ReasonCode $reasonCode -ObservedState $observedState -DuplicateEffects $duplicateEffects -HarnessExitCode $exitCode -SourceReport $sourceReport -SourceScenario $sourceScenario -Checks $checks
    }
    return New-CrashRecoveryEvidence -Status "Partial" -ReasonCode "crash_recovery_evidence_incomplete" -ObservedState $observedState -DuplicateEffects $duplicateEffects -HarnessExitCode $exitCode -SourceReport $sourceReport -SourceScenario $sourceScenario -Checks $checks
}

function Get-RelativeFileState {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $parts = $RelativePath.Replace("/", [System.IO.Path]::DirectorySeparatorChar)
    $path = Join-Path $vaultPath $parts
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return [ordered]@{ exists = $false; length = 0; sha256 = $null }
    }
    $item = Get-Item -LiteralPath $path
    return [ordered]@{
        exists = $true
        length = [int64]$item.Length
        sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$runtimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("agentpet-llmwiki-action-" + [Guid]::NewGuid().ToString("N"))
$backendDir = Join-Path $repoRoot "apps\backend"
$databasePath = Join-Path (Join-Path $runtimeRoot "data") "agent_pet_action_journey.sqlite3"
$vaultPath = Join-Path $runtimeRoot "vault"
$sessionToken = [Guid]::NewGuid().ToString("N")
$modelKey = [Guid]::NewGuid().ToString("N")
$sqliteCommand = (Get-Command sqlite3 -ErrorAction SilentlyContinue).Source
$pythonCommand = (Get-Command python -ErrorAction SilentlyContinue).Source
$selectedPort = if ($Port -gt 0) { $Port } else { New-LlmWikiIsolatedPort }
$modelPort = New-LlmWikiIsolatedPort
$baseUrl = "http://127.0.0.1`:$selectedPort"
$modelBaseUrl = "http://127.0.0.1`:$modelPort"
$sidecar = $null
$modelStub = $null
$startedAt = (Get-Date).ToUniversalTime().ToString("o")
$runnerError = $null
$report = $null

try {
    New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null
    Assert-Journey ([bool]$pythonCommand) "PYTHON_MISSING"
    Assert-Journey ([bool]$sqliteCommand) "SQLITE_CLI_MISSING"

    $modelStub = Start-ModelStub -Python $pythonCommand -Port $modelPort
    Assert-Journey (Wait-ModelStub -BaseUrl $modelBaseUrl) "MODEL_STUB_HEALTH_TIMEOUT"

    $sidecar = Start-LlmWikiIsolatedSidecar -BackendDir $backendDir -RuntimeRoot $runtimeRoot -SessionToken $sessionToken -Port $selectedPort -DatabaseFileName "agent_pet_action_journey.sqlite3" -Environment @{
        AGENT_PET_MODEL_BASE_URL = "$modelBaseUrl/v1"
        AGENT_PET_EMBEDDING_BASE_URL = "http://127.0.0.1:9/v1"
        AGENT_PET_MODEL_TIMEOUT_SECONDS = "30"
    }
    $health = Wait-LlmWikiHealth -BaseUrl $baseUrl -SessionToken $sessionToken -TimeoutSeconds $StartupTimeoutSeconds
    Assert-Journey ($null -ne $health) "SIDECAR_HEALTH_TIMEOUT"

    $vault = Invoke-ActionApi -Method POST -Path "/api/vaults/init" -Body ([ordered]@{
        path = $vaultPath
        create_if_missing = $true
        confirmed = $true
    })
    Assert-Journey ($vault.status -eq 200) "VAULT_INIT_FAILED"

    $modelConfig = Invoke-ActionApi -Method PUT -Path "/api/settings/model-config" -Body ([ordered]@{
        provider = "openai-compatible"
        base_url = "$modelBaseUrl/v1"
        model = "llmwiki-semantic-stub"
    })
    Assert-Journey ($modelConfig.status -eq 200) "MODEL_CONFIG_FAILED"
    $modelCredential = Invoke-ActionApi -Method PUT -Path "/api/settings/model-key" -Body ([ordered]@{
        provider = "openai-compatible"
        api_key = $modelKey
    })
    Assert-Journey ($modelCredential.status -eq 200) "MODEL_KEY_FAILED"

    $automation = Invoke-ActionApi -Method PUT -Path "/api/settings/automation" -Body ([ordered]@{
        auto_chat_diary = $false
        auto_structured_memory = $false
        auto_long_term_memory = $false
        auto_wiki_organize = $true
        local_privacy_mode = $false
        proactive_trigger_frequency = "off"
        use_negotiation = $false
        max_rounds = 5
    })
    Assert-Journey ($automation.status -eq 200 -and [bool]$automation.body.auto_wiki_organize) "AUTOMATION_CONFIG_FAILED"

    $rejectTarget = "Wiki/Action-L3-Reject.md"
    $rejectMessage = "Overwrite Markdown file $rejectTarget with rejected high-risk evidence."
    $rejectChat = Invoke-ChatJourney -Name "reject" -Message $rejectMessage
    $rejectCheckpoint = Get-PendingCheckpoint -RunId $rejectChat.agent_run_id
    $rejectStoredBefore = Get-CheckpointEvidence -Name "reject-before" -CheckpointId $rejectCheckpoint.checkpoint_id
    $rejectActionBefore = Get-ActionEvidence -Name "reject-before" -IdempotencyKey $rejectStoredBefore.idempotency_key
    $rejectFileBefore = Get-RelativeFileState -RelativePath $rejectTarget

    $rejectDecision = Invoke-CheckpointDecision -Checkpoint $rejectCheckpoint -StoredCheckpoint $rejectStoredBefore -Decision "rejected"
    Assert-Journey ($rejectDecision.status -eq 200) "REJECT_DECISION_HTTP_FAILED"
    $rejectStoredAfter = Get-CheckpointEvidence -Name "reject-after" -CheckpointId $rejectCheckpoint.checkpoint_id
    $rejectActionAfter = Get-ActionEvidence -Name "reject-after" -IdempotencyKey $rejectStoredBefore.idempotency_key
    $rejectFileAfter = Get-RelativeFileState -RelativePath $rejectTarget

    $approveTarget = "Wiki/Action-L3-Approve.md"
    $approveMessage = "Overwrite Markdown file $approveTarget with approved high-risk evidence."
    $approveChat = Invoke-ChatJourney -Name "approve" -Message $approveMessage
    $approveCheckpoint = Get-PendingCheckpoint -RunId $approveChat.agent_run_id
    $approveStoredBefore = Get-CheckpointEvidence -Name "approve-before" -CheckpointId $approveCheckpoint.checkpoint_id
    $approveActionBefore = Get-ActionEvidence -Name "approve-before" -IdempotencyKey $approveStoredBefore.idempotency_key
    $approveFileBefore = Get-RelativeFileState -RelativePath $approveTarget

    $approveDecision = Invoke-CheckpointDecision -Checkpoint $approveCheckpoint -StoredCheckpoint $approveStoredBefore -Decision "approved"
    Assert-Journey ($approveDecision.status -eq 200) "APPROVE_DECISION_HTTP_FAILED"
    $approveStoredAfter = Get-CheckpointEvidence -Name "approve-after" -CheckpointId $approveCheckpoint.checkpoint_id
    $approveActionAfter = Get-ActionEvidence -Name "approve-after" -IdempotencyKey $approveStoredBefore.idempotency_key
    $approveFileAfter = Get-RelativeFileState -RelativePath $approveTarget

    $replayBeforeRestart = Invoke-CheckpointDecision -Checkpoint $approveCheckpoint -StoredCheckpoint $approveStoredBefore -Decision "approved"
    Assert-Journey ($replayBeforeRestart.status -eq 200) "APPROVE_REPLAY_HTTP_FAILED"

    Stop-And-CaptureSidecar -Process $sidecar -Label "before-restart"
    $sidecar = $null
    $sidecar = Start-LlmWikiIsolatedSidecar -BackendDir $backendDir -RuntimeRoot $runtimeRoot -SessionToken $sessionToken -Port $selectedPort -DatabaseFileName "agent_pet_action_journey.sqlite3" -Environment @{
        AGENT_PET_MODEL_BASE_URL = "$modelBaseUrl/v1"
        AGENT_PET_EMBEDDING_BASE_URL = "http://127.0.0.1:9/v1"
        AGENT_PET_MODEL_TIMEOUT_SECONDS = "30"
    }
    $restartHealth = Wait-LlmWikiHealth -BaseUrl $baseUrl -SessionToken $sessionToken -TimeoutSeconds $StartupTimeoutSeconds
    Assert-Journey ($null -ne $restartHealth) "SIDECAR_RESTART_HEALTH_TIMEOUT"
    $replayAfterRestart = Invoke-CheckpointDecision -Checkpoint $approveCheckpoint -StoredCheckpoint $approveStoredBefore -Decision "approved"
    Assert-Journey ($replayAfterRestart.status -eq 200) "APPROVE_RESTART_REPLAY_HTTP_FAILED"
    $approveStoredRestarted = Get-CheckpointEvidence -Name "approve-restarted" -CheckpointId $approveCheckpoint.checkpoint_id
    $approveActionRestarted = Get-ActionEvidence -Name "approve-restarted" -IdempotencyKey $approveStoredBefore.idempotency_key
    $approveFileRestarted = Get-RelativeFileState -RelativePath $approveTarget

    $rejectProposal = $rejectStoredBefore.state.action_proposal
    $approveProposal = $approveStoredBefore.state.action_proposal
    $rejectOriginalPreserved = (
        [string]$rejectStoredBefore.state.user_message -eq $rejectMessage -and
        [string]$rejectProposal.action_type -eq "wiki.page.write" -and
        [string]$rejectProposal.target_ref -eq $rejectTarget -and
        [string]$rejectProposal.parameters.target_path -eq $rejectTarget -and
        [string]$rejectStoredBefore.state.policy_decision.canonical_parameters.target_path -eq $rejectTarget
    )
    $approveOriginalPreserved = (
        [string]$approveStoredBefore.state.user_message -eq $approveMessage -and
        [string]$approveProposal.action_type -eq "wiki.page.write" -and
        [string]$approveProposal.target_ref -eq $approveTarget -and
        [string]$approveProposal.parameters.target_path -eq $approveTarget -and
        [string]$approveStoredBefore.state.policy_decision.canonical_parameters.target_path -eq $approveTarget
    )
    $executableWikiTargetBound = (
        $approveOriginalPreserved -and $rejectOriginalPreserved
    )
    $rejectZeroEffect = (
        $rejectOriginalPreserved -and
        -not $rejectFileBefore.exists -and
        -not $rejectFileAfter.exists -and
        [string]$rejectDecision.body.status -eq "rejected" -and
        -not [bool]$rejectDecision.body.effect_applied -and
        [string]$rejectStoredAfter.status -eq "rejected" -and
        $rejectActionBefore.count -eq 1 -and
        $rejectActionAfter.count -eq 1
    )
    $approvedTargetExecutedOnce = (
        $approveOriginalPreserved -and
        -not $approveFileBefore.exists -and
        $approveFileAfter.exists -and
        $approveFileAfter.length -gt 0 -and
        $approveFileRestarted.exists -and
        [string]$approveFileAfter.sha256 -eq [string]$approveFileRestarted.sha256 -and
        [string]$approveDecision.body.status -eq "completed" -and
        [bool]$approveDecision.body.effect_applied -and
        [string]$approveStoredAfter.status -eq "completed" -and
        [string]$approveStoredAfter.terminal_receipt_ref -ne "" -and
        $approveActionBefore.count -eq 1 -and
        $approveActionAfter.count -eq 1 -and
        $approveActionRestarted.count -eq 1 -and
        [string]$approveActionAfter.actions[0].status -eq "completed" -and
        [string]$approveActionAfter.actions[0].metadata.execution_receipt.status -eq "verified" -and
        [string]$approveActionAfter.actions[0].metadata.execution_receipt.result.target_path -eq $approveTarget
    )
    $verifiedReceiptReplayed = (
        $approvedTargetExecutedOnce -and
        [string]$replayBeforeRestart.body.status -eq "completed" -and
        [string]$replayAfterRestart.body.status -eq "completed" -and
        -not [bool]$replayBeforeRestart.body.effect_applied -and
        -not [bool]$replayAfterRestart.body.effect_applied -and
        [string]$approveStoredAfter.terminal_receipt_ref -eq [string]$approveStoredRestarted.terminal_receipt_ref -and
        [string]$approveActionAfter.actions[0].metadata.execution_receipt.receipt_ref -eq [string]$approveActionRestarted.actions[0].metadata.execution_receipt.receipt_ref -and
        [string]$approveActionAfter.actions[0].metadata.execution_receipt.receipt_ref -eq [string]$approveStoredRestarted.terminal_receipt_ref
    )
    $crashRecoveryEvidence = Invoke-CrashRecoveryFaultHarness -BackendDir $backendDir -OutputDir $resolvedOutput -Python $pythonCommand

    $scenarios = @(
        [ordered]@{
            scenario = "checkpoint_preserves_original_request"
            status = if ($approveOriginalPreserved -and $rejectOriginalPreserved) { "Passed" } else { "Failed" }
            observed_state = "Both checkpoints retained the synthetic request text and immutable proposal/policy binding."
            duplicate_effects = 0
            evidence = @("checkpoint-approve-before.json", "checkpoint-reject-before.json")
        },
        [ordered]@{
            scenario = "reject_has_zero_wiki_effect"
            status = if ($rejectZeroEffect) { "Passed" } else { "Failed" }
            observed_state = "The real decision endpoint rejected the checkpoint and the requested Wiki path never existed."
            duplicate_effects = 0
            evidence = @("actions-reject-before.json", "actions-reject-after.json", "checkpoint-reject-after.json")
        },
        [ordered]@{
            scenario = "approve_executes_original_wiki_target_once"
            status = if ($approvedTargetExecutedOnce) { "Passed" } else { "Failed" }
            observed_state = "The configured semantic classifier bound the explicit Wiki target; approval wrote that path once and persisted a verified receipt."
            duplicate_effects = 0
            evidence = @("checkpoint-approve-before.json", "checkpoint-approve-after.json", "actions-approve-after.json")
        },
        [ordered]@{
            scenario = "restart_replays_original_verified_receipt"
            status = if ($verifiedReceiptReplayed) { "Passed" } else { "Failed" }
            observed_state = "Replays before and after sidecar restart returned the same terminal verified receipt without a second action row or file change."
            duplicate_effects = 0
            evidence = @("actions-approve-after.json", "actions-approve-restarted.json", "checkpoint-approve-restarted.json")
        },
        $crashRecoveryEvidence
    )
    $failed = @($scenarios | Where-Object { $_.status -eq "Failed" }).Count
    $partial = @($scenarios | Where-Object { $_.status -eq "Partial" }).Count
    $status = if ($failed -gt 0) { "Failed" } elseif ($partial -gt 0) { "Partial" } else { "Passed" }
    $exitCode = if ($failed -gt 0) { 1 } elseif ($partial -gt 0) { 2 } else { 0 }
    $report = [ordered]@{
        schema_version = "llmwiki-action-journey.v3"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        started_at = $startedAt
        status = $status
        verification_level = "L3"
        evidence_mode = "real_isolated_sidecar_authenticated_http_sse_read_only_sqlite_loopback_model_stub_and_subprocess_crash_harness"
        product_boundary = "Approval and restart replay are proven through the authenticated production API with a deterministic loopback OpenAI-compatible classifier, not a live external model. Post-effect, pre-receipt recovery is proven separately by a real subprocess crash through the production coordinator and WikiService; it is not an HTTP-triggered production crash."
        claims = [ordered]@{
            original_request_preserved = [bool]($approveOriginalPreserved -and $rejectOriginalPreserved)
            executable_wiki_target_bound = [bool]$executableWikiTargetBound
            reject_zero_effect = [bool]$rejectZeroEffect
            approved_target_executed_once = [bool]$approvedTargetExecutedOnce
            verified_receipt_replayed = [bool]$verifiedReceiptReplayed
            crash_window_recovered = [bool]($crashRecoveryEvidence.status -eq "Passed")
        }
        evidence_boundaries = @(
            "The API approval/replay journey and the subprocess crash-recovery harness are separate isolated executions.",
            "The crash harness invokes production coordinator and WikiService code directly; it does not expose a production fault-injection endpoint."
        )
        scenarios = $scenarios
        summary = [ordered]@{
            total = $scenarios.Count
            passed = @($scenarios | Where-Object { $_.status -eq "Passed" }).Count
            failed = $failed
            partial = $partial
        }
        prerequisites = [ordered]@{
            sidecar_started = $true
            sidecar_restarted = $true
            isolated_database = $true
            isolated_vault = $true
            model_provider_used = $true
            model_provider_mode = "loopback_openai_compatible_deterministic_stub"
            sqlite_opened_read_only = $true
            fault_harness_report_loaded = [bool]$crashRecoveryEvidence.details.strict_checks.source_schema_v1
            real_subprocess_crash_observed = [bool]$crashRecoveryEvidence.details.strict_checks.child_exit_code_86
        }
        cleanup = [ordered]@{ runtime_removed = $false; runtime_root_name = [System.IO.Path]::GetFileName($runtimeRoot) }
        exit_code = $exitCode
    }
}
catch {
    $runnerError = [string]$_.Exception.Message
    $report = [ordered]@{
        schema_version = "llmwiki-action-journey.v3"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        started_at = $startedAt
        status = "Failed"
        verification_level = "L3"
        evidence_mode = "real_isolated_sidecar_authenticated_http_sse_read_only_sqlite_loopback_model_stub_and_subprocess_crash_harness"
        runner_error = $runnerError
        scenarios = @()
        summary = [ordered]@{ total = 0; passed = 0; failed = 1; partial = 0 }
        cleanup = [ordered]@{ runtime_removed = $false; runtime_root_name = [System.IO.Path]::GetFileName($runtimeRoot) }
        exit_code = 1
    }
}
finally {
    if ($sidecar) {
        Stop-And-CaptureSidecar -Process $sidecar -Label "final"
    }
    if ($modelStub) {
        Stop-And-CaptureModelStub -Process $modelStub
    }
    if ($null -eq $report) {
        $report = [ordered]@{
            schema_version = "llmwiki-action-journey.v3"
            generated_at = (Get-Date).ToUniversalTime().ToString("o")
            status = "Failed"
            runner_error = "report_not_created"
            exit_code = 1
            cleanup = [ordered]@{ runtime_removed = $false; runtime_root_name = [System.IO.Path]::GetFileName($runtimeRoot) }
        }
    }
    try {
        $runtimeFull = [System.IO.Path]::GetFullPath($runtimeRoot)
        $tempFull = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        $runtimeName = [System.IO.Path]::GetFileName($runtimeFull)
        if ($runtimeFull.StartsWith($tempFull, [System.StringComparison]::OrdinalIgnoreCase) -and $runtimeName.StartsWith("agentpet-llmwiki-action-", [System.StringComparison]::OrdinalIgnoreCase)) {
            if (Test-Path -LiteralPath $runtimeFull) {
                Remove-Item -LiteralPath $runtimeFull -Recurse -Force
            }
            $report.cleanup.runtime_removed = -not (Test-Path -LiteralPath $runtimeFull)
        }
    }
    catch {
        $report.cleanup.runtime_removed = $false
    }
    Write-JsonEvidence -Name "action-journey-report.json" -Value $report
}

if ($runnerError) {
    [Console]::Error.WriteLine("ACTION_JOURNEY_FAILED: $runnerError")
}
exit [int]$report.exit_code

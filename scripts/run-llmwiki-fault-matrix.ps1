[CmdletBinding()]
param(
    [string]$OutputDir = "output\verification\LLMWIKI-013\faults",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 0,
    [int]$StartupTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
. (Join-Path $PSScriptRoot "llmwiki-sidecar-harness.ps1")
$resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    [System.IO.Path]::GetFullPath($OutputDir)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDir))
}
$allowedRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "output\verification\LLMWIKI-013"))
if (-not $resolvedOutput.StartsWith($allowedRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Error "OUTPUT_DIR_OUTSIDE_LLMWIKI_013"
    exit 2
}
if ($StartupTimeoutSeconds -lt 5 -or $StartupTimeoutSeconds -gt 300) {
    Write-Error "INVALID_STARTUP_TIMEOUT"
    exit 2
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Value
    )
    Write-LlmWikiUtf8NoBom -Path $Path -Value $Value
}

function Write-JsonReport {
    param([Parameter(Mandatory = $true)][object]$Value)
    Write-Utf8NoBom -Path (Join-Path $resolvedOutput "fault-matrix-report.json") -Value ($Value | ConvertTo-Json -Depth 30)
    $lines = @(
        "# LLM Wiki fault matrix",
        "",
        "- status: **$($Value.status)**",
        ("- runner: " + [string]$Value.schema_version),
        ("- evidence mode: " + [string]$Value.evidence_mode),
        "- passed: $($Value.summary.passed)",
        "- failed: $($Value.summary.failed)",
        "- partial: $($Value.summary.partial)",
        "",
        "| Scenario | Status | Observed state | Duplicate effects | Next step |",
        "| --- | --- | --- | ---: | --- |"
    )
    foreach ($item in @($Value.scenarios)) {
        $duplicate = if ($null -eq $item.duplicate_effects) { "not verified" } else { [string]$item.duplicate_effects }
        $nextStep = ([string]$item.user_next_step).Replace("|", "/")
        $observed = ([string]$item.observed_state).Replace("|", "/")
        $lines += "| $($item.scenario) | $($item.status) | $observed | $duplicate | $nextStep |"
    }
    $lines += "", "Partial means the current product has no safe public injection contract for that failure; it is not a pass.", ""
    Write-Utf8NoBom -Path (Join-Path $resolvedOutput "fault-matrix-report.md") -Value (($lines -join "`n") + "`n")
}

function New-ScenarioDefinitions {
    return @(
        [ordered]@{ scenario = "model_offline"; reason = "real_model_transport"; next = "Configure a local model or retry the model connection; no answer should be treated as durable evidence." },
        [ordered]@{ scenario = "no_evidence"; reason = "empty_memory_search"; next = "Show no evidence and ask the user to add or import a source." },
        [ordered]@{ scenario = "invalid_structured_output"; reason = "missing_model_fixture_hook"; next = "Add a bounded offline structured-output fault fixture before claiming this gate." },
        [ordered]@{ scenario = "relation_conflict"; reason = "missing_relation_conflict_fixture"; next = "Add two contradictory low-risk facts through the supported proposal path and keep both isolated." },
        [ordered]@{ scenario = "markdown_write_conflict"; reason = "missing_versioned_write_precondition"; next = "Expose an expected content hash or revision in the public write contract, then rerun." },
        [ordered]@{ scenario = "kuzu_missing_or_corrupt"; reason = "real_projection_fallback"; next = "Use SQLite fallback and rebuild the derived projection after the dependency or file is restored." },
        [ordered]@{ scenario = "sidecar_crash"; reason = "backend_restart_only"; next = "Verify the Electron supervisor, tray state and durable job recovery in a packaged Windows run." },
        [ordered]@{ scenario = "sleep_resume"; reason = "requires_os_sleep"; next = "Run the manual sleep and wake procedure; do not claim online time while the machine sleeps." },
        [ordered]@{ scenario = "notification_permission_denied"; reason = "requires_os_notification_permission"; next = "Deny Windows notification permission and verify a visible manual retry state." },
        [ordered]@{ scenario = "effect_after_claim_before_receipt"; reason = "missing_crash_boundary_hook"; next = "Inject a process stop after the real effect and before receipt persistence, then verify receipt replay." },
        [ordered]@{ scenario = "sensitive_content"; reason = "real_policy_rejection"; next = "Keep the content out of memory and Wiki; offer a redacted local alternative." },
        [ordered]@{ scenario = "prompt_injection_source"; reason = "missing_remote_call_audit_fixture"; next = "Run the import policy fixture and prove no unauthorized graph write or remote disclosure." },
        [ordered]@{ scenario = "model_timeout"; reason = "missing_provider_timeout_fixture"; next = "Run with a controlled timeout provider and prove bounded read-only retry." },
        [ordered]@{ scenario = "rate_limit"; reason = "missing_provider_rate_limit_fixture"; next = "Run with a controlled 429 provider and prove no write side effect." },
        [ordered]@{ scenario = "quota_exhausted"; reason = "missing_provider_quota_fixture"; next = "Run with a controlled quota response and keep the local browsing path available." },
        [ordered]@{ scenario = "user_cancel"; reason = "missing_cancel_transport_fixture"; next = "Cancel a partial SSE and prove the fragment does not enter memory, Wiki or a receipt." },
        [ordered]@{ scenario = "partial_sse"; reason = "missing_partial_sse_fixture"; next = "Drop an SSE stream at a deterministic boundary and verify recovery without duplicate effects." },
        [ordered]@{ scenario = "cross_vault_scope"; reason = "missing_two_vault_fixture"; next = "Bind two isolated Vaults and prove same-name entities never cross the active Vault boundary." }
    )
}

function New-PartialResult {
    param(
        [Parameter(Mandatory = $true)][string]$Scenario,
        [Parameter(Mandatory = $true)][string]$ReasonCode,
        [Parameter(Mandatory = $true)][string]$NextStep,
        [string]$Observed = "not_verified",
        [string]$InjectedAt = "not_run"
    )
    return [ordered]@{
        scenario = $Scenario
        status = "Partial"
        reason_code = $ReasonCode
        injected_at = $InjectedAt
        observed_at = (Get-Date).ToUniversalTime().ToString("o")
        observed_state = $Observed
        user_next_step = $NextStep
        duplicate_effects = $null
        evidence = @()
        exit_code = 2
    }
}

function New-FailedResult {
    param(
        [Parameter(Mandatory = $true)][string]$Scenario,
        [Parameter(Mandatory = $true)][string]$ReasonCode,
        [Parameter(Mandatory = $true)][string]$NextStep,
        [Parameter(Mandatory = $true)][string]$Observed,
        [string]$InjectedAt = "real_api"
    )
    return [ordered]@{
        scenario = $Scenario
        status = "Failed"
        reason_code = $ReasonCode
        injected_at = $InjectedAt
        observed_at = (Get-Date).ToUniversalTime().ToString("o")
        observed_state = $Observed
        user_next_step = $NextStep
        duplicate_effects = $null
        evidence = @()
        exit_code = 1
    }
}

function New-PassedResult {
    param(
        [Parameter(Mandatory = $true)][string]$Scenario,
        [Parameter(Mandatory = $true)][string]$Observed,
        [Parameter(Mandatory = $true)][string]$NextStep,
        [Parameter(Mandatory = $true)][string[]]$Evidence,
        [int]$DuplicateEffects = 0,
        [string]$InjectedAt = "real_api"
    )
    return [ordered]@{
        scenario = $Scenario
        status = "Passed"
        reason_code = "verified"
        injected_at = $InjectedAt
        observed_at = (Get-Date).ToUniversalTime().ToString("o")
        observed_state = $Observed
        user_next_step = $NextStep
        duplicate_effects = $DuplicateEffects
        evidence = $Evidence
        exit_code = 0
    }
}

function New-IsolatedPort {
    return New-LlmWikiIsolatedPort
}

function Get-JsonBody {
    param([string]$Text)
    return Get-LlmWikiJsonBody $Text
}

function Invoke-FaultApi {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST", "PUT", "PATCH", "DELETE")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body
    )
    $response = Invoke-LlmWikiApi -Method $Method -BaseUrl $baseUrl -SessionToken $sessionToken -Path $Path -Body $Body
    $result = [ordered]@{
        status = $response.status
        body = $response.body
        raw_length = ([string]$response.raw).Length
    }
    if ($response.error) {
        $result.error = $response.error
    }
    return $result
}

function Start-IsolatedSidecar {
    param(
        [Parameter(Mandatory = $true)][string]$BackendDir,
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [Parameter(Mandatory = $true)][string]$Token,
        [Parameter(Mandatory = $true)][int]$ListenPort
    )
    return Start-LlmWikiIsolatedSidecar -BackendDir $BackendDir -RuntimeRoot $RuntimeRoot -SessionToken $Token -Port $ListenPort -HostName $HostName -DatabaseFileName "agent_pet_fault_matrix.sqlite3" -Environment @{
        AGENT_PET_MODEL_BASE_URL = "http://127.0.0.1:9/v1"
        AGENT_PET_EMBEDDING_BASE_URL = "http://127.0.0.1:9/v1"
        AGENT_PET_MODEL_TIMEOUT_SECONDS = "2"
    }
}

function Stop-IsolatedSidecar {
    param(
        [System.Diagnostics.Process]$Process,
        [switch]$Dispose
    )
    Stop-LlmWikiIsolatedSidecar -Process $Process -Dispose:$Dispose
}

function Wait-Health {
    param([int]$TimeoutSeconds)
    return Wait-LlmWikiHealth -BaseUrl $baseUrl -SessionToken $sessionToken -TimeoutSeconds $TimeoutSeconds
}

function New-IdempotencyKey {
    return New-LlmWikiIdempotencyKey
}

function Get-ScenarioByName {
    param([object[]]$Definitions, [string]$Name)
    return $Definitions | Where-Object { $_.scenario -eq $Name } | Select-Object -First 1
}

function Add-BackendHarnessResults {
    param(
        [Parameter(Mandatory = $true)][string]$BackendDir,
        [Parameter(Mandatory = $true)][string]$OutputDir,
        [Parameter(Mandatory = $true)][System.Collections.Generic.List[object]]$Results
    )

    $scenarioNames = @(
        "invalid_structured_output",
        "relation_conflict",
        "prompt_injection_source",
        "effect_after_claim_before_receipt",
        "markdown_write_conflict",
        "cross_vault_scope",
        "model_timeout",
        "rate_limit",
        "quota_exhausted",
        "user_cancel",
        "partial_sse"
    )
    $harnessDir = Join-Path $OutputDir "backend-harness"
    New-Item -ItemType Directory -Force -Path $harnessDir | Out-Null
    $lines = @()
    $exitCode = 1
    Push-Location $BackendDir
    try {
        $lines = @(& python -m app.evals.llmwiki_fault_scenarios --output-dir $harnessDir 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    Write-Utf8NoBom -Path (Join-Path $OutputDir "backend-harness.log") -Value (($lines -join "`n") + "`n")

    $reportPath = Join-Path $harnessDir "backend-fault-scenarios.json"
    if ($exitCode -eq 0 -and (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($item in @($report.scenarios)) {
            $item | Add-Member -NotePropertyName observed_at -NotePropertyValue ((Get-Date).ToUniversalTime().ToString("o")) -Force
            $Results.Add($item)
        }
        return
    }

    $observed = if ($lines.Count -gt 0) {
        "backend fault harness exited $exitCode; inspect backend-harness.log"
    }
    else {
        "backend fault harness exited $exitCode without output"
    }
    foreach ($scenario in $scenarioNames) {
        $definition = Get-ScenarioByName -Definitions $scenarioDefinitions -Name $scenario
        $Results.Add((New-FailedResult -Scenario $scenario -ReasonCode "backend_fault_harness_failed" -NextStep $definition.next -Observed $observed -InjectedAt "backend_fault_harness"))
    }
}

$scenarioDefinitions = @(New-ScenarioDefinitions)
$scenarioResults = [System.Collections.Generic.List[object]]::new()
$runtimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("agentpet-llmwiki-fault-" + [Guid]::NewGuid().ToString("N"))
$sessionToken = [Guid]::NewGuid().ToString("N")
$backendDir = Join-Path $repoRoot "apps\backend"
$sidecar = $null
$sidecarStdout = ""
$sidecarStderr = ""
$baseUrl = ""
$startedAt = (Get-Date).ToUniversalTime().ToString("o")
$runnerFailureCode = ""
$runnerFailureTrace = ""

try {
    New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null
    $selectedPort = if ($Port -gt 0) { $Port } else { New-IsolatedPort }
    $baseUrl = "http://$HostName`:$selectedPort"
    $sidecar = Start-IsolatedSidecar -BackendDir $backendDir -RuntimeRoot $runtimeRoot -Token $sessionToken -ListenPort $selectedPort
    $health = Wait-Health -TimeoutSeconds $StartupTimeoutSeconds
    if ($null -eq $health) { throw "SIDECAR_HEALTH_TIMEOUT" }
    if ([string]$health.body.status -eq "degraded" -and [string]$health.body.database -ne "ok") { throw "SIDECAR_DATABASE_NOT_READY" }

    $vaultPath = Join-Path $runtimeRoot "vault"
    $vault = Invoke-FaultApi -Method POST -Path "/api/vaults/init" -Body ([ordered]@{ path = $vaultPath; create_if_missing = $true; confirmed = $true })
    if ($vault.status -ne 200) { throw "ISOLATED_VAULT_INIT_FAILED" }

    $noEvidenceQuery = "llmwiki-fault-no-evidence-$([Guid]::NewGuid().ToString('N'))"
    $emptySearch = Invoke-FaultApi -Method POST -Path "/api/memory/search" -Body ([ordered]@{ query = $noEvidenceQuery; top_k = 5; mode = "fts"; source_scope = "all" })
    if ($emptySearch.status -ne 200) {
        $scenarioResults.Add((New-FailedResult -Scenario "no_evidence" -ReasonCode "memory_search_http_error" -NextStep "Keep the no-evidence state visible and fix the search endpoint before release." -Observed "HTTP status $($emptySearch.status)" -InjectedAt "/api/memory/search"))
    }
    elseif (@($emptySearch.body.results).Count -ne 0) {
        $scenarioResults.Add((New-FailedResult -Scenario "no_evidence" -ReasonCode "unexpected_evidence" -NextStep "Prevent ungrounded results from entering the answer context." -Observed "returned $(@($emptySearch.body.results).Count) result(s)" -InjectedAt "/api/memory/search"))
    }
    else {
        $scenarioResults.Add((New-PassedResult -Scenario "no_evidence" -Observed "empty search returned zero evidence" -NextStep "Ask for a source or explicit memory before answering." -Evidence @("POST /api/memory/search", "isolated Vault", "unique query")))
    }

    $modelKey = Invoke-FaultApi -Method PUT -Path "/api/settings/model-key" -Body ([ordered]@{ provider = "openai-compatible"; api_key = "fault-matrix-synthetic-key" })
    $modelConfig = Invoke-FaultApi -Method PUT -Path "/api/settings/model-config" -Body ([ordered]@{ provider = "openai-compatible"; base_url = "http://127.0.0.1:9/v1"; model = "fault-matrix-unreachable" })
    if ($modelKey.status -eq 200 -and $modelConfig.status -eq 200) {
        $modelTest = Invoke-FaultApi -Method POST -Path "/api/settings/model-test" -Body ([ordered]@{})
        $modelError = if ($modelTest.body) { [string]$modelTest.body.error_code } else { "" }
        if ($modelTest.status -eq 200 -and [string]$modelTest.body.status -eq "failed" -and $modelError -in @("provider_unreachable", "provider_timeout", "model_invocation_failed")) {
            $scenarioResults.Add((New-PassedResult -Scenario "model_offline" -Observed "model-test returned a bounded offline error: $modelError" -NextStep "Use local search and retry the model connection; do not write a model failure into memory." -Evidence @("PUT /api/settings/model-config", "POST /api/settings/model-test", "closed loopback provider") -InjectedAt "/api/settings/model-test"))
        }
        elseif ($modelTest.status -eq 200) {
            $scenarioResults.Add((New-FailedResult -Scenario "model_offline" -ReasonCode "offline_error_not_classified" -NextStep "Return a stable offline state without claiming a generated answer." -Observed "model-test status $($modelTest.body.status), error $modelError" -InjectedAt "/api/settings/model-test"))
        }
        else {
            $scenarioResults.Add((New-FailedResult -Scenario "model_offline" -ReasonCode "model_test_http_error" -NextStep "Expose a safe retry state for an unavailable model." -Observed "HTTP status $($modelTest.status)" -InjectedAt "/api/settings/model-test"))
        }
    }
    else {
        $scenarioResults.Add((New-PartialResult -Scenario "model_offline" -ReasonCode "credential_store_unavailable" -NextStep "Run the offline provider probe in an environment with the local credential store available." -Observed "model configuration could not be isolated" -InjectedAt "/api/settings/model-config"))
    }

    # The endpoint requires an Idempotency-Key, so issue the request directly once
    # with a random key and keep the key out of the report.
    $rebuildParameters = @{
        Method = "POST"
        Uri = "$baseUrl/api/diagnostics/memory-graph/rebuild"
        Headers = @{ Authorization = "Bearer $sessionToken"; Accept = "application/json"; "Idempotency-Key" = (New-IdempotencyKey) }
        UseBasicParsing = $true
        TimeoutSec = 30
    }
    try {
        $rebuildResponse = Invoke-WebRequest @rebuildParameters
        $rebuild = [ordered]@{ status = [int]$rebuildResponse.StatusCode; body = Get-JsonBody $rebuildResponse.Content }
    }
    catch {
        $rebuild = [ordered]@{ status = 0; body = $null }
    }
    if ($rebuild.status -ne 200 -or $null -eq $rebuild.body) {
        $scenarioResults.Add((New-FailedResult -Scenario "kuzu_missing_or_corrupt" -ReasonCode "graph_rebuild_http_error" -NextStep "Keep SQLite graph reads available and expose a rebuild error with a retry action." -Observed "HTTP status $($rebuild.status)" -InjectedAt "/api/diagnostics/memory-graph/rebuild"))
    }
    else {
        $fallbackObserved = $false
        $fallbackEvidence = @("POST /api/diagnostics/memory-graph/rebuild")
        if ([bool]$rebuild.body.degraded -or [string]$rebuild.body.fallback_code) {
            $fallbackObserved = $true
            $fallbackEvidence += "real dependency fallback: $([string]$rebuild.body.fallback_code)"
        }
        else {
            $generationId = [string]$rebuild.body.generation_id
            if ($generationId -match "^[A-Za-z0-9_-]{1,120}$") {
                $projectionPath = [System.IO.Path]::GetFullPath((Join-Path (Join-Path (Join-Path $runtimeRoot "data") "memory-graph") "memory_graph.$generationId.kuzu"))
                $runtimeFull = [System.IO.Path]::GetFullPath($runtimeRoot)
                if ($projectionPath.StartsWith($runtimeFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $projectionPath -PathType Leaf)) {
                    Remove-Item -LiteralPath $projectionPath -Force
                    $fallbackEvidence += "isolated projection file removed"
                }
            }
        }
        $graph = Invoke-FaultApi -Method GET -Path "/api/memory/graph"
        # The public graph contract nests projection health under `generation`.
        # Read that authoritative response shape so the fault gate does not
        # mistake a healthy fallback for a missing observation.
        $generation = if ($graph.body) { $graph.body.generation } else { $null }
        if (
            $graph.status -eq 200 -and
            $null -ne $generation -and
            [bool]$graph.body.degraded_mode -and
            [string]$generation.backend -eq "sqlite" -and
            [string]$generation.status -eq "degraded" -and
            [string]$generation.fallback_code
        ) {
            $fallbackObserved = $true
            $fallbackEvidence += "GET /api/memory/graph reported SQLite fallback"
        }
        if ($fallbackObserved) {
            $scenarioResults.Add((New-PassedResult -Scenario "kuzu_missing_or_corrupt" -Observed "SQLite remained authoritative after projection degradation" -NextStep "Repair or rebuild the optional projection; keep degraded status visible." -Evidence $fallbackEvidence -InjectedAt "/api/memory/graph"))
        }
        else {
            $observedBackend = if ($null -ne $generation) { [string]$generation.backend } else { "missing_generation" }
            $observedFallback = if ($null -ne $generation) { [string]$generation.fallback_code } else { "missing_generation" }
            $scenarioResults.Add((New-FailedResult -Scenario "kuzu_missing_or_corrupt" -ReasonCode "sqlite_fallback_not_observed" -NextStep "Do not expose a healthy graph claim when the projection is unavailable." -Observed "backend $observedBackend, fallback $observedFallback" -InjectedAt "/api/memory/graph"))
        }
    }

    $beforeProposals = Invoke-FaultApi -Method GET -Path "/api/memory/proposals"
    $sensitive = Invoke-FaultApi -Method POST -Path "/api/memory/proposals" -Body ([ordered]@{ type = "preference"; content = "password=fault-matrix-synthetic-secret"; target_path = "Memories\LongTerm\fault-fixture.md" })
    $afterProposals = Invoke-FaultApi -Method GET -Path "/api/memory/proposals"
    $sensitiveCode = if ($sensitive.body) { [string]$sensitive.body.error.code } else { "" }
    $beforeCount = if ($beforeProposals.body) { @($beforeProposals.body.proposals).Count } else { -1 }
    $afterCount = if ($afterProposals.body) { @($afterProposals.body.proposals).Count } else { -1 }
    if ($sensitive.status -eq 422 -and $sensitiveCode -eq "sensitive_memory_rejected" -and $beforeCount -eq $afterCount) {
        $scenarioResults.Add((New-PassedResult -Scenario "sensitive_content" -Observed "credential-like proposal rejected and pending count unchanged" -NextStep "Keep sensitive text out of memory and offer a redacted local workflow." -Evidence @("POST /api/memory/proposals", "stable rejection code", "proposal count before/after") -InjectedAt "/api/memory/proposals"))
    }
    else {
        $scenarioResults.Add((New-FailedResult -Scenario "sensitive_content" -ReasonCode "sensitive_policy_not_proven" -NextStep "Reject sensitive content before any durable write and expose the rejection reason." -Observed "HTTP $($sensitive.status), code $sensitiveCode, proposal counts $beforeCount/$afterCount" -InjectedAt "/api/memory/proposals"))
    }

    # A process restart is useful evidence for the backend itself, but it does
    # not prove the Electron supervisor or a packaged Windows recovery path.
    Stop-IsolatedSidecar -Process $sidecar -Dispose
    $sidecar = Start-IsolatedSidecar -BackendDir $backendDir -RuntimeRoot $runtimeRoot -Token $sessionToken -ListenPort $selectedPort
    $restartedHealth = Wait-Health -TimeoutSeconds $StartupTimeoutSeconds
    if ($null -eq $restartedHealth) {
        $scenarioResults.Add((New-FailedResult -Scenario "sidecar_crash" -ReasonCode "backend_restart_health_failed" -NextStep "Restore sidecar health before allowing user actions." -Observed "health did not return after process restart" -InjectedAt "sidecar process stop"))
    }
    else {
        $scenarioResults.Add((New-PartialResult -Scenario "sidecar_crash" -ReasonCode "backend_restart_only" -NextStep "Verify Electron supervisor, tray state and durable job recovery in a packaged Windows run." -Observed "backend process restarted and health returned; Electron path not exercised" -InjectedAt "sidecar process stop"))
    }

    Add-BackendHarnessResults -BackendDir $backendDir -OutputDir $resolvedOutput -Results $scenarioResults
}
catch {
    $runnerFailureCode = [string]$_.Exception.Message
    $runnerFailureTrace = ([string]$_.ScriptStackTrace).Replace($repoRoot, "[REPOSITORY_ROOT]").Replace($runtimeRoot, "[ISOLATED_RUNTIME]")
}
finally {
    if ($sidecar) {
        Stop-IsolatedSidecar -Process $sidecar
        try {
            $sidecarStdout = Read-LlmWikiSidecarLog -Process $sidecar -Stream stdout
            $sidecarStderr = Read-LlmWikiSidecarLog -Process $sidecar -Stream stderr
        }
        catch { }
        try { $sidecar.Dispose() } catch { }
    }
    if ($sidecarStdout -or $sidecarStderr) {
        Write-Utf8NoBom -Path (Join-Path $resolvedOutput "sidecar.stdout.log") -Value $sidecarStdout
        Write-Utf8NoBom -Path (Join-Path $resolvedOutput "sidecar.stderr.log") -Value $sidecarStderr
    }
    $known = @($scenarioResults | ForEach-Object { $_.scenario })
    foreach ($definition in $scenarioDefinitions) {
        if ($known -notcontains $definition.scenario) {
            $scenarioResults.Add((New-PartialResult -Scenario $definition.scenario -ReasonCode $definition.reason -NextStep $definition.next))
        }
    }
    $passed = @($scenarioResults | Where-Object { $_.status -eq "Passed" }).Count
    $failed = @($scenarioResults | Where-Object { $_.status -eq "Failed" }).Count
    $partial = @($scenarioResults | Where-Object { $_.status -eq "Partial" }).Count
    $status = if ($failed -gt 0) { "Failed" } elseif ($partial -gt 0) { "Partial" } else { "Passed" }
    $exitCode = if ($failed -gt 0) { 1 } elseif ($partial -gt 0) { 2 } else { 0 }
    $report = [ordered]@{
        schema_version = "llmwiki-fault-matrix.v1"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        started_at = $startedAt
        status = $status
        evidence_mode = "real_isolated_sidecar_api_plus_deterministic_backend_faults_and_explicit_gaps"
        prerequisites = [ordered]@{
            python = [bool](Get-Command python -ErrorAction SilentlyContinue)
            isolated_database = [bool](Test-Path -LiteralPath (Join-Path $runtimeRoot "data") -PathType Container)
            sidecar_health = $null -ne $health
            electron_supervisor = "not_run"
            os_sleep = "not_run"
            notification_permission = "not_run"
        }
        base_url = if ($baseUrl) { $baseUrl } else { "not_started" }
        runner_error = if ($runnerFailureCode) { $runnerFailureCode } else { $null }
        runner_error_trace = if ($runnerFailureTrace) { $runnerFailureTrace } else { $null }
        scenarios = @($scenarioResults)
        summary = [ordered]@{ total = @($scenarioResults).Count; passed = $passed; failed = $failed; partial = $partial }
        cleanup = [ordered]@{ runtime_removed = $false; runtime_root_name = [System.IO.Path]::GetFileName($runtimeRoot) }
        exit_code = $exitCode
    }
    Write-JsonReport -Value $report
    try {
        $runtimeFull = [System.IO.Path]::GetFullPath($runtimeRoot)
        $tempFull = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if ($runtimeFull.StartsWith($tempFull, [System.StringComparison]::OrdinalIgnoreCase) -and [System.IO.Path]::GetFileName($runtimeFull).StartsWith("agentpet-llmwiki-fault-", [System.StringComparison]::OrdinalIgnoreCase)) {
            if (Test-Path -LiteralPath $runtimeFull) { Remove-Item -LiteralPath $runtimeFull -Recurse -Force }
            $report.cleanup.runtime_removed = -not (Test-Path -LiteralPath $runtimeFull)
            Write-JsonReport -Value $report
        }
    }
    catch {
        Write-Warning "ISOLATED_RUNTIME_CLEANUP_FAILED"
    }
    if ($runnerFailureCode) { [Console]::Error.WriteLine("FAULT_MATRIX_PREREQUISITE_FAILED: $runnerFailureCode") }
    exit $exitCode
}

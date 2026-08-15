[CmdletBinding()]
param(
    [string]$OutputDir = "output\verification\LLMWIKI-004",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 0,
    [int]$StartupTimeoutSeconds = 45,
    [int]$JobTimeoutSeconds = 20
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
$allowedOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "output\verification\LLMWIKI-004"))
if (
    $resolvedOutput -ne $allowedOutputRoot -and
    -not $resolvedOutput.StartsWith($allowedOutputRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
) {
    Write-Error "OUTPUT_DIR_OUTSIDE_LLMWIKI_004"
    exit 2
}
if ($StartupTimeoutSeconds -lt 5 -or $StartupTimeoutSeconds -gt 300) {
    Write-Error "INVALID_STARTUP_TIMEOUT"
    exit 2
}
if ($JobTimeoutSeconds -lt 3 -or $JobTimeoutSeconds -gt 300) {
    Write-Error "INVALID_JOB_TIMEOUT"
    exit 2
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )
    Write-LlmWikiUtf8NoBom -Path $Path -Value $Value
}

function Assert-Journey {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Code
    )
    if (-not $Condition) {
        throw $Code
    }
}

function Protect-EvidenceText {
    param([AllowEmptyString()][string]$Value)
    $protected = [string]$Value
    foreach ($secret in @($sessionToken, $runtimeRoot, $vaultRoot, $databasePath, $repoRoot) | Where-Object { $_ }) {
        $replacement = if ($secret -eq $sessionToken) {
            "[REDACTED_TOKEN]"
        }
        elseif ($secret -eq $repoRoot) {
            "[REPOSITORY_ROOT]"
        }
        elseif ($secret -eq $databasePath) {
            "[ISOLATED_DATABASE]"
        }
        elseif ($secret -eq $vaultRoot) {
            "[ISOLATED_VAULT]"
        }
        else {
            "[ISOLATED_RUNTIME]"
        }
        $protected = $protected.Replace([string]$secret, $replacement)
    }
    return $protected
}

function Write-JsonEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][object]$Value
    )
    $json = $Value | ConvertTo-Json -Depth 50
    Write-Utf8NoBom -Path (Join-Path $resolvedOutput $Name) -Value ((Protect-EvidenceText $json) + "`n")
}

function Invoke-JourneyApi {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST", "PUT", "PATCH", "DELETE")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body,
        [hashtable]$Headers = @{},
        [int]$TimeoutSeconds = 20
    )
    return Invoke-LlmWikiApi -Method $Method -BaseUrl $baseUrl -SessionToken $sessionToken -Path $Path -Body $Body -Headers $Headers -TimeoutSeconds $TimeoutSeconds
}

function Invoke-JourneyChat {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [Parameter(Mandatory = $true)][string]$EvidencePrefix
    )
    $accepted = Invoke-JourneyApi -Method POST -Path "/api/chat" -Body ([ordered]@{ message = $Message }) -TimeoutSeconds 30
    Assert-Journey ($accepted.status -eq 200 -and $null -ne $accepted.body) "${EvidencePrefix}_CHAT_ACCEPT_FAILED"
    $streamUrl = [string]$accepted.body.stream_url
    Assert-Journey (-not [string]::IsNullOrWhiteSpace($streamUrl)) "${EvidencePrefix}_STREAM_URL_MISSING"
    $streamResponse = Invoke-WebRequest -UseBasicParsing -Method GET -Uri "$baseUrl$streamUrl" -Headers @{
        Authorization = "Bearer $sessionToken"
        Accept = "text/event-stream"
    } -TimeoutSec 90
    $raw = [string]$streamResponse.Content
    $events = ConvertFrom-SseText -Value $raw
    Assert-Journey (@($events | Where-Object { $_.event -eq "done" }).Count -eq 1) "${EvidencePrefix}_DONE_EVENT_MISSING"
    Assert-Journey (@($events | Where-Object { $_.event -eq "error" }).Count -eq 0) "${EvidencePrefix}_ERROR_EVENT"
    Write-JsonEvidence -Name "$EvidencePrefix-request.json" -Value ([ordered]@{ method = "POST"; path = "/api/chat"; body = @{ message = $Message }; accepted = $accepted.body })
    Write-Utf8NoBom -Path (Join-Path $resolvedOutput "$EvidencePrefix-sse.txt") -Value ((Protect-EvidenceText $raw).TrimEnd() + "`n")
    return [ordered]@{
        accepted = $accepted.body
        events = @($events)
        raw = $raw
    }
}

function ConvertFrom-SseText {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    $events = [System.Collections.Generic.List[object]]::new()
    $current = [ordered]@{}
    foreach ($rawLine in ($Value -split "`r?`n")) {
        $line = $rawLine.Trim()
        if (-not $line) {
            if ($current.Count -gt 0) {
                $events.Add([pscustomobject]$current)
                $current = [ordered]@{}
            }
            continue
        }
        if ($line.StartsWith(":")) {
            continue
        }
        $separator = $line.IndexOf(":")
        if ($separator -lt 0) {
            continue
        }
        $field = $line.Substring(0, $separator)
        $value = $line.Substring($separator + 1).TrimStart()
        if ($field -eq "data" -and $current.Contains("data")) {
            $current.data = ([string]$current.data) + "`n" + $value
        }
        else {
            $current[$field] = $value
        }
    }
    if ($current.Count -gt 0) {
        $events.Add([pscustomobject]$current)
    }
    return @($events)
}

function Get-CitationPayloads {
    param([Parameter(Mandatory = $true)][object[]]$Events)
    $citations = [System.Collections.Generic.List[object]]::new()
    foreach ($event in @($Events | Where-Object { $_.event -eq "citation" })) {
        try {
            $payload = ([string]$event.data) | ConvertFrom-Json
        }
        catch {
            throw "INVALID_CITATION_SSE_JSON"
        }
        if ($null -ne $payload.citation) {
            $citations.Add($payload.citation)
        }
    }
    return @($citations)
}

function Wait-ForConsolidationAction {
    param(
        [Parameter(Mandatory = $true)][string]$AgentRunId,
        [Parameter(Mandatory = $true)][string]$EvidenceName
    )
    $deadline = (Get-Date).AddSeconds($JobTimeoutSeconds)
    $lastBody = $null
    while ((Get-Date) -lt $deadline) {
        $response = Invoke-JourneyApi -Method GET -Path "/api/agent/actions?agent_run_id=$AgentRunId&limit=50"
        if ($response.status -eq 200 -and $null -ne $response.body) {
            $lastBody = $response.body
            $matching = @($response.body.actions | Where-Object {
                $_.action_type -eq "memory.consolidation.candidate" -and $_.status -eq "completed"
            })
            if ($matching.Count -gt 0) {
                Write-JsonEvidence -Name $EvidenceName -Value $response.body
                return $matching[0]
            }
        }
        Start-Sleep -Milliseconds 250
    }
    if ($null -ne $lastBody) {
        Write-JsonEvidence -Name $EvidenceName -Value $lastBody
    }
    throw "CONSOLIDATION_ACTION_NOT_COMPLETED"
}

function Wait-ForPostReplyJob {
    param([Parameter(Mandatory = $true)][string]$AgentRunId)
    $deadline = (Get-Date).AddSeconds($JobTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $row = Invoke-SqliteJsonQuery -Query @"
SELECT id, status, attempts, last_error_code, stage_states_json, created_at, updated_at, completed_at
FROM post_reply_memory_jobs
WHERE agent_run_id = '$AgentRunId'
ORDER BY created_at DESC
LIMIT 1;
"@
        if (@($row).Count -gt 0 -and [string]$row[0].status -eq "completed") {
            return $row[0]
        }
        Start-Sleep -Milliseconds 250
    }
    throw "POST_REPLY_JOB_NOT_COMPLETED"
}

function Invoke-SqliteJsonQuery {
    param([Parameter(Mandatory = $true)][string]$Query)
    $sqlite = (Get-Command sqlite3 -ErrorAction Stop).Source
    $raw = & $sqlite -readonly -json $databasePath $Query 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "SQLITE_READ_FAILED"
    }
    $text = ($raw -join "`n").Trim()
    if (-not $text) {
        return @()
    }
    $parsed = ConvertFrom-Json $text
    foreach ($row in @($parsed)) {
        $row
    }
}

function New-JourneySecret {
    $bytes = New-Object byte[] 48
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Get-LifecycleSnapshot {
    param([Parameter(Mandatory = $true)][string]$Stage)
    $snapshot = [ordered]@{
        stage = $Stage
        captured_at = (Get-Date).ToUniversalTime().ToString("o")
        candidates = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, fact_id, memory_kind, source_track, status, normalized_value, superseded_by, updated_at
FROM memory_candidates
ORDER BY created_at, id;
"@)
        graph_facts = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, statement_kind, subject, predicate, object, relation_type,
       subject_entity_id, subject_fact_id, object_entity_id, object_fact_id,
       status, updated_at
FROM memory_graph_facts
ORDER BY created_at, id;
"@)
        memory_fact_artifact_bindings = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, fact_id, vault_id, artifact_type, artifact_ref, status, created_at, updated_at
FROM memory_fact_artifact_bindings
ORDER BY created_at, id;
"@)
        documented_in_relations = @(Invoke-SqliteJsonQuery -Query @"
SELECT relation.id, relation.subject_entity_id, relation.subject_fact_id,
       relation.object_entity_id, relation.object_fact_id, relation.subject,
       relation.predicate, relation.object, relation.status,
       page.wiki_relative_path, relation.created_at, relation.updated_at
FROM memory_graph_facts relation
LEFT JOIN wiki_page_bindings page ON page.page_entity_id = relation.object_entity_id
WHERE relation.statement_kind = 'relation'
  AND relation.relation_type = 'documented_in'
ORDER BY relation.created_at, relation.id;
"@)
        active_documented_in_relations = @(Invoke-SqliteJsonQuery -Query @"
SELECT relation.id, relation.subject_entity_id, relation.subject_fact_id,
       relation.object_entity_id, relation.object_fact_id, relation.subject,
       relation.predicate, relation.object, relation.status,
       page.wiki_relative_path, relation.created_at, relation.updated_at
FROM memory_graph_facts relation
LEFT JOIN wiki_page_bindings page ON page.page_entity_id = relation.object_entity_id
WHERE relation.statement_kind = 'relation'
  AND relation.relation_type = 'documented_in'
  AND relation.status = 'active'
ORDER BY relation.created_at, relation.id;
"@)
        evidence = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, candidate_id, fact_id, source_type, source_text_hash, evidence_key, created_at
FROM memory_evidence
ORDER BY created_at, id;
"@)
        executions = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, idempotency_key, action_type, status, metadata_json, created_at, updated_at, completed_at
FROM agent_actions
WHERE idempotency_key IS NOT NULL
ORDER BY created_at, id;
"@)
        post_reply_jobs = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, agent_run_id, status, attempts, last_error_code, created_at, updated_at, completed_at
FROM post_reply_memory_jobs
ORDER BY created_at, id;
"@)
    }
    Write-JsonEvidence -Name "sqlite-$Stage.json" -Value $snapshot
    return $snapshot
}

function Start-JourneySidecar {
    $selected = if ($Port -gt 0) { $Port } else { New-LlmWikiIsolatedPort }
    $script:selectedPort = $selected
    $script:baseUrl = "http://${HostName}:$selected"
    $process = Start-LlmWikiIsolatedSidecar -BackendDir $backendDir -RuntimeRoot $runtimeRoot -SessionToken $sessionToken -Port $selected -HostName $HostName -DatabaseFileName ([System.IO.Path]::GetFileName($databasePath)) -Environment @{
        AGENT_PET_MODEL_BASE_URL = "http://127.0.0.1:9/v1"
        AGENT_PET_EMBEDDING_BASE_URL = "http://127.0.0.1:9/v1"
        AGENT_PET_MODEL_TIMEOUT_SECONDS = "2"
        AGENT_PET_ALLOW_INSECURE_FILE_CREDENTIALS = "1"
    }
    $health = Wait-LlmWikiHealth -BaseUrl $baseUrl -SessionToken $sessionToken -TimeoutSeconds $StartupTimeoutSeconds
    if ($null -eq $health) {
        Stop-LlmWikiIsolatedSidecar -Process $process
        throw "SIDECAR_HEALTH_TIMEOUT"
    }
    return $process
}

function Stop-JourneySidecar {
    param([System.Diagnostics.Process]$Process)
    if ($null -eq $Process) {
        return
    }
    Stop-LlmWikiIsolatedSidecar -Process $Process
    $stdout = Read-LlmWikiSidecarLog -Process $Process -Stream stdout
    $stderr = Read-LlmWikiSidecarLog -Process $Process -Stream stderr
    $script:processOrdinal += 1
    Write-Utf8NoBom -Path (Join-Path $resolvedOutput ("sidecar-{0:D2}.stdout.log" -f $script:processOrdinal)) -Value ((Protect-EvidenceText $stdout).TrimEnd() + "`n")
    Write-Utf8NoBom -Path (Join-Path $resolvedOutput ("sidecar-{0:D2}.stderr.log" -f $script:processOrdinal)) -Value ((Protect-EvidenceText $stderr).TrimEnd() + "`n")
    try { $Process.Dispose() } catch { }
}

function Get-GraphClaimByValue {
    param([Parameter(Mandatory = $true)][string]$Value)
    $graph = Invoke-JourneyApi -Method GET -Path "/api/memory/graph?limit=80"
    Assert-Journey ($graph.status -eq 200 -and $null -ne $graph.body) "GRAPH_READ_FAILED"
    $claimNodes = @($graph.body.nodes | Where-Object {
        $_.status -eq "active" -and ([string]$_.label).IndexOf($Value, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    })
    foreach ($node in $claimNodes) {
        $detail = Invoke-JourneyApi -Method GET -Path "/api/memory/graph/nodes/$([uri]::EscapeDataString([string]$node.node_id))"
        if ($detail.status -eq 200 -and @($detail.body.claim_ids).Count -gt 0) {
            return [ordered]@{ graph = $graph.body; node = $node; detail = $detail.body; claim_id = [string]$detail.body.claim_ids[0] }
        }
    }
    throw "GRAPH_CLAIM_NOT_FOUND_$Value"
}

function Assert-SearchFact {
    param(
        [Parameter(Mandatory = $true)][string]$Query,
        [Parameter(Mandatory = $true)][string]$FactId,
        [Parameter(Mandatory = $true)][bool]$Expected,
        [Parameter(Mandatory = $true)][string]$EvidenceName
    )
    $response = Invoke-JourneyApi -Method POST -Path "/api/memory/search" -Body ([ordered]@{
        query = $Query
        top_k = 10
        source_scope = "personal_memory"
    })
    Assert-Journey ($response.status -eq 200 -and $null -ne $response.body) "SEARCH_FAILED_$EvidenceName"
    $found = @($response.body.results | Where-Object { [string]$_.fact_id -eq $FactId }).Count -gt 0
    Assert-Journey ($found -eq $Expected) "SEARCH_EXPECTATION_FAILED_$EvidenceName"
    if ($Expected) {
        $result = @($response.body.results | Where-Object { [string]$_.fact_id -eq $FactId })[0]
        Assert-Journey ([string]$result.retrieval_mode -eq "graph_activation") "SEARCH_NOT_GRAPH_ACTIVATION_$EvidenceName"
        Assert-Journey ([string]$result.lifecycle_status -eq "active") "SEARCH_NOT_ACTIVE_$EvidenceName"
        Assert-Journey ([bool]$result.recall_permissions.can_answer_context) "SEARCH_PERMISSION_DENIED_$EvidenceName"
        Assert-Journey (@($result.evidence_refs).Count -gt 0) "SEARCH_EVIDENCE_MISSING_$EvidenceName"
        Assert-Journey (@($result.citation_refs).Count -gt 0) "SEARCH_CITATION_MISSING_$EvidenceName"
    }
    Write-JsonEvidence -Name $EvidenceName -Value $response.body
    return $response.body
}

function Get-FactIdForClaim {
    param([Parameter(Mandatory = $true)][string]$ClaimId)
    $detail = Invoke-JourneyApi -Method GET -Path "/api/memory/graph/claims/$([uri]::EscapeDataString($ClaimId))"
    Assert-Journey ($detail.status -eq 200 -and $null -ne $detail.body) "CLAIM_DETAIL_FAILED"
    $search = Invoke-JourneyApi -Method POST -Path "/api/memory/search" -Body ([ordered]@{
        query = [string]$detail.body.literal_value
        top_k = 10
        source_scope = "personal_memory"
    })
    Assert-Journey ($search.status -eq 200) "CLAIM_FACT_SEARCH_FAILED"
    $candidate = @($search.body.results | Where-Object {
        [string]$_.lifecycle_status -eq "active" -and ([string]$_.snippet).IndexOf([string]$detail.body.literal_value, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    }) | Select-Object -First 1
    Assert-Journey ($null -ne $candidate -and -not [string]::IsNullOrWhiteSpace([string]$candidate.fact_id)) "CLAIM_FACT_ID_MISSING"
    return [string]$candidate.fact_id
}

function Invoke-ReplacementFactWikiIngest {
    param([Parameter(Mandatory = $true)][string]$FactId)

    $parsedFactId = [Guid]::Empty
    Assert-Journey ([Guid]::TryParse($FactId, [ref]$parsedFactId)) "WIKI_BINDING_FACT_ID_INVALID"
    $factRows = @(Invoke-SqliteJsonQuery -Query @"
SELECT fact.id, fact.subject_entity_id, fact.subject, fact.predicate, fact.object,
       fact.category, fact.status, entity.entity_type, entity.canonical_name
FROM memory_graph_facts fact
JOIN memory_entities entity ON entity.id = fact.subject_entity_id
WHERE fact.id = '$FactId';
"@)
    Assert-Journey ($factRows.Count -eq 1) "WIKI_BINDING_FACT_DESCRIPTOR_MISSING"
    $fact = $factRows[0]
    Assert-Journey ([string]$fact.status -eq "active") "WIKI_BINDING_FACT_NOT_ACTIVE"
    Assert-Journey (-not [string]::IsNullOrWhiteSpace([string]$fact.subject_entity_id)) "WIKI_BINDING_SUBJECT_ENTITY_MISSING"
    Assert-Journey (-not [string]::IsNullOrWhiteSpace([string]$fact.entity_type)) "WIKI_BINDING_ENTITY_TYPE_MISSING"
    Assert-Journey (-not [string]::IsNullOrWhiteSpace([string]$fact.canonical_name)) "WIKI_BINDING_ENTITY_NAME_MISSING"

    $content = "User confirmed this memory for the local Wiki: $([string]$fact.subject) $([string]$fact.predicate) $([string]$fact.object)."
    $factType = if ([string]::IsNullOrWhiteSpace([string]$fact.category)) { "preference" } else { [string]$fact.category }
    $sourceMetadata = [ordered]@{
        memory_extraction = [ordered]@{
            wrapper_version = "llmwiki.wiki-extraction.v1"
            provenance = "explicit_user"
            payload = [ordered]@{
                schema_version = "llmwiki.entity-extraction.v1"
                entities = @(
                    [ordered]@{
                        entity_ref = "replacement-memory-subject"
                        entity_type = [string]$fact.entity_type
                        name = [string]$fact.canonical_name
                        aliases = @()
                        confidence = 1.0
                        risk_tier = "low"
                        evidence = [ordered]@{ start = 0; end = $content.Length }
                    }
                )
                claims = @(
                    [ordered]@{
                        claim_ref = "replacement-memory-claim"
                        subject_entity_ref = "replacement-memory-subject"
                        predicate = [string]$fact.predicate
                        value = [string]$fact.object
                        fact_type = $factType
                        confidence = 1.0
                        evidence = [ordered]@{ start = 0; end = $content.Length }
                    }
                )
                relations = @()
                sensitive = @()
                conflicts = @()
                uncertainties = @()
            }
        }
    }
    $previewBody = [ordered]@{
        title = "Preferred editor memory evidence"
        content = $content
        source_type = "user_message"
        tags = @("memory/preference", "evidence")
        links = @()
        max_pages = 1
        source_metadata = $sourceMetadata
    }
    $preview = Invoke-JourneyApi -Method POST -Path "/api/wiki/ingest/preview" -Body $previewBody
    Assert-Journey ($preview.status -eq 200 -and $null -ne $preview.body) "WIKI_BINDING_PREVIEW_FAILED"
    Assert-Journey ([string]$preview.body.status -eq "preview") "WIKI_BINDING_PREVIEW_STATUS_INVALID"
    Assert-Journey (-not [string]::IsNullOrWhiteSpace([string]$preview.body.preview_token)) "WIKI_BINDING_PREVIEW_TOKEN_MISSING"
    Assert-Journey (@($preview.body.page_plans).Count -eq 1) "WIKI_BINDING_PAGE_PLAN_COUNT_INVALID"
    Write-JsonEvidence -Name "15-wiki-preview.json" -Value ([ordered]@{ request = $previewBody; response = $preview.body })

    $confirmBody = [ordered]@{
        preview_token = [string]$preview.body.preview_token
        user_confirmed = $true
    }
    $confirm = Invoke-JourneyApi -Method POST -Path "/api/wiki/ingest/confirm" -Body $confirmBody
    Assert-Journey ($confirm.status -eq 200 -and $null -ne $confirm.body) "WIKI_BINDING_CONFIRM_FAILED"
    Assert-Journey ([string]$confirm.body.status -eq "planned") "WIKI_BINDING_CONFIRM_STATUS_INVALID"
    Assert-Journey ([string]$confirm.body.source_hash -eq [string]$preview.body.source_hash) "WIKI_BINDING_SOURCE_HASH_CHANGED"
    Write-JsonEvidence -Name "16-wiki-confirm.json" -Value ([ordered]@{ request = $confirmBody; response = $confirm.body })

    $reviewBody = [ordered]@{ run_id = [string]$confirm.body.run_id }
    $review = Invoke-JourneyApi -Method POST -Path "/api/wiki/ingest/review" -Body $reviewBody
    Assert-Journey ($review.status -eq 200 -and $null -ne $review.body) "WIKI_BINDING_REVIEW_FAILED"
    Assert-Journey ([string]$review.body.status -in @("reviewed", "model_not_configured")) "WIKI_BINDING_REVIEW_STATUS_INVALID"
    Assert-Journey (-not [string]::IsNullOrWhiteSpace([string]$review.body.review_id)) "WIKI_BINDING_REVIEW_ID_MISSING"
    $targetPath = [string]$confirm.body.page_plans[0].target_path
    Assert-Journey (@($review.body.recommended_targets) -contains $targetPath) "WIKI_BINDING_TARGET_NOT_RECOMMENDED"
    Write-JsonEvidence -Name "17-wiki-review.json" -Value ([ordered]@{ request = $reviewBody; response = $review.body })

    $applyBody = [ordered]@{
        run_id = [string]$confirm.body.run_id
        approved_targets = @($targetPath)
        review_id = [string]$review.body.review_id
        review_acknowledged = $true
    }
    $apply = Invoke-JourneyApi -Method POST -Path "/api/wiki/ingest/apply" -Body $applyBody
    Assert-Journey ($apply.status -eq 200 -and $null -ne $apply.body) "WIKI_BINDING_APPLY_FAILED"
    Assert-Journey ([string]$apply.body.status -eq "applied") "WIKI_BINDING_APPLY_STATUS_INVALID"
    Assert-Journey ([int]$apply.body.pages_written -eq 1) "WIKI_BINDING_PAGE_NOT_WRITTEN"
    Assert-Journey ([string]$apply.body.page_results[0].relative_path -eq $targetPath) "WIKI_BINDING_TARGET_CHANGED"
    Write-JsonEvidence -Name "18-wiki-apply.json" -Value ([ordered]@{ request = $applyBody; response = $apply.body })

    return [ordered]@{
        source_id = [string]$confirm.body.source_id
        source_hash = [string]$confirm.body.source_hash
        run_id = [string]$confirm.body.run_id
        review_id = [string]$review.body.review_id
        target_path = $targetPath
    }
}

$backendDir = Join-Path $repoRoot "apps\backend"
$runtimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("agentpet-llmwiki-memory-" + [Guid]::NewGuid().ToString("N"))
$vaultRoot = Join-Path $runtimeRoot "vault"
$databasePath = Join-Path (Join-Path $runtimeRoot "data") "agent_pet_memory_journey.sqlite3"
$sessionToken = New-JourneySecret
$sidecar = $null
$processOrdinal = 0
$selectedPort = 0
$baseUrl = ""
$restartEvents = [System.Collections.Generic.List[object]]::new()
$startedAt = (Get-Date).ToUniversalTime().ToString("o")
$report = $null
$exitCode = 1

New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null
Get-ChildItem -LiteralPath $resolvedOutput -File -ErrorAction SilentlyContinue | Remove-Item -Force

try {
    Assert-Journey (Test-Path -LiteralPath $backendDir -PathType Container) "BACKEND_DIR_MISSING"
    Assert-Journey ($null -ne (Get-Command python -ErrorAction SilentlyContinue)) "PYTHON_MISSING"
    Assert-Journey ($null -ne (Get-Command sqlite3 -ErrorAction SilentlyContinue)) "SQLITE_CLI_MISSING"

    $sidecar = Start-JourneySidecar
    $restartEvents.Add([ordered]@{ ordinal = 1; pid = $sidecar.Id; started_at = (Get-Date).ToUniversalTime().ToString("o"); reason = "initial_start" })

    $vault = Invoke-JourneyApi -Method POST -Path "/api/vaults/init" -Body ([ordered]@{
        path = $vaultRoot
        create_if_missing = $true
        confirmed = $true
    })
    Assert-Journey ($vault.status -eq 200 -and $null -ne $vault.body.vault_id) "VAULT_INIT_FAILED"
    Write-JsonEvidence -Name "01-vault-init.json" -Value ([ordered]@{ request = @{ path = "[ISOLATED_VAULT]"; create_if_missing = $true; confirmed = $true }; response = $vault.body })

    $automation = Invoke-JourneyApi -Method PUT -Path "/api/settings/automation" -Body ([ordered]@{
        auto_chat_diary = $false
        auto_structured_memory = $false
        auto_long_term_memory = $true
        auto_wiki_organize = $false
        local_privacy_mode = $false
        proactive_trigger_frequency = "low"
        use_negotiation = $false
        max_rounds = 5
    })
    Assert-Journey ($automation.status -eq 200 -and [bool]$automation.body.auto_long_term_memory) "AUTOMATION_ENABLE_FAILED"
    Write-JsonEvidence -Name "02-automation.json" -Value $automation.body

    $saveChat = Invoke-JourneyChat -Message "Remember this: my preferred editor = VS Code." -EvidencePrefix "03-save"
    $saveRunId = [string]$saveChat.accepted.agent_run_id
    $null = Wait-ForConsolidationAction -AgentRunId $saveRunId -EvidenceName "04-consolidation-action.json"
    $postReplyJob = Wait-ForPostReplyJob -AgentRunId $saveRunId
    Write-JsonEvidence -Name "05-post-reply-job.json" -Value $postReplyJob
    $savedGraph = Get-GraphClaimByValue -Value "VS Code"
    $oldClaimId = [string]$savedGraph.claim_id
    $oldFactId = Get-FactIdForClaim -ClaimId $oldClaimId
    Write-JsonEvidence -Name "06-graph-after-save.json" -Value $savedGraph.graph
    $null = Assert-SearchFact -Query "preferred editor VS Code" -FactId $oldFactId -Expected $true -EvidenceName "07-search-after-save.json"
    $null = Get-LifecycleSnapshot -Stage "after-save"

    $firstPid = $sidecar.Id
    Stop-JourneySidecar -Process $sidecar
    $sidecar = $null
    $restartAt = (Get-Date).ToUniversalTime().ToString("o")
    $sidecar = Start-JourneySidecar
    Assert-Journey ($sidecar.Id -ne $firstPid) "FIRST_RESTART_PID_UNCHANGED"
    $restartEvents.Add([ordered]@{ ordinal = 2; previous_pid = $firstPid; pid = $sidecar.Id; started_at = $restartAt; reason = "verify_new_session_recall" })

    $recallChat = Invoke-JourneyChat -Message "What is my preferred editor?" -EvidencePrefix "08-recall-after-restart"
    Assert-Journey ([string]$recallChat.accepted.conversation_id -ne [string]$saveChat.accepted.conversation_id) "RECALL_CONVERSATION_NOT_NEW"
    $recallCitations = @(Get-CitationPayloads -Events $recallChat.events)
    $oldCitation = @($recallCitations | Where-Object { [string]$_.fact_id -eq $oldFactId }) | Select-Object -First 1
    Assert-Journey ($null -ne $oldCitation) "RECALL_CITATION_FOR_OLD_FACT_MISSING"
    Assert-Journey (@($oldCitation.evidence_refs).Count -gt 0) "RECALL_EVIDENCE_REFS_MISSING"
    Assert-Journey (@($oldCitation.citation_refs).Count -gt 0) "RECALL_CITATION_REFS_MISSING"
    Write-JsonEvidence -Name "09-recall-citations.json" -Value $recallCitations

    $correctionKey = New-LlmWikiIdempotencyKey
    $correctionBody = [ordered]@{ action = "correct"; confirmed = $true; replacement = @{ value = "JetBrains" } }
    $correction = Invoke-JourneyApi -Method POST -Path "/api/memory/graph/claims/$oldClaimId/actions" -Body $correctionBody -Headers @{ "Idempotency-Key" = $correctionKey }
    Write-JsonEvidence -Name "10-correction-attempt.json" -Value ([ordered]@{ request = $correctionBody; response = $correction.body; status = $correction.status; idempotency_key = "[REDACTED_IDEMPOTENCY_KEY]" })
    Assert-Journey ($correction.status -eq 200 -and $null -ne $correction.body) "CORRECTION_FAILED"
    Assert-Journey ([string]$correction.body.status -eq "active") "CORRECTION_STATUS_INVALID"
    Assert-Journey (-not [string]::IsNullOrWhiteSpace([string]$correction.body.replacement_id)) "CORRECTION_REPLACEMENT_MISSING"
    Assert-Journey (-not [bool]$correction.body.replayed) "FIRST_CORRECTION_WAS_REPLAY"
    $correctionReplay = Invoke-JourneyApi -Method POST -Path "/api/memory/graph/claims/$oldClaimId/actions" -Body $correctionBody -Headers @{ "Idempotency-Key" = $correctionKey }
    Assert-Journey ($correctionReplay.status -eq 200 -and [bool]$correctionReplay.body.replayed) "CORRECTION_REPLAY_NOT_PROVEN"
    Assert-Journey ([string]$correctionReplay.body.operation_id -eq [string]$correction.body.operation_id) "CORRECTION_REPLAY_RECEIPT_CHANGED"
    Assert-Journey ([string]$correctionReplay.body.replacement_id -eq [string]$correction.body.replacement_id) "CORRECTION_REPLAY_REPLACEMENT_CHANGED"
    $newClaimId = [string]$correction.body.replacement_id
    $newFactId = Get-FactIdForClaim -ClaimId $newClaimId
    Write-JsonEvidence -Name "10-correction-receipts.json" -Value ([ordered]@{ request = $correctionBody; first = $correction.body; replay = $correctionReplay.body; idempotency_key = "[REDACTED_IDEMPOTENCY_KEY]" })
    $null = Get-LifecycleSnapshot -Stage "after-correction"

    $secondPid = $sidecar.Id
    Stop-JourneySidecar -Process $sidecar
    $sidecar = $null
    $secondRestartAt = (Get-Date).ToUniversalTime().ToString("o")
    $sidecar = Start-JourneySidecar
    Assert-Journey ($sidecar.Id -ne $secondPid) "SECOND_RESTART_PID_UNCHANGED"
    $restartEvents.Add([ordered]@{ ordinal = 3; previous_pid = $secondPid; pid = $sidecar.Id; started_at = $secondRestartAt; reason = "verify_correction_propagation" })

    $null = Assert-SearchFact -Query "VS Code" -FactId $oldFactId -Expected $false -EvidenceName "11-old-search-after-correction.json"
    $null = Assert-SearchFact -Query "JetBrains" -FactId $newFactId -Expected $true -EvidenceName "12-new-search-after-correction.json"
    $correctedChat = Invoke-JourneyChat -Message "What is my preferred editor?" -EvidencePrefix "13-recall-corrected"
    $correctedCitations = @(Get-CitationPayloads -Events $correctedChat.events)
    Assert-Journey (@($correctedCitations | Where-Object { [string]$_.fact_id -eq $oldFactId }).Count -eq 0) "OLD_FACT_STILL_CITED"
    Assert-Journey (@($correctedCitations | Where-Object { [string]$_.fact_id -eq $newFactId }).Count -gt 0) "NEW_FACT_CITATION_MISSING"
    Write-JsonEvidence -Name "14-corrected-citations.json" -Value $correctedCitations

    $wikiIngest = Invoke-ReplacementFactWikiIngest -FactId $newFactId
    $beforeForgetSnapshot = Get-LifecycleSnapshot -Stage "after-wiki-binding"
    $replacementArtifactBindingsBeforeForget = @($beforeForgetSnapshot.memory_fact_artifact_bindings | Where-Object {
        [string]$_.fact_id -eq $newFactId -and [string]$_.status -eq "active"
    })
    $replacementDocumentedInBeforeForget = @($beforeForgetSnapshot.active_documented_in_relations | Where-Object {
        [string]$_.subject_fact_id -eq $newFactId
    })
    Assert-Journey ($replacementArtifactBindingsBeforeForget.Count -ge 2) "WIKI_BINDING_ACTIVE_ARTIFACTS_MISSING"
    Assert-Journey (@($replacementArtifactBindingsBeforeForget | Where-Object {
        [string]$_.artifact_type -eq "source"
    }).Count -ge 1) "WIKI_BINDING_ACTIVE_SOURCE_MISSING"
    Assert-Journey (@($replacementArtifactBindingsBeforeForget | Where-Object {
        [string]$_.artifact_type -eq "wiki_page" -and [string]$_.artifact_ref -eq [string]$wikiIngest.target_path
    }).Count -eq 1) "WIKI_BINDING_ACTIVE_PAGE_MISSING"
    Assert-Journey ($replacementDocumentedInBeforeForget.Count -ge 1) "WIKI_BINDING_ACTIVE_DOCUMENTED_IN_MISSING"
    Assert-Journey (@($replacementDocumentedInBeforeForget | Where-Object {
        [string]$_.wiki_relative_path -eq [string]$wikiIngest.target_path
    }).Count -ge 1) "WIKI_BINDING_DOCUMENTED_IN_TARGET_MISMATCH"
    [string[]]$artifactBindingIds = @($replacementArtifactBindingsBeforeForget | ForEach-Object { [string]$_.id })
    [string[]]$documentedInRelationIds = @($replacementDocumentedInBeforeForget | ForEach-Object { [string]$_.id })

    $forgetKey = New-LlmWikiIdempotencyKey
    $forgetBody = [ordered]@{ action = "forget"; confirmed = $true }
    $forgotten = Invoke-JourneyApi -Method POST -Path "/api/memory/graph/claims/$newClaimId/actions" -Body $forgetBody -Headers @{ "Idempotency-Key" = $forgetKey }
    Write-JsonEvidence -Name "19-forget-attempt.json" -Value ([ordered]@{ request = $forgetBody; response = $forgotten.body; status = $forgotten.status; idempotency_key = "[REDACTED_IDEMPOTENCY_KEY]" })
    Assert-Journey ($forgotten.status -eq 200 -and [string]$forgotten.body.status -eq "forgotten") "FORGET_FAILED"
    Write-JsonEvidence -Name "19-forget-receipt.json" -Value ([ordered]@{ request = $forgetBody; response = $forgotten.body; idempotency_key = "[REDACTED_IDEMPOTENCY_KEY]" })

    $null = Assert-SearchFact -Query "JetBrains" -FactId $newFactId -Expected $false -EvidenceName "20-search-after-forget.json"
    $graphAfterForget = Invoke-JourneyApi -Method GET -Path "/api/memory/graph?limit=80"
    Assert-Journey ($graphAfterForget.status -eq 200) "GRAPH_AFTER_FORGET_FAILED"
    Assert-Journey (@($graphAfterForget.body.nodes | Where-Object { ([string]$_.label).IndexOf("JetBrains", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count -eq 0) "FORGOTTEN_VALUE_STILL_PUBLIC"
    Write-JsonEvidence -Name "21-graph-after-forget.json" -Value $graphAfterForget.body
    $forgottenChat = Invoke-JourneyChat -Message "What is my preferred editor?" -EvidencePrefix "22-recall-after-forget"
    $forgottenCitations = @(Get-CitationPayloads -Events $forgottenChat.events)
    Assert-Journey (@($forgottenCitations | Where-Object { [string]$_.fact_id -in @($oldFactId, $newFactId) }).Count -eq 0) "FORGOTTEN_FACT_STILL_CITED"
    Write-JsonEvidence -Name "23-forgotten-citations.json" -Value $forgottenCitations
    $finalSnapshot = Get-LifecycleSnapshot -Stage "after-forget"

    $oldCandidate = @($finalSnapshot.candidates | Where-Object { [string]$_.fact_id -eq $oldFactId }) | Select-Object -First 1
    $newCandidate = @($finalSnapshot.candidates | Where-Object { [string]$_.fact_id -eq $newFactId }) | Select-Object -First 1
    $oldFact = @($finalSnapshot.graph_facts | Where-Object { [string]$_.id -eq $oldFactId }) | Select-Object -First 1
    $newFact = @($finalSnapshot.graph_facts | Where-Object { [string]$_.id -eq $newFactId }) | Select-Object -First 1
    $supersedes = @($finalSnapshot.graph_facts | Where-Object {
        [string]$_.statement_kind -eq "relation" -and [string]$_.relation_type -eq "supersedes"
    })
    $activeReplacementArtifactBindings = @($finalSnapshot.memory_fact_artifact_bindings | Where-Object {
        [string]$_.fact_id -eq $newFactId -and [string]$_.status -eq "active"
    })
    $activeReplacementDocumentedInRelations = @($finalSnapshot.active_documented_in_relations | Where-Object {
        [string]$_.subject_fact_id -eq $newFactId -or [string]$_.object_fact_id -eq $newFactId
    })
    $replacementArtifactBindingsAfterForget = @($finalSnapshot.memory_fact_artifact_bindings | Where-Object {
        [string]$_.id -in $artifactBindingIds
    })
    $replacementDocumentedInAfterForget = @($finalSnapshot.documented_in_relations | Where-Object {
        [string]$_.id -in $documentedInRelationIds
    })
    Assert-Journey ($null -ne $oldCandidate -and [string]$oldCandidate.status -eq "superseded") "OLD_CANDIDATE_NOT_SUPERSEDED"
    Assert-Journey ($null -ne $newCandidate -and [string]$newCandidate.status -eq "forgotten") "NEW_CANDIDATE_NOT_FORGOTTEN"
    Assert-Journey ($null -ne $oldFact -and [string]$oldFact.status -eq "superseded") "OLD_FACT_NOT_SUPERSEDED"
    Assert-Journey ($null -ne $newFact -and [string]$newFact.status -eq "forgotten") "NEW_FACT_NOT_FORGOTTEN"
    Assert-Journey ($supersedes.Count -eq 1) "SUPERSEDES_RELATION_COUNT_INVALID"
    Assert-Journey ($activeReplacementArtifactBindings.Count -eq 0) "FORGOTTEN_FACT_HAS_ACTIVE_ARTIFACT_BINDING"
    Assert-Journey ($activeReplacementDocumentedInRelations.Count -eq 0) "FORGOTTEN_FACT_HAS_ACTIVE_DOCUMENTED_IN_RELATION"
    Assert-Journey ($replacementArtifactBindingsAfterForget.Count -eq $artifactBindingIds.Count) "WIKI_BINDING_ARTIFACT_HISTORY_MISSING"
    Assert-Journey (@($replacementArtifactBindingsAfterForget | Where-Object {
        [string]$_.status -ne "revoked"
    }).Count -eq 0) "WIKI_BINDING_ARTIFACT_NOT_REVOKED"
    Assert-Journey ($replacementDocumentedInAfterForget.Count -eq $documentedInRelationIds.Count) "WIKI_BINDING_DOCUMENTED_IN_HISTORY_MISSING"
    Assert-Journey (@($replacementDocumentedInAfterForget | Where-Object {
        [string]$_.status -eq "active"
    }).Count -eq 0) "WIKI_BINDING_DOCUMENTED_IN_STILL_ACTIVE"
    Write-JsonEvidence -Name "24-wiki-binding-lifecycle.json" -Value ([ordered]@{
        replacement_fact_id = $newFactId
        wiki_target_path = [string]$wikiIngest.target_path
        before_forget = [ordered]@{
            artifact_bindings = $replacementArtifactBindingsBeforeForget
            documented_in_relations = $replacementDocumentedInBeforeForget
        }
        after_forget = [ordered]@{
            artifact_bindings = $replacementArtifactBindingsAfterForget
            documented_in_relations = $replacementDocumentedInAfterForget
        }
    })

    $report = [ordered]@{
        schema_version = "llmwiki-memory-journey.v3"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        started_at = $startedAt
        status = "Passed"
        evidence_level = "L3"
        evidence_mode = "real_isolated_sidecar_http_sse_with_read_only_sqlite_validation"
        boundary = "This proves the local backend process-restart and real Wiki closure journey. The versioned extraction fixture proves lifecycle integration, not live-model extraction quality. It does not prove Electron supervision, packaged Windows recovery, 24-hour stability, or 7-day business outcomes."
        assertions = [ordered]@{
            save_completed = $true
            first_process_restart = $true
            new_conversation_recall_has_citation = $true
            correction_receipt_replayed = $true
            second_process_restart = $true
            old_fact_not_recalled = $true
            replacement_fact_recalled_with_citation = $true
            replacement_fact_bound_through_wiki_closure = $true
            replacement_fact_had_active_documented_in = $true
            forgotten_fact_not_searchable = $true
            forgotten_fact_not_in_public_graph = $true
            forgotten_fact_not_cited = $true
            forgotten_fact_has_no_active_artifact_binding = $true
            forgotten_fact_has_no_active_documented_in_relation = $true
            forgotten_fact_artifact_bindings_revoked = $true
            forgotten_fact_documented_in_relations_inactive = $true
        }
        process_restarts = @($restartEvents)
        public_references = [ordered]@{
            old_claim_id = $oldClaimId
            replacement_claim_id = $newClaimId
            old_fact_id = $oldFactId
            replacement_fact_id = $newFactId
            correction_operation_id = [string]$correction.body.operation_id
            forget_operation_id = [string]$forgotten.body.operation_id
        }
        wiki_closure = [ordered]@{
            source_id = [string]$wikiIngest.source_id
            source_hash = [string]$wikiIngest.source_hash
            run_id = [string]$wikiIngest.run_id
            review_id = [string]$wikiIngest.review_id
            target_path = [string]$wikiIngest.target_path
            artifact_binding_ids = $artifactBindingIds
            documented_in_relation_ids = $documentedInRelationIds
        }
        exit_code = 0
    }
    $exitCode = 0
}
catch {
    $report = [ordered]@{
        schema_version = "llmwiki-memory-journey.v3"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        started_at = $startedAt
        status = "Failed"
        evidence_level = "L3-not-achieved"
        evidence_mode = "real_isolated_sidecar_http_sse_with_read_only_sqlite_validation"
        failure_code = Protect-EvidenceText ([string]$_.Exception.Message)
        failure_trace = Protect-EvidenceText ([string]$_.ScriptStackTrace)
        process_restarts = @($restartEvents)
        exit_code = 1
    }
    $exitCode = 1
}
finally {
    if ($null -ne $sidecar) {
        Stop-JourneySidecar -Process $sidecar
        $sidecar = $null
    }
    Write-JsonEvidence -Name "journey-report.json" -Value $report
    Write-JsonEvidence -Name "process-restarts.json" -Value @($restartEvents)
    $summary = @(
        "# LLMWIKI-004 memory journey",
        "",
        "- status: **$($report.status)**",
        "- evidence level: $($report.evidence_level)",
        "- mode: $($report.evidence_mode)",
        "- process starts: $(@($restartEvents).Count)",
        "- exit code: $exitCode",
        "",
        "The runner changes product state only through authenticated HTTP and SSE. SQLite is opened read-only for lifecycle evidence snapshots.",
        "This result does not claim Electron supervision, packaged recovery, 24-hour stability, or business KPI improvement.",
        ""
    )
    if ($report.status -eq "Failed") {
        $summary += "Failure code: $($report.failure_code)", ""
    }
    Write-Utf8NoBom -Path (Join-Path $resolvedOutput "journey-report.md") -Value ((Protect-EvidenceText ($summary -join "`n")).TrimEnd() + "`n")
    try {
        $runtimeFull = [System.IO.Path]::GetFullPath($runtimeRoot)
        $tempFull = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if (
            $runtimeFull.StartsWith($tempFull, [System.StringComparison]::OrdinalIgnoreCase) -and
            [System.IO.Path]::GetFileName($runtimeFull).StartsWith("agentpet-llmwiki-memory-", [System.StringComparison]::OrdinalIgnoreCase) -and
            (Test-Path -LiteralPath $runtimeFull)
        ) {
            Remove-Item -LiteralPath $runtimeFull -Recurse -Force
        }
    }
    catch {
        Write-Warning "ISOLATED_RUNTIME_CLEANUP_FAILED"
    }
}

exit $exitCode

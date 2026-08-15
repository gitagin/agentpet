[CmdletBinding()]
param(
    [string]$OutputDir = "output\verification\LLMWIKI-006\journey",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 0,
    [int]$StartupTimeoutSeconds = 45
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
$allowedOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "output\verification\LLMWIKI-006"))
if (
    $resolvedOutput -ne $allowedOutputRoot -and
    -not $resolvedOutput.StartsWith(
        $allowedOutputRoot + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )
) {
    Write-Error "OUTPUT_DIR_OUTSIDE_LLMWIKI_006"
    exit 2
}
if ($StartupTimeoutSeconds -lt 5 -or $StartupTimeoutSeconds -gt 300) {
    Write-Error "INVALID_STARTUP_TIMEOUT"
    exit 2
}

function Assert-WikiJourney {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Code
    )
    if (-not $Condition) {
        throw $Code
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

function Protect-EvidenceText {
    param([AllowEmptyString()][string]$Value)

    $protected = [string]$Value
    $replacements = [ordered]@{
        $sessionToken = "[REDACTED_TOKEN]"
        $databasePath = "[ISOLATED_DATABASE]"
        $vaultRoot = "[ISOLATED_VAULT]"
        $runtimeRoot = "[ISOLATED_RUNTIME]"
        $repoRoot = "[REPOSITORY_ROOT]"
    }
    foreach ($secret in $replacements.Keys | Where-Object { $_ }) {
        $protected = $protected.Replace([string]$secret, [string]$replacements[$secret])
        $escapedSecret = ([string]$secret).Replace("\", "\\")
        $protected = $protected.Replace($escapedSecret, [string]$replacements[$secret])
    }
    $protected = [regex]::Replace(
        $protected,
        '(?i)Authorization:\s*Bearer\s+[^\s"'']+',
        'Authorization: Bearer [REDACTED_TOKEN]'
    )
    $protected = [regex]::Replace(
        $protected,
        '(?i)[A-Z]:\\\\\.\.\.\\\\[^"\r\n]+',
        '[REDACTED_PATH_LABEL]'
    )
    return $protected
}

function ConvertTo-LintEvidence {
    param([Parameter(Mandatory = $true)][object]$LintResponse)

    return [ordered]@{
        generated_at = $LintResponse.generated_at
        summary = $LintResponse.summary
        issue_codes = @($LintResponse.issues | ForEach-Object {
            [ordered]@{
                severity = [string]$_.severity
                code = [string]$_.code
                path = [string]$_.path
            }
        })
        report_page = [ordered]@{
            relative_path = [string]$LintResponse.report_page.relative_path
            status = [string]$LintResponse.report_page.status
            action_id = [string]$LintResponse.report_page.action_id
        }
        action_id = [string]$LintResponse.action_id
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )
    Write-LlmWikiUtf8NoBom -Path $Path -Value $Value
}

function Write-JsonEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][object]$Value
    )
    $json = $Value | ConvertTo-Json -Depth 60
    Write-Utf8NoBom -Path (Join-Path $resolvedOutput $Name) -Value ((Protect-EvidenceText $json) + "`n")
}

function Invoke-JourneyApi {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST", "PUT", "PATCH", "DELETE")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body,
        [int]$TimeoutSeconds = 30
    )
    return Invoke-LlmWikiApi `
        -Method $Method `
        -BaseUrl $baseUrl `
        -SessionToken $sessionToken `
        -Path $Path `
        -Body $Body `
        -TimeoutSeconds $TimeoutSeconds
}

function Assert-ApiResponse {
    param(
        [Parameter(Mandatory = $true)][object]$Response,
        [Parameter(Mandatory = $true)][string]$Code
    )
    Assert-WikiJourney ($Response.status -eq 200 -and $null -ne $Response.body) $Code
}

function Invoke-SqliteJsonQuery {
    param([Parameter(Mandatory = $true)][string]$Query)

    $raw = & $sqliteCommand -readonly -json $databasePath $Query 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "SQLITE_READ_FAILED"
    }
    $text = ($raw -join "`n").Trim()
    if (-not $text) {
        return @()
    }
    return (ConvertFrom-Json -InputObject $text)
}

function New-ExtractionFixture {
    param(
        [Parameter(Mandatory = $true)][string]$SourceText,
        [Parameter(Mandatory = $true)][string]$ClaimRef,
        [Parameter(Mandatory = $true)][string]$ClaimPredicate,
        [Parameter(Mandatory = $true)][string]$ClaimValue,
        [Parameter(Mandatory = $true)][string]$ConceptRef,
        [Parameter(Mandatory = $true)][string]$ConceptName
    )

    $end = $SourceText.Length
    return [ordered]@{
        memory_extraction = [ordered]@{
            wrapper_version = "llmwiki.wiki-extraction.v1"
            provenance = "explicit_user"
            payload = [ordered]@{
                schema_version = "llmwiki.entity-extraction.v1"
                entities = @(
                    [ordered]@{
                        entity_ref = "project-atlas"
                        entity_type = "project"
                        name = "Atlas"
                        aliases = @("Atlas project")
                        confidence = 0.98
                        risk_tier = "low"
                        evidence = [ordered]@{ start = 0; end = $end }
                    },
                    [ordered]@{
                        entity_ref = $ConceptRef
                        entity_type = "concept"
                        name = $ConceptName
                        aliases = @()
                        confidence = 0.94
                        risk_tier = "low"
                        evidence = [ordered]@{ start = 0; end = $end }
                    }
                )
                claims = @(
                    [ordered]@{
                        claim_ref = $ClaimRef
                        subject_entity_ref = "project-atlas"
                        predicate = $ClaimPredicate
                        value = $ClaimValue
                        fact_type = "project"
                        confidence = 0.96
                        evidence = [ordered]@{ start = 0; end = $end }
                    }
                )
                relations = @(
                    [ordered]@{
                        subject = [ordered]@{ kind = "entity"; ref = "project-atlas" }
                        relation = "related_to"
                        object = [ordered]@{ kind = "entity"; ref = $ConceptRef }
                        confidence = 0.91
                        evidence = [ordered]@{ start = 0; end = $end }
                    }
                )
                sensitive = @()
                conflicts = @()
                uncertainties = @()
            }
        }
    }
}

function Invoke-IngestLifecycle {
    param(
        [Parameter(Mandatory = $true)][string]$EvidencePrefix,
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][object]$SourceMetadata
    )

    $previewBody = [ordered]@{
        title = $Title
        content = $Content
        source_type = "user_message"
        tags = @("project/Atlas", "reliability")
        links = @()
        max_pages = 1
        source_metadata = $SourceMetadata
    }
    $preview = Invoke-JourneyApi -Method POST -Path "/api/wiki/ingest/preview" -Body $previewBody
    Assert-ApiResponse $preview "${EvidencePrefix}_PREVIEW_FAILED"
    Assert-WikiJourney ([string]$preview.body.status -eq "preview") "${EvidencePrefix}_PREVIEW_STATUS_INVALID"
    Assert-WikiJourney (-not [string]::IsNullOrWhiteSpace([string]$preview.body.preview_token)) "${EvidencePrefix}_TOKEN_MISSING"
    Assert-WikiJourney (@($preview.body.page_plans).Count -eq 1) "${EvidencePrefix}_PAGE_PLAN_COUNT_INVALID"
    Write-JsonEvidence -Name "$EvidencePrefix-preview.json" -Value ([ordered]@{
        request = $previewBody
        response = $preview.body
    })

    $confirmBody = [ordered]@{
        preview_token = [string]$preview.body.preview_token
        user_confirmed = $true
    }
    $confirm = Invoke-JourneyApi -Method POST -Path "/api/wiki/ingest/confirm" -Body $confirmBody
    Assert-ApiResponse $confirm "${EvidencePrefix}_CONFIRM_FAILED"
    Assert-WikiJourney ([string]$confirm.body.status -eq "planned") "${EvidencePrefix}_CONFIRM_STATUS_INVALID"
    Assert-WikiJourney ([string]$confirm.body.source_hash -eq [string]$preview.body.source_hash) "${EvidencePrefix}_SOURCE_HASH_CHANGED"
    Assert-WikiJourney ([string]$confirm.body.source_id -eq [string]$preview.body.source_id) "${EvidencePrefix}_SOURCE_ID_CHANGED"
    Write-JsonEvidence -Name "$EvidencePrefix-confirm.json" -Value $confirm.body

    $review = Invoke-JourneyApi -Method POST -Path "/api/wiki/ingest/review" -Body ([ordered]@{
        run_id = [string]$confirm.body.run_id
    })
    Assert-ApiResponse $review "${EvidencePrefix}_REVIEW_FAILED"
    Assert-WikiJourney ([string]$review.body.status -in @("reviewed", "model_not_configured")) "${EvidencePrefix}_REVIEW_STATUS_INVALID"
    Assert-WikiJourney (-not [string]::IsNullOrWhiteSpace([string]$review.body.review_id)) "${EvidencePrefix}_REVIEW_ID_MISSING"
    $target = [string]$confirm.body.page_plans[0].target_path
    Assert-WikiJourney (@($review.body.recommended_targets) -contains $target) "${EvidencePrefix}_TARGET_NOT_RECOMMENDED"
    Write-JsonEvidence -Name "$EvidencePrefix-review.json" -Value $review.body

    $applyBody = [ordered]@{
        run_id = [string]$confirm.body.run_id
        approved_targets = @($target)
        review_id = [string]$review.body.review_id
        review_acknowledged = $true
    }
    $apply = Invoke-JourneyApi -Method POST -Path "/api/wiki/ingest/apply" -Body $applyBody
    Assert-ApiResponse $apply "${EvidencePrefix}_APPLY_FAILED"
    Assert-WikiJourney ([string]$apply.body.status -eq "applied") "${EvidencePrefix}_APPLY_STATUS_INVALID"
    Assert-WikiJourney ([int]$apply.body.pages_written -eq 1) "${EvidencePrefix}_PAGE_NOT_WRITTEN"
    Assert-WikiJourney ([string]$apply.body.page_results[0].relative_path -eq $target) "${EvidencePrefix}_TARGET_CHANGED"
    Write-JsonEvidence -Name "$EvidencePrefix-apply.json" -Value $apply.body

    return [ordered]@{
        title = $Title
        content = $Content
        source_hash = [string]$confirm.body.source_hash
        source_id = [string]$confirm.body.source_id
        run_id = [string]$confirm.body.run_id
        review_id = [string]$review.body.review_id
        review_status = [string]$review.body.status
        target_path = $target
        confirm_response = $confirm.body
        review_response = $review.body
        apply_body = $applyBody
        apply_response = $apply.body
    }
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    $path = Join-Path $vaultRoot ($RelativePath.Replace("/", [System.IO.Path]::DirectorySeparatorChar))
    Assert-WikiJourney (Test-Path -LiteralPath $path -PathType Leaf) "WIKI_PAGE_MISSING_$RelativePath"
    return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-DatabaseSnapshot {
    param([Parameter(Mandatory = $true)][string]$Stage)

    $snapshot = [ordered]@{
        stage = $Stage
        captured_at = (Get-Date).ToUniversalTime().ToString("o")
        sources = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, source_hash, title, source_type, created_at, updated_at
FROM wiki_sources
ORDER BY source_hash;
"@)
        workflows = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, source_id, status, created_at, updated_at
FROM wiki_workflow_runs
WHERE workflow_type = 'ingest'
ORDER BY created_at, id;
"@)
        reviews = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, run_id, source_id, status, created_at, updated_at
FROM wiki_ingest_reviews
ORDER BY created_at, id;
"@)
        entities = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, entity_type, canonical_name, status, confidence
FROM memory_entities
ORDER BY entity_type, canonical_name, id;
"@)
        facts = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, statement_kind, subject_entity_id, predicate, object, relation_type,
       object_entity_id, status, confidence, source_type
FROM memory_graph_facts
ORDER BY statement_kind, relation_type, predicate, id;
"@)
        evidence = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, fact_id, source_type, source_text_hash, evidence_key
FROM memory_evidence
ORDER BY id;
"@)
        page_bindings = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, vault_id, page_entity_id, wiki_relative_path, content_hash, revision, status
FROM wiki_page_bindings
ORDER BY wiki_relative_path;
"@)
        artifact_bindings = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, fact_id, vault_id, artifact_type, artifact_ref, status
FROM memory_fact_artifact_bindings
ORDER BY artifact_ref, fact_id, artifact_type;
"@)
        actions = @(Invoke-SqliteJsonQuery -Query @"
SELECT id, action_type, status, idempotency_key, target_paths_json, created_at, completed_at
FROM agent_actions
WHERE action_type LIKE 'wiki.%'
ORDER BY created_at, id;
"@)
    }
    Write-JsonEvidence -Name "sqlite-$Stage.json" -Value $snapshot
    return $snapshot
}

function Assert-VerifiedActionReceipts {
    $rows = @(Invoke-SqliteJsonQuery -Query @"
SELECT action_type, status, idempotency_key, metadata_json
FROM agent_actions
WHERE action_type IN (
    'wiki.ingest.confirm', 'wiki.ingest.review', 'wiki.ingest.apply',
    'wiki.synthesize.write', 'wiki.lint.report'
)
ORDER BY created_at, id;
"@)
    Assert-WikiJourney ($rows.Count -eq 9) "WIKI_ACTION_RECEIPT_COUNT_INVALID"
    foreach ($row in $rows) {
        Assert-WikiJourney ([string]$row.status -eq "completed") "WIKI_ACTION_NOT_COMPLETED"
        Assert-WikiJourney ([string]$row.idempotency_key -match '^[0-9a-f]{64}$') "WIKI_IDEMPOTENCY_KEY_INVALID"
        $metadata = [string]$row.metadata_json | ConvertFrom-Json
        Assert-WikiJourney ([string]$metadata.execution_receipt.status -eq "verified") "WIKI_RECEIPT_NOT_VERIFIED"
        Assert-WikiJourney ([string]$metadata.verification_result.status -eq "verified") "WIKI_READBACK_NOT_VERIFIED"
    }
    Write-JsonEvidence -Name "action-receipts.json" -Value ([ordered]@{
        count = $rows.Count
        actions = @($rows | ForEach-Object {
            $metadata = [string]$_.metadata_json | ConvertFrom-Json
            [ordered]@{
                action_type = [string]$_.action_type
                status = [string]$_.status
                idempotency_key_length = ([string]$_.idempotency_key).Length
                receipt_status = [string]$metadata.execution_receipt.status
                verification_status = [string]$metadata.verification_result.status
            }
        })
    })
}

function Start-JourneySidecar {
    $selectedPort = if ($Port -gt 0) { $Port } else { New-LlmWikiIsolatedPort }
    $script:baseUrl = "http://${HostName}:$selectedPort"
    $process = Start-LlmWikiIsolatedSidecar `
        -BackendDir $backendDir `
        -RuntimeRoot $runtimeRoot `
        -SessionToken $sessionToken `
        -Port $selectedPort `
        -HostName $HostName `
        -DatabaseFileName ([System.IO.Path]::GetFileName($databasePath)) `
        -Environment @{
            AGENT_PET_MODEL_BASE_URL = "http://127.0.0.1:9/v1"
            AGENT_PET_EMBEDDING_BASE_URL = "http://127.0.0.1:9/v1"
            AGENT_PET_MODEL_TIMEOUT_SECONDS = "2"
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
    $ordinal = $script:sidecarOrdinal + 1
    $script:sidecarOrdinal = $ordinal
    $stdout = Read-LlmWikiSidecarLog -Process $Process -Stream stdout
    $stderr = Read-LlmWikiSidecarLog -Process $Process -Stream stderr
    Write-Utf8NoBom -Path (Join-Path $resolvedOutput ("sidecar-{0:D2}.stdout.log" -f $ordinal)) -Value ((Protect-EvidenceText $stdout).TrimEnd() + "`n")
    Write-Utf8NoBom -Path (Join-Path $resolvedOutput ("sidecar-{0:D2}.stderr.log" -f $ordinal)) -Value ((Protect-EvidenceText $stderr).TrimEnd() + "`n")
    try { $Process.Dispose() } catch { }
}

function Write-FinalReport {
    param([Parameter(Mandatory = $true)][object]$Value)

    Write-JsonEvidence -Name "wiki-journey-report.json" -Value $Value
    $checks = @($Value.checks)
    $lines = @(
        "# LLM Wiki source-to-decision journey",
        "",
        "- status: **$($Value.status)**",
        "- evidence level: L3 isolated sidecar process",
        "- fixture boundary: $($Value.fixture_boundary)",
        "- source count: $($Value.summary.source_count)",
        "- active extracted claims: $($Value.summary.active_claim_count)",
        "- active extracted relations: $($Value.summary.active_relation_count)",
        "- active Wiki bindings: $($Value.summary.active_wiki_binding_count)",
        "- verified lifecycle receipts: $($Value.summary.verified_receipt_count)",
        "- lint errors: $($Value.summary.lint_errors)",
        "- lint warnings: $($Value.summary.lint_warnings)",
        "",
        "| Check | Result |",
        "| --- | --- |"
    )
    foreach ($check in $checks) {
        $lines += "| $($check.name) | $($check.status) |"
    }
    $lines += @(
        "",
        "## Durable artifacts",
        "",
        "- Source pages: ``$($Value.artifacts.source_paths -join '`, `')``",
        "- Synthesis page: ``$($Value.artifacts.synthesis_path)``",
        "- Decision page: ``$($Value.artifacts.decision_path)``",
        "- SQLite and Markdown hashes are recorded in the JSON evidence without exposing local absolute paths.",
        "",
        "## Boundary",
        "",
        "The versioned extraction fixtures exercise validation, activation, evidence binding, and restart durability. They do not measure a live model's extraction accuracy.",
        ""
    )
    Write-Utf8NoBom -Path (Join-Path $resolvedOutput "wiki-journey-report.md") -Value (($lines -join "`n") + "`n")
}

$backendDir = Join-Path $repoRoot "apps\backend"
$runtimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("agentpet-llmwiki-wiki-" + [Guid]::NewGuid().ToString("N"))
$vaultRoot = Join-Path $runtimeRoot "vault"
$databasePath = Join-Path (Join-Path $runtimeRoot "data") "agent_pet_wiki_journey.sqlite3"
$sessionToken = New-JourneySecret
$sqliteCommand = (Get-Command sqlite3 -ErrorAction SilentlyContinue).Source
$baseUrl = ""
$sidecar = $null
$sidecarOrdinal = 0
$startedAt = (Get-Date).ToUniversalTime().ToString("o")
$report = $null
$exitCode = 1

New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null
Get-ChildItem -LiteralPath $resolvedOutput -File -ErrorAction SilentlyContinue | Remove-Item -Force

try {
    Assert-WikiJourney (Test-Path -LiteralPath $backendDir -PathType Container) "BACKEND_DIR_MISSING"
    Assert-WikiJourney ($null -ne (Get-Command python -ErrorAction SilentlyContinue)) "PYTHON_MISSING"
    Assert-WikiJourney (-not [string]::IsNullOrWhiteSpace($sqliteCommand)) "SQLITE_CLI_MISSING"

    $sidecar = Start-JourneySidecar
    $vault = Invoke-JourneyApi -Method POST -Path "/api/vaults/init" -Body ([ordered]@{
        path = $vaultRoot
        create_if_missing = $true
        confirmed = $true
    })
    Assert-ApiResponse $vault "VAULT_INIT_FAILED"
    Assert-WikiJourney (-not [string]::IsNullOrWhiteSpace([string]$vault.body.vault_id)) "VAULT_ID_MISSING"
    Write-JsonEvidence -Name "00-vault-init.json" -Value ([ordered]@{
        request = [ordered]@{ path = "[ISOLATED_VAULT]"; create_if_missing = $true; confirmed = $true }
        response = $vault.body
    })

    $sourceOneText = "Atlas uses receipt readback before marking Wiki writes complete. This is an explicit user-provided project fact."
    $sourceTwoText = "Atlas keeps SQLite as authority and rebuilds derived graph projections. This is independent explicit user evidence."
    $sourceOne = Invoke-IngestLifecycle `
        -EvidencePrefix "01-source-one" `
        -Title "Atlas Receipt Readback" `
        -Content $sourceOneText `
        -SourceMetadata (New-ExtractionFixture `
            -SourceText $sourceOneText `
            -ClaimRef "claim-receipt-readback" `
            -ClaimPredicate "uses_receipt_readback" `
            -ClaimValue "receipt readback before completion" `
            -ConceptRef "concept-receipt-readback" `
            -ConceptName "Receipt readback")
    $sourceTwo = Invoke-IngestLifecycle `
        -EvidencePrefix "02-source-two" `
        -Title "Atlas Authority Boundary" `
        -Content $sourceTwoText `
        -SourceMetadata (New-ExtractionFixture `
            -SourceText $sourceTwoText `
            -ClaimRef "claim-sqlite-authority" `
            -ClaimPredicate "uses_authority_store" `
            -ClaimValue "SQLite authority with rebuildable projections" `
            -ConceptRef "concept-derived-projection" `
            -ConceptName "Derived graph projection")

    Assert-WikiJourney ($sourceOne.source_hash -ne $sourceTwo.source_hash) "SOURCES_NOT_INDEPENDENT"
    Assert-WikiJourney ($sourceOne.source_id -ne $sourceTwo.source_id) "SOURCE_IDENTITIES_NOT_INDEPENDENT"

    $sourceOneReplayApply = Invoke-JourneyApi -Method POST -Path "/api/wiki/ingest/apply" -Body $sourceOne.apply_body
    Assert-ApiResponse $sourceOneReplayApply "SOURCE_ONE_APPLY_REPLAY_FAILED"
    Assert-WikiJourney (($sourceOneReplayApply.body | ConvertTo-Json -Depth 30 -Compress) -eq ($sourceOne.apply_response | ConvertTo-Json -Depth 30 -Compress)) "SOURCE_ONE_APPLY_RECEIPT_CHANGED"
    Write-JsonEvidence -Name "03-source-one-apply-replay.json" -Value $sourceOneReplayApply.body

    $beforeReimport = Get-DatabaseSnapshot -Stage "before-reimport"
    $reimportedSourceOne = Invoke-IngestLifecycle `
        -EvidencePrefix "04-source-one-reimport" `
        -Title $sourceOne.title `
        -Content $sourceOne.content `
        -SourceMetadata (New-ExtractionFixture `
            -SourceText $sourceOne.content `
            -ClaimRef "claim-receipt-readback" `
            -ClaimPredicate "uses_receipt_readback" `
            -ClaimValue "receipt readback before completion" `
            -ConceptRef "concept-receipt-readback" `
            -ConceptName "Receipt readback")
    Assert-WikiJourney ($reimportedSourceOne.source_hash -eq $sourceOne.source_hash) "SOURCE_ONE_REIMPORT_HASH_CHANGED"
    Assert-WikiJourney ($reimportedSourceOne.source_id -eq $sourceOne.source_id) "SOURCE_ONE_REIMPORT_ID_CHANGED"
    Assert-WikiJourney ($reimportedSourceOne.run_id -eq $sourceOne.run_id) "SOURCE_ONE_REIMPORT_RUN_CHANGED"
    Assert-WikiJourney ($reimportedSourceOne.review_id -eq $sourceOne.review_id) "SOURCE_ONE_REIMPORT_REVIEW_CHANGED"
    Assert-WikiJourney ($reimportedSourceOne.target_path -eq $sourceOne.target_path) "SOURCE_ONE_REIMPORT_TARGET_CHANGED"
    Assert-WikiJourney (($reimportedSourceOne.confirm_response | ConvertTo-Json -Depth 30 -Compress) -eq ($sourceOne.confirm_response | ConvertTo-Json -Depth 30 -Compress)) "SOURCE_ONE_REIMPORT_CONFIRM_RECEIPT_CHANGED"
    Assert-WikiJourney (($reimportedSourceOne.review_response | ConvertTo-Json -Depth 30 -Compress) -eq ($sourceOne.review_response | ConvertTo-Json -Depth 30 -Compress)) "SOURCE_ONE_REIMPORT_REVIEW_RECEIPT_CHANGED"
    Assert-WikiJourney (($reimportedSourceOne.apply_response | ConvertTo-Json -Depth 30 -Compress) -eq ($sourceOne.apply_response | ConvertTo-Json -Depth 30 -Compress)) "SOURCE_ONE_REIMPORT_APPLY_RECEIPT_CHANGED"
    $afterReimport = Get-DatabaseSnapshot -Stage "after-reimport"
    Assert-WikiJourney (@($afterReimport.sources).Count -eq @($beforeReimport.sources).Count) "SOURCE_ONE_REIMPORT_DUPLICATED_SOURCE"
    Assert-WikiJourney (@($afterReimport.workflows).Count -eq @($beforeReimport.workflows).Count) "SOURCE_ONE_REIMPORT_DUPLICATED_WORKFLOW"
    Assert-WikiJourney (@($afterReimport.reviews).Count -eq @($beforeReimport.reviews).Count) "SOURCE_ONE_REIMPORT_DUPLICATED_REVIEW"
    Assert-WikiJourney (@($afterReimport.entities).Count -eq @($beforeReimport.entities).Count) "SOURCE_ONE_REIMPORT_DUPLICATED_ENTITY"
    Assert-WikiJourney (@($afterReimport.facts).Count -eq @($beforeReimport.facts).Count) "SOURCE_ONE_REIMPORT_DUPLICATED_FACT_OR_RELATION"
    Assert-WikiJourney (@($afterReimport.page_bindings).Count -eq @($beforeReimport.page_bindings).Count) "SOURCE_ONE_REIMPORT_DUPLICATED_PAGE_BINDING"
    Assert-WikiJourney (@($afterReimport.artifact_bindings).Count -eq @($beforeReimport.artifact_bindings).Count) "SOURCE_ONE_REIMPORT_DUPLICATED_ARTIFACT_BINDING"
    Assert-WikiJourney (@($afterReimport.actions).Count -eq @($beforeReimport.actions).Count) "SOURCE_ONE_REIMPORT_DUPLICATED_ACTION"

    $sourcePaths = @($sourceOne.target_path, $sourceTwo.target_path)
    $synthesisBody = [ordered]@{
        title = "Atlas Reliable Wiki Writes"
        content = "Atlas combines receipt readback with an authoritative SQLite store; graph projections remain derived and rebuildable."
        source_paths = $sourcePaths
        tags = @("atlas", "reliability")
        links = @()
        page_type = "synthesis"
        evidence_ids = @()
        entity_ids = @()
        fact_ids = @()
    }
    $synthesis = Invoke-JourneyApi -Method POST -Path "/api/wiki/synthesize" -Body $synthesisBody
    Assert-ApiResponse $synthesis "SYNTHESIS_FAILED"
    Assert-WikiJourney ([string]$synthesis.body.page.relative_path -eq "Wiki/Syntheses/Atlas-Reliable-Wiki-Writes.md") "SYNTHESIS_PATH_INVALID"
    Assert-WikiJourney ([string]$synthesis.body.page.status -in @("created", "updated")) "SYNTHESIS_NOT_WRITTEN"
    Assert-WikiJourney (-not [string]::IsNullOrWhiteSpace([string]$synthesis.body.action_id)) "SYNTHESIS_ACTION_ID_MISSING"
    Write-JsonEvidence -Name "05-synthesis.json" -Value ([ordered]@{ request = $synthesisBody; response = $synthesis.body })

    $decisionBody = [ordered]@{
        title = "Use SQLite as the Wiki authority"
        content = "The two independent sources were reviewed for durability and recoverability."
        source_paths = $sourcePaths
        tags = @("atlas", "decision")
        links = @("Wiki/Syntheses/Atlas-Reliable-Wiki-Writes.md")
        page_type = "decision"
        user_decision = "Use SQLite as the authority store and keep the graph projection rebuildable."
        evidence_ids = @()
        entity_ids = @()
        fact_ids = @()
    }
    $decision = Invoke-JourneyApi -Method POST -Path "/api/wiki/synthesize" -Body $decisionBody
    Assert-ApiResponse $decision "DECISION_FAILED"
    Assert-WikiJourney ([string]$decision.body.page.relative_path -eq "Wiki/Decisions/Use-SQLite-as-the-Wiki-authority.md") "DECISION_PATH_INVALID"
    Assert-WikiJourney (-not [string]::IsNullOrWhiteSpace([string]$decision.body.action_id)) "DECISION_ACTION_ID_MISSING"
    Write-JsonEvidence -Name "06-decision.json" -Value ([ordered]@{ request = $decisionBody; response = $decision.body })

    $synthesisPath = [string]$synthesis.body.page.relative_path
    $decisionPath = [string]$decision.body.page.relative_path
    $sourceOneHash = Get-FileSha256 -RelativePath $sourceOne.target_path
    $sourceTwoHash = Get-FileSha256 -RelativePath $sourceTwo.target_path
    $synthesisHash = Get-FileSha256 -RelativePath $synthesisPath
    $decisionHash = Get-FileSha256 -RelativePath $decisionPath
    Write-JsonEvidence -Name "07-markdown-hashes-before-restart.json" -Value ([ordered]@{
        pages = @(
            [ordered]@{ relative_path = $sourceOne.target_path; sha256 = $sourceOneHash },
            [ordered]@{ relative_path = $sourceTwo.target_path; sha256 = $sourceTwoHash },
            [ordered]@{ relative_path = $synthesisPath; sha256 = $synthesisHash },
            [ordered]@{ relative_path = $decisionPath; sha256 = $decisionHash }
        )
    })

    $beforeRestart = Get-DatabaseSnapshot -Stage "before-restart"
    $activeExtractedClaims = @($beforeRestart.facts | Where-Object {
        $_.statement_kind -eq "claim" -and $_.status -eq "active" -and $_.source_type -eq "user_message"
    })
    $activeExtractedRelations = @($beforeRestart.facts | Where-Object {
        $_.statement_kind -eq "relation" -and $_.relation_type -eq "related_to" -and $_.status -eq "active"
    })
    Assert-WikiJourney ($activeExtractedClaims.Count -eq 2) "ACTIVE_EXTRACTED_CLAIM_COUNT_INVALID"
    Assert-WikiJourney ($activeExtractedRelations.Count -eq 2) "ACTIVE_EXTRACTED_RELATION_COUNT_INVALID"
    Assert-WikiJourney (@($beforeRestart.sources).Count -eq 2) "SOURCE_ROW_COUNT_INVALID"
    Assert-WikiJourney (@($beforeRestart.page_bindings | Where-Object { $_.status -eq "active" }).Count -eq 4) "ACTIVE_PAGE_BINDING_COUNT_INVALID"
    Assert-WikiJourney (@($beforeRestart.artifact_bindings | Where-Object { $_.status -eq "active" }).Count -ge 8) "ARTIFACT_BINDINGS_MISSING"

    $firstProcessId = $sidecar.Id
    Stop-JourneySidecar -Process $sidecar
    $sidecar = $null
    $sidecar = Start-JourneySidecar
    Assert-WikiJourney ($sidecar.Id -ne $firstProcessId) "SIDECAR_RESTART_NOT_REAL"

    $vaultStatus = Invoke-JourneyApi -Method GET -Path "/api/vaults/status"
    Assert-ApiResponse $vaultStatus "VAULT_STATUS_AFTER_RESTART_FAILED"
    Assert-WikiJourney ([bool]$vaultStatus.body.configured) "VAULT_NOT_RESTORED_AFTER_RESTART"
    Assert-WikiJourney ([string]$vaultStatus.body.active_vault_id -eq [string]$vault.body.vault_id) "ACTIVE_VAULT_CHANGED_AFTER_RESTART"
    Write-JsonEvidence -Name "08-vault-after-restart.json" -Value $vaultStatus.body

    $pagesAfterRestart = Invoke-JourneyApi -Method GET -Path "/api/wiki/pages"
    Assert-ApiResponse $pagesAfterRestart "WIKI_PAGES_AFTER_RESTART_FAILED"
    $pathsAfterRestart = @($pagesAfterRestart.body.pages | ForEach-Object { [string]$_.relative_path })
    foreach ($requiredPath in @($sourceOne.target_path, $sourceTwo.target_path, $synthesisPath, $decisionPath)) {
        Assert-WikiJourney ($pathsAfterRestart -contains $requiredPath) "WIKI_PAGE_NOT_RESTORED_$requiredPath"
    }
    Assert-WikiJourney ((Get-FileSha256 $sourceOne.target_path) -eq $sourceOneHash) "SOURCE_ONE_HASH_CHANGED_AFTER_RESTART"
    Assert-WikiJourney ((Get-FileSha256 $sourceTwo.target_path) -eq $sourceTwoHash) "SOURCE_TWO_HASH_CHANGED_AFTER_RESTART"
    Assert-WikiJourney ((Get-FileSha256 $synthesisPath) -eq $synthesisHash) "SYNTHESIS_HASH_CHANGED_AFTER_RESTART"
    Assert-WikiJourney ((Get-FileSha256 $decisionPath) -eq $decisionHash) "DECISION_HASH_CHANGED_AFTER_RESTART"
    Write-JsonEvidence -Name "09-pages-after-restart.json" -Value $pagesAfterRestart.body

    $afterRestart = Get-DatabaseSnapshot -Stage "after-restart"
    Assert-WikiJourney (@($afterRestart.sources).Count -eq @($beforeRestart.sources).Count) "SOURCE_COUNT_CHANGED_AFTER_RESTART"
    Assert-WikiJourney (@($afterRestart.entities).Count -eq @($beforeRestart.entities).Count) "ENTITY_COUNT_CHANGED_AFTER_RESTART"
    Assert-WikiJourney (@($afterRestart.facts).Count -eq @($beforeRestart.facts).Count) "FACT_COUNT_CHANGED_AFTER_RESTART"
    Assert-WikiJourney (@($afterRestart.page_bindings).Count -eq @($beforeRestart.page_bindings).Count) "PAGE_BINDING_COUNT_CHANGED_AFTER_RESTART"
    Assert-WikiJourney (@($afterRestart.artifact_bindings).Count -eq @($beforeRestart.artifact_bindings).Count) "ARTIFACT_BINDING_COUNT_CHANGED_AFTER_RESTART"

    $lint = Invoke-JourneyApi -Method POST -Path "/api/wiki/lint" -Body ([ordered]@{ write_report = $true })
    Assert-ApiResponse $lint "WIKI_LINT_FAILED"
    Assert-WikiJourney ([int]$lint.body.summary.errors -eq 0) "WIKI_LINT_ERRORS_PRESENT"
    Assert-WikiJourney (-not [string]::IsNullOrWhiteSpace([string]$lint.body.report_page.relative_path)) "WIKI_LINT_REPORT_MISSING"
    Assert-WikiJourney (-not [string]::IsNullOrWhiteSpace([string]$lint.body.action_id)) "WIKI_LINT_ACTION_ID_MISSING"
    Write-JsonEvidence -Name "10-lint.json" -Value (ConvertTo-LintEvidence -LintResponse $lint.body)

    $index = Invoke-JourneyApi -Method GET -Path "/api/wiki/index"
    Assert-ApiResponse $index "WIKI_INDEX_FAILED"
    $indexedPaths = @($index.body.entries | ForEach-Object { [string]$_.relative_path })
    foreach ($requiredPath in @($sourceOne.target_path, $sourceTwo.target_path, $synthesisPath, $decisionPath)) {
        Assert-WikiJourney ($indexedPaths -contains $requiredPath) "WIKI_INDEX_MISSING_$requiredPath"
    }
    Write-JsonEvidence -Name "11-index.json" -Value $index.body

    Assert-VerifiedActionReceipts
    $verifiedReceiptRows = @(Invoke-SqliteJsonQuery -Query @"
SELECT id
FROM agent_actions
WHERE action_type IN (
    'wiki.ingest.confirm', 'wiki.ingest.review', 'wiki.ingest.apply',
    'wiki.synthesize.write', 'wiki.lint.report'
)
AND status = 'completed';
"@)
    $verifiedReceipts = $verifiedReceiptRows.Count

    $report = [ordered]@{
        schema_version = "llmwiki.wiki-journey.v1"
        status = "Passed"
        started_at = $startedAt
        completed_at = (Get-Date).ToUniversalTime().ToString("o")
        fixture_boundary = "Deterministic versioned extraction fixtures prove the lifecycle contract, not live-model extraction quality."
        summary = [ordered]@{
            source_count = 2
            active_claim_count = $activeExtractedClaims.Count
            active_relation_count = $activeExtractedRelations.Count
            active_wiki_binding_count = 4
            verified_receipt_count = $verifiedReceipts
            lint_errors = [int]$lint.body.summary.errors
            lint_warnings = [int]$lint.body.summary.warnings
        }
        checks = @(
            [ordered]@{ name = "isolated SQLite and Vault"; status = "Passed" },
            [ordered]@{ name = "preview-confirm-review-apply for two independent sources"; status = "Passed" },
            [ordered]@{ name = "versioned explicit-user entity, claim, and relation activation"; status = "Passed" },
            [ordered]@{ name = "Markdown and SQLite authoritative bindings"; status = "Passed" },
            [ordered]@{ name = "full repeated import without duplicate durable effects"; status = "Passed" },
            [ordered]@{ name = "two-source grounded synthesis"; status = "Passed" },
            [ordered]@{ name = "explicit user decision page"; status = "Passed" },
            [ordered]@{ name = "real sidecar restart durability"; status = "Passed" },
            [ordered]@{ name = "Wiki lint with zero errors"; status = "Passed" },
            [ordered]@{ name = "verified lifecycle receipts and authoritative readback"; status = "Passed" }
        )
        artifacts = [ordered]@{
            source_hashes = @($sourceOne.source_hash, $sourceTwo.source_hash)
            source_paths = $sourcePaths
            synthesis_path = $synthesisPath
            decision_path = $decisionPath
            lint_report_path = [string]$lint.body.report_page.relative_path
            markdown_sha256 = [ordered]@{
                source_one = $sourceOneHash
                source_two = $sourceTwoHash
                synthesis = $synthesisHash
                decision = $decisionHash
            }
        }
    }
    Write-FinalReport -Value $report
    $exitCode = 0
}
catch {
    $safeError = Protect-EvidenceText ([string]$_.Exception.Message)
    $report = [ordered]@{
        schema_version = "llmwiki.wiki-journey.v1"
        status = "Failed"
        started_at = $startedAt
        completed_at = (Get-Date).ToUniversalTime().ToString("o")
        fixture_boundary = "Deterministic versioned extraction fixtures prove the lifecycle contract, not live-model extraction quality."
        error_code = $safeError
        summary = [ordered]@{
            source_count = 0
            active_claim_count = 0
            active_relation_count = 0
            active_wiki_binding_count = 0
            verified_receipt_count = 0
            lint_errors = -1
            lint_warnings = -1
        }
        checks = @([ordered]@{ name = "journey completion"; status = "Failed: $safeError" })
        artifacts = [ordered]@{
            source_paths = @()
            synthesis_path = ""
            decision_path = ""
        }
    }
    Write-FinalReport -Value $report
    Write-Error $safeError
    $exitCode = 1
}
finally {
    if ($null -ne $sidecar) {
        Stop-JourneySidecar -Process $sidecar
    }
}

if ($exitCode -eq 0) {
    Write-Host "LLMWIKI-006 wiki journey: PASS"
    Write-Host "Report: $resolvedOutput\wiki-journey-report.json"
}
exit $exitCode

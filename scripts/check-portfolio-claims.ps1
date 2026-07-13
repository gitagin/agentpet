param()

$ErrorActionPreference = "Stop"
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Failures = [System.Collections.Generic.List[string]]::new()

$PublicClaimFiles = @(
    (Join-Path $RepoRoot "README.md")
)
$PublicClaimFiles += @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot "docs\portfolio") -Filter "*.md" -File -ErrorAction SilentlyContinue | ForEach-Object FullName)
$PublicClaimFiles += @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot "docs\architecture") -Filter "*.md" -File -ErrorAction SilentlyContinue | ForEach-Object FullName)

if ($PublicClaimFiles.Count -lt 5) {
    $Failures.Add("Expected README plus portfolio and architecture public claim files.")
}

$ForbiddenClaims = @(
    "fully autonomous",
    "production-grade",
    "enterprise-grade",
    "self-healing",
    "zero hallucination",
    "guaranteed accuracy",
    "unlimited multi-agent",
    "packaged portfolio demo is complete",
    "reranked hybrid RAG is enabled"
)

foreach ($Path in $PublicClaimFiles) {
    $Content = Get-Content -LiteralPath $Path -Raw -Encoding utf8
    foreach ($Claim in $ForbiddenClaims) {
        if ($Content.IndexOf($Claim, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $Failures.Add("Forbidden claim '$Claim' in $Path")
        }
    }
    if ($Content -match '(?i)(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|xoxb-[A-Za-z0-9-]{16,}|AKIA[A-Z0-9]{16}') {
        $Failures.Add("Credential-shaped value found in $Path")
    }
    if ($Content -match '(?i)Authorization:\s*Bearer\s+(?!dev-token\b|\.\.\.\b|<)[A-Za-z0-9._-]{8,}') {
        $Failures.Add("Bearer value found in $Path")
    }
    if ($Content -match '(?i)[A-Z]:\\Users\\[^\\\s]+') {
        $Failures.Add("Private Windows user path found in $Path")
    }
}

$MatrixPath = Join-Path $RepoRoot "docs\portfolio\claim-evidence-index.md"
if (-not (Test-Path -LiteralPath $MatrixPath -PathType Leaf)) {
    $Failures.Add("Claim evidence index is missing.")
}
else {
    $Matrix = Get-Content -LiteralPath $MatrixPath -Raw -Encoding utf8
    foreach ($Required in @(
        "simple social chat may use a fast path",
        "SQLite and Markdown are authoritative",
        "agent-pet-retrieval-synthetic-v1.0.0",
        "TASK-1215",
        "Defer",
        "TASK-1216"
    )) {
        if ($Matrix.IndexOf($Required, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
            $Failures.Add("Claim evidence index is missing '$Required'.")
        }
    }
}

if (Get-Command git -ErrorAction SilentlyContinue) {
    Push-Location $RepoRoot
    try {
        $TrackedState = @(git ls-files | Where-Object { $_ -match '(?i)\.(db|sqlite|sqlite3|dpapi|key|pem)$' })
        if ($LASTEXITCODE -ne 0) {
            $Failures.Add("git ls-files failed while checking tracked local state.")
        }
        elseif ($TrackedState.Count -gt 0) {
            $Failures.Add("Tracked credential/database artifacts: $($TrackedState -join ', ')")
        }
    }
    finally {
        Pop-Location
    }
}

if ($Failures.Count -gt 0) {
    Write-Host "Portfolio claim gate failed:"
    foreach ($Failure in $Failures) { Write-Host "- $Failure" }
    exit 1
}

Write-Host "Portfolio claim gate passed."
Write-Host "Checked $($PublicClaimFiles.Count) public claim files; no forbidden claim, credential-shaped value, private user path, or tracked local-state artifact was found."

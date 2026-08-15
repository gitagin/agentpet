param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Failures = [System.Collections.Generic.List[string]]::new()

function Add-Failure([string]$Message) {
    [void]$Failures.Add($Message)
}

function Read-Utf8([string]$Path) {
    return [System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($false, $true))
}

function Local-Context([string]$Text, [int]$Index, [int]$Length) {
    $radius = 120
    $start = [Math]::Max(0, $Index - $radius)
    $end = [Math]::Min($Text.Length, $Index + $Length + $radius)
    return $Text.Substring($start, $end - $start)
}

function Line-Number([string]$Text, [int]$Index) {
    if ($Index -le 0) { return 1 }
    return 1 + ([regex]::Matches($Text.Substring(0, $Index), "`n").Count)
}

function Is-Explicit-Limitation([string]$Context) {
    # A claim is acceptable only when the same local sentence explicitly
    # denies it, marks it unverified/partial, or says evidence is insufficient.
    return $Context -match '(?is)(?:not\s+(?:a\s+)?claim|not\s+(?:a|an)\b|not\s+(?:proven|verified|supported|enabled|available|guaranteed|suitable|the\s+authority|default)|does\s+not\s+(?:prove|provide|resume|mean|imply)|do\s+not\s+(?:claim|call|describe|present)|must\s+not\s+(?:claim|present)|cannot\s+(?:claim|prove|guarantee)|without\s+(?:evidence|a\s+denominator)|no\s+(?:real|accepted|general|hosted|universal|business|team|enterprise|parallel|unlimited)|unverified|unproven|unclaimed|insufficient[_\s-]*sample|partial|defer|excluded|deliberately\s+unclaimed|not\s+fully|not\s+yet|\u975e\u76ee\u6807|\u4e0d\u5f97|\u4e0d\u80fd|\u4e0d\u7b49\u4e8e|\u4e0d\u63d0\u4f9b|\u4e0d\u5ba3\u79f0|\u4e0d\u80fd\u8bc1\u660e|\u4e0d\u4ee3\u8868|\u4e0d\u4f5c\u4e3a|\u4e0d\u652f\u6301|\u672a(?:\u5b8c\u6210|\u9a8c\u8bc1|\u8bc1\u660e|\u8fd0\u884c|\u901a\u8fc7)|\u5c1a\u672a|\u6ca1\u6709|\u8bc1\u636e\u4e0d\u8db3|\u5f85\u4eba\u5de5|\u4ec5(?:\u4f5c|\u4e3a)|\u53ea(?:\u80fd|\u8bc1\u660e|\u8bb0\u5f55)|\u4e0d\u5e94|\u4e0d\u53ef)'
}

function Check-RepositoryPathReferences([string]$Content, [string]$SourcePath) {
    # Public evidence links must resolve in this checkout; a prose claim is not
    # auditable when its cited file was renamed or never existed.
    $pattern = '`(?<path>(?:apps|docs|scripts|output|vault)[\\/][^`\r\n\s]+)'
    foreach ($Match in [regex]::Matches($Content, $pattern)) {
        $Candidate = [string]$Match.Groups['path'].Value
        if ($Candidate.Contains('::')) {
            $Candidate = $Candidate.Substring(0, $Candidate.IndexOf('::', [System.StringComparison]::Ordinal))
        }
        $Candidate = $Candidate.TrimEnd(',', ';', ':', ')', ']')
        if ([string]::IsNullOrWhiteSpace($Candidate) -or $Candidate.Contains('*')) { continue }
        try {
            $Resolved = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot ($Candidate -replace '/', '\')))
        }
        catch {
            $line = Line-Number $Content $Match.Index
            Add-Failure "Invalid repository evidence path in ${SourcePath}:$line -> '$Candidate'"
            continue
        }
        $rootPrefix = $RepoRoot.TrimEnd('\') + '\'
        if (-not $Resolved.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $line = Line-Number $Content $Match.Index
            Add-Failure "Repository evidence path escapes checkout in ${SourcePath}:$line -> '$Candidate'"
        }
        elseif (-not (Test-Path -LiteralPath $Resolved)) {
            $line = Line-Number $Content $Match.Index
            Add-Failure "Missing repository evidence path in ${SourcePath}:$line -> '$Candidate'"
        }
    }
}

$PublicClaimFiles = @(
    (Join-Path $RepoRoot "README.md"),
    (Join-Path $RepoRoot "PRODUCT.md"),
    (Join-Path $RepoRoot "docs\current-specification.md"),
    (Join-Path $RepoRoot "docs\architecture\verified-system.md"),
    (Join-Path $RepoRoot "docs\mvp-acceptance-coverage.md"),
    (Join-Path $RepoRoot "docs\runbook.md"),
    (Join-Path $RepoRoot "docs\evals\retrieval-evaluation-contract.md")
)
$PublicClaimFiles += @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot "docs\portfolio") -Filter "*.md" -File -ErrorAction SilentlyContinue | ForEach-Object FullName)
$PublicClaimFiles = @($PublicClaimFiles | Select-Object -Unique)

foreach ($Path in $PublicClaimFiles) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Add-Failure "Public claim file is missing: $Path"
    }
}

if ($PublicClaimFiles.Count -lt 11) {
    Add-Failure "Expected README, PRODUCT, current specification, architecture, acceptance, runbook, eval contract and portfolio claim files."
}

$ForbiddenPatterns = @(
    @{ Name = "exactly-once guarantee"; Regex = '(?i)\bexactly[\s-]*once\b|\u6070\u597d\u4e00\u6b21|\u7cbe\u786e\u4e00\u6b21' },
    @{ Name = "24x7/always-online claim"; Regex = '(?i)24\s*[x\u00d7*/]\s*7|\u5168\u5929(?:\u5728\u7ebf|\u5019)|always[\s-]*on(?:line)?|around[\s-]*the[\s-]*clock|continuous\s+uptime|24[\s-]*hour(?:s)?\s+(?:availability|online|uptime|service)|24\s*\u5c0f\u65f6\s*(?:\u8fd0\u884c|\u5728\u7ebf|\u53ef\u7528|\u7a33\u5b9a)' },
    @{ Name = "enterprise claim"; Regex = '(?i)\benterprise(?:[\s-]*grade)?\b|\u4f01\u4e1a(?:\u7ea7|\u79df\u6237|\u5e73\u53f0)|multi[\s-]*tenant' },
    @{ Name = "GraphRAG claim"; Regex = '(?i)\bgraph[\s-]*rag\b|graphrag|\u56fe\u8c31\s*RAG' },
    @{ Name = "unbounded agent claim"; Regex = '(?i)\bunlimited\s+(?:agents?|multi[\s-]*agent)|\u65e0\u9650(?:\u591a|\u4e2a)?\s*Agent|\b(?:multi|multiple)\s*[- ]?agents?\b|\u591a\s*Agent|parallel\s+(?:expert|specialist)\s+(?:swarm|agents?)|\u5e76\u884c\u4e13\u5bb6(?:\u7fa4\u4f53|\u96c6\u7fa4)' },
    @{ Name = "guaranteed accuracy claim"; Regex = '(?i)\b(?:guaranteed|100%|zero)\s+(?:accuracy|hallucination|error)\b|guaranteed\s+answer|\u4fdd\u8bc1(?:\u51c6\u786e|\u65e0\u5e7b\u89c9)|\u51c6\u786e\u7387\s*100%' },
    @{ Name = "production-grade/self-healing claim"; Regex = '(?i)\bproduction[\s-]*grade\b|\bself[\s-]*healing\b|\u751f\u4ea7\u7ea7|\u751f\u4ea7\u5c31\u7eea|\u81ea\u52a8\u81ea\u6108|\u81ea\u6108\u7cfb\u7edf' },
    @{ Name = "unqualified production receipt"; Regex = '(?i)\bproduction\s+(?:execution\s+)?receipts?\s+(?:are|is)\s+(?:fully\s+)?(?:wired|integrated|verified|complete)|\u751f\u4ea7(?:\u5df2|\u5df2\u7ecf)?\u63a5\u5165(?:\u4e86)?(?:\u6267\u884c)?\u56de\u6267' },
    @{ Name = "unmeasured business uplift"; Regex = '(?i)\b(?:business|productivity|efficiency|retention|revenue)\s+(?:uplift|improvement|increase|gain)\b|(?:\u6548\u7387|\u751f\u4ea7\u529b|\u7559\u5b58|\u6536\u5165|\u4e1a\u52a1|\u4e1a\u52a1\u6307\u6807)(?:\u63d0\u5347|\u63d0\u9ad8|\u589e\u957f|\u6539\u5584)\s*\d{0,3}%?|(?:\u8282\u7701|\u51cf\u5c11)\s*\d{1,3}%' }
)

foreach ($Path in $PublicClaimFiles) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { continue }
    try {
        $Content = Read-Utf8 $Path
    }
    catch {
        Add-Failure "File is not valid strict UTF-8: $Path"
        continue
    }

    if ($Content -match "(?m)[ \t]+$") {
        Add-Failure "Trailing whitespace in $Path"
    }
    if ($Content -match '(?i)(?:^|[\s`])(?:TODO|TBD|\u5f85\u5b9a)(?:$|[\s`])') {
        Add-Failure "Placeholder marker found in $Path"
    }
    if ($Content -match "(?i)TASK-\d{4}") {
        Add-Failure "Obsolete TASK-* evidence reference found in $Path"
    }
    if ($Content -match "(?i)(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|xoxb-[A-Za-z0-9-]{16,}|AKIA[A-Z0-9]{16}") {
        Add-Failure "Credential-shaped value found in $Path"
    }
    if ($Content -match "(?i)Authorization:\s*Bearer\s+(?!dev-token\b|\.\.\.\b|<)[A-Za-z0-9._-]{8,}") {
        Add-Failure "Bearer value found in $Path"
    }
    if ($Content -match "(?i)[A-Z]:\\Users\\[^\\\s`]+") {
        Add-Failure "Private Windows user path found in $Path"
    }

    Check-RepositoryPathReferences $Content $Path

    foreach ($Pattern in $ForbiddenPatterns) {
        $matches = [regex]::Matches($Content, $Pattern.Regex)
        foreach ($Match in $matches) {
            $Context = Local-Context $Content $Match.Index $Match.Length
            if (-not (Is-Explicit-Limitation $Context)) {
                $line = Line-Number $Content $Match.Index
                Add-Failure "Unqualified $($Pattern.Name) in ${Path}:$line -> '$($Match.Value)'"
            }
        }
    }
}

$MatrixPath = Join-Path $RepoRoot "docs\portfolio\claim-evidence-index.md"
if (-not (Test-Path -LiteralPath $MatrixPath -PathType Leaf)) {
    Add-Failure "Claim evidence index is missing."
}
else {
    $Matrix = Read-Utf8 $MatrixPath
    foreach ($Required in @(
        "ActionLifecycleCoordinator",
        "apps/backend/app/api/services/adapters.py",
        "apps/backend/tests/test_action_lifecycle_wiring.py",
        "apps/backend/app/services/memory_graph_kuzu.py",
        "apps/backend/app/api/memory/graph.py",
        "SQLite",
        "Markdown",
        "FTS5",
        "agent-pet-retrieval-synthetic-v1.0.0",
        "output/verification/LLMWIKI-011/eval/report.json",
        "output/verification/LLMWIKI-013/faults/fault-matrix-report.md",
        "output/verification/LLMWIKI-013/visual/visual-report.json",
        "insufficient_sample",
        "Partial"
    )) {
        if ($Matrix.IndexOf($Required, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
            Add-Failure "Claim evidence index is missing current evidence '$Required'."
        }
    }
}

foreach ($EvidencePath in @(
    "apps/backend/app/api/services/adapters.py",
    "apps/backend/tests/test_action_lifecycle_wiring.py",
    "apps/backend/tests/test_production_checkpoint_resume.py",
    "apps/backend/tests/test_production_action_recovery.py",
    "apps/backend/app/services/memory_graph_kuzu.py",
    "apps/backend/app/api/memory/graph.py",
    "output/verification/LLMWIKI-011/eval/report.json",
    "output/verification/LLMWIKI-013/faults/fault-matrix-report.md",
    "output/verification/LLMWIKI-013/visual/visual-report.json"
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot $EvidencePath) -PathType Leaf)) {
        Add-Failure "Required evidence path is missing: $EvidencePath"
    }
}

if (Get-Command git -ErrorAction SilentlyContinue) {
    Push-Location $RepoRoot
    try {
        $TrackedState = @(git ls-files | Where-Object { $_ -match "(?i)\.(db|sqlite|sqlite3|dpapi|key|pem)$" })
        if ($LASTEXITCODE -ne 0) {
            Add-Failure "git ls-files failed while checking tracked local state."
        }
        elseif ($TrackedState.Count -gt 0) {
            Add-Failure "Tracked credential/database artifacts: $($TrackedState -join ', ')"
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
Write-Host "Checked $($PublicClaimFiles.Count) public claim files, current evidence paths, credential patterns, limitation context and tracked local-state extensions."

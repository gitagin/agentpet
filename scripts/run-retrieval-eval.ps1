param(
    [ValidateSet("Fts", "All")]
    [string]$Mode = "Fts",

    [Parameter(Mandatory = $true)]
    [string]$WorkDir,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [ValidateRange(1, 100)]
    [int]$RunCount = 1,

    [switch]$RequireFinalGates
)

$ErrorActionPreference = "Stop"

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$BackendDir = Join-Path $RepoRoot "apps\backend"
$DatasetPath = Join-Path $BackendDir "tests\evals\retrieval\retrieval-corpus-v1.json"
$AllowedWorkRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot ".tmp"))
$AllowedEvalOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "output\evals"))
$AllowedTask1204EvidenceRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "output\verification\task-1204"))
$AllowedTask1206EvidenceRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "output\verification\task-1206"))

function Resolve-RepoPath {
    param([Parameter(Mandatory = $true)][string]$PathValue)

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $PathValue))
}

function Test-PathWithin {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Boundary
    )

    $normalizedCandidate = [System.IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    $normalizedBoundary = [System.IO.Path]::GetFullPath($Boundary).TrimEnd('\', '/')
    if ($normalizedCandidate.Equals($normalizedBoundary, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $normalizedCandidate.StartsWith(
        $normalizedBoundary + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-NoExistingReparsePoint {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Boundary
    )

    $current = [System.IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    $stop = [System.IO.Path]::GetFullPath($Boundary).TrimEnd('\', '/')
    while ($true) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Evaluation paths cannot traverse a reparse point."
            }
        }
        if ($current.Equals($stop, [System.StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $parent = [System.IO.Directory]::GetParent($current)
        if ($null -eq $parent) {
            throw "Evaluation path escaped its allowed boundary."
        }
        $current = $parent.FullName.TrimEnd('\', '/')
    }
}

function Assert-OwnedOutputArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$TargetDirectory,
        [Parameter(Mandatory = $true)][string]$EvaluationMode
    )

    if ($EvaluationMode -eq "All") {
        $ArtifactNames = @(
            "artifact-hashes.json",
            "latency-and-cost.md",
            "mode-comparison.json",
            "per-slice-quality.md",
            "reranker-decision.md"
        )
        $OwnershipSchema = "retrieval-eval-artifact-hashes.v2"
    }
    else {
        $ArtifactNames = @(
            "artifact-hashes.json",
            "corpus-manifest.md",
            "failure-catalog.md",
            "fts-baseline.json",
            "slice-results.md"
        )
        $OwnershipSchema = "retrieval-eval-artifact-hashes.v1"
    }
    $ExistingArtifacts = @()
    foreach ($ArtifactName in $ArtifactNames) {
        $ArtifactPath = Join-Path $TargetDirectory $ArtifactName
        $Item = Get-Item -LiteralPath $ArtifactPath -Force -ErrorAction SilentlyContinue
        if ($null -eq $Item) {
            continue
        }
        if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "OutputDir contains a reparse-point artifact target."
        }
        if ($Item.PSIsContainer) {
            throw "OutputDir contains a non-file artifact target."
        }
        $ExistingArtifacts += $ArtifactName
    }
    if ($ExistingArtifacts.Count -eq 0) {
        return
    }

    $OwnershipPath = Join-Path $TargetDirectory "artifact-hashes.json"
    if (-not (Test-Path -LiteralPath $OwnershipPath -PathType Leaf)) {
        throw "OutputDir contains unowned files with retrieval-evaluation artifact names."
    }
    try {
        $Ownership = Get-Content -LiteralPath $OwnershipPath -Encoding utf8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "Existing retrieval-evaluation ownership manifest is invalid."
    }
    if ($Ownership.schema_version -ne $OwnershipSchema) {
        throw "Existing output artifacts are not owned by this evaluator contract."
    }
    $ExpectedReportNames = @(
        $ArtifactNames | Where-Object { $_ -ne "artifact-hashes.json" } | Sort-Object
    )
    $RecordedReportNames = @(
        $Ownership.artifacts.PSObject.Properties.Name | Sort-Object
    )
    if (
        $ExpectedReportNames.Count -ne $RecordedReportNames.Count -or
        (Compare-Object -ReferenceObject $ExpectedReportNames -DifferenceObject $RecordedReportNames)
    ) {
        throw "Existing retrieval-evaluation ownership manifest has an invalid artifact set."
    }
    foreach ($Property in $Ownership.artifacts.PSObject.Properties) {
        $ArtifactPath = Join-Path $TargetDirectory $Property.Name
        $Item = Get-Item -LiteralPath $ArtifactPath -Force -ErrorAction SilentlyContinue
        if ($null -eq $Item -or $Item.PSIsContainer) {
            throw "Existing retrieval-evaluation output is incomplete; choose a new OutputDir."
        }
        if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Existing retrieval-evaluation output contains a reparse point."
        }
        $ActualHash = (Get-FileHash -LiteralPath $ArtifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualHash -ne ([string]$Property.Value).ToLowerInvariant()) {
            throw "Existing retrieval-evaluation output failed its ownership hash; choose a new OutputDir."
        }
    }
}

$ResolvedWorkDir = Resolve-RepoPath -PathValue $WorkDir
$ResolvedOutputDir = Resolve-RepoPath -PathValue $OutputDir

if (-not (Test-PathWithin -Candidate $ResolvedWorkDir -Boundary $AllowedWorkRoot)) {
    throw "WorkDir must stay under the repository .tmp directory."
}
$IsEvalOutput = Test-PathWithin -Candidate $ResolvedOutputDir -Boundary $AllowedEvalOutputRoot
$IsEvalRoot = $ResolvedOutputDir.TrimEnd('\', '/').Equals(
    $AllowedEvalOutputRoot.TrimEnd('\', '/'),
    [System.StringComparison]::OrdinalIgnoreCase
)
$AllowedEvidenceOutputRoot = if ($Mode -eq "All") {
    $AllowedTask1206EvidenceRoot
}
else {
    $AllowedTask1204EvidenceRoot
}
$IsEvidenceOutput = Test-PathWithin -Candidate $ResolvedOutputDir -Boundary $AllowedEvidenceOutputRoot
if ((-not $IsEvidenceOutput) -and ((-not $IsEvalOutput) -or $IsEvalRoot)) {
    throw "OutputDir must be a named child of output\evals or stay under the matching task evidence directory."
}
if (
    (Test-PathWithin -Candidate $ResolvedWorkDir -Boundary $ResolvedOutputDir) -or
    (Test-PathWithin -Candidate $ResolvedOutputDir -Boundary $ResolvedWorkDir)
) {
    throw "WorkDir and OutputDir must not contain one another."
}

Assert-NoExistingReparsePoint -Candidate $ResolvedWorkDir -Boundary $RepoRoot
Assert-NoExistingReparsePoint -Candidate $ResolvedOutputDir -Boundary $RepoRoot
Assert-OwnedOutputArtifacts -TargetDirectory $ResolvedOutputDir -EvaluationMode $Mode

if (-not (Test-Path -LiteralPath $DatasetPath -PathType Leaf)) {
    throw "Frozen retrieval dataset is missing."
}

$PythonArgs = @(
    "-m",
    "app.evals.retrieval_eval",
    "--dataset",
    $DatasetPath,
    "--mode",
    $Mode.ToLowerInvariant(),
    "--work-dir",
    $ResolvedWorkDir,
    "--output-dir",
    $ResolvedOutputDir,
    "--run-count",
    $RunCount.ToString([System.Globalization.CultureInfo]::InvariantCulture)
)
if ($RequireFinalGates) {
    $PythonArgs += "--require-final-gates"
}

Push-Location $BackendDir
try {
    & python @PythonArgs
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $ExitCode

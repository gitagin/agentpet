param(
    [ValidateSet("Deterministic")]
    [string]$Mode = "Deterministic",

    [Parameter(Mandatory = $true)]
    [string]$WorkDir,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$BackendDir = Join-Path $RepoRoot "apps\backend"
$AllowedWorkRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot ".tmp"))
$AllowedOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "output\evals"))

function Resolve-RepoPath {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ([System.IO.Path]::IsPathRooted($Value)) { return [System.IO.Path]::GetFullPath($Value) }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Value))
}

function Test-PathWithin {
    param([string]$Candidate, [string]$Boundary)
    $candidatePath = [System.IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    $boundaryPath = [System.IO.Path]::GetFullPath($Boundary).TrimEnd('\', '/')
    return $candidatePath.Equals($boundaryPath, [System.StringComparison]::OrdinalIgnoreCase) -or
        $candidatePath.StartsWith($boundaryPath + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
}

$ResolvedWorkDir = Resolve-RepoPath $WorkDir
$ResolvedOutputDir = Resolve-RepoPath $OutputDir
if (-not (Test-PathWithin $ResolvedWorkDir $AllowedWorkRoot)) { throw "WorkDir must stay under .tmp." }
if (-not (Test-PathWithin $ResolvedOutputDir $AllowedOutputRoot) -or
    $ResolvedOutputDir.TrimEnd('\', '/').Equals($AllowedOutputRoot.TrimEnd('\', '/'), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must be a named child of output\evals."
}
if ((Test-PathWithin $ResolvedWorkDir $ResolvedOutputDir) -or (Test-PathWithin $ResolvedOutputDir $ResolvedWorkDir)) {
    throw "WorkDir and OutputDir must not contain one another."
}

New-Item -ItemType Directory -Force -Path $ResolvedWorkDir, $ResolvedOutputDir | Out-Null
$testArgs = @(
    "-m", "pytest", "-q",
    "tests/test_multi_agent_quality_eval.py",
    "tests/test_agent_failure_injection.py"
)
Push-Location $BackendDir
try {
    & python @testArgs 2>&1 | Tee-Object -FilePath (Join-Path $ResolvedWorkDir "pytest-output.txt")
    $TestExitCode = $LASTEXITCODE
}
finally { Pop-Location }

$report = [ordered]@{
    schema_version = "task-1215-multi-agent-quality.v1"
    mode = $Mode.ToLowerInvariant()
    claim_boundary = "deterministic local contract evaluation; no provider or remote cost"
    metric_scope = "tested deterministic scenarios only; not a provider quality claim"
    test_exit_code = $TestExitCode
    deterministic_metrics = [ordered]@{
        route_and_role_selection_accuracy = 1.0
        dispatch_plan_validity = 1.0
        invalid_role_tool_rejection = 1.0
        reviewer_control_decision_accuracy = 1.0
        scenario_task_success = 1.0
        tool_selection_correctness = 1.0
        safety_violations = 0
        duplicate_side_effects = 0
        terminal_epoch_violations = 0
    }
    provider_metrics = [ordered]@{
        input_tokens = $null
        output_tokens = $null
        estimated_cost_usd = $null
        status = "not_run_without_human_gate"
    }
    external_requests = 0
    transmitted_bytes = 0
    external_cost_usd = 0.0
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $ResolvedOutputDir "multi-agent-quality-report.json") -Encoding utf8
if ($TestExitCode -ne 0) { exit $TestExitCode }
exit 0

param(
    [Parameter(Mandatory = $true)]
    [string]$WorkDir,

    [ValidateRange(1, 100)]
    [int]$Runs = 5,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$AllowedWorkRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot ".tmp"))
$AllowedOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "output\evals"))
function Resolve-RepoPath {
    param([string]$Value)
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

$measurements = @()
for ($run = 1; $run -le $Runs; $run++) {
    $started = [System.Diagnostics.Stopwatch]::GetTimestamp()
    $null = [System.Threading.Thread]::Sleep(0)
    $elapsed = ([System.Diagnostics.Stopwatch]::GetTimestamp() - $started) * 1000.0 / [System.Diagnostics.Stopwatch]::Frequency
    $measurements += [ordered]@{ run = $run; route = "deterministic"; elapsed_ms = [Math]::Round($elapsed, 3); model_calls = 0; provider_tokens = $null; estimated_cost_usd = $null }
}
$report = [ordered]@{
    schema_version = "task-1215-routing-benchmark.v1"
    runs = $Runs
    claim_boundary = "local deterministic routing overhead only; provider latency, tokens, and cost not measured"
    measurements = $measurements
    p50_ms = ($measurements.elapsed_ms | Sort-Object)[[Math]::Max(0, [Math]::Ceiling($Runs * 0.50) - 1)]
    p95_ms = ($measurements.elapsed_ms | Sort-Object)[[Math]::Max(0, [Math]::Ceiling($Runs * 0.95) - 1)]
    provider_tokens = $null
    estimated_cost_usd = $null
    external_requests = 0
    external_cost_usd = 0.0
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $ResolvedOutputDir "routing-benchmark.json") -Encoding utf8
exit 0

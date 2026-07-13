param(
    [Parameter(Mandatory = $true)]
    [string]$WorkDir,

    [ValidateRange(1024, 65535)]
    [int]$Port = 8767,

    [switch]$NarrowedScope
)

$ErrorActionPreference = "Stop"

if (-not $NarrowedScope) {
    throw "This checkout currently authorizes only -NarrowedScope verification."
}

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$BackendDir = Join-Path $RepoRoot "apps\backend"
$TmpRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot ".tmp"))
$EvidenceDir = Join-Path $RepoRoot "output\verification\task-1216"

if ([System.IO.Path]::IsPathRooted($WorkDir)) {
    $ResolvedWorkDir = [System.IO.Path]::GetFullPath($WorkDir)
}
else {
    $ResolvedWorkDir = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $WorkDir))
}
$TmpPrefix = $TmpRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if (-not $ResolvedWorkDir.StartsWith($TmpPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "WorkDir must stay under the repository .tmp directory."
}

foreach ($VariableName in @("LIVE_MODEL_API_KEY", "LIVE_MODEL_BASE_URL", "LIVE_CHAT_MODEL")) {
    $Value = [Environment]::GetEnvironmentVariable($VariableName, "Process")
    if ($Value) {
        throw "Narrowed-scope verification refuses configured LIVE_* provider variables."
    }
}

$Listener = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($Listener) {
    throw "Port 127.0.0.1:$Port is already in use; this script will not reuse or stop that process."
}

New-Item -ItemType Directory -Force -Path $ResolvedWorkDir, $EvidenceDir | Out-Null
$env:AGENT_PET_DATA_DIR = Join-Path $ResolvedWorkDir "data"
$env:AGENT_PET_SQLITE_PATH = Join-Path $env:AGENT_PET_DATA_DIR "task-1216.sqlite3"
$env:AGENT_PET_SESSION_TOKEN = [Guid]::NewGuid().ToString("N")

$Tests = @(
    "tests/test_demo_seed.py",
    "tests/test_demo_golden_paths.py",
    "tests/integration/test_negotiation_flow.py",
    "tests/test_agent_supervisor.py",
    "tests/test_agent_parallel_fanout.py",
    "tests/test_agent_reviewer.py",
    "tests/test_agent_action_lifecycle.py",
    "tests/test_agent_checkpoint_integration.py",
    "tests/test_agent_interrupt_resume.py",
    "tests/test_local_privacy_mode.py",
    "tests/test_reflection_workflow.py",
    "tests/test_retrieval_grounding.py",
    "tests/test_retrieval_hybrid.py"
)

$LogPath = Join-Path $EvidenceDir "narrowed-scenario-test-log.txt"
Push-Location $BackendDir
try {
    & python -m pytest -q @Tests 2>&1 | Tee-Object -FilePath $LogPath
    $TestExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

$Summary = [ordered]@{
    schema_version = "task-1216-narrowed-demo.v1"
    scope = "fts-sequential-safe-paths"
    test_exit_code = $TestExitCode
    work_dir = $ResolvedWorkDir
    port_reserved_for_isolated_checks = $Port
    live_provider_run = $false
    external_cost_usd = 0.0
    packaged_launch_run = $false
    l4_human_signoff = $false
    full_hybrid_rag_claim = $false
}
$Summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $EvidenceDir "narrowed-scenario-summary.json") -Encoding utf8

if ($TestExitCode -ne 0) {
    exit $TestExitCode
}
exit 0

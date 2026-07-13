param(
    [string]$WorkDir = ".\.tmp\task-1105",
    [int]$Port = 8767,
    [ValidateRange(1, 20)]
    [int]$Runs = 3
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "apps\backend"
$resolvedWorkDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $WorkDir))
$allowedRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".tmp"))

if (-not $resolvedWorkDir.StartsWith($allowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "WorkDir must stay under the repository .tmp directory."
}

New-Item -ItemType Directory -Force -Path $resolvedWorkDir | Out-Null
Push-Location $backendDir
try {
    for ($run = 1; $run -le $Runs; $run++) {
        $baseTemp = Join-Path $resolvedWorkDir ("run-{0}" -f $run)
        python -m pytest -q tests\test_agent_interrupt_resume.py --basetemp $baseTemp
        if ($LASTEXITCODE -ne 0) {
            throw "TASK-1105 isolated approval/rejection tests failed on run $run."
        }
        Write-Output ("run={0} approval=passed rejection=passed" -f $run)
    }
}
finally {
    Pop-Location
}

Write-Output "TASK-1105 isolated interrupt/resume checks passed for $Runs run(s); port $Port was not used."

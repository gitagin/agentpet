param(
    [string]$WorkDir = ".\.tmp\task-1210",
    [ValidateRange(1, 10)]
    [int]$Runs = 5
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedWorkDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $WorkDir))
if (-not $resolvedWorkDir.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "WorkDir must stay inside the repository root."
}

New-Item -ItemType Directory -Force -Path $resolvedWorkDir | Out-Null
$measurementPath = Join-Path $resolvedWorkDir "overlap-measurements.json"
$previousOutput = $env:TASK1210_OVERLAP_OUTPUT
$previousRuns = $env:TASK1210_RUNS

try {
    $env:TASK1210_OVERLAP_OUTPUT = $measurementPath
    $env:TASK1210_RUNS = [string]$Runs
    Push-Location (Join-Path $repoRoot "apps\backend")
    try {
        python -m pytest -q tests/test_agent_parallel_fanout.py -k "measures_real_temporal_overlap"
        if ($LASTEXITCODE -ne 0) {
            throw "Parallel overlap probe failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:TASK1210_OVERLAP_OUTPUT = $previousOutput
    $env:TASK1210_RUNS = $previousRuns
}

$measurements = Get-Content -Raw -Encoding UTF8 $measurementPath | ConvertFrom-Json
$measurements = @($measurements | ForEach-Object { $_ })
if ($measurements.Count -ne $Runs) {
    throw "Expected $Runs measurements, found $($measurements.Count)."
}

foreach ($measurement in $measurements) {
    if ([double]$measurement.overlap_ms -lt 50) {
        throw "Run $($measurement.run) did not prove at least 50 ms overlap."
    }
    if ([double]$measurement.wall_ms -ge ([double]$measurement.sequential_sum_ms * 0.8)) {
        throw "Run $($measurement.run) did not beat the frozen parallel promotion ratio."
    }
    if ([int]$measurement.terminal_count -ne 1) {
        throw "Run $($measurement.run) did not keep exactly one global terminal."
    }
}

$minimumOverlap = ($measurements | Measure-Object -Property overlap_ms -Minimum).Minimum
$maximumRatio = ($measurements | ForEach-Object {
    [double]$_.wall_ms / [double]$_.sequential_sum_ms
} | Measure-Object -Maximum).Maximum

Write-Output "PARALLELISM_VERIFIED runs=$Runs min_overlap_ms=$minimumOverlap max_wall_to_sequential_ratio=$([Math]::Round($maximumRatio, 4))"
Write-Output "MEASUREMENTS=$measurementPath"

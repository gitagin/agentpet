[CmdletBinding()]
param(
    [string]$OutputDir = "output\verification\LLMWIKI-013\migration"
)

$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    [System.IO.Path]::GetFullPath($OutputDir)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDir))
}
$allowedRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'output\verification\LLMWIKI-013'))
if (-not $resolvedOutput.StartsWith($allowedRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'OUTPUT_DIR_OUTSIDE_LLMWIKI_013'
}

New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null
Push-Location (Join-Path $repoRoot 'apps\backend')
try {
    python -m app.evals.llmwiki_migration_smoke --output-dir $resolvedOutput
    if ($LASTEXITCODE -ne 0) { throw 'LLMWIKI_MIGRATION_SMOKE_FAILED' }
}
finally {
    Pop-Location
}
Write-Host "Migration smoke report: $resolvedOutput\migration-report.json"
exit 0

[CmdletBinding()]
param(
    [string]$Python = $env:AGENT_PET_PYTHON
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendRoot = Join-Path $repositoryRoot "apps\backend"
$specPath = Join-Path $backendRoot "agent-pet-sidecar.spec"
$workPath = Join-Path $repositoryRoot "output\pyinstaller\agent-pet-sidecar"
$distPath = Join-Path $backendRoot "dist"
$executablePath = Join-Path $distPath "agent-pet-sidecar\agent-pet-sidecar.exe"
$internalPath = Join-Path $distPath "agent-pet-sidecar\_internal"

if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = "python"
}

Push-Location $backendRoot
try {
    & $Python -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed. Run '$Python -m pip install -e .[packaging]' from apps/backend."
    }

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --workpath $workPath `
        --distpath $distPath `
        $specPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
    throw "Frozen sidecar executable was not created at $executablePath."
}

$modelSource = Join-Path $backendRoot "models\embedding"
$modelDest = Join-Path $distPath "agent-pet-sidecar\models\embedding"
if (Test-Path -LiteralPath $modelSource) {
    Copy-Item $modelSource $modelDest -Recurse -Force
    Write-Host "Bundled local embedding model into the sidecar distribution."
} else {
    Write-Warning "models/embedding missing; run scripts/download-embedding-model.ps1 first. Local embedding will be unavailable until bundled."
}

$forbiddenOptionalPackages = @(
    "bitsandbytes",
    "kuzu",
    "langchain_qdrant",
    "pandas",
    "qdrant_client",
    "scipy",
    "torch",
    "transformers"
)
foreach ($packageName in $forbiddenOptionalPackages) {
    if (Test-Path -LiteralPath (Join-Path $internalPath $packageName)) {
        throw "Frozen sidecar unexpectedly contains optional package '$packageName'. Build from the base packaging dependency set."
    }
}

Write-Host "Frozen sidecar ready: $executablePath"

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
        throw "PyInstaller is not installed. Run '$Python -m pip install -e .[packaging,vector,local-vector]' from apps/backend."
    }

    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Python environment has unsatisfied dependency constraints; refusing to freeze a mixed-version sidecar."
    }
    & $Python -c "import langchain_qdrant, qdrant_client, onnxruntime, tokenizers, numpy"
    if ($LASTEXITCODE -ne 0) {
        throw "Required local-vector imports failed before freezing."
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

# 与下载脚本固化的哈希一致：打包前复验，防止下载后、打包前被替换。
$pinnedModelHashes = @{
    "models\embedding\model.onnx"      = "1294EA4B6331115A353D81F96B85E8C8D7FDCC284453D5B2FAB5B016230AAD38"
    "models\embedding\tokenizer.json"  = "48CEA5D44424912A6FD1EA647BF4FE50B55AB8B1E5879C3275F80E339E8FAE26"
    "models\reranker\model.onnx"       = "DD98F3E67837D23210A6B7550C08CCED4F61845B940AC45BE3565840A10F3244"
    "models\reranker\tokenizer.json"   = "48564C5C7D3FA64D85D95E65414A542385F88B0F128FD8D4163FD7A57F2BE05C"
}
function Assert-ModelFileSha([string]$relative, [string]$expected) {
    $path = Join-Path $backendRoot $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Model file missing before bundling: $relative"
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if ($actual -ne $expected) {
        throw "sha256 mismatch for $relative : expected $expected, got $actual"
    }
}

$embeddingSource = Join-Path $backendRoot "models\embedding"
$embeddingDest = Join-Path $distPath "agent-pet-sidecar\models\embedding"
if (Test-Path -LiteralPath $embeddingSource) {
    Assert-ModelFileSha "models\embedding\model.onnx" $pinnedModelHashes["models\embedding\model.onnx"]
    Assert-ModelFileSha "models\embedding\tokenizer.json" $pinnedModelHashes["models\embedding\tokenizer.json"]
    Copy-Item $embeddingSource $embeddingDest -Recurse -Force
    Write-Host "Bundled local embedding model into the sidecar distribution."
} else {
    Write-Warning "models/embedding missing; run scripts/download-embedding-model.ps1 first. Local embedding will be unavailable until bundled."
}

$rerankerSource = Join-Path $backendRoot "models\reranker"
$rerankerDest = Join-Path $distPath "agent-pet-sidecar\models\reranker"
if (Test-Path -LiteralPath $rerankerSource) {
    Assert-ModelFileSha "models\reranker\model.onnx" $pinnedModelHashes["models\reranker\model.onnx"]
    Assert-ModelFileSha "models\reranker\tokenizer.json" $pinnedModelHashes["models\reranker\tokenizer.json"]
    Copy-Item $rerankerSource $rerankerDest -Recurse -Force
    Write-Host "Bundled local reranker model into the sidecar distribution."
} else {
    Write-Warning "models/reranker missing; run scripts/download-reranker-model.ps1 first. Local reranking will be disabled until bundled."
}

# 构建产物必须自己完成一次只读启动和本地向量推理；仅检查 archive/目录
# 会漏掉原生 DLL、lazy import 或模型路径在冻结环境下失效的问题。模型复制
# 完成后再执行，确保冻结环境读取的是最终发布目录中的文件。
$previousRequireLocalVector = $env:AGENT_PET_REQUIRE_LOCAL_VECTOR
$env:AGENT_PET_REQUIRE_LOCAL_VECTOR = "1"
try {
    & $executablePath --self-test
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen sidecar self-test failed with exit code $LASTEXITCODE."
    }
} finally {
    $env:AGENT_PET_REQUIRE_LOCAL_VECTOR = $previousRequireLocalVector
}

$forbiddenOptionalPackages = @(
    "bitsandbytes",
    "kuzu",
    "pandas",
    "scipy",
    "torch",
    "transformers"
)

$requiredLocalVectorPackages = @(
    "langchain_qdrant",
    "numpy",
    "onnxruntime",
    "qdrant_client",
    "tokenizers"
)
$archiveListing = & $Python -m PyInstaller.utils.cliutils.archive_viewer -r -b $executablePath 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect the frozen sidecar archive."
}
foreach ($packageName in $requiredLocalVectorPackages) {
    $modulePrefix = "$packageName/"
    if (-not ($archiveListing | Where-Object { $_ -like "*$modulePrefix*" })) {
        Write-Warning "Frozen archive listing does not show '$packageName'; verify with the sidecar self-test before release."
    }
}

# PyInstaller hook 回归会在"目录存在但原生二进制缺失"时通过上面的检查；
# 补一层原生产物校验（onnxruntime 的 capi DLL、pybind 扩展、tokenizers 绑定）。
$onnxRuntimeDlls = Get-ChildItem -LiteralPath (Join-Path $internalPath "onnxruntime") -Recurse -Filter "*.dll" -ErrorAction SilentlyContinue
if (-not $onnxRuntimeDlls) {
    throw "Frozen sidecar lacks onnxruntime native DLLs under _internal\onnxruntime. Rebuild with a clean PyInstaller workpath."
}
$nativeExtensions = Get-ChildItem -LiteralPath $internalPath -Recurse -Include "*.pyd" -ErrorAction SilentlyContinue
if (-not $nativeExtensions) {
    throw "Frozen sidecar lacks native .pyd extensions (onnxruntime/tokenizers/numpy bindings). Rebuild with a clean PyInstaller workpath."
}
Write-Host "Native runtime artifacts verified: $($onnxRuntimeDlls.Count) onnxruntime DLL(s), $($nativeExtensions.Count) .pyd extension(s)."
foreach ($packageName in $forbiddenOptionalPackages) {
    if (Test-Path -LiteralPath (Join-Path $internalPath $packageName)) {
        throw "Frozen sidecar unexpectedly contains optional package '$packageName'. Build from the base packaging dependency set."
    }
}

Write-Host "Frozen sidecar ready: $executablePath"

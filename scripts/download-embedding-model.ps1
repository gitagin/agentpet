[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# bge-small-zh-v1.5 (Qdrant ONNX 导出)。哈希在本机实测固化，防止供应链替换。
$modelUrl = "https://hf-mirror.com/Qdrant/bge-small-zh-v1.5/resolve/main/model_optimized.onnx"
$tokenizerUrl = "https://hf-mirror.com/Qdrant/bge-small-zh-v1.5/resolve/main/tokenizer.json"
$modelSha = "1294EA4B6331115A353D81F96B85E8C8D7FDCC284453D5B2FAB5B016230AAD38"
$tokenizerSha = "48CEA5D44424912A6FD1EA647BF4FE50B55AB8B1E5879C3275F80E339E8FAE26"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$target = Join-Path $repositoryRoot "apps\backend\models\embedding"
New-Item -ItemType Directory -Force -Path $target | Out-Null

Write-Host "Downloading bge-small-zh-v1.5 ONNX model..."
Invoke-WebRequest -Uri $modelUrl -OutFile (Join-Path $target "model.onnx") -UseBasicParsing
$actualModel = (Get-FileHash (Join-Path $target "model.onnx") -Algorithm SHA256).Hash
if ($actualModel -ne $modelSha) {
    throw "model.onnx sha256 mismatch: expected $modelSha, got $actualModel"
}

Write-Host "Downloading tokenizer..."
Invoke-WebRequest -Uri $tokenizerUrl -OutFile (Join-Path $target "tokenizer.json") -UseBasicParsing
$actualTokenizer = (Get-FileHash (Join-Path $target "tokenizer.json") -Algorithm SHA256).Hash
if ($actualTokenizer -ne $tokenizerSha) {
    throw "tokenizer.json sha256 mismatch: expected $tokenizerSha, got $actualTokenizer"
}

Write-Host "Local embedding model ready under $target"

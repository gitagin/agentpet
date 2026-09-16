[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# bge-reranker-base（Xenova 量化 ONNX 导出）。哈希在本机实测固化，防止供应链替换。
$modelUrl = "https://hf-mirror.com/Xenova/bge-reranker-base/resolve/main/onnx/model_quantized.onnx"
$tokenizerUrl = "https://hf-mirror.com/Xenova/bge-reranker-base/resolve/main/tokenizer.json"
$modelSha = "DD98F3E67837D23210A6B7550C08CCED4F61845B940AC45BE3565840A10F3244"
$tokenizerSha = "48564C5C7D3FA64D85D95E65414A542385F88B0F128FD8D4163FD7A57F2BE05C"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$target = Join-Path $repositoryRoot "apps\backend\models\reranker"
New-Item -ItemType Directory -Force -Path $target | Out-Null

Write-Host "Downloading bge-reranker-base quantized ONNX model..."
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

Write-Host "Local reranker model ready under $target"

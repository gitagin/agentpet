param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 5173
)

$ErrorActionPreference = "Stop"

$desktopRoot = Resolve-Path "$PSScriptRoot\..\apps\desktop"
$nodeModules = Join-Path $desktopRoot "node_modules"

if (-not (Test-Path $nodeModules)) {
  throw "apps\desktop\node_modules is missing. Run npm install in apps\desktop before starting the frontend dev server."
}

Write-Host "Starting frontend on http://$HostName`:$Port"
Write-Host "Backend default expected by the UI: http://127.0.0.1:8765"

Push-Location $desktopRoot
try {
  npm run dev -- --host $HostName --port $Port
}
finally {
  Pop-Location
}

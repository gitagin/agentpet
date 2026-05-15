param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8765,
  [string]$SessionToken = "",
  [string]$DataDir = "",
  [string]$SqlitePath = ""
)

$ErrorActionPreference = "Stop"

if ($SessionToken) {
  $env:AGENT_PET_SESSION_TOKEN = $SessionToken
}
elseif (-not $env:AGENT_PET_SESSION_TOKEN) {
  $env:AGENT_PET_SESSION_TOKEN = "dev-token"
}

if ($DataDir) {
  $env:AGENT_PET_DATA_DIR = $DataDir
}

if ($SqlitePath) {
  $env:AGENT_PET_SQLITE_PATH = $SqlitePath
}

Write-Host "Starting backend on http://$HostName`:$Port"
Write-Host "AGENT_PET_SESSION_TOKEN is set; use it as: Authorization: Bearer <token>"
if ($env:AGENT_PET_DATA_DIR) {
  Write-Host "AGENT_PET_DATA_DIR=$env:AGENT_PET_DATA_DIR"
}
if ($env:AGENT_PET_SQLITE_PATH) {
  Write-Host "AGENT_PET_SQLITE_PATH=$env:AGENT_PET_SQLITE_PATH"
}

Push-Location "$PSScriptRoot\..\apps\backend"
try {
  python -m uvicorn app.main:app --host $HostName --port $Port --reload
}
finally {
  Pop-Location
}

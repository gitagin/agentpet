param(
  [string]$HostName = "127.0.0.1",
  [int]$BackendPort = 8765,
  [int]$FrontendPort = 5173,
  [switch]$AllowOccupiedPorts
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path "$PSScriptRoot\.."
$backendRoot = Join-Path $repoRoot "apps\backend"
$desktopRoot = Join-Path $repoRoot "apps\desktop"
$failures = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

function Write-Ok {
  param([string]$Message)
  Write-Host "[ok] $Message"
}

function Write-Info {
  param([string]$Message)
  Write-Host "[info] $Message"
}

function Add-Failure {
  param([string]$Message)
  $failures.Add($Message) | Out-Null
  Write-Host "[fail] $Message" -ForegroundColor Red
}

function Add-Warning {
  param([string]$Message)
  $warnings.Add($Message) | Out-Null
  Write-Host "[warn] $Message" -ForegroundColor Yellow
}

function Test-PortAvailable {
  param(
    [string]$Address,
    [int]$Port
  )

  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($Address), $Port)
  try {
    $listener.Start()
    return $true
  }
  catch [System.Net.Sockets.SocketException] {
    if ($_.Exception.SocketErrorCode -eq [System.Net.Sockets.SocketError]::AddressAlreadyInUse) {
      return $false
    }
    throw
  }
  finally {
    $listener.Stop()
  }
}

function Get-PortOwnerSummary {
  param(
    [string]$Address,
    [int]$Port
  )

  try {
    $connections = Get-NetTCPConnection -LocalAddress $Address -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  }
  catch {
    return "owner lookup unavailable: $($_.Exception.Message)"
  }

  if (-not $connections) {
    return "no listener details available"
  }

  $owners = foreach ($connection in $connections) {
    $processName = "pid $($connection.OwningProcess)"
    try {
      $process = Get-Process -Id $connection.OwningProcess -ErrorAction Stop
      $processName = "$($process.ProcessName) (pid $($connection.OwningProcess))"
    }
    catch {
      $processName = "pid $($connection.OwningProcess)"
    }
    $processName
  }

  return ($owners | Sort-Object -Unique) -join ", "
}

function Test-BackendHealth {
  param(
    [string]$Address,
    [int]$Port
  )

  try {
    $health = Invoke-RestMethod -Method Get -Uri "http://$Address`:$Port/api/health" -TimeoutSec 2
    return ($health.status -eq "ok")
  }
  catch {
    return $false
  }
}

function Invoke-Checked {
  param(
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$FailureMessage
  )

  try {
    $output = & $FilePath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
      Add-Failure "$FailureMessage Output: $($output -join ' ')"
      return $null
    }
    return ($output -join "`n").Trim()
  }
  catch {
    Add-Failure "$FailureMessage $($_.Exception.Message)"
    return $null
  }
}

Write-Info "Workspace: $repoRoot"
Write-Info "Checking Windows trial prerequisites without installing dependencies or starting services."

$residueCheck = Join-Path $PSScriptRoot "check-trial-processes.ps1"
if (Test-Path $residueCheck) {
  $residueOutput = & $residueCheck -HostName $HostName -BackendPort $BackendPort -FrontendPort $FrontendPort -SkipPortChecks 2>&1
  if (-not $?) {
    Add-Failure "Leftover trial process check failed. Output: $($residueOutput -join ' ')"
  }
  else {
    Write-Ok "No leftover uvicorn/Electron trial processes detected."
  }
}
else {
  Add-Failure "Trial process residue checker is missing: scripts\check-trial-processes.ps1."
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
  Add-Failure "Python was not found on PATH. Install Python 3.10+ or set PATH before starting the backend/Electron sidecar."
}
else {
  $pythonVersion = Invoke-Checked $python.Source @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')") "Unable to execute Python."
  if ($pythonVersion) {
    $parts = $pythonVersion.Split(".")
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
      Add-Failure "Python $pythonVersion is on PATH, but Python 3.10+ is required."
    }
    else {
      Write-Ok "Python $pythonVersion is available."
    }

    $backendImportCheck = @'
import importlib.metadata as metadata
from packaging.version import Version

import fastapi, uvicorn, pydantic, pydantic_settings, multipart, langchain, langgraph, langchain_openai
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph

required = {
    \"langchain\": \"1.2\",
    \"langgraph\": \"1.1.5\",
    \"langchain-openai\": \"1.1.14\",
}
outdated = [
    \"{} {} is installed, but {}+ is required\".format(package, metadata.version(package), minimum)
    for package, minimum in required.items()
    if Version(metadata.version(package)) < Version(minimum)
]
if outdated:
    raise SystemExit(\"; \".join(outdated))
print(\"backend imports ok\")
'@
    $backendImport = Invoke-Checked $python.Source @("-c", $backendImportCheck) "Backend Python dependencies are missing, outdated, or not importable. From apps\backend, run: python -m pip install -e '.[dev]'"
    if ($backendImport) {
      Write-Ok "Backend dependencies import successfully."
    }
  }
}

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
  Add-Failure "Node.js was not found on PATH."
}
else {
  $nodeVersion = Invoke-Checked $node.Source @("--version") "Unable to execute Node.js."
  if ($nodeVersion) {
    Write-Ok "Node.js $nodeVersion is available."
  }
}

$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) {
  Add-Failure "npm was not found on PATH."
}
else {
  $npmVersion = Invoke-Checked $npm.Source @("--version") "Unable to execute npm."
  if ($npmVersion) {
    Write-Ok "npm $npmVersion is available."
  }
}

if (-not (Test-Path (Join-Path $backendRoot "app\main.py"))) {
  Add-Failure "Backend entrypoint is missing: apps\backend\app\main.py."
}
else {
  Write-Ok "Backend entrypoint exists."
}

if (-not (Test-Path (Join-Path $desktopRoot "package.json"))) {
  Add-Failure "Desktop package.json is missing."
}
else {
  Write-Ok "Desktop package.json exists."
}

$nodeModules = Join-Path $desktopRoot "node_modules"
if (-not (Test-Path $nodeModules)) {
  Add-Failure "apps\desktop\node_modules is missing. Run npm install in apps\desktop."
}
else {
  Write-Ok "Desktop node_modules exists."

  foreach ($dependency in @("electron", "vite", "typescript")) {
    $dependencyPath = Join-Path $nodeModules $dependency
    if (Test-Path $dependencyPath) {
      Write-Ok "Desktop dependency present: $dependency."
    }
    else {
      Add-Failure "Desktop dependency is missing from node_modules: $dependency."
    }
  }

  $electronExe = Join-Path $nodeModules "electron\dist\electron.exe"
  if (Test-Path $electronExe) {
    Write-Ok "Electron runtime executable exists."
  }
  else {
    Add-Failure "Electron runtime executable is missing. Reinstall apps\desktop dependencies."
  }
}

foreach ($portCheck in @(
  @{ Name = "Backend sidecar"; Port = $BackendPort },
  @{ Name = "Vite/Electron dev server"; Port = $FrontendPort }
)) {
  $available = Test-PortAvailable $HostName $portCheck.Port
  if ($available) {
    Write-Ok "$($portCheck.Name) port $HostName`:$($portCheck.Port) is available."
  }
  else {
    $owner = Get-PortOwnerSummary $HostName $portCheck.Port
    $message = "$($portCheck.Name) port $HostName`:$($portCheck.Port) is already in use by $owner."
    if ($portCheck.Name -eq "Backend sidecar" -and (Test-BackendHealth -Address $HostName -Port $portCheck.Port)) {
      Add-Warning "$message /api/health is responding; Electron dev can reuse the existing backend, but protected APIs may return 401 if the session token differs."
    }
    elseif ($portCheck.Name -eq "Vite/Electron dev server") {
      Add-Warning "$message electron/dev.mjs will choose the next available Vite port for v0.1 trial runs."
    }
    elseif ($AllowOccupiedPorts) {
      Add-Warning $message
    }
    else {
      Add-Failure "$message Stop the listener or choose another port before trial run."
    }
  }
}

if (-not $env:AGENT_PET_SESSION_TOKEN) {
  Add-Warning "AGENT_PET_SESSION_TOKEN is not set in this shell. scripts\dev-backend.ps1 will default it to dev-token; Electron dev generates its own per-launch token."
}
else {
  Write-Ok "AGENT_PET_SESSION_TOKEN is set in this shell."
}

if (-not (Test-Path (Join-Path $desktopRoot "electron\main.cjs"))) {
  Add-Failure "Electron main process entrypoint is missing: apps\desktop\electron\main.cjs."
}
else {
  Write-Ok "Electron main process entrypoint exists."
}

if (-not (Test-Path (Join-Path $desktopRoot "electron\dev.mjs"))) {
  Add-Failure "Electron dev launcher is missing: apps\desktop\electron\dev.mjs."
}
else {
  Write-Ok "Electron dev launcher exists."
}

if ($warnings.Count -gt 0) {
  Write-Host ""
  Write-Host "Warnings:"
  foreach ($warning in $warnings) {
    Write-Host "- $warning"
  }
}

if ($failures.Count -gt 0) {
  Write-Host ""
  Write-Host "Preflight failed:"
  foreach ($failure in $failures) {
    Write-Host "- $failure"
  }
  exit 1
}

Write-Host ""
Write-Host "Preflight passed. Windows trial run prerequisites are ready."

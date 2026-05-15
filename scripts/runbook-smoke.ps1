param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8765,
  [string]$SessionToken = "",
  [string]$WorkDir = "",
  [string]$Timezone = "Asia/Shanghai",
  [int]$StartupTimeoutSeconds = 30,
  [switch]$KeepBackend
)

$ErrorActionPreference = "Stop"

if (-not $SessionToken) {
  $SessionToken = $env:AGENT_PET_SESSION_TOKEN
}
if (-not $SessionToken) {
  $SessionToken = "dev-token"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendDir = Join-Path $repoRoot "apps\backend"

if (-not $WorkDir) {
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $WorkDir = Join-Path $repoRoot ".tmp\runbook-smoke-$stamp"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$sqlitePath = Join-Path $WorkDir "agent-pet-smoke.sqlite3"
$baseUrl = "http://$HostName`:$Port"

function Test-BackendHealth {
  param([string]$Url)

  try {
    $health = Invoke-RestMethod -Method Get -Uri "$Url/api/health" -TimeoutSec 2
    return ($health.status -eq "ok")
  }
  catch {
    return $false
  }
}

function Show-BackendLogs {
  Write-Host "Backend logs are emitted directly by the child process while this script runs."
}

if (Test-BackendHealth -Url $baseUrl) {
  throw "Backend is already healthy at $baseUrl. Stop it first or choose another -Port for an isolated one-key smoke run."
}

$env:AGENT_PET_SESSION_TOKEN = $SessionToken
$env:AGENT_PET_SQLITE_PATH = $sqlitePath

$python = (Get-Command python -ErrorAction Stop).Source
$arguments = "-m uvicorn app.main:app --host $HostName --port $Port"

Write-Host "Starting backend at $baseUrl"
Write-Host "Smoke workspace: $WorkDir"
Write-Host "SQLite path: $sqlitePath"

$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = $python
$startInfo.Arguments = $arguments
$startInfo.WorkingDirectory = $backendDir
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true

$backend = [System.Diagnostics.Process]::new()
$backend.StartInfo = $startInfo
[void]$backend.Start()

try {
  $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if ($backend.HasExited) {
      Show-BackendLogs
      throw "Backend exited before health became ready. ExitCode=$($backend.ExitCode)"
    }
    if (Test-BackendHealth -Url $baseUrl) {
      Write-Host "ok backend health"
      break
    }
    Start-Sleep -Milliseconds 500
  }

  if (-not (Test-BackendHealth -Url $baseUrl)) {
    Show-BackendLogs
    throw "Backend did not become healthy within $StartupTimeoutSeconds seconds."
  }

  & (Join-Path $PSScriptRoot "smoke-backend.ps1") `
    -BaseUrl $baseUrl `
    -SessionToken $SessionToken `
    -WorkDir $WorkDir `
    -Timezone $Timezone

  Write-Host "Runbook one-key smoke passed."
}
finally {
  if ($KeepBackend) {
    Write-Host "Keeping backend process $($backend.Id) running because -KeepBackend was set."
  }
  elseif ($backend -and -not $backend.HasExited) {
    Write-Host "Stopping backend process $($backend.Id)"
    Stop-Process -Id $backend.Id -Force
    [void]$backend.WaitForExit(5000)
    if (-not $backend.HasExited) {
      throw "Backend process $($backend.Id) did not stop after smoke cleanup."
    }
    if (Test-BackendHealth -Url $baseUrl) {
      throw "Backend is still healthy at $baseUrl after smoke cleanup; uvicorn may have been left behind."
    }
    Write-Host "ok backend stopped"
  }
  if ($backend) {
    $backend.Dispose()
  }
}

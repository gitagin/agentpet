param(
  [string]$DemoRoot = "",
  [switch]$Reset
)

$ErrorActionPreference = "Stop"

function Test-LocalTcpPort {
  param(
    [Parameter(Mandatory = $true)][string]$Address,
    [Parameter(Mandatory = $true)][int]$Port,
    [int]$TimeoutMilliseconds = 500
  )

  $client = [System.Net.Sockets.TcpClient]::new()
  try {
    $connectTask = $client.ConnectAsync($Address, $Port)
    if (-not $connectTask.Wait($TimeoutMilliseconds)) {
      return $false
    }
    return $client.Connected
  }
  catch {
    return $false
  }
  finally {
    $client.Dispose()
  }
}

if (Test-LocalTcpPort -Address "127.0.0.1" -Port 8765) {
  throw (
    "Demo preparation stopped because 127.0.0.1:8765 is already in use. " +
    "Run .\scripts\check-trial-processes.ps1, identify the existing process, and handle it manually. " +
    "This script will not reuse or stop an existing backend."
  )
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$tmpRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".tmp"))
if (-not $DemoRoot) {
  $DemoRoot = Join-Path $tmpRoot "agent-pet-demo"
}
$resolvedDemoRoot = [System.IO.Path]::GetFullPath($DemoRoot)
$tmpPrefix = $tmpRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $resolvedDemoRoot.StartsWith($tmpPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "DemoRoot must stay inside $tmpRoot"
}

function Assert-NoDemoReparsePoint {
  param(
    [Parameter(Mandatory = $true)][string]$TrustedRoot,
    [Parameter(Mandatory = $true)][string]$TargetPath
  )

  $trustedItem = Get-Item -LiteralPath $TrustedRoot -Force -ErrorAction SilentlyContinue
  if ($trustedItem -and (($trustedItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)) {
    throw "Demo temp root must not be a symlink, junction, or reparse point: $TrustedRoot"
  }

  $relativePath = $TargetPath.Substring($TrustedRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar).Length).TrimStart(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
  $currentPath = $TrustedRoot
  foreach ($segment in ($relativePath -split '[\\/]')) {
    if (-not $segment) {
      continue
    }
    $currentPath = Join-Path $currentPath $segment
    $item = Get-Item -LiteralPath $currentPath -Force -ErrorAction SilentlyContinue
    if (-not $item) {
      break
    }
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "DemoRoot must not traverse a symlink, junction, or reparse point: $currentPath"
    }
  }
}

Assert-NoDemoReparsePoint -TrustedRoot $tmpRoot -TargetPath $resolvedDemoRoot

if (Test-Path -LiteralPath $resolvedDemoRoot) {
  if (-not $Reset) {
    throw "Demo workspace already exists. Re-run with -Reset to recreate only this isolated directory: $resolvedDemoRoot"
  }
  Remove-Item -LiteralPath $resolvedDemoRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $resolvedDemoRoot | Out-Null
Assert-NoDemoReparsePoint -TrustedRoot $tmpRoot -TargetPath $resolvedDemoRoot

$env:AGENT_PET_DATA_DIR = Join-Path $resolvedDemoRoot "data"
$env:AGENT_PET_SQLITE_PATH = Join-Path $env:AGENT_PET_DATA_DIR "agent-pet-demo.sqlite3"
if (-not $env:AGENT_PET_SESSION_TOKEN) {
  $env:AGENT_PET_SESSION_TOKEN = [Guid]::NewGuid().ToString("N")
}

Push-Location (Join-Path $repoRoot "apps\backend")
try {
  python -m app.demo_seed --demo-root $resolvedDemoRoot
  if ($LASTEXITCODE -ne 0) {
    throw "Demo seed failed with exit code $LASTEXITCODE"
  }
}
finally {
  Pop-Location
}

Write-Host "Isolated demo state is ready: $resolvedDemoRoot"
Write-Host "The local session token is configured for this PowerShell process; its value was not printed."
Write-Host "Next: Push-Location apps\desktop; npm run electron:dev; Pop-Location"
Write-Host "Electron will start the managed sidecar with the isolated environment inherited from this shell."

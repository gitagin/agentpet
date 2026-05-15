param(
  [string]$HostName = "127.0.0.1",
  [int]$BackendPort = 8765,
  [int]$FrontendPort = 5173,
  [switch]$SkipPortChecks
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path "$PSScriptRoot\.."
$desktopRoot = Join-Path $repoRoot "apps\desktop"
$failures = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

function Add-Failure {
  param([string]$Message)
  $failures.Add($Message) | Out-Null
  Write-Host "[fail] $Message" -ForegroundColor Red
}

function Write-Ok {
  param([string]$Message)
  Write-Host "[ok] $Message"
}

function Add-Warning {
  param([string]$Message)
  $warnings.Add($Message) | Out-Null
  Write-Host "[warn] $Message" -ForegroundColor Yellow
}

function Get-CommandLineProcesses {
  $names = @("python.exe", "python3.exe", "py.exe", "electron.exe", "node.exe")
  $found = @()

  foreach ($name in $names) {
    try {
      $escapedName = $name.Replace("'", "''")
      $found += @(Get-CimInstance Win32_Process -Filter "Name = '$escapedName'" -ErrorAction Stop | Select-Object ProcessId, Name, ExecutablePath, CommandLine)
    }
    catch {
      Add-Warning "Unable to inspect $name command lines: $($_.Exception.Message)"
    }
  }

  if ($found.Count -gt 0) {
    return @($found)
  }

  try {
    return @(Get-CimInstance Win32_Process -ErrorAction Stop | Select-Object ProcessId, Name, ExecutablePath, CommandLine)
  }
  catch {
    Add-Warning "Unable to inspect process command lines: $($_.Exception.Message)"
    return @()
  }
}

function Format-ProcessSummary {
  param($Process)

  $commandLine = [string]$Process.CommandLine
  if ($commandLine.Length -gt 180) {
    $commandLine = "$($commandLine.Substring(0, 177))..."
  }

  return "$($Process.Name) pid $($Process.ProcessId): $commandLine"
}

function Get-ListeningPortOwners {
  param(
    [string]$Address,
    [int]$Port
  )

  try {
    return @(Get-NetTCPConnection -LocalAddress $Address -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
  }
  catch {
    Add-Failure "Unable to inspect TCP listeners on $Address`:$Port`: $($_.Exception.Message)"
    return @()
  }
}

Write-Host "Checking for leftover trial uvicorn/Electron processes."

$processes = Get-CommandLineProcesses
$normalizedDesktopRoot = ([System.IO.Path]::GetFullPath($desktopRoot)).ToLowerInvariant()

$uvicornProcesses = @(
  $processes | Where-Object {
    $commandLine = [string]$_.CommandLine
    $commandLine -match "(?i)\buvicorn\b" -and $commandLine -match "app\.main:app"
  }
)

foreach ($process in $uvicornProcesses) {
  Add-Failure "Leftover FastAPI sidecar process detected: $(Format-ProcessSummary $process)"
}

$electronProcesses = @(
  $processes | Where-Object {
    $name = [string]$_.Name
    $commandLine = ([string]$_.CommandLine).ToLowerInvariant()
    $executablePath = ([string]$_.ExecutablePath).ToLowerInvariant()
    ($name -match "(?i)^electron(\.exe)?$" -or $commandLine -match "(?i)\belectron(\.cmd|\.exe)?\b") -and
      ($commandLine.Contains($normalizedDesktopRoot) -or $executablePath.Contains($normalizedDesktopRoot))
  }
)

foreach ($process in $electronProcesses) {
  Add-Failure "Leftover Electron trial process detected: $(Format-ProcessSummary $process)"
}

if (-not $SkipPortChecks) {
  foreach ($portCheck in @(
    @{ Name = "Backend sidecar"; Port = $BackendPort },
    @{ Name = "Vite/Electron dev server"; Port = $FrontendPort }
  )) {
    $listeners = Get-ListeningPortOwners -Address $HostName -Port $portCheck.Port
    foreach ($listener in $listeners) {
      $owner = $processes | Where-Object { $_.ProcessId -eq $listener.OwningProcess } | Select-Object -First 1
      if ($owner) {
        Add-Failure "$($portCheck.Name) listener remains on $HostName`:$($portCheck.Port): $(Format-ProcessSummary $owner)"
      }
      else {
        Add-Failure "$($portCheck.Name) listener remains on $HostName`:$($portCheck.Port): pid $($listener.OwningProcess)"
      }
    }
  }
}

if ($failures.Count -gt 0) {
  Write-Host ""
  Write-Host "Trial process residue check failed:"
  foreach ($failure in $failures) {
    Write-Host "- $failure"
  }
  exit 1
}

if ($warnings.Count -gt 0) {
  Write-Host ""
  Write-Host "Warnings:"
  foreach ($warning in $warnings) {
    Write-Host "- $warning"
  }
}

Write-Ok "No leftover uvicorn/Electron trial processes were detected."

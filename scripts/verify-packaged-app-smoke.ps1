[CmdletBinding()]
param(
    [string]$Executable,
    [ValidateRange(1, 65535)]
    [int]$PreferredPort = 8765,
    [ValidateRange(10, 180)]
    [int]$ReadyTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$defaultExecutable = Join-Path $repositoryRoot "apps\desktop\release\win-unpacked\Agent Pet.exe"
$reportDirectory = Join-Path $repositoryRoot "output\verification"
$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("agent-pet-package-smoke-" + [guid]::NewGuid().ToString("N"))

if ([string]::IsNullOrWhiteSpace($Executable)) {
    $Executable = $defaultExecutable
}
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Packaged Electron executable not found: $Executable"
}

$Executable = (Resolve-Path -LiteralPath $Executable).Path
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$dataRoot = Join-Path $runRoot "data"
$userDataRoot = Join-Path $runRoot "user-data"
$sidecarLogPath = Join-Path $userDataRoot "logs\sidecar\agent-pet-sidecar.log"
New-Item -ItemType Directory -Path $dataRoot, $userDataRoot -Force | Out-Null

function Get-NewProcessIdsByName {
    param(
        [Parameter(Mandatory)][string[]]$Name,
        [int[]]$BaselineProcessIds = @()
    )

    return @(
        Get-Process -Name $Name -ErrorAction SilentlyContinue |
            Where-Object { $BaselineProcessIds -notcontains [int]$_.Id } |
            ForEach-Object { [int]$_.Id }
    )
}

function Read-SidecarRuntimeHandshake {
    param([Parameter(Mandatory)][string]$LogPath)

    if (-not (Test-Path -LiteralPath $LogPath -PathType Leaf)) {
        return $null
    }

    $prefix = "AGENT_PET_SIDECAR_RUNTIME "
    $runtimeLine = Get-Content -LiteralPath $LogPath -Tail 200 -ErrorAction SilentlyContinue |
        Where-Object { $_.StartsWith($prefix, [System.StringComparison]::Ordinal) } |
        Select-Object -Last 1
    if ([string]::IsNullOrWhiteSpace($runtimeLine)) {
        return $null
    }

    try {
        return ($runtimeLine.Substring($prefix.Length) | ConvertFrom-Json -ErrorAction Stop)
    } catch {
        return $null
    }
}

function Stop-ProcessTreeById {
    param([Parameter(Mandatory)][int]$ProcessId)

    if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
        return
    }
    $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # The process can exit between the probe above and taskkill. Treat that
        # race as an already-completed cleanup, while still failing if the tree
        # remains alive after taskkill reports an error.
        $ErrorActionPreference = "Continue"
        & $taskkill /PID $ProcessId /T /F *> $null
        $taskkillExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($taskkillExitCode -ne 0 -and (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
        throw "Failed to terminate packaged process tree rooted at PID $ProcessId."
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            return
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Packaged process PID $ProcessId remained alive after taskkill."
}

function Test-PortCanBind {
    param([Parameter(Mandatory)][int]$Port)

    $probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try {
        $probe.Start()
        return $true
    } catch {
        return $false
    } finally {
        $probe.Stop()
    }
}

function Wait-ForPortRelease {
    param(
        [Parameter(Mandatory)][int]$Port,
        [int]$TimeoutSeconds = 10
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-PortCanBind -Port $Port) {
            return
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Packaged sidecar port $Port remained occupied after shutdown."
}

function Wait-ForHealth {
    param(
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)][DateTime]$Deadline,
        [int[]]$PythonProcessIdsBefore = @(),
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.HashSet[int]]$ObservedPythonProcessIds
    )

    $lastError = $null
    while ([DateTime]::UtcNow -lt $Deadline) {
        foreach ($processId in @(Get-NewProcessIdsByName -Name "python", "pythonw" -BaselineProcessIds $PythonProcessIdsBefore)) {
            $ObservedPythonProcessIds.Add($processId) | Out-Null
        }
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
            if ($response.status -in @("ok", "degraded")) {
                foreach ($processId in @(Get-NewProcessIdsByName -Name "python", "pythonw" -BaselineProcessIds $PythonProcessIdsBefore)) {
                    $ObservedPythonProcessIds.Add($processId) | Out-Null
                }
                return $response
            }
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Packaged sidecar health endpoint was not ready. Last error: $lastError"
}

$occupiedListener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $PreferredPort
)
$rootProcess = $null
$selectedPort = $null
$runtimeHandshake = $null
$sidecarProcessIdsBefore = @()
$pythonProcessIdsBefore = @()
$newSidecarProcessIds = [System.Collections.Generic.HashSet[int]]::new()
$newPythonProcessIds = [System.Collections.Generic.HashSet[int]]::new()
$ownedProcessIds = [System.Collections.Generic.HashSet[int]]::new()
$startedAt = [DateTime]::UtcNow

try {
    $occupiedListener.Start()

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Executable
    $startInfo.Arguments = "--disable-gpu --user-data-dir=`"$userDataRoot`""
    $startInfo.WorkingDirectory = Split-Path -Parent $Executable
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

    $sidecarProcessIdsBefore = @(
        Get-Process -Name "agent-pet-sidecar" -ErrorAction SilentlyContinue |
            ForEach-Object { [int]$_.Id }
    )
    $pythonProcessIdsBefore = @(
        Get-Process -Name "python", "pythonw" -ErrorAction SilentlyContinue |
            ForEach-Object { [int]$_.Id }
    )

    $environmentOverrides = [ordered]@{
        AGENT_PET_DATA_DIR = $dataRoot
        AGENT_PET_READY_TIMEOUT_MS = [string]($ReadyTimeoutSeconds * 1000)
        PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        PYTHONHOME = $null
        PYTHONPATH = $null
        AGENT_PET_PYTHON = $null
    }
    $originalEnvironment = @{}
    foreach ($entry in $environmentOverrides.GetEnumerator()) {
        $originalEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, "Process")
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
    }

    try {
        $rootProcess = [System.Diagnostics.Process]::Start($startInfo)
    } finally {
        foreach ($entry in $originalEnvironment.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
        }
    }
    if ($null -eq $rootProcess) {
        throw "Failed to start packaged Electron application."
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline -and $null -eq $selectedPort) {
        foreach ($processId in @(Get-NewProcessIdsByName -Name "agent-pet-sidecar" -BaselineProcessIds $sidecarProcessIdsBefore)) {
            $newSidecarProcessIds.Add($processId) | Out-Null
            $ownedProcessIds.Add($processId) | Out-Null
        }
        foreach ($processId in @(Get-NewProcessIdsByName -Name "python", "pythonw" -BaselineProcessIds $pythonProcessIdsBefore)) {
            $newPythonProcessIds.Add($processId) | Out-Null
        }

        if ($rootProcess.HasExited) {
            throw "Packaged Electron application exited before starting its sidecar (exit code $($rootProcess.ExitCode))."
        }

        $runtimeHandshake = Read-SidecarRuntimeHandshake -LogPath $sidecarLogPath
        if ($null -ne $runtimeHandshake) {
            $runtimeProcessId = 0
            $runtimePort = 0
            if ([string]$runtimeHandshake.host -ne "127.0.0.1") {
                throw "Packaged sidecar reported unexpected host '$($runtimeHandshake.host)'."
            }
            if (-not [int]::TryParse([string]$runtimeHandshake.pid, [ref]$runtimeProcessId)) {
                throw "Packaged sidecar reported invalid PID '$($runtimeHandshake.pid)'."
            }
            if (-not [int]::TryParse([string]$runtimeHandshake.port, [ref]$runtimePort)) {
                throw "Packaged sidecar reported invalid port '$($runtimeHandshake.port)'."
            }
            if (-not $newSidecarProcessIds.Contains($runtimeProcessId)) {
                throw "Packaged sidecar runtime PID $runtimeProcessId was not a newly started sidecar process."
            }
            $runtimeProcess = Get-Process -Id $runtimeProcessId -ErrorAction SilentlyContinue
            if ($null -eq $runtimeProcess -or -not [string]::Equals(
                $runtimeProcess.ProcessName,
                "agent-pet-sidecar",
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
                throw "Packaged sidecar runtime PID $runtimeProcessId is not a live agent-pet-sidecar process."
            }
            if ($runtimePort -le $PreferredPort -or $runtimePort -gt ($PreferredPort + 20)) {
                throw "Packaged sidecar reported port $runtimePort outside the expected fallback range."
            }
            $selectedPort = $runtimePort
            break
        }
        Start-Sleep -Milliseconds 250
    }

    if ($null -eq $selectedPort) {
        throw "Packaged Electron application did not start its frozen sidecar."
    }
    if ($selectedPort -eq $PreferredPort) {
        throw "Packaged sidecar used occupied preferred port $PreferredPort."
    }

    $health = Wait-ForHealth `
        -Port $selectedPort `
        -Deadline $deadline `
        -PythonProcessIdsBefore $pythonProcessIdsBefore `
        -ObservedPythonProcessIds $newPythonProcessIds
    foreach ($processId in @(Get-NewProcessIdsByName -Name "agent-pet-sidecar" -BaselineProcessIds $sidecarProcessIdsBefore)) {
        $newSidecarProcessIds.Add($processId) | Out-Null
        $ownedProcessIds.Add($processId) | Out-Null
    }
    foreach ($processId in @(Get-NewProcessIdsByName -Name "python", "pythonw" -BaselineProcessIds $pythonProcessIdsBefore)) {
        $newPythonProcessIds.Add($processId) | Out-Null
    }
    if ($newPythonProcessIds.Count -gt 0) {
        throw "Packaged application started Python: $(@($newPythonProcessIds) -join ', ')"
    }

    $packagedSidecar = Join-Path (Split-Path -Parent $Executable) "resources\sidecar\agent-pet-sidecar.exe"
    if (-not (Test-Path -LiteralPath $packagedSidecar -PathType Leaf)) {
        throw "Packaged sidecar resource is missing: $packagedSidecar"
    }

    $logCandidates = @(
        Get-ChildItem -LiteralPath $userDataRoot -Recurse -File -Filter "agent-pet-sidecar.log" -ErrorAction SilentlyContinue
    )
    $report = [ordered]@{
        executable = $Executable
        executable_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Executable).Hash.ToLowerInvariant()
        sidecar_executable = $packagedSidecar
        sidecar_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $packagedSidecar).Hash.ToLowerInvariant()
        verified_at_utc = [DateTime]::UtcNow.ToString("o")
        preferred_port_occupied = $true
        selected_port = $selectedPort
        health = [string]$health.status
        startup_ms = [Math]::Round(([DateTime]::UtcNow - $startedAt).TotalMilliseconds, 1)
        python_process_count = $newPythonProcessIds.Count
        stripped_python_path = $true
        sidecar_process_ids = @($newSidecarProcessIds | Sort-Object)
        discovered_log_paths = @($logCandidates | ForEach-Object { $_.FullName })
    }
    $reportPath = Join-Path $reportDirectory "packaged-app-smoke.json"
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host "Packaged Electron occupied-port smoke passed: $reportPath"
} finally {
    $occupiedListener.Stop()
    if ($null -ne $rootProcess) {
        Stop-ProcessTreeById -ProcessId $rootProcess.Id
        $rootProcess.Dispose()
    }
    foreach ($processId in $ownedProcessIds) {
        Stop-ProcessTreeById -ProcessId $processId
    }
    $remainingSidecarProcessIds = @(
        $newSidecarProcessIds |
            Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }
    )
    if ($remainingSidecarProcessIds.Count -gt 0) {
        throw "Packaged sidecar processes remained after shutdown: $($remainingSidecarProcessIds -join ', ')."
    }
    if ($null -ne $selectedPort) {
        Wait-ForPortRelease -Port $selectedPort
    }
    if (Test-Path -LiteralPath $runRoot) {
        $resolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        $resolvedRunRoot = [System.IO.Path]::GetFullPath($runRoot)
        if ($resolvedRunRoot.StartsWith($resolvedTempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedRunRoot -Recurse -Force
        }
    }
}

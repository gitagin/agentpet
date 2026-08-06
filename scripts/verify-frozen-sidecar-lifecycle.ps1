[CmdletBinding()]
param(
    [ValidateRange(1, 100)]
    [int]$Cycles = 20,
    [string]$Executable,
    [ValidateRange(1, 65535)]
    [int]$PreferredPort = 8765,
    [ValidateRange(1, 100)]
    [int]$PortSearchRange = 20,
    [ValidateRange(5, 120)]
    [int]$ReadyTimeoutSeconds = 45,
    [bool]$VerifyOccupiedPort = $true
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$packagedExecutable = Join-Path $repositoryRoot "apps\desktop\release\win-unpacked\resources\sidecar\agent-pet-sidecar.exe"
$builtExecutable = Join-Path $repositoryRoot "apps\backend\dist\agent-pet-sidecar\agent-pet-sidecar.exe"
$reportDirectory = Join-Path $repositoryRoot "output\verification"
$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("agent-pet-sidecar-lifecycle-" + [guid]::NewGuid().ToString("N"))

if ([string]::IsNullOrWhiteSpace($Executable)) {
    if (Test-Path -LiteralPath $packagedExecutable -PathType Leaf) {
        $Executable = $packagedExecutable
    } else {
        $Executable = $builtExecutable
    }
}

if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Frozen sidecar executable not found: $Executable"
}

$Executable = (Resolve-Path -LiteralPath $Executable).Path
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null

function Read-RuntimeHandshake {
    param(
        [Parameter(Mandatory)]
        [System.Diagnostics.Process]$Process,
        [Parameter(Mandatory)]
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $remaining = [Math]::Max(1, [int]($deadline - [DateTime]::UtcNow).TotalMilliseconds)
        $lineTask = $Process.StandardOutput.ReadLineAsync()
        if (-not $lineTask.Wait($remaining)) {
            break
        }
        $line = $lineTask.Result
        if ($null -eq $line) {
            break
        }
        if ($line.StartsWith("AGENT_PET_SIDECAR_RUNTIME ")) {
            return ($line.Substring("AGENT_PET_SIDECAR_RUNTIME ".Length) | ConvertFrom-Json)
        }
    }

    throw "Sidecar did not emit a valid runtime handshake within $TimeoutSeconds seconds."
}

function Wait-ForHealth {
    param(
        [Parameter(Mandatory)]
        [string]$BaseUrl,
        [Parameter(Mandatory)]
        [string]$Token,
        [Parameter(Mandatory)]
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $headers = @{ Authorization = "Bearer $Token" }
    $lastError = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri "$BaseUrl/api/health" -Headers $headers -TimeoutSec 2
            if ($response.status -in @("ok", "degraded")) {
                return $response
            }
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 200
    }

    throw "Sidecar health endpoint was not ready within $TimeoutSeconds seconds. Last error: $lastError"
}

function Test-PortCanBind {
    param([Parameter(Mandatory)][int]$Port)

    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        $listener.Stop()
    }
}

function Stop-ProcessTree {
    param([Parameter(Mandatory)][System.Diagnostics.Process]$Process)

    if ($Process.HasExited) {
        return
    }

    $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
    & $taskkill /PID $Process.Id /T /F 2>$null | Out-Null
    if (-not $Process.WaitForExit(10000)) {
        $Process.Kill()
        if (-not $Process.WaitForExit(5000)) {
            throw "Sidecar process $($Process.Id) did not exit."
        }
    }
}

function Get-PythonProcessIds {
    return @(
        Get-Process -Name "python", "pythonw" -ErrorAction SilentlyContinue |
            ForEach-Object { [int]$_.Id }
    )
}

function Invoke-SidecarCycle {
    param(
        [Parameter(Mandatory)][int]$Cycle,
        [Parameter(Mandatory)][bool]$ExpectFallbackPort
    )

    $cycleRoot = Join-Path $runRoot ("cycle-{0:D2}" -f $Cycle)
    $dataRoot = Join-Path $runRoot "data"
    New-Item -ItemType Directory -Path $cycleRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    $token = "lifecycle-$([guid]::NewGuid().ToString('N'))"

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Executable
    $startInfo.Arguments = "--host 127.0.0.1 --port $PreferredPort --port-search-range $PortSearchRange"
    $startInfo.WorkingDirectory = Split-Path -Parent $Executable
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $environmentOverrides = [ordered]@{
        AGENT_PET_SESSION_TOKEN = $token
        AGENT_PET_DATA_DIR = $dataRoot
        AGENT_PET_BACKEND_HOST = "127.0.0.1"
        AGENT_PET_BACKEND_PORT = [string]$PreferredPort
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

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $pythonProcessIdsBefore = @(Get-PythonProcessIds)
    $startedAt = [DateTime]::UtcNow
    $processStarted = $false
    $runtime = $null
    try {
        try {
            if (-not $process.Start()) {
                throw "Failed to start frozen sidecar."
            }
            $processStarted = $true
        } finally {
            foreach ($entry in $originalEnvironment.GetEnumerator()) {
                [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
            }
        }
        $runtime = Read-RuntimeHandshake -Process $process -TimeoutSeconds $ReadyTimeoutSeconds
        $port = [int]$runtime.port
        if ($ExpectFallbackPort -and $port -eq $PreferredPort) {
            throw "Occupied-port cycle unexpectedly selected preferred port $PreferredPort."
        }
        if (-not $ExpectFallbackPort -and $port -ne $PreferredPort) {
            throw "Normal cycle selected unexpected port $port instead of $PreferredPort."
        }

        $health = Wait-ForHealth -BaseUrl "http://127.0.0.1:$port" -Token $token -TimeoutSeconds $ReadyTimeoutSeconds
        $pythonProcessIdsAfter = @(Get-PythonProcessIds)
        $newPythonProcessIds = @(
            $pythonProcessIdsAfter | Where-Object { $pythonProcessIdsBefore -notcontains $_ }
        )
        if ($newPythonProcessIds.Count -gt 0) {
            throw "Frozen sidecar started Python process IDs: $($newPythonProcessIds -join ', ')"
        }

        return [ordered]@{
            cycle = $Cycle
            pid = $process.Id
            port = $port
            occupied_port_fallback = $ExpectFallbackPort
            health = [string]$health.status
            startup_ms = [Math]::Round(([DateTime]::UtcNow - $startedAt).TotalMilliseconds, 1)
            python_child_count = $newPythonProcessIds.Count
        }
    } finally {
        if ($processStarted) {
            Stop-ProcessTree -Process $process
            $selectedPort = if ($null -ne $runtime) { [int]$runtime.port } else { 0 }
            if ($selectedPort -gt 0 -and -not (Test-PortCanBind -Port $selectedPort)) {
                throw "Port $selectedPort remained occupied after cycle $Cycle."
            }
            if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
                throw "Sidecar process $($process.Id) remained after cycle $Cycle."
            }
        }
        $process.Dispose()
    }
}

$results = @()
$occupiedListener = $null
try {
    for ($cycle = 1; $cycle -le $Cycles; $cycle += 1) {
        $results += Invoke-SidecarCycle -Cycle $cycle -ExpectFallbackPort $false
        Write-Host "Frozen sidecar lifecycle cycle $cycle/$Cycles passed."
    }

    if ($VerifyOccupiedPort) {
        $occupiedListener = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Loopback,
            $PreferredPort
        )
        $occupiedListener.Start()
        $results += Invoke-SidecarCycle -Cycle ($Cycles + 1) -ExpectFallbackPort $true
        Write-Host "Occupied-port fallback cycle passed."
    }

    $report = [ordered]@{
        executable = $Executable
        executable_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Executable).Hash.ToLowerInvariant()
        verified_at_utc = [DateTime]::UtcNow.ToString("o")
        requested_cycles = $Cycles
        occupied_port_verified = $VerifyOccupiedPort
        python_path_removed = $true
        cycles = $results
    }
    $reportPath = Join-Path $reportDirectory "frozen-sidecar-lifecycle.json"
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host "Frozen sidecar lifecycle verification passed: $reportPath"
} finally {
    if ($null -ne $occupiedListener) {
        $occupiedListener.Stop()
    }
    if (Test-Path -LiteralPath $runRoot) {
        $resolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        $resolvedRunRoot = [System.IO.Path]::GetFullPath($runRoot)
        if ($resolvedRunRoot.StartsWith($resolvedTempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedRunRoot -Recurse -Force
        }
    }
}

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Write-LlmWikiUtf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $Value, [System.Text.UTF8Encoding]::new($false))
}

function Get-LlmWikiJsonBody {
    param([AllowEmptyString()][string]$Text)

    if (-not $Text) {
        return $null
    }
    try {
        return $Text | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function New-LlmWikiIsolatedPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try {
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

function New-LlmWikiIdempotencyKey {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes([Guid]::NewGuid().ToString("N"))
    $hash = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($hash.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $hash.Dispose()
    }
}

function Invoke-LlmWikiApi {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST", "PUT", "PATCH", "DELETE")][string]$Method,
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$SessionToken,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body,
        [hashtable]$Headers = @{},
        [int]$TimeoutSeconds = 20
    )

    $requestHeaders = @{
        Authorization = "Bearer $SessionToken"
        Accept = "application/json"
    }
    foreach ($name in $Headers.Keys) {
        $requestHeaders[$name] = $Headers[$name]
    }
    $parameters = @{
        Method = $Method
        Uri = "$BaseUrl$Path"
        Headers = $requestHeaders
        UseBasicParsing = $true
        TimeoutSec = $TimeoutSeconds
    }
    if ($null -ne $Body) {
        $parameters.Body = $Body | ConvertTo-Json -Depth 50 -Compress
        $parameters.ContentType = "application/json"
    }

    try {
        $response = Invoke-WebRequest @parameters
        return [ordered]@{
            status = [int]$response.StatusCode
            body = Get-LlmWikiJsonBody ([string]$response.Content)
            raw = [string]$response.Content
        }
    }
    catch {
        $statusCode = 0
        $raw = ""
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $raw = [string]$_.ErrorDetails.Message
        }
        $response = $_.Exception.Response
        if ($response) {
            try {
                $statusCode = [int]$response.StatusCode
            }
            catch {
                $statusCode = 0
            }
            if (-not $raw) {
                try {
                    $reader = [System.IO.StreamReader]::new($response.GetResponseStream())
                    try {
                        $raw = $reader.ReadToEnd()
                    }
                    finally {
                        $reader.Dispose()
                    }
                }
                catch {
                    $raw = ""
                }
            }
        }
        return [ordered]@{
            status = $statusCode
            body = Get-LlmWikiJsonBody $raw
            raw = $raw
            error = "request_failed"
        }
    }
}

function Start-LlmWikiIsolatedSidecar {
    param(
        [Parameter(Mandatory = $true)][string]$BackendDir,
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [Parameter(Mandatory = $true)][string]$SessionToken,
        [Parameter(Mandatory = $true)][int]$Port,
        [string]$HostName = "127.0.0.1",
        [hashtable]$Environment = @{},
        [string]$DatabaseFileName = "agent_pet_llmwiki.sqlite3"
    )

    $python = (Get-Command python -ErrorAction Stop).Source
    $dataDir = Join-Path $RuntimeRoot "data"
    $vaultDir = Join-Path $RuntimeRoot "vault"
    New-Item -ItemType Directory -Force -Path $dataDir, $vaultDir | Out-Null

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $python
    $startInfo.Arguments = "-m app.sidecar_entry --host $HostName --port $Port --port-search-range 0"
    $startInfo.WorkingDirectory = $BackendDir
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $overrides = @{
        AGENT_PET_SESSION_TOKEN = $SessionToken
        AGENT_PET_DATA_DIR = $dataDir
        AGENT_PET_SQLITE_PATH = (Join-Path $dataDir $DatabaseFileName)
    }
    foreach ($name in $Environment.Keys) {
        $overrides[$name] = [string]$Environment[$name]
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $previousEnvironment = @{}
    try {
        foreach ($name in $overrides.Keys) {
            $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable(
                $name,
                [EnvironmentVariableTarget]::Process
            )
            [Environment]::SetEnvironmentVariable(
                $name,
                [string]$overrides[$name],
                [EnvironmentVariableTarget]::Process
            )
        }
        if (-not $process.Start()) {
            throw "SIDECAR_START_FAILED"
        }
    }
    finally {
        foreach ($name in $previousEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable(
                $name,
                $previousEnvironment[$name],
                [EnvironmentVariableTarget]::Process
            )
        }
    }
    $process | Add-Member -NotePropertyName LlmWikiStdoutTask -NotePropertyValue ($process.StandardOutput.ReadToEndAsync()) -Force
    $process | Add-Member -NotePropertyName LlmWikiStderrTask -NotePropertyValue ($process.StandardError.ReadToEndAsync()) -Force
    $process | Add-Member -NotePropertyName LlmWikiRuntimeRoot -NotePropertyValue $RuntimeRoot -Force
    $process | Add-Member -NotePropertyName LlmWikiSessionToken -NotePropertyValue $SessionToken -Force
    return $process
}

function Stop-LlmWikiIsolatedSidecar {
    param(
        [System.Diagnostics.Process]$Process,
        [switch]$Dispose
    )

    if ($null -eq $Process) {
        return
    }
    try {
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
            [void]$Process.WaitForExit(5000)
        }
    }
    catch {
    }
    if ($Dispose) {
        try {
            $Process.Dispose()
        }
        catch {
        }
    }
}

function Wait-LlmWikiHealth {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$SessionToken,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $response = Invoke-LlmWikiApi -Method GET -BaseUrl $BaseUrl -SessionToken $SessionToken -Path "/api/health"
        if (
            $response.status -eq 200 -and
            $response.body -and
            [string]$response.body.status -in @("ok", "degraded")
        ) {
            return $response
        }
        Start-Sleep -Milliseconds 400
    }
    return $null
}

function Read-LlmWikiSidecarLog {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][ValidateSet("stdout", "stderr")][string]$Stream,
        [string[]]$AdditionalSecrets = @()
    )

    $task = if ($Stream -eq "stdout") { $Process.LlmWikiStdoutTask } else { $Process.LlmWikiStderrTask }
    $value = if ($task) { [string]$task.GetAwaiter().GetResult() } else { "" }
    $secrets = @(
        [string]$Process.LlmWikiSessionToken
        [string]$Process.LlmWikiRuntimeRoot
        $AdditionalSecrets
    ) | Where-Object { $_ }
    foreach ($secret in $secrets) {
        $replacement = if ($secret -eq [string]$Process.LlmWikiRuntimeRoot) { "[ISOLATED_RUNTIME]" } else { "[REDACTED]" }
        $value = $value.Replace($secret, $replacement)
    }
    return $value
}

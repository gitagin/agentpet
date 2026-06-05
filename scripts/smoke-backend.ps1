param(
  [string]$BaseUrl = "http://127.0.0.1:8765",
  [string]$SessionToken = "",
  [string]$WorkDir = "",
  [string]$Timezone = "Asia/Shanghai"
)

$ErrorActionPreference = "Stop"

if (-not $SessionToken) {
  $SessionToken = $env:AGENT_PET_SESSION_TOKEN
}
if (-not $SessionToken) {
  $SessionToken = "dev-token"
}

if (-not $WorkDir) {
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) "agent-pet-smoke-$stamp"
}

$BaseUrl = $BaseUrl.TrimEnd("/")
$headers = @{
  Authorization = "Bearer $SessionToken"
  Accept = "application/json"
}

function Invoke-SmokeJson {
  param(
    [string]$Method,
    [string]$Path,
    [object]$Body = $null
  )

  $params = @{
    Method = $Method
    Uri = "$BaseUrl$Path"
    Headers = $headers
    ContentType = "application/json"
  }
  if ($null -ne $Body) {
    $params.Body = ($Body | ConvertTo-Json -Depth 10)
  }
  Invoke-RestMethod @params
}

function Assert-True {
  param(
    [bool]$Condition,
    [string]$Message
  )
  if (-not $Condition) {
    throw $Message
  }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$vaultRoot = Join-Path $WorkDir "PetMemoryVault"
New-Item -ItemType Directory -Force -Path $vaultRoot | Out-Null
Set-Content -LiteralPath (Join-Path $vaultRoot "Project.md") -Encoding UTF8 -Value "# Project Memory`n`nThe smoke sentinel keyword is citrine-falcon."
Set-Content -LiteralPath (Join-Path $vaultRoot "Preferences.md") -Encoding UTF8 -Value "# Preferences`n"

Write-Host "Smoke workspace: $WorkDir"

$health = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/health"
Assert-True ($health.status -eq "ok") "Health check did not return status=ok."
Assert-True (-not ($health.PSObject.Properties.Name -contains "active_vault_id")) "Health response leaked active_vault_id."
Write-Host "ok health"

$unauthorizedStatus = 0
try {
  Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/vaults/status" | Out-Null
}
catch {
  $unauthorizedStatus = [int]$_.Exception.Response.StatusCode
}
Assert-True ($unauthorizedStatus -eq 401) "Protected endpoint without Authorization should return 401."
Write-Host "ok auth-required"

$vault = Invoke-SmokeJson -Method Post -Path "/api/vaults/init" -Body @{
  path = $vaultRoot
  create_if_missing = $false
  confirmed = $true
}
Assert-True ([bool]$vault.vault_id) "Vault init did not return vault_id."
Write-Host "ok vault init $($vault.vault_id)"

$index = Invoke-SmokeJson -Method Post -Path "/api/vaults/$($vault.vault_id)/index" -Body @{}
Assert-True ($index.files_indexed -ge 1) "Vault index did not index any files."
Write-Host "ok vault index files_indexed=$($index.files_indexed)"

$search = Invoke-SmokeJson -Method Post -Path "/api/memory/search" -Body @{
  query = "citrine-falcon"
  top_k = 5
  mode = "fts"
}
Assert-True ($search.results.Count -ge 1) "Memory search did not return the smoke sentinel."
Assert-True ($search.results[0].relative_path -eq "Project.md") "Memory search returned an unexpected first path."
Write-Host "ok memory search"

$proposal = Invoke-SmokeJson -Method Post -Path "/api/memory/proposals" -Body @{
  type = "preference"
  content = "User prefers smoke test notes to stay concise."
  target_path = "Preferences.md"
}
Assert-True ($proposal.status -eq "pending") "Memory proposal was not pending."
$confirmed = Invoke-SmokeJson -Method Post -Path "/api/memory/proposals/$($proposal.proposal_id)/confirm" -Body @{}
Assert-True ($confirmed.status -eq "confirmed") "Memory proposal was not confirmed."
Assert-True ((Get-Content -LiteralPath (Join-Path $vaultRoot "Preferences.md") -Raw).Contains("smoke test notes")) "Confirmed proposal was not written to Markdown."
Write-Host "ok memory proposal confirm"

$rejectedProposal = Invoke-SmokeJson -Method Post -Path "/api/memory/proposals" -Body @{
  type = "fact"
  content = "Rejected smoke memory must not be written."
  target_path = "Preferences.md"
}
$rejected = Invoke-SmokeJson -Method Post -Path "/api/memory/proposals/$($rejectedProposal.proposal_id)/reject" -Body @{
  reason = "smoke rejection path"
}
Assert-True ($rejected.status -eq "rejected") "Memory proposal was not rejected."
Assert-True (-not (Get-Content -LiteralPath (Join-Path $vaultRoot "Preferences.md") -Raw).Contains("Rejected smoke memory")) "Rejected proposal was written to Markdown."
Write-Host "ok memory proposal reject"

$task = Invoke-SmokeJson -Method Post -Path "/api/tasks" -Body @{
  title = "Smoke reminder"
  description = "Verify task endpoint"
  due_at = "2026-04-27T15:00:00"
  remind_at = "2026-04-27T14:30:00"
  timezone = $Timezone
  source_text = "smoke test reminder"
}
Assert-True ([bool]$task.task_id) "Task create did not return task_id."
$tasks = Invoke-SmokeJson -Method Get -Path "/api/tasks"
Assert-True ($tasks.tasks.Count -ge 1) "Task list did not return the created task."
Write-Host "ok tasks"

$chat = Invoke-SmokeJson -Method Post -Path "/api/chat" -Body @{
  message = "Search memory for citrine-falcon."
}
Assert-True ([bool]$chat.stream_url) "Chat did not return stream_url."
$streamResponse = Invoke-WebRequest -UseBasicParsing -Method Get -Uri "$BaseUrl$($chat.stream_url)" -Headers @{
  Authorization = "Bearer $SessionToken"
  Accept = "text/event-stream"
}
Assert-True ($streamResponse.Content.Contains("event:")) "Chat stream did not contain SSE events."
Assert-True ($streamResponse.Content.Contains("event: done") -or $streamResponse.Content.Contains("event: error")) "Chat stream did not finish with done/error."
Write-Host "ok chat stream"

$diagnostics = Invoke-SmokeJson -Method Get -Path "/api/diagnostics/export"
Assert-True ($diagnostics.database.reachable -eq $true) "Diagnostics export did not report a reachable database."
Assert-True ($diagnostics.database.quick_check -eq "ok") "Diagnostics export quick_check was not ok."
Assert-True ($diagnostics.vault.configured -eq $true) "Diagnostics export did not report a configured Vault."
Assert-True ($diagnostics.vault.vault_count -ge 1) "Diagnostics export did not include the smoke Vault."
Assert-True ($diagnostics.recent_index_jobs.Count -ge 1) "Diagnostics export did not include recent index jobs."
Assert-True ($diagnostics.database.table_counts.tasks -ge 1) "Diagnostics export did not include the smoke task count."
Write-Host "ok diagnostics export"

Write-Host "Backend smoke test passed."

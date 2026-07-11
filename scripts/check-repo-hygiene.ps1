$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $RepoRoot
try {
  $git = Get-Command git -ErrorAction SilentlyContinue
  if ($null -eq $git) {
    Write-Host "repo hygiene check skipped: git is not available."
    exit 0
  }

  $tracked = @(git -c core.quotepath=false ls-files)
  if ($LASTEXITCODE -ne 0) {
    Write-Error "repo hygiene check failed: git ls-files did not complete."
    exit 1
  }

  $forbiddenPatterns = @(
    '(^|/)\.coverage(\..*)?$',
    '(^|/)[^/]+\.egg-info/',
    '(^|/)__pycache__/',
    '(^|/)\.pytest_cache/',
    '(^|/)\.mypy_cache/',
    '(^|/)\.ruff_cache/',
    '(^|/)\.vite/',
    '(^|/)node_modules/',
    '(^|/)dist/',
    '(^|/)release/',
    '(^|/)chrome-profile[^/]*/',
    '(^|/)\.tmp-seethrough-prompt[^/]*\.json$',
    '(^|/)\.claude/settings\.local\.json$',
    '(^|/)[^/]+\.credentials/',
    '\.(log|pid|pyc|pyo|db|db-wal|db-shm|db-journal|sqlite|sqlite3|sqlite-wal|sqlite-shm|dpapi)$'
  )

  $forbiddenPrefixes = @(
    'output/',
    'apps/desktop/output/',
    '.playwright-cli/',
    'vault/',
    '.codex/',
    '.impeccable/live/'
  )

  $allowedLargePrefixes = @(
    'apps/desktop/public/images/',
    'apps/desktop/public/sprite-pet/'
  )

  $failures = New-Object System.Collections.Generic.List[string]
  $forbiddenPrefixCounts = @{}
  foreach ($path in $tracked) {
    if (-not (Test-Path -LiteralPath $path)) {
      continue
    }
    $normalized = $path.Replace('\', '/')
    $matchedForbiddenPrefix = $false
    foreach ($prefix in $forbiddenPrefixes) {
      if ($normalized.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        if (-not $forbiddenPrefixCounts.ContainsKey($prefix)) {
          $forbiddenPrefixCounts[$prefix] = 0
        }
        $forbiddenPrefixCounts[$prefix] += 1
        $matchedForbiddenPrefix = $true
        break
      }
    }
    if ($matchedForbiddenPrefix) {
      continue
    }
    foreach ($pattern in $forbiddenPatterns) {
      if ($normalized -match $pattern) {
        $failures.Add("tracked generated/local-state file: $normalized") | Out-Null
        break
      }
    }
  }

  foreach ($prefix in $forbiddenPrefixes) {
    if ($forbiddenPrefixCounts.ContainsKey($prefix)) {
      $failures.Add(
        "tracked generated/local-state prefix: $prefix ($($forbiddenPrefixCounts[$prefix]) files)"
      ) | Out-Null
    }
  }

  $largeFiles = New-Object System.Collections.Generic.List[object]
  $presentTrackedCount = 0
  $trackedSize = 0L
  $allowedLargeSize = 0L
  foreach ($path in $tracked) {
    if (-not (Test-Path -LiteralPath $path)) {
      continue
    }
    $item = Get-Item -LiteralPath $path
    $presentTrackedCount += 1
    $trackedSize += $item.Length
    $normalized = $path.Replace('\', '/')
    $isAllowedLarge = $false
    foreach ($prefix in $allowedLargePrefixes) {
      if ($normalized.StartsWith($prefix)) {
        $isAllowedLarge = $true
        $allowedLargeSize += $item.Length
        break
      }
    }
    if ($item.Length -gt 20MB -and -not $isAllowedLarge) {
      $largeFiles.Add([pscustomobject]@{
        Path = $normalized
        SizeMB = [math]::Round($item.Length / 1MB, 2)
      }) | Out-Null
    }
  }

  foreach ($file in $largeFiles) {
    $failures.Add("tracked file exceeds 20MB outside allowed asset roots: $($file.Path) ($($file.SizeMB) MB)") | Out-Null
  }

  $maxTrackedSize = 100MB
  if ($trackedSize -gt $maxTrackedSize) {
    $failures.Add(
      "tracked repository size exceeds 100 MB budget: $([math]::Round($trackedSize / 1MB, 2)) MB"
    ) | Out-Null
  }

  Write-Host ("tracked index entries: {0}" -f $tracked.Count)
  Write-Host ("present tracked files: {0}" -f $presentTrackedCount)
  Write-Host ("tracked size: {0} MB" -f ([math]::Round($trackedSize / 1MB, 2)))
  Write-Host ("allowed large asset size: {0} MB" -f ([math]::Round($allowedLargeSize / 1MB, 2)))

  if ($failures.Count -gt 0) {
    Write-Error ("repo hygiene check failed:`n- " + ($failures -join "`n- "))
    exit 1
  }

  Write-Host "repo hygiene check passed."
}
finally {
  Pop-Location
}

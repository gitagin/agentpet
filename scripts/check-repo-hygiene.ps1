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
    '(^|/)\.vite/',
    '(^|/)node_modules/',
    '(^|/)dist/',
    '(^|/)release/',
    '(^|/)[^/]+\.credentials/',
    '\.(pyc|pyo|db|sqlite|sqlite3|sqlite-wal|sqlite-shm|dpapi)$'
  )

  $allowedLargePrefixes = @(
    'apps/desktop/public/images/',
    'apps/desktop/public/sprite-pet/'
  )

  $failures = New-Object System.Collections.Generic.List[string]
  foreach ($path in $tracked) {
    if (-not (Test-Path -LiteralPath $path)) {
      continue
    }
    $normalized = $path.Replace('\', '/')
    foreach ($pattern in $forbiddenPatterns) {
      if ($normalized -match $pattern) {
        $failures.Add("tracked generated/local-state file: $normalized") | Out-Null
        break
      }
    }
  }

  $largeFiles = New-Object System.Collections.Generic.List[object]
  $trackedSize = 0L
  $allowedLargeSize = 0L
  foreach ($path in $tracked) {
    if (-not (Test-Path -LiteralPath $path)) {
      continue
    }
    $item = Get-Item -LiteralPath $path
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

  Write-Host ("tracked files: {0}" -f $tracked.Count)
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

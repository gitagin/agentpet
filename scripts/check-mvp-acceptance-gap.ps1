$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$MatrixPath = Join-Path $RepoRoot "docs\mvp-acceptance-coverage.md"
$BackendRoot = Join-Path $RepoRoot "apps\backend"
$DesktopRoot = Join-Path $RepoRoot "apps\desktop"

$failures = New-Object System.Collections.Generic.List[string]
$notes = New-Object System.Collections.Generic.List[string]

function Add-Failure {
  param([string]$Message)
  $failures.Add($Message) | Out-Null
}

function Add-Note {
  param([string]$Message)
  $notes.Add($Message) | Out-Null
}

function Read-Text {
  param([string]$Path)
  return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Test-Text {
  param(
    [string]$Text,
    [string]$Pattern
  )
  return [regex]::IsMatch($Text, $Pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
}

if (-not (Test-Path $MatrixPath)) {
  Add-Failure "Coverage matrix is missing: docs\mvp-acceptance-coverage.md"
} else {
  $matrix = Read-Text $MatrixPath
  foreach ($id in 1..18) {
    $mvpId = "MVP-{0:D2}" -f $id
    if ($matrix -notmatch [regex]::Escape($mvpId)) {
      Add-Failure "Coverage matrix is missing $mvpId."
    }
  }

  $requiredRows = @{
    "MVP-14" = "Covered"
    "MVP-15" = "Partial"
    "MVP-18" = "Covered"
    "Full Live2D" = "Partial / Gap"
    "Actual signed auto-update" = "Out of scope / Gap"
  }

  foreach ($entry in $requiredRows.GetEnumerator()) {
    $pattern = "\|\s*$([regex]::Escape($entry.Key))\s*\|[^\r\n]*$([regex]::Escape($entry.Value))[^\r\n]*\|"
    if (-not (Test-Text $matrix $pattern)) {
      Add-Failure "Coverage matrix does not mark '$($entry.Key)' as '$($entry.Value)'."
    }
  }

  foreach ($term in @(
    'Manual Electron validation on 2026-05-15 confirmed near-term reminder triggered and emitted one OS notification',
    'Full natural-language date parsing is not implemented',
    'structured audit/application logging implementation',
    'lacks lip sync, complex motion sequencing, multi-character resource management',
    'no `publish`, signing, or `autoUpdater` contract'
  )) {
    if (-not $matrix.Contains($term)) {
      Add-Failure "Coverage matrix is missing gap detail: $term"
    }
  }
}

$electronMainPath = Join-Path $DesktopRoot "electron\main.cjs"
$electronRoot = Join-Path $DesktopRoot "electron"
if (-not (Test-Path $electronMainPath)) {
  Add-Failure "Electron main file is missing."
} else {
  $electronRuntimeFiles = Get-ChildItem -Path $electronRoot -File |
    Where-Object { $_.Extension -in @(".cjs", ".js") }
  $electronRuntime = ($electronRuntimeFiles | ForEach-Object { Read-Text $_.FullName }) -join "`n"
  if (-not (Test-Text $electronRuntime "spawn\s*\(")) {
    Add-Failure "Electron runtime no longer shows a sidecar spawn signal."
  }
  if (-not (Test-Text $electronRuntime "AGENT_PET_SESSION_TOKEN")) {
    Add-Failure "Electron runtime no longer passes AGENT_PET_SESSION_TOKEN to the sidecar."
  }
  if (-not (Test-Text $electronRuntime "\bNotification\b|new\s+Notification\s*\(")) {
    Add-Failure "Electron runtime no longer references Notification; update MVP-14 matrix if reminder delivery is removed."
  }
  if (-not (Test-Text $electronRuntime "agent-pet:show-reminder-notification")) {
    Add-Failure "Electron reminder notification IPC bridge is missing."
  }
  if (-not (Test-Text $electronRuntime "\bTray\b|new\s+Tray\s*\(")) {
    Add-Failure "Electron runtime no longer references Tray; update tray coverage notes."
  }
  if (Test-Text $electronRuntime "autoUpdater|electron-updater") {
    Add-Failure "Electron runtime now references an updater; update signed auto-update coverage notes."
  }
}

$schedulerPath = Join-Path $BackendRoot "app\scheduler\reminders.py"
if (-not (Test-Path $schedulerPath)) {
  Add-Failure "Reminder scheduler file is missing."
} else {
  $scheduler = Read-Text $schedulerPath
  foreach ($term in @(
    "class\s+APSchedulerReminderScheduler",
    "AsyncIOScheduler",
    "SQLAlchemyJobStore",
    "fire_reminder_job"
  )) {
    if (-not (Test-Text $scheduler $term)) {
      Add-Failure "Persistent reminder scheduler signal is missing: $term"
    }
  }
}

$taskTestsPath = Join-Path $BackendRoot "tests\test_tasks_services.py"
if (Test-Path $taskTestsPath) {
  $taskTests = Read-Text $taskTestsPath
  foreach ($term in @(
    "test_scheduler_failure_keeps_task_and_marks_reminder_unscheduled",
    "test_create_task_converts_local_times_to_utc_and_schedules_reminder",
    "test_create_task_parses_chinese_absolute_reminder_time"
  )) {
    if ($taskTests -notlike "*$term*") {
      Add-Failure "Task service acceptance evidence is missing: $term"
    }
  }
} else {
  Add-Failure "Task service tests are missing."
}

$schedulerTestsPath = Join-Path $BackendRoot "tests\test_reminder_scheduler.py"
if (Test-Path $schedulerTestsPath) {
  $schedulerTests = Read-Text $schedulerTestsPath
  foreach ($term in @(
    "test_reminder_job_persists_across_scheduler_restart",
    "test_due_reminder_job_marks_reminder_triggered",
    "test_cancelled_reminder_job_is_not_restored_after_restart"
  )) {
    if ($schedulerTests -notlike "*$term*") {
      Add-Failure "Persistent scheduler acceptance evidence is missing: $term"
    }
  }
} else {
  Add-Failure "Persistent reminder scheduler tests are missing."
}

$desktopFiles = Get-ChildItem -Path $DesktopRoot -Recurse -File |
  Where-Object { $_.FullName -notmatch "\\node_modules\\|\\dist\\" }
$desktopText = ($desktopFiles | ForEach-Object { Read-Text $_.FullName }) -join "`n"
if (-not (Test-Text $desktopText "live2d|Cubism")) {
  Add-Failure "Live2D/Cubism signal is missing; update Live2D coverage notes."
}

Add-Note "Checked MVP matrix, persistent reminder runtime, Live2D partial coverage, tray integration, and updater gap."

foreach ($note in $notes) {
  Write-Host "note: $note"
}

if ($failures.Count -gt 0) {
  Write-Error ("MVP acceptance gap contract failed:`n- " + ($failures -join "`n- "))
  exit 1
}

Write-Host "MVP acceptance gap contract passed."

$files = @(
  'apps/desktop/src/styles/dashboard.css',
  'apps/desktop/src/styles/desktop-polish.css',
  'apps/desktop/src/styles/llmwiki-memory.css',
  'apps/desktop/src/styles/stage-restore.css'
)
foreach ($file in $files) {
  Write-Output ("===== " + $file + " =====")
  $lines = Get-Content $file
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'bottom-nav|control-bottom-dock|stage-footer') {
      $start = [Math]::Max(0, $i - 4)
      $end = [Math]::Min($lines.Count - 1, $i + 8)
      for ($j = $start; $j -le $end; $j++) {
        "{0}:{1}" -f ($j + 1), $lines[$j]
      }
      ''
    }
  }
}

param([string]$Path, [int]$Start, [int]$Count)
$i = 0
Get-Content -LiteralPath $Path | ForEach-Object { $i++; if ($i -ge $Start -and $i -lt ($Start + $Count)) { Write-Output ("{0}: {1}" -f $i, $_) } }

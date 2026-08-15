[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BaselinePath,

    [string]$TaskPath = "$(Join-Path $PSScriptRoot '..\修改task.md')"
)

$ErrorActionPreference = 'Stop'

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Value)

    return [System.IO.Path]::GetFullPath($Value)
}

function Read-StatusLines {
    param([Parameter(Mandatory = $true)][string]$Value)

    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return @($Value -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    }
    return @()
}

function Get-PathPart {
    param([Parameter(Mandatory = $true)][string]$Line)

    if ($Line.Length -lt 4) {
        return $Line.Trim()
    }
    $path = $Line.Substring(3).Trim()
    if ($path -match ' -> ') {
        $path = $path.Substring($path.LastIndexOf(' -> ', [System.StringComparison]::Ordinal) + 4)
    }
    return $path.Trim('"')
}

function Get-ComparableLines {
    param([Parameter(Mandatory = $true)][string[]]$Lines)

    return @(
        $Lines |
            Where-Object { (Get-PathPart $_) -ne '修改task.md' } |
            Sort-Object
    )
}

$baseline = Resolve-FullPath $BaselinePath
$task = Resolve-FullPath $TaskPath
if (-not (Test-Path -LiteralPath $baseline -PathType Leaf)) {
    Write-Error "BOUNDARY_BASELINE_MISSING:$baseline"
    exit 2
}
if (-not (Test-Path -LiteralPath $task -PathType Leaf)) {
    Write-Error "TASK_FILE_MISSING:$task"
    exit 1
}

$gitLines = & git -c core.quotepath=false status --porcelain=v1 --untracked-files=all
if ($LASTEXITCODE -ne 0) {
    Write-Error 'GIT_STATUS_FAILED'
    exit 1
}

$before = Get-ComparableLines (Read-StatusLines (Get-Content -LiteralPath $baseline -Raw -Encoding UTF8))
$after = Get-ComparableLines (Read-StatusLines (($gitLines -join "`n")))
$difference = Compare-Object -ReferenceObject $before -DifferenceObject $after
if ($null -ne $difference -and @($difference).Count -gt 0) {
    $payload = [ordered]@{
        status = 'failed'
        reason = 'unrelated_worktree_changes'
        baseline = $before
        current = $after
        difference = @($difference | ForEach-Object {
                [ordered]@{ side = $_.SideIndicator; line = $_.InputObject }
            })
    }
    $payload | ConvertTo-Json -Depth 8
    exit 1
}

[ordered]@{
    status = 'passed'
    task_file = $task
    baseline_path = $baseline
    unrelated_paths_unchanged = $true
    current_status_count = @($gitLines).Count
} | ConvertTo-Json -Depth 5
exit 0

$ProjectRoot = 'D:\GitHub\qBittorrent rss rules'

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Project path not found: $ProjectRoot"
}

Set-Location -LiteralPath $ProjectRoot

$Targets = @(
    '.history',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '.venv-linux',
    'dist',
    'work',
    'debug.log',
    'logs\search-debug.log',
    'logs\search-debug-pc101412.log',
    'logs\search-debug-DESKTOP-4OSCNPH.log'
)

$Targets += Get-ChildItem -LiteralPath $ProjectRoot -Force -File -Filter '.tmp_*' |
    Select-Object -ExpandProperty FullName

$Resolved = foreach ($Target in $Targets) {
    $Path = if ([IO.Path]::IsPathRooted($Target)) {
        $Target
    } else {
        Join-Path $ProjectRoot $Target
    }

    if (Test-Path -LiteralPath $Path) {
        Get-Item -LiteralPath $Path
    }
}

$TotalBytes = 0

Write-Host "`nCleanup candidates:`n" -ForegroundColor Cyan

foreach ($Item in $Resolved) {
    $Bytes = if ($Item.PSIsContainer) {
        (Get-ChildItem -LiteralPath $Item.FullName -File -Recurse -Force -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
    } else {
        $Item.Length
    }

    if ($null -eq $Bytes) { $Bytes = 0 }
    $TotalBytes += $Bytes

    Write-Host ("{0,8:N2} GB  {1}" -f ($Bytes / 1GB), $Item.FullName)
}

Write-Host ("`nPotentially reclaimable: {0:N2} GB" -f ($TotalBytes / 1GB)) -ForegroundColor Yellow
Write-Host "`nNot touched: data, logs\qa, .venv, source, .git, QbRssRulesDesktop, and nppBackup." -ForegroundColor Green

$Answer = Read-Host "`nDelete these candidates permanently? Type DELETE"
if ($Answer -cne 'DELETE') {
    Write-Host 'Cancelled. Nothing was deleted.' -ForegroundColor Yellow
    exit 0
}

foreach ($Item in $Resolved) {
    Remove-Item -LiteralPath $Item.FullName -Recurse -Force -ErrorAction Stop
}

Write-Host ("`nDeleted {0} items; reclaimed approximately {1:N2} GB." -f $Resolved.Count, ($TotalBytes / 1GB)) -ForegroundColor Green
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$ShortcutName = "qB RSS Rules Desktop.lnk"
)

$ErrorActionPreference = "Stop"

$exePath = Join-Path $ProjectRoot "QbRssRulesDesktop\bin\x64\Debug\net10.0-windows10.0.19041.0\win-x64\QbRssRulesDesktop.exe"
if (-not (Test-Path $exePath)) {
    throw "WinUI executable not found: $exePath"
}

$desktopDir = [Environment]::GetFolderPath("Desktop")
$shortcutTargets = @(
    (Join-Path $ProjectRoot $ShortcutName),
    (Join-Path $desktopDir $ShortcutName)
)

$legacyRepoShortcut = Join-Path $ProjectRoot "QbRssRulesDesktop.exe.lnk"
if ((Test-Path $legacyRepoShortcut) -and ($legacyRepoShortcut -notin $shortcutTargets)) {
    Remove-Item $legacyRepoShortcut -Force
}

$shell = New-Object -ComObject WScript.Shell
$workingDirectory = Split-Path $exePath -Parent

foreach ($shortcutPath in $shortcutTargets) {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $exePath
    $shortcut.WorkingDirectory = $workingDirectory
    $shortcut.IconLocation = "$exePath,0"
    $shortcut.Description = "Launch qB RSS Rules Desktop"
    $shortcut.Save()
    Write-Output "Updated shortcut: $shortcutPath"
}

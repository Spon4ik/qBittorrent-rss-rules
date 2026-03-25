param(
    [string]$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "Programs\qB RSS Rules Desktop"),
    [switch]$SkipShortcuts
)

$ErrorActionPreference = "Stop"

function Invoke-Robocopy {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination,
        [string[]]$ExtraArgs = @()
    )

    if (-not (Test-Path $Source)) {
        throw "Source path not found: $Source"
    }

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $arguments = @($Source, $Destination) + $ExtraArgs
    & robocopy @arguments | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed ($LASTEXITCODE): $Source -> $Destination"
    }
}

function Set-Shortcut {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ShortcutPath,
        [Parameter(Mandatory = $true)]
        [string]$TargetPath,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.IconLocation = "$TargetPath,0"
    $shortcut.Description = "Launch qB RSS Rules Desktop"
    $shortcut.Save()
}

$sourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
$installRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$requiredPaths = @(
    (Join-Path $sourceRoot "QbRssRulesDesktop.exe"),
    (Join-Path $sourceRoot "app\main.py"),
    (Join-Path $sourceRoot "python\python.exe")
)

foreach ($requiredPath in $requiredPaths) {
    if (-not (Test-Path $requiredPath)) {
        throw "Bundle is incomplete. Missing: $requiredPath"
    }
}

Write-Output "Installing bundle to: $installRoot"
New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
Invoke-Robocopy -Source $sourceRoot -Destination $installRoot -ExtraArgs @("/E", "/R:1", "/W:1", "/XD", "data", "logs")
New-Item -ItemType Directory -Force -Path (Join-Path $installRoot "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $installRoot "logs") | Out-Null

$installedExe = Join-Path $installRoot "QbRssRulesDesktop.exe"
if (-not (Test-Path $installedExe)) {
    throw "Installed executable not found: $installedExe"
}

if (-not $SkipShortcuts) {
    $desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "qB RSS Rules Desktop.lnk"
    $startMenuDir = [Environment]::GetFolderPath("Programs")
    $startMenuShortcut = Join-Path $startMenuDir "qB RSS Rules Desktop.lnk"
    Set-Shortcut -ShortcutPath $desktopShortcut -TargetPath $installedExe -WorkingDirectory $installRoot
    Set-Shortcut -ShortcutPath $startMenuShortcut -TargetPath $installedExe -WorkingDirectory $installRoot
    Write-Output "Updated shortcut: $desktopShortcut"
    Write-Output "Updated shortcut: $startMenuShortcut"
}

Write-Output "Launcher: $installedExe"
Write-Output "User data is preserved in: $(Join-Path $installRoot 'data')"

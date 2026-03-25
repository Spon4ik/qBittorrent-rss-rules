param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Configuration = "Release",
    [string]$Platform = "x64",
    [string]$OutputRoot = "dist",
    [switch]$CreateZip
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

$projectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$outputRoot = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    [System.IO.Path]::GetFullPath($OutputRoot)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputRoot))
}
$bundleName = "qB RSS Rules Desktop-win-$Platform"
$bundleRoot = Join-Path $outputRoot $bundleName
$zipPath = Join-Path $outputRoot "$bundleName.zip"

$desktopProject = Join-Path $projectRoot "QbRssRulesDesktop\QbRssRulesDesktop.csproj"
$publishProfile = "win-$Platform"
$publishDir = Join-Path $projectRoot "QbRssRulesDesktop\bin\$Configuration\net10.0-windows10.0.19041.0\win-$Platform\publish"
$repoPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$repoSitePackages = Join-Path $projectRoot ".venv\Lib\site-packages"
$installScript = Join-Path $projectRoot "scripts\install_desktop_bundle.ps1"
$installCmdTemplate = Join-Path $projectRoot "scripts\install_desktop_bundle.cmd"
$dotnetCmd = Join-Path $env:ProgramFiles "dotnet\dotnet.exe"
if (-not (Test-Path $dotnetCmd)) {
    $dotnetCmd = "dotnet"
}

if (-not (Test-Path $desktopProject)) {
    throw "Desktop project not found: $desktopProject"
}
if (-not (Test-Path $repoPython)) {
    throw "Repo virtualenv Python not found: $repoPython"
}
if (-not (Test-Path $repoSitePackages)) {
    throw "Repo site-packages not found: $repoSitePackages"
}
if (-not (Test-Path $installScript)) {
    throw "Install script not found: $installScript"
}
if (-not (Test-Path $installCmdTemplate)) {
    throw "Install CMD template not found: $installCmdTemplate"
}

$pythonBase = (& $repoPython -c "import sys; print(sys.base_prefix)").Trim()
if ([string]::IsNullOrWhiteSpace($pythonBase) -or -not (Test-Path $pythonBase)) {
    throw "Could not resolve the base Python installation used by .venv."
}

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
if (Test-Path $bundleRoot) {
    Remove-Item -Recurse -Force $bundleRoot
}
if ($CreateZip -and (Test-Path $zipPath)) {
    Remove-Item -Force $zipPath
}

Write-Output "Publishing WinUI desktop app ($Configuration/$Platform)..."
& $dotnetCmd publish $desktopProject -c $Configuration -p:Platform=$Platform -p:PublishProfile=$publishProfile -p:PublishTrimmed=false -p:PublishReadyToRun=false
if ($LASTEXITCODE -ne 0) {
    throw "dotnet publish failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path $publishDir)) {
    throw "Publish output not found: $publishDir"
}

Write-Output "Staging bundle: $bundleRoot"
New-Item -ItemType Directory -Force -Path $bundleRoot | Out-Null
Invoke-Robocopy -Source $publishDir -Destination $bundleRoot -ExtraArgs @("/E", "/R:1", "/W:1")
Invoke-Robocopy -Source (Join-Path $projectRoot "app") -Destination (Join-Path $bundleRoot "app") -ExtraArgs @("/E", "/R:1", "/W:1", "/XD", "__pycache__")
Invoke-Robocopy -Source $pythonBase -Destination (Join-Path $bundleRoot "python") -ExtraArgs @("/E", "/R:1", "/W:1", "/XD", "__pycache__")
Invoke-Robocopy -Source $repoSitePackages -Destination (Join-Path $bundleRoot "python\Lib\site-packages") -ExtraArgs @("/E", "/R:1", "/W:1", "/XD", "__pycache__")

New-Item -ItemType Directory -Force -Path (Join-Path $bundleRoot "scripts") | Out-Null
Copy-Item $installScript (Join-Path $bundleRoot "scripts\install_desktop_bundle.ps1") -Force
Copy-Item $installCmdTemplate (Join-Path $bundleRoot "Install qB RSS Rules Desktop.cmd") -Force
New-Item -ItemType Directory -Force -Path (Join-Path $bundleRoot "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $bundleRoot "logs") | Out-Null

$installNotes = @(
    "qB RSS Rules Desktop Windows bundle",
    "",
    "Portable launch:",
    "  Run QbRssRulesDesktop.exe directly from this folder.",
    "",
    "Installed launch:",
    "  Double-click 'Install qB RSS Rules Desktop.cmd'.",
    "  The installer copies this bundle to %LOCALAPPDATA%\Programs\qB RSS Rules Desktop",
    "  and creates Desktop and Start Menu shortcuts.",
    "",
    "Updates:",
    "  Re-run the installer from a newer bundle. Existing data\\ and logs\\ are preserved.",
    "",
    "Backend runtime:",
    "  This bundle includes a private Python runtime under python\\ and does not require",
    "  a system-wide Python installation.",
    ""
)
$installNotes | Set-Content -Path (Join-Path $bundleRoot "INSTALL.txt") -Encoding ASCII

if ($CreateZip) {
    Write-Output "Creating bundle zip: $zipPath"
    Compress-Archive -Path $bundleRoot -DestinationPath $zipPath -Force
}

Write-Output "Bundle ready:"
Write-Output "  Folder: $bundleRoot"
if ($CreateZip) {
    Write-Output "  Zip:    $zipPath"
}

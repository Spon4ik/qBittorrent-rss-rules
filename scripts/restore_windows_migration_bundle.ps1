[CmdletBinding()]
param(
    [string]$MigrationRoot = (Join-Path $env:USERPROFILE "OneDrive\Migration-192.168.1.52"),
    [string]$BackupRoot = "",
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$QbContentRoot = "C:\Torrent",
    [string]$JackettStremioHost = "http://host.docker.internal:9117",
    [switch]$SkipWingetInstall,
    [switch]$InstallDesktopSdk,
    [switch]$BuildRulesDesktop,
    [switch]$LaunchRulesDesktop,
    [switch]$SkipRulesAppStart
)

$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from an elevated PowerShell session."
    }
}

function Write-Section {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Output ""
    Write-Output "== $Message =="
}

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

function Grant-DirectoryModifyAccess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [string]$Identity = "NT AUTHORITY\NETWORK SERVICE"
    )

    if (-not (Test-Path $Path)) {
        throw "Path not found for ACL grant: $Path"
    }

    Invoke-CheckedCommand -FilePath "icacls.exe" -Arguments @(
        $Path,
        "/grant",
        "${Identity}:(OI)(CI)M",
        "/T",
        "/C",
        "/Q"
    ) -Description "Granting modify access to $Identity on $Path"
}

function Resolve-CommandPath {
    param(
        [string[]]$Names = @(),
        [string[]]$CandidatePaths = @()
    )

    foreach ($candidatePath in $CandidatePaths) {
        if ($candidatePath -and (Test-Path $candidatePath)) {
            return $candidatePath
        }
    }

    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    return $null
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if ($WorkingDirectory) {
        Push-Location $WorkingDirectory
    }

    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Description failed with exit code $LASTEXITCODE."
        }
    } finally {
        if ($WorkingDirectory) {
            Pop-Location
        }
    }
}

function Test-WingetPackageInstalled {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WingetCommand,
        [Parameter(Mandatory = $true)]
        [string]$PackageId
    )

    $output = & $WingetCommand list --id $PackageId --exact --accept-source-agreements 2>&1
    $listExitCode = $LASTEXITCODE
    $joinedOutput = $output | Out-String

    if ($listExitCode -ne 0) {
        return $false
    }

    if ($joinedOutput -match "No installed package found") {
        return $false
    }

    return $joinedOutput -match [regex]::Escape($PackageId)
}

function Invoke-WingetInstall {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WingetCommand,
        [Parameter(Mandatory = $true)]
        [string]$PackageId,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $WingetCommand @Arguments
    $installExitCode = $LASTEXITCODE
    if ($installExitCode -eq 0) {
        return
    }

    if (Test-WingetPackageInstalled -WingetCommand $WingetCommand -PackageId $PackageId) {
        Write-Warning "$Description returned exit code $installExitCode, but winget reports $PackageId is already installed. Continuing."
        return
    }

    throw "$Description failed with exit code $installExitCode."
}

function Resolve-BackupRootPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$MigrationRootPath,
        [string]$RequestedBackupRoot
    )

    if ($RequestedBackupRoot) {
        $resolvedBackupRoot = [System.IO.Path]::GetFullPath($RequestedBackupRoot)
        if (-not (Test-Path $resolvedBackupRoot)) {
            throw "Backup root not found: $resolvedBackupRoot"
        }
        return $resolvedBackupRoot
    }

    if (-not (Test-Path $MigrationRootPath)) {
        throw "Migration root not found: $MigrationRootPath"
    }

    $latestBackup = Get-ChildItem -Path $MigrationRootPath -Directory -Filter "backup-*" |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if (-not $latestBackup) {
        throw "No backup-* directories found under $MigrationRootPath"
    }
    return $latestBackup.FullName
}

function Read-InspectObject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        throw "Docker inspect file not found: $Path"
    }

    $payload = Get-Content $Path -Raw | ConvertFrom-Json
    if ($payload -is [System.Array]) {
        return $payload[0]
    }
    return $payload
}

function Get-InspectEnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [object]$InspectObject,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    foreach ($entry in ($InspectObject.Config.Env | Where-Object { $_ })) {
        if ($entry.StartsWith("$Name=")) {
            return $entry.Substring($Name.Length + 1)
        }
    }

    return $null
}

function Wait-ForDockerReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DockerCommand
    )

    $dockerDesktopExe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerDesktopExe) {
        Start-Process -FilePath $dockerDesktopExe | Out-Null
    }

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        for ($attempt = 1; $attempt -le 60; $attempt++) {
            & $DockerCommand version > $null 2> $null
            if ($LASTEXITCODE -eq 0) {
                return
            }
            Start-Sleep -Seconds 5
        }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    throw "Docker Desktop did not become ready. Start Docker Desktop once, wait for it to finish initializing, then rerun the script."
}

function ConvertTo-QbIniPathValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return ($Path -replace "\\", "\\\\")
}

function Set-IniLineValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Content,
        [Parameter(Mandatory = $true)]
        [string]$Key,
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $pattern = "(?m)^" + [regex]::Escape($Key) + "=.*$"
    $replacement = "$Key=$Value"

    if ([regex]::IsMatch($Content, $pattern)) {
        return [regex]::Replace($Content, $pattern, $replacement)
    }

    if ($Content -and -not $Content.EndsWith("`r`n")) {
        $Content += "`r`n"
    }
    return $Content + $replacement + "`r`n"
}

function Ensure-VirtualEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath,
        [string]$PyLauncher,
        [string]$PythonCommand
    )

    $venvDir = Join-Path $RepoPath ".venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    $venvIsUsable = $false

    if (Test-Path $venvPython) {
        & $venvPython -c "import sys; print(sys.executable)" *> $null
        $venvIsUsable = $LASTEXITCODE -eq 0
    }

    if (-not $venvIsUsable) {
        Remove-Item -Recurse -Force $venvDir -ErrorAction SilentlyContinue
        if ($PyLauncher) {
            Invoke-CheckedCommand -FilePath $PyLauncher -Arguments @("-3.12", "-m", "venv", $venvDir) -Description "Creating .venv with py launcher"
        } elseif ($PythonCommand) {
            Invoke-CheckedCommand -FilePath $PythonCommand -Arguments @("-m", "venv", $venvDir) -Description "Creating .venv with python"
        } else {
            throw "Python 3.12 launcher/interpreter not found after installation."
        }
    }

    return $venvPython
}

function Remove-DockerContainerIfPresent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DockerCommand,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $DockerCommand container inspect $Name > $null 2> $null
        if ($LASTEXITCODE -eq 0) {
            & $DockerCommand rm -f $Name > $null 2> $null
            if ($LASTEXITCODE -ne 0) {
                throw "Removing Docker container '$Name' failed with exit code $LASTEXITCODE."
            }
        }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Start-RulesApp {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath,
        [switch]$Desktop
    )

    $runDev = Join-Path $RepoPath "scripts\run_dev.bat"
    if (-not (Test-Path $runDev)) {
        throw "run_dev.bat not found: $runDev"
    }

    $mode = if ($Desktop) { "desktop" } else { "api" }
    Start-Process -FilePath "cmd.exe" -WorkingDirectory $RepoPath -ArgumentList @("/c", "scripts\run_dev.bat $mode") | Out-Null
}

function Test-LocalHttpEndpoint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return $response.StatusCode
    } catch {
        return $null
    }
}

$repoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$migrationRoot = [System.IO.Path]::GetFullPath($MigrationRoot)
Assert-Administrator
$backupRootPath = Resolve-BackupRootPath -MigrationRootPath $migrationRoot -RequestedBackupRoot $BackupRoot
$backupMetaRoot = Join-Path $backupRootPath "meta"
$backupDockerRoot = Join-Path $backupRootPath "docker"
$backupJellyfinRoot = Join-Path $backupRootPath "jellyfin\Server"
$backupQbRoamingRoot = Join-Path $backupRootPath "qbittorrent\Roaming"
$backupQbBtBackupRoot = Join-Path $backupRootPath "qbittorrent\BT_backup"
$backupRulesDataRoot = Join-Path $backupRootPath "qb-rules-app\data"
$dockerCommand = Resolve-CommandPath -Names @("docker") -CandidatePaths @(
    (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
)
$wingetCommand = Resolve-CommandPath -Names @("winget")
$pyLauncher = Resolve-CommandPath -Names @("py")
$pythonCommand = Resolve-CommandPath -Names @("python") -CandidatePaths @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
)

if (-not (Test-Path (Join-Path $repoRoot "pyproject.toml"))) {
    throw "Repo root does not look valid: $repoRoot"
}

Write-Section "Resolved Paths"
Write-Output "Backup root: $backupRootPath"
Write-Output "Repo root:   $repoRoot"
Write-Output "Content root: $QbContentRoot"

if (-not $SkipWingetInstall) {
    if (-not $wingetCommand) {
        throw "winget was not found in PATH."
    }

    Write-Section "Installing Required Windows Packages"
    $qBVersion = $null
    $qBVersionFile = Join-Path $backupMetaRoot "qbittorrent-version.txt"
    if (Test-Path $qBVersionFile) {
        $versionLine = Get-Content $qBVersionFile | Where-Object { $_ -match "ProductVersion" } | Select-Object -First 1
        if ($versionLine) {
            $qBVersion = (($versionLine -split ":", 2)[1]).Trim().TrimStart("v")
        }
    }

    Invoke-WingetInstall -WingetCommand $wingetCommand -PackageId "Docker.DockerDesktop" -Arguments @(
        "install", "--id", "Docker.DockerDesktop", "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"
    ) -Description "Installing Docker Desktop"
    Invoke-WingetInstall -WingetCommand $wingetCommand -PackageId "Jellyfin.Server" -Arguments @(
        "install", "--id", "Jellyfin.Server", "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"
    ) -Description "Installing Jellyfin Server"

    $qBArguments = @(
        "install", "--id", "qBittorrent.qBittorrent", "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"
    )
    if ($qBVersion) {
        $qBArguments += @("--version", $qBVersion)
    }
    Invoke-WingetInstall -WingetCommand $wingetCommand -PackageId "qBittorrent.qBittorrent" -Arguments $qBArguments -Description "Installing qBittorrent"

    Invoke-WingetInstall -WingetCommand $wingetCommand -PackageId "Python.Python.3.12" -Arguments @(
        "install", "--id", "Python.Python.3.12", "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"
    ) -Description "Installing Python 3.12"

    if ($InstallDesktopSdk -or $BuildRulesDesktop -or $LaunchRulesDesktop) {
        Invoke-WingetInstall -WingetCommand $wingetCommand -PackageId "Microsoft.DotNet.SDK.10" -Arguments @(
            "install", "--id", "Microsoft.DotNet.SDK.10", "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"
        ) -Description "Installing .NET SDK 10"
    }

    $dockerCommand = Resolve-CommandPath -Names @("docker") -CandidatePaths @(
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
    )
    $pyLauncher = Resolve-CommandPath -Names @("py")
    $pythonCommand = Resolve-CommandPath -Names @("python") -CandidatePaths @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
    )
}

if (-not $dockerCommand) {
    throw "docker command not found. Install Docker Desktop and rerun."
}

Write-Section "Stopping Existing Target Services"
Get-Process qbittorrent -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Service *Jellyfin* -ErrorAction SilentlyContinue | Stop-Service -Force

Wait-ForDockerReady -DockerCommand $dockerCommand
Remove-DockerContainerIfPresent -DockerCommand $dockerCommand -Name "jackett"
Remove-DockerContainerIfPresent -DockerCommand $dockerCommand -Name "jackett-stremio"
Remove-DockerContainerIfPresent -DockerCommand $dockerCommand -Name "flaresolverr"

$qbExportRoot = Join-Path $QbContentRoot "_torrent_files"
$qbExportArchiveRoot = Join-Path $qbExportRoot "Archive"
$baseFolders = @(
    $QbContentRoot,
    (Join-Path $QbContentRoot "Movies"),
    (Join-Path $QbContentRoot "Series"),
    (Join-Path $QbContentRoot "Audiobooks"),
    $qbExportRoot,
    $qbExportArchiveRoot
)

Write-Section "Creating Local Target Paths"
foreach ($folder in $baseFolders) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
}

Write-Section "Restoring Jellyfin"
Invoke-Robocopy -Source $backupJellyfinRoot -Destination "C:\ProgramData\Jellyfin\Server" -ExtraArgs @("/MIR", "/FFT", "/R:1", "/W:1", "/XJ")
Grant-DirectoryModifyAccess -Path "C:\ProgramData\Jellyfin\Server"
Get-Service *Jellyfin* -ErrorAction SilentlyContinue | Start-Service

Write-Section "Restoring Docker Services"
$jackettInspect = Read-InspectObject -Path (Join-Path $backupDockerRoot "jackett.inspect.json")
$flaresolverrInspect = Read-InspectObject -Path (Join-Path $backupDockerRoot "flaresolverr.inspect.json")
$jackettStremioInspect = Read-InspectObject -Path (Join-Path $backupDockerRoot "jackett-stremio.inspect.json")
$jackettTimeZone = Get-InspectEnvValue -InspectObject $jackettInspect -Name "TZ"
if (-not $jackettTimeZone) {
    $jackettTimeZone = "Asia/Jerusalem"
}
$jackettStremioApiKeys = Get-InspectEnvValue -InspectObject $jackettStremioInspect -Name "JACKETT_APIKEYS"
if (-not $jackettStremioApiKeys) {
    throw "Could not resolve JACKETT_APIKEYS from backup inspect."
}

Invoke-CheckedCommand -FilePath $dockerCommand -Arguments @("volume", "create", "jackett_config") -Description "Creating jackett_config volume"
Invoke-CheckedCommand -FilePath $dockerCommand -Arguments @("volume", "create", "jackett_downloads") -Description "Creating jackett_downloads volume"

Invoke-CheckedCommand -FilePath $dockerCommand -Arguments @(
    "run", "--rm",
    "-v", "jackett_config:/to",
    "-v", "${backupDockerRoot}:/from",
    "alpine",
    "sh", "-c", "cd /to && tar xf /from/jackett_config.tar"
) -Description "Restoring jackett_config volume"

Invoke-CheckedCommand -FilePath $dockerCommand -Arguments @(
    "run", "--rm",
    "-v", "jackett_downloads:/to",
    "-v", "${backupDockerRoot}:/from",
    "alpine",
    "sh", "-c", "cd /to && tar xf /from/jackett_downloads.tar"
) -Description "Restoring jackett_downloads volume"

Invoke-CheckedCommand -FilePath $dockerCommand -Arguments @(
    "run", "-d",
    "--name", "jackett",
    "--restart", "unless-stopped",
    "-p", "9117:9117",
    "-v", "jackett_config:/config",
    "-v", "jackett_downloads:/downloads",
    "-e", "TZ=$jackettTimeZone",
    $jackettInspect.Config.Image
) -Description "Starting jackett container"

Invoke-CheckedCommand -FilePath $dockerCommand -Arguments @(
    "run", "-d",
    "--name", "flaresolverr",
    "--restart", "unless-stopped",
    "-p", "8191:8191",
    $flaresolverrInspect.Config.Image
) -Description "Starting flaresolverr container"

Invoke-CheckedCommand -FilePath $dockerCommand -Arguments @(
    "run", "-d",
    "--name", "jackett-stremio",
    "--restart", "unless-stopped",
    "-p", "7000:7000",
    "-e", "JACKETT_HOSTS=$JackettStremioHost",
    "-e", "JACKETT_APIKEYS=$jackettStremioApiKeys",
    $jackettStremioInspect.Config.Image
) -Description "Starting jackett-stremio container"

Write-Section "Restoring qBittorrent"
Invoke-Robocopy -Source $backupQbRoamingRoot -Destination (Join-Path $env:APPDATA "qBittorrent") -ExtraArgs @("/MIR", "/FFT", "/R:1", "/W:1", "/XJ")
if (Test-Path $backupQbBtBackupRoot) {
    Invoke-Robocopy -Source $backupQbBtBackupRoot -Destination (Join-Path $env:LOCALAPPDATA "qBittorrent\BT_backup") -ExtraArgs @("/MIR", "/FFT", "/R:1", "/W:1", "/XJ")
}

$qBIniPath = Join-Path $env:APPDATA "qBittorrent\qBittorrent.ini"
if (-not (Test-Path $qBIniPath)) {
    throw "qBittorrent.ini not found after restore: $qBIniPath"
}
$qBIniContent = Get-Content $qBIniPath -Raw
$qBIniContent = Set-IniLineValue -Content $qBIniContent -Key "Session\DefaultSavePath" -Value (ConvertTo-QbIniPathValue -Path $QbContentRoot)
$qBIniContent = Set-IniLineValue -Content $qBIniContent -Key "Session\TorrentExportDirectory" -Value (ConvertTo-QbIniPathValue -Path $qbExportRoot)
$qBIniContent = Set-IniLineValue -Content $qBIniContent -Key "Session\FinishedTorrentExportDirectory" -Value (ConvertTo-QbIniPathValue -Path $qbExportArchiveRoot)
Set-Content -Path $qBIniPath -Value $qBIniContent

$qBExecutable = Resolve-CommandPath -Names @("qbittorrent") -CandidatePaths @(
    "C:\Program Files\qBittorrent\qbittorrent.exe"
)
if (-not $qBExecutable) {
    throw "qBittorrent executable not found after installation."
}
Start-Process -FilePath $qBExecutable | Out-Null

Write-Section "Restoring Rules App Data"
Invoke-Robocopy -Source $backupRulesDataRoot -Destination (Join-Path $repoRoot "data") -ExtraArgs @("/MIR", "/FFT", "/R:1", "/W:1", "/XJ")
$venvPython = Ensure-VirtualEnvironment -RepoPath $repoRoot -PyLauncher $pyLauncher -PythonCommand $pythonCommand
Invoke-CheckedCommand -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip") -Description "Upgrading pip in .venv"
Invoke-CheckedCommand -FilePath $venvPython -Arguments @("-m", "pip", "install", "-e", ".[dev]") -WorkingDirectory $repoRoot -Description "Installing rules app dependencies"

if ($BuildRulesDesktop -or $LaunchRulesDesktop) {
    Write-Section "Building Rules Desktop"
    Push-Location $repoRoot
    try {
        Invoke-CheckedCommand -FilePath "cmd.exe" -Arguments @("/c", "scripts\run_dev.bat desktop-build") -Description "Building rules desktop"
    } finally {
        Pop-Location
    }
}

if ($LaunchRulesDesktop) {
    Write-Section "Starting Rules Desktop"
    Start-RulesApp -RepoPath $repoRoot -Desktop
} elseif (-not $SkipRulesAppStart) {
    Write-Section "Starting Rules API"
    Start-RulesApp -RepoPath $repoRoot
}

Write-Section "Validation Summary"
$validation = [PSCustomObject]@{
    Jellyfin = Test-LocalHttpEndpoint -Url "http://127.0.0.1:8096"
    qBittorrent = Test-LocalHttpEndpoint -Url "http://127.0.0.1:8080"
    Jackett = Test-LocalHttpEndpoint -Url "http://127.0.0.1:9117"
    FlareSolverr = Test-LocalHttpEndpoint -Url "http://127.0.0.1:8191"
    JackettStremio = Test-LocalHttpEndpoint -Url "http://127.0.0.1:7000"
    RulesApp = if ($LaunchRulesDesktop) { "desktop-launched" } elseif (-not $SkipRulesAppStart) { Test-LocalHttpEndpoint -Url "http://127.0.0.1:8000/health" } else { "not-started" }
}
$validation | Format-List | Out-String | Write-Output

Write-Output "Restore complete."
Write-Output "Note: qB payload files were not migrated. Restored torrent session state will cause qBittorrent to recheck/redownload into $QbContentRoot."
Write-Output "Note: Jellyfin metadata/config were restored, but media files remain absent until you copy or otherwise expose the actual library content on the new machine."

param(
    [string]$ComposeFile = "C:\Users\nucc\docker-config\docker-compose.yml",
    [string]$Service = "qb-rss-rules",
    [string]$HealthUrl = "http://127.0.0.1:8000/health",
    [int]$HealthTimeoutSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$DockerExe = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$DockerDesktopExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$LogDir = Join-Path $RepoRoot "logs\docker"
$LogFile = Join-Path $LogDir "update-docker-last.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Content -LiteralPath $LogFile -Encoding UTF8 -Value @(
    "qBittorrent RSS Rules Docker update",
    "Started: $([DateTime]::Now.ToString('s'))",
    "Repository: $RepoRoot",
    "Compose: $ComposeFile",
    "Service: $Service",
    ""
)

function Add-Log {
    param([string]$Message)
    Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value $Message
}

function Show-FailureTail {
    Write-Host ""
    Write-Host "Last Docker log lines:"
    if (Test-Path -LiteralPath $LogFile) {
        Get-Content -LiteralPath $LogFile -Tail 50
    }
    Write-Host ""
    Write-Host "Full log: $LogFile"
}

function Test-DockerEngine {
    & $DockerExe info --format "{{.ServerVersion}}" *> $null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-DockerLogged {
    param([Parameter(Mandatory = $true)][string[]]$DockerArguments)

    Add-Log ("docker " + ($DockerArguments -join " "))
    & $DockerExe @DockerArguments *>> $LogFile
    return $LASTEXITCODE
}

function Get-GitValue {
    param([Parameter(Mandatory = $true)][string[]]$GitArguments)

    try {
        $value = & git -C $RepoRoot @GitArguments 2>$null
        if ($LASTEXITCODE -eq 0) {
            return (($value -join "`n").Trim())
        }
    }
    catch {
        # Git metadata is useful reporting only; Docker refresh must not depend on it.
    }
    return ""
}

try {
    if (-not (Test-Path -LiteralPath $DockerExe)) {
        throw "Docker CLI not found at '$DockerExe'."
    }
    if (-not (Test-Path -LiteralPath $ComposeFile)) {
        throw "Shared Compose file not found at '$ComposeFile'."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "Dockerfile"))) {
        throw "Dockerfile not found in repository '$RepoRoot'."
    }

    $branch = Get-GitValue -GitArguments @("branch", "--show-current")
    $commit = Get-GitValue -GitArguments @("rev-parse", "--short", "HEAD")
    $gitLabel = if ($branch -and $commit) { "$branch @ $commit" } elseif ($commit) { $commit } else { "unknown" }

    Write-Host "Updating Docker service '$Service'..."
    Write-Host "Git: $gitLabel"
    Write-Host "Compose: $ComposeFile"
    Add-Log "Git: $gitLabel"

    if (-not (Test-DockerEngine)) {
        if (-not (Test-Path -LiteralPath $DockerDesktopExe)) {
            throw "Docker engine is unavailable and Docker Desktop was not found at '$DockerDesktopExe'."
        }

        Write-Host "Docker engine is not ready; starting Docker Desktop..."
        Add-Log "Docker engine unavailable; starting Docker Desktop."
        Start-Process -FilePath $DockerDesktopExe | Out-Null

        $dockerDeadline = [DateTime]::UtcNow.AddSeconds(120)
        while ([DateTime]::UtcNow -lt $dockerDeadline) {
            Start-Sleep -Seconds 2
            if (Test-DockerEngine) {
                break
            }
        }

        if (-not (Test-DockerEngine)) {
            throw "Docker engine did not become ready within 120 seconds."
        }
    }

    # Safety check: the shared Compose file must build this checkout, not another clone.
    $configOutput = & $DockerExe compose -f $ComposeFile config --format json 2>> $LogFile
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose configuration validation failed."
    }

    $composeConfig = (($configOutput -join "`n") | ConvertFrom-Json)
    $serviceProperty = $composeConfig.services.PSObject.Properties[$Service]
    if ($null -eq $serviceProperty) {
        throw "Service '$Service' is not defined in '$ComposeFile'."
    }

    $serviceConfig = $serviceProperty.Value
    $buildContext = $null
    if ($serviceConfig.build -is [string]) {
        $buildContext = [string]$serviceConfig.build
    }
    elseif ($null -ne $serviceConfig.build -and $null -ne $serviceConfig.build.context) {
        $buildContext = [string]$serviceConfig.build.context
    }

    if ([string]::IsNullOrWhiteSpace($buildContext)) {
        throw "Service '$Service' does not define a Docker build context."
    }
    if (-not (Test-Path -LiteralPath $buildContext)) {
        throw "Compose build context '$buildContext' does not exist."
    }

    $configuredRepoRoot = (Resolve-Path -LiteralPath $buildContext).Path
    if (-not [string]::Equals($configuredRepoRoot, $RepoRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Compose builds '$configuredRepoRoot', but this updater is running from '$RepoRoot'. Update the shared Compose build context before rebuilding."
    }

    Write-Host "Building and restarting only '$Service' (full output is captured to the log)..."
    $composeExit = Invoke-DockerLogged -DockerArguments @(
        "compose", "-f", $ComposeFile, "up", "--build", "-d", $Service
    )
    if ($composeExit -ne 0) {
        throw "Docker Compose build/start failed with exit code $composeExit."
    }

    Write-Host "Waiting for backend health..."
    $healthDeadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    $healthResponse = $null
    $lastHealthError = ""

    while ([DateTime]::UtcNow -lt $healthDeadline) {
        try {
            $healthResponse = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 5
            if ($null -ne $healthResponse) {
                break
            }
        }
        catch {
            $lastHealthError = $_.Exception.Message
        }
        Start-Sleep -Seconds 2
    }

    if ($null -eq $healthResponse) {
        Add-Log "Health check timed out: $lastHealthError"
        [void](Invoke-DockerLogged -DockerArguments @("compose", "-f", $ComposeFile, "ps", $Service))
        Add-Log "docker logs --tail 80 $Service"
        & $DockerExe logs --tail 80 $Service *>> $LogFile
        throw "Backend did not become healthy at '$HealthUrl' within $HealthTimeoutSeconds seconds."
    }

    $appVersion = ""
    if ($healthResponse -isnot [string] -and $null -ne $healthResponse.PSObject.Properties["app_version"]) {
        $appVersion = [string]$healthResponse.app_version
    }

    Add-Log "Health check passed: $HealthUrl"
    Add-Log "Finished: $([DateTime]::Now.ToString('s'))"

    Write-Host "[OK] '$Service' was rebuilt from the current checkout and is healthy."
    if ($appVersion) {
        Write-Host "App version: $appVersion"
    }
    Write-Host "Health: $HealthUrl"
    Write-Host "Full log: $LogFile"
    exit 0
}
catch {
    $message = $_.Exception.Message
    Add-Log "ERROR: $message"
    Add-Log "Finished: $([DateTime]::Now.ToString('s'))"
    Write-Host "[FAIL] $message"
    Show-FailureTail
    exit 1
}

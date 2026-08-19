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
$ComposeEnvFile = Join-Path (Split-Path -Parent $ComposeFile) ".env"
$LogDir = Join-Path $RepoRoot "logs\docker"
$LogFile = Join-Path $LogDir "update-docker-last.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Content -LiteralPath $LogFile -Encoding UTF8 -Value @(
    "qBittorrent RSS Rules Docker update",
    "Started: $([DateTime]::Now.ToString('s'))",
    "Repository: $RepoRoot",
    "Compose: $ComposeFile",
    "Environment: $ComposeEnvFile",
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

function Invoke-DockerNative {
    param(
        [Parameter(Mandatory = $true)][string[]]$DockerArguments,
        [ValidateSet("Log", "Capture", "Discard")][string]$OutputMode = "Log"
    )

    # Docker/Compose writes ordinary progress messages to stderr. With the script-wide
    # ErrorActionPreference=Stop, PowerShell can turn those messages into terminating
    # NativeCommandError records before LASTEXITCODE is inspected. At this boundary,
    # native stdout/stderr are data; the process exit code is authoritative.
    $previousErrorActionPreference = $ErrorActionPreference
    $nativePreferenceVariable = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $hadNativePreference = $null -ne $nativePreferenceVariable
    $previousNativePreference = if ($hadNativePreference) { $nativePreferenceVariable.Value } else { $null }
    $stdout = @()
    $exitCode = 1

    try {
        $ErrorActionPreference = "Continue"
        if ($hadNativePreference) {
            Set-Variable -Name PSNativeCommandUseErrorActionPreference -Value $false
        }

        switch ($OutputMode) {
            "Capture" {
                $stdout = @(& $DockerExe @DockerArguments 2>> $LogFile)
            }
            "Discard" {
                & $DockerExe @DockerArguments 1> $null 2> $null
            }
            default {
                # Merge stderr into stdout before a single UTF-8 writer handles the stream.
                # This avoids both NativeCommandError false failures and Windows sharing
                # violations from independently opening one log file for streams 1 and 2.
                & $DockerExe @DockerArguments 2>&1 | Out-File -LiteralPath $LogFile -Append -Encoding utf8
            }
        }
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($hadNativePreference) {
            Set-Variable -Name PSNativeCommandUseErrorActionPreference -Value $previousNativePreference
        }
        $ErrorActionPreference = $previousErrorActionPreference
    }

    return [pscustomobject]@{
        ExitCode = [int]$exitCode
        StdOut = $stdout
    }
}

function Test-DockerEngine {
    $result = Invoke-DockerNative -DockerArguments @("info", "--format", "{{.ServerVersion}}") -OutputMode "Discard"
    return ($result.ExitCode -eq 0)
}

function Invoke-DockerLogged {
    param([Parameter(Mandatory = $true)][string[]]$DockerArguments)

    Add-Log ("docker " + ($DockerArguments -join " "))
    $result = Invoke-DockerNative -DockerArguments $DockerArguments -OutputMode "Log"
    Add-Log "docker exit code: $($result.ExitCode)"
    return $result.ExitCode
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

    $composeBaseArgs = @("compose")
    if (Test-Path -LiteralPath $ComposeEnvFile) {
        $composeBaseArgs += @("--env-file", $ComposeEnvFile)
    }
    $composeBaseArgs += @("-f", $ComposeFile)

    $branch = Get-GitValue -GitArguments @("branch", "--show-current")
    $commit = Get-GitValue -GitArguments @("rev-parse", "--short", "HEAD")
    $gitLabel = if ($branch -and $commit) { "$branch @ $commit" } elseif ($commit) { $commit } else { "unknown" }

    Write-Host "Updating Docker service '$Service'..."
    Write-Host "Git: $gitLabel"
    Write-Host "Compose: $ComposeFile"
    if (Test-Path -LiteralPath $ComposeEnvFile) {
        Write-Host "Environment: $ComposeEnvFile"
    }
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
    $configArgs = $composeBaseArgs + @("config", "--format", "json")
    Add-Log ("docker " + ($configArgs -join " "))
    $configResult = Invoke-DockerNative -DockerArguments $configArgs -OutputMode "Capture"
    Add-Log "docker config exit code: $($configResult.ExitCode)"
    if ($configResult.ExitCode -ne 0) {
        throw "Docker Compose configuration validation failed with exit code $($configResult.ExitCode)."
    }

    $configOutput = @($configResult.StdOut)
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
    $upArgs = $composeBaseArgs + @("up", "--build", "-d", $Service)
    $composeExit = Invoke-DockerLogged -DockerArguments $upArgs
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
        $psArgs = $composeBaseArgs + @("ps", $Service)
        [void](Invoke-DockerLogged -DockerArguments $psArgs)
        [void](Invoke-DockerLogged -DockerArguments @("logs", "--tail", "80", $Service))
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

param(
    [string]$ComposeFile = "C:\Users\nucc\docker-config\docker-compose.yml",
    [string]$Service = "qb-rss-rules",
    [string]$HealthUrl = "http://127.0.0.1:8000/health",
    [int]$HealthTimeoutSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$dockerCommand = Get-Command docker.exe -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
$DockerExe = if ($null -ne $dockerCommand) {
    $dockerCommand.Source
}
else {
    "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
}
$DockerDesktopExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$ComposeEnvFile = Join-Path (Split-Path -Parent $ComposeFile) ".env"
$LogDir = Join-Path $RepoRoot "logs\docker"
$LogFile = Join-Path $LogDir "update-docker-last.log"
$LifecycleAuditFile = Join-Path $LogDir "container-lifecycle.jsonl"
$LifecycleAuditModule = Join-Path $PSScriptRoot "DockerLifecycleAudit.psm1"
$DockerNativeProcessModule = Join-Path $PSScriptRoot "DockerNativeProcess.psm1"
Import-Module $LifecycleAuditModule -Force
Import-Module $DockerNativeProcessModule -Force

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Content -LiteralPath $LogFile -Encoding UTF8 -Value @(
    "qBittorrent RSS Rules Docker update",
    "Started: $([DateTime]::Now.ToString('s'))",
    "Repository: $RepoRoot",
    "Compose: $ComposeFile",
    "Environment: $ComposeEnvFile",
    "Service: $Service",
    "Lifecycle audit: $LifecycleAuditFile",
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

    return Invoke-DockerNativeProcess `
        -DockerExe $DockerExe `
        -DockerArguments $DockerArguments `
        -OutputMode $OutputMode `
        -LogFile $LogFile
}

function Test-DockerEngine {
    $result = Invoke-DockerNative -DockerArguments @("info", "--format", "{{.ServerVersion}}") -OutputMode "Discard"
    return ($result.ExitCode -eq 0)
}

function Wait-DockerEngine {
    param([int]$TimeoutSeconds = 120)

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-DockerEngine) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return (Test-DockerEngine)
}

function Invoke-DockerLogged {
    param([Parameter(Mandatory = $true)][string[]]$DockerArguments)

    Add-Log ("docker " + ($DockerArguments -join " "))
    $result = Invoke-DockerNative -DockerArguments $DockerArguments -OutputMode "Log"
    Add-Log "docker exit code: $($result.ExitCode)"
    return $result.ExitCode
}

function Test-KnownDesktopMountStateFailure {
    if (-not (Test-Path -LiteralPath $LogFile)) {
        return $false
    }

    $tailText = ((Get-Content -LiteralPath $LogFile -Tail 120) -join "`n")
    return (
        $tailText -match "error while creating mount source path '/run/desktop/mnt/host/" -and
        $tailText -match "mkdir /run/desktop/mnt/host/.+: file exists"
    )
}

function Restart-DockerDesktopForMountRecovery {
    Write-Host "Detected a stale Docker Desktop host-mount state; restarting Docker Desktop once..."
    Add-Log "Detected known Docker Desktop host-mount state failure; attempting one Docker Desktop restart."

    # `docker desktop restart` is Docker Desktop's supported CLI restart operation.
    $restartResult = Invoke-DockerNative -DockerArguments @("desktop", "restart", "--timeout", "120") -OutputMode "Log"
    Add-Log "docker desktop restart exit code: $($restartResult.ExitCode)"
    if ($restartResult.ExitCode -ne 0) {
        return $false
    }

    if (-not (Wait-DockerEngine -TimeoutSeconds 120)) {
        Add-Log "Docker engine did not become ready after Docker Desktop restart."
        return $false
    }

    Add-Log "Docker engine is ready after Docker Desktop restart."
    return $true
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
    $checkoutSha = Get-GitValue -GitArguments @("rev-parse", "HEAD")
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

        if (-not (Wait-DockerEngine -TimeoutSeconds 120)) {
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
    $lifecycleRunId = [Guid]::NewGuid().ToString("N")
    $lifecycleAttempt = 1
    $lifecycleAttemptId = [Guid]::NewGuid().ToString("N")
    $dockerInvoker = {
        param($DockerArguments, $OutputMode)
        Invoke-DockerNative -DockerArguments $DockerArguments -OutputMode $OutputMode
    }
    $beforeSnapshot = Get-DockerLifecycleTargetSnapshot `
        -ComposeArguments $composeBaseArgs `
        -Service $Service `
        -DockerInvoker $dockerInvoker
    Write-DockerLifecycleAuditRecord `
        -AuditPath $LifecycleAuditFile `
        -RunId $lifecycleRunId `
        -AttemptId $lifecycleAttemptId `
        -Attempt $lifecycleAttempt `
        -Event "compose_up_intent" `
        -Service $Service `
        -CheckoutSha $checkoutSha `
        -Operation "compose_up" `
        -BeforeSnapshot $beforeSnapshot
    $composeExit = Invoke-DockerLogged -DockerArguments $upArgs
    $afterSnapshot = Get-DockerLifecycleTargetSnapshot `
        -ComposeArguments $composeBaseArgs `
        -Service $Service `
        -DockerInvoker $dockerInvoker
    $identityChanged = $null
    if ($beforeSnapshot.QuerySucceeded -and $afterSnapshot.QuerySucceeded -and
        $beforeSnapshot.ContainerCount -le 1 -and $afterSnapshot.ContainerCount -le 1) {
        $identityChanged = ([string]$beforeSnapshot.ContainerId -ne [string]$afterSnapshot.ContainerId)
    }
    $startProven = Test-DockerLifecycleProvenRunning `
        -Snapshot $afterSnapshot `
        -Service $Service `
        -ComposeExitCode $composeExit
    Write-DockerLifecycleAuditRecord `
        -AuditPath $LifecycleAuditFile `
        -RunId $lifecycleRunId `
        -AttemptId $lifecycleAttemptId `
        -Attempt $lifecycleAttempt `
        -Event "compose_up_result" `
        -Service $Service `
        -CheckoutSha $checkoutSha `
        -Operation "compose_up" `
        -BeforeSnapshot $beforeSnapshot `
        -AfterSnapshot $afterSnapshot `
        -ComposeExitCode $composeExit `
        -IdentityChanged $identityChanged `
        -ExpectedServiceProvenRunning $startProven

    if ($composeExit -ne 0 -and (Test-KnownDesktopMountStateFailure)) {
        if (Restart-DockerDesktopForMountRecovery) {
            Write-Host "Retrying Docker Compose once after Docker Desktop restart..."
            Add-Log "Retrying Compose up once after Docker Desktop restart."
            $lifecycleAttempt++
            $lifecycleAttemptId = [Guid]::NewGuid().ToString("N")
            $beforeSnapshot = Get-DockerLifecycleTargetSnapshot `
                -ComposeArguments $composeBaseArgs `
                -Service $Service `
                -DockerInvoker $dockerInvoker
            Write-DockerLifecycleAuditRecord `
                -AuditPath $LifecycleAuditFile `
                -RunId $lifecycleRunId `
                -AttemptId $lifecycleAttemptId `
                -Attempt $lifecycleAttempt `
                -Event "compose_up_intent" `
                -Service $Service `
                -CheckoutSha $checkoutSha `
                -Operation "compose_up" `
                -BeforeSnapshot $beforeSnapshot
            $composeExit = Invoke-DockerLogged -DockerArguments $upArgs
            $afterSnapshot = Get-DockerLifecycleTargetSnapshot `
                -ComposeArguments $composeBaseArgs `
                -Service $Service `
                -DockerInvoker $dockerInvoker
            $identityChanged = $null
            if ($beforeSnapshot.QuerySucceeded -and $afterSnapshot.QuerySucceeded -and
                $beforeSnapshot.ContainerCount -le 1 -and $afterSnapshot.ContainerCount -le 1) {
                $identityChanged = ([string]$beforeSnapshot.ContainerId -ne [string]$afterSnapshot.ContainerId)
            }
            $startProven = Test-DockerLifecycleProvenRunning `
                -Snapshot $afterSnapshot `
                -Service $Service `
                -ComposeExitCode $composeExit
            Write-DockerLifecycleAuditRecord `
                -AuditPath $LifecycleAuditFile `
                -RunId $lifecycleRunId `
                -AttemptId $lifecycleAttemptId `
                -Attempt $lifecycleAttempt `
                -Event "compose_up_result" `
                -Service $Service `
                -CheckoutSha $checkoutSha `
                -Operation "compose_up" `
                -BeforeSnapshot $beforeSnapshot `
                -AfterSnapshot $afterSnapshot `
                -ComposeExitCode $composeExit `
                -IdentityChanged $identityChanged `
                -ExpectedServiceProvenRunning $startProven
        }
    }

    if ($composeExit -ne 0) {
        throw "Docker Compose build/start failed with exit code $composeExit."
    }
    if (-not $startProven) {
        throw "Docker Compose exited successfully, but target service '$Service' could not be proven present and running."
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
    Write-Host "Lifecycle audit: $LifecycleAuditFile"
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

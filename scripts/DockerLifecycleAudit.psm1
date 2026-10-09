function New-DockerLifecycleSnapshot {
    param(
        [bool]$QuerySucceeded,
        [int]$ContainerCount = 0,
        [AllowNull()][string]$ContainerId = $null,
        [AllowNull()][string]$ImageId = $null,
        [AllowNull()][string]$State = $null,
        [AllowNull()][string]$Health = $null,
        [AllowNull()][string]$Service = $null
    )

    return [pscustomobject]@{
        QuerySucceeded = $QuerySucceeded
        ContainerCount = $ContainerCount
        ContainerId = $ContainerId
        ImageId = $ImageId
        State = $State
        Health = $Health
        Service = $Service
    }
}

function Get-DockerLifecycleTargetSnapshot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string[]]$ComposeArguments,
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][scriptblock]$DockerInvoker
    )

    $psArguments = $ComposeArguments + @("ps", "--all", "--quiet", $Service)
    $psResult = & $DockerInvoker $psArguments "Capture"
    if ($null -eq $psResult -or $psResult.ExitCode -ne 0) {
        return New-DockerLifecycleSnapshot -QuerySucceeded $false
    }

    $containerIds = @(
        @($psResult.StdOut) |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { $_ -match "^[0-9a-fA-F]{12,64}$" }
    )
    if ($containerIds.Count -ne 1) {
        return New-DockerLifecycleSnapshot -QuerySucceeded $true -ContainerCount $containerIds.Count
    }

    $quote = [string][char]34
    $format = '{{.Id}}|{{.Image}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}not_configured{{end}}|{{index .Config.Labels ' + $quote + 'com.docker.compose.service' + $quote + '}}'
    $inspectArguments = @("inspect", "--format", $format, $containerIds[0])
    $inspectResult = & $DockerInvoker $inspectArguments "Capture"
    if ($null -eq $inspectResult -or $inspectResult.ExitCode -ne 0) {
        return New-DockerLifecycleSnapshot -QuerySucceeded $false -ContainerCount 1 -ContainerId $containerIds[0]
    }

    $summaryLines = @(
        @($inspectResult.StdOut) |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { $_ }
    )
    if ($summaryLines.Count -ne 1) {
        return New-DockerLifecycleSnapshot -QuerySucceeded $false -ContainerCount 1 -ContainerId $containerIds[0]
    }

    $parts = $summaryLines[0].Split('|')
    if ($parts.Count -ne 5 -or $parts[0] -notmatch "^[0-9a-fA-F]{12,64}$") {
        return New-DockerLifecycleSnapshot -QuerySucceeded $false -ContainerCount 1 -ContainerId $containerIds[0]
    }

    $imageId = $parts[1]
    if ($imageId -notmatch "^sha256:[0-9a-fA-F]{64}$") {
        $imageId = $null
    }
    return New-DockerLifecycleSnapshot `
        -QuerySucceeded $true `
        -ContainerCount 1 `
        -ContainerId $parts[0] `
        -ImageId $imageId `
        -State $parts[2] `
        -Health $parts[3] `
        -Service $parts[4]
}

function Test-DockerLifecycleProvenRunning {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][psobject]$Snapshot,
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][int]$ComposeExitCode
    )

    return (
        $ComposeExitCode -eq 0 -and
        $Snapshot.QuerySucceeded -and
        $Snapshot.ContainerCount -eq 1 -and
        -not [string]::IsNullOrWhiteSpace([string]$Snapshot.ContainerId) -and
        [string]::Equals([string]$Snapshot.Service, $Service, [StringComparison]::Ordinal) -and
        [string]::Equals([string]$Snapshot.State, "running", [StringComparison]::OrdinalIgnoreCase)
    )
}

function ConvertTo-DockerLifecycleAuditSnapshot {
    param([AllowNull()][psobject]$Snapshot)

    if ($null -eq $Snapshot) {
        return $null
    }
    return [ordered]@{
        query_succeeded = [bool]$Snapshot.QuerySucceeded
        container_count = [int]$Snapshot.ContainerCount
        container_id = $Snapshot.ContainerId
        image_id = $Snapshot.ImageId
        state = $Snapshot.State
        health = $Snapshot.Health
        service = $Snapshot.Service
    }
}

function Write-DockerLifecycleAuditRecord {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$AuditPath,
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][string]$AttemptId,
        [Parameter(Mandatory = $true)][ValidateSet("compose_up_intent", "compose_up_result")][string]$Event,
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string]$CheckoutSha,
        [Parameter(Mandatory = $true)][ValidateSet("compose_up")][string]$Operation,
        [Parameter(Mandatory = $true)][ValidateRange(1, 100)][int]$Attempt,
        [Parameter(Mandatory = $true)][psobject]$BeforeSnapshot,
        [AllowNull()][psobject]$AfterSnapshot = $null,
        [AllowNull()][object]$ComposeExitCode = $null,
        [AllowNull()][object]$IdentityChanged = $null,
        [AllowNull()][object]$ExpectedServiceProvenRunning = $null
    )

    $record = [ordered]@{
        timestamp_utc = [DateTime]::UtcNow.ToString("o")
        run_id = $RunId
        attempt = $Attempt
        attempt_id = $AttemptId
        event = $Event
        service = $Service
        checkout_sha = $CheckoutSha
        operation = $Operation
        compose_exit_code = if ($Event -eq "compose_up_result") { [int]$ComposeExitCode } else { $null }
        before = ConvertTo-DockerLifecycleAuditSnapshot -Snapshot $BeforeSnapshot
        after = if ($Event -eq "compose_up_result") {
            ConvertTo-DockerLifecycleAuditSnapshot -Snapshot $AfterSnapshot
        } else {
            $null
        }
        identity_changed = if ($Event -eq "compose_up_result") { $IdentityChanged } else { $null }
        expected_service_proven_running = if ($Event -eq "compose_up_result") {
            $ExpectedServiceProvenRunning
        } else {
            $null
        }
    }
    $line = ($record | ConvertTo-Json -Depth 4 -Compress) + [Environment]::NewLine
    $fullPath = [System.IO.Path]::GetFullPath($AuditPath)
    $directory = [System.IO.Path]::GetDirectoryName($fullPath)
    [System.IO.Directory]::CreateDirectory($directory) | Out-Null

    $mutex = [System.Threading.Mutex]::new($false, "Local\qbrss-docker-lifecycle-audit")
    $locked = $false
    try {
        $locked = $mutex.WaitOne([TimeSpan]::FromSeconds(10))
        if (-not $locked) {
            throw "Timed out waiting to append the Docker lifecycle audit record."
        }
        [System.IO.File]::AppendAllText(
            $fullPath,
            $line,
            [System.Text.UTF8Encoding]::new($false)
        )
    }
    finally {
        if ($locked) {
            $mutex.ReleaseMutex()
        }
        $mutex.Dispose()
    }
}

Export-ModuleMember -Function Get-DockerLifecycleTargetSnapshot, Test-DockerLifecycleProvenRunning, Write-DockerLifecycleAuditRecord

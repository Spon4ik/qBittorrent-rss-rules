function Write-DockerLifecycleAuditRecord {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$AuditPath,
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][ValidateSet("compose_up_intent", "compose_up_result")][string]$Event,
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Commit,
        [Parameter(Mandatory = $true)][ValidateRange(1, 100)][int]$Attempt,
        [int]$ExitCode = -1
    )

    $record = [ordered]@{
        timestamp_utc = [DateTime]::UtcNow.ToString("o")
        run_id = $RunId
        attempt = $Attempt
        event = $Event
        service = $Service
        commit = $Commit
        exit_code = if ($Event -eq "compose_up_result") { $ExitCode } else { $null }
    }
    $line = ($record | ConvertTo-Json -Compress) + [Environment]::NewLine
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

Export-ModuleMember -Function Write-DockerLifecycleAuditRecord

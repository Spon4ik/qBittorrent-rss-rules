function ConvertTo-WindowsProcessArgument {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)

    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }

    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append([char]34)
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq [char]92) {
            $backslashes++
            continue
        }

        if ($character -eq [char]34) {
            [void]$builder.Append([char]92, (2 * $backslashes) + 1)
            [void]$builder.Append([char]34)
        }
        else {
            if ($backslashes -gt 0) {
                [void]$builder.Append([char]92, $backslashes)
            }
            [void]$builder.Append($character)
        }
        $backslashes = 0
    }

    if ($backslashes -gt 0) {
        [void]$builder.Append([char]92, 2 * $backslashes)
    }
    [void]$builder.Append([char]34)
    return $builder.ToString()
}

function Invoke-DockerNativeProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DockerExe,
        [Parameter(Mandatory = $true)][string[]]$DockerArguments,
        [ValidateSet("Log", "Capture", "Discard")][string]$OutputMode = "Log",
        [Parameter(Mandatory = $true)][string]$LogFile
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $DockerExe
    $startInfo.Arguments = (@($DockerArguments | ForEach-Object {
        ConvertTo-WindowsProcessArgument -Value ([string]$_)
    }) -join " ")
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "Could not start native command $DockerExe"
        }

        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $exitCode = [int]$process.ExitCode
    }
    finally {
        $process.Dispose()
    }

    if ($OutputMode -eq "Log") {
        $logContent = $stdout + $stderr
    }
    elseif ($OutputMode -eq "Capture") {
        $logContent = $stderr
    }
    else {
        $logContent = ""
    }

    if (-not [string]::IsNullOrEmpty($logContent)) {
        [System.IO.File]::AppendAllText(
            $LogFile,
            $logContent,
            [System.Text.UTF8Encoding]::new($false)
        )
    }

    $stdoutLines = @()
    if (-not [string]::IsNullOrEmpty($stdout)) {
        $stdoutLines = @($stdout -split "\r\n|\n|\r")
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        StdOut = $stdoutLines
    }
}

Export-ModuleMember -Function Invoke-DockerNativeProcess

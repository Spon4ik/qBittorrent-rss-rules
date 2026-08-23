param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("status", "start", "stop", "restart")]
    [string]$Action,
    [string]$ComposeFile = "C:\Users\nucc\docker-config\docker-compose.yml",
    [string]$Service = "qb-rss-rules",
    [string]$HealthUrl = "http://127.0.0.1:8000/health",
    [int]$EngineTimeoutSeconds = 120,
    [int]$HealthTimeoutSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"
$RuntimeScript = Join-Path $PSScriptRoot "docker_runtime.py"
$ReportDir = Join-Path $Root "logs\qa"
$ReportFile = Join-Path $ReportDir "docker-runtime.json"

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    Write-Host "ERROR: Python virtual environment not found: $PythonExe"
    exit 2
}
if (-not (Test-Path -LiteralPath $RuntimeScript -PathType Leaf)) {
    Write-Host "ERROR: Docker runtime helper not found: $RuntimeScript"
    exit 2
}

New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$Arguments = @(
    $RuntimeScript,
    $Action,
    "--compose-file", $ComposeFile,
    "--service", $Service,
    "--health-url", $HealthUrl,
    "--engine-timeout", [string]$EngineTimeoutSeconds,
    "--health-timeout", [string]$HealthTimeoutSeconds,
    "--output", $ReportFile
)

# Invoke the maintained Python helper through an exact executable path. Never use
# Start-Process on the token "docker" or another shell/open association here.
& $PythonExe @Arguments
$ExitCode = $LASTEXITCODE
Write-Host "Docker runtime report: $ReportFile"
exit $ExitCode

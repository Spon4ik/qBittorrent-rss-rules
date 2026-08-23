@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%POWERSHELL_EXE%" (
  echo ERROR: Windows PowerShell not found: %POWERSHELL_EXE%
  exit /b 2
)

if "%~1"=="" goto :usage

"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%docker_runtime.ps1" %*
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\docker_runtime.bat ^<status^|start^|stop^|restart^> [PowerShell options]
exit /b 2

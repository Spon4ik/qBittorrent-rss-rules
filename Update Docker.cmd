@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
set "NO_PAUSE=0"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%scripts\update_docker.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo Docker update completed successfully.
) else (
  echo Docker update failed with exit code %EXIT_CODE%.
)

if "%NO_PAUSE%"=="0" pause
exit /b %EXIT_CODE%

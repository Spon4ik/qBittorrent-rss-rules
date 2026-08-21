@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_ROOT=%~dp0"
set "NO_PAUSE=0"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%scripts\update_docker.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if "!EXIT_CODE!"=="0" (
  call "%PROJECT_ROOT%scripts\runtime_state.bat" --require-runtime-current
  set "STATE_EXIT=!ERRORLEVEL!"
  if not "!STATE_EXIT!"=="0" set "EXIT_CODE=!STATE_EXIT!"
)

echo.
if "!EXIT_CODE!"=="0" (
  echo Docker update completed successfully and the deployed runtime matches the checkout version.
) else (
  echo Docker update failed or the deployed runtime is stale. Exit code !EXIT_CODE!.
)

if "%NO_PAUSE%"=="0" pause
exit /b !EXIT_CODE!

@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
set "NO_PAUSE=0"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

pushd "%PROJECT_ROOT%" >nul

echo Finalizing backend change...
echo.
echo [1/2] Running deterministic project checks...
call "scripts\check.bat"
set "CHECK_EXIT=%ERRORLEVEL%"
if not "%CHECK_EXIT%"=="0" (
  echo.
  echo [FAIL] Deterministic validation failed. Docker was not rebuilt.
  set "EXIT_CODE=%CHECK_EXIT%"
  goto :finish
)

echo.
echo [2/2] Deterministic validation passed. Rebuilding and validating Docker...
call "Update Docker.cmd" --no-pause
set "DOCKER_EXIT=%ERRORLEVEL%"
if not "%DOCKER_EXIT%"=="0" (
  echo.
  echo [FAIL] Local checks passed, but Docker finalization failed.
  set "EXIT_CODE=%DOCKER_EXIT%"
  goto :finish
)

echo.
echo [OK] Backend finalization completed: local checks passed and Docker is healthy.
set "EXIT_CODE=0"

:finish
popd >nul
if "%NO_PAUSE%"=="0" pause
exit /b %EXIT_CODE%

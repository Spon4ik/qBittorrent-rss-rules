@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
set "NO_PAUSE=0"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

pushd "%PROJECT_ROOT%" >nul

echo Finalizing backend change...
echo.
echo [1/4] Running deterministic project checks...
call "scripts\check.bat"
set "CHECK_EXIT=%ERRORLEVEL%"
if not "%CHECK_EXIT%"=="0" (
  echo.
  echo [FAIL] Deterministic validation failed. Docker deployment was NOT ATTEMPTED.
  echo.
  echo Current checkout/upstream/runtime state:
  call "scripts\runtime_state.bat"
  set "EXIT_CODE=%CHECK_EXIT%"
  goto :finish
)

echo.
echo [2/4] Deterministic validation passed. Rebuilding and validating Docker...
call "Update Docker.cmd" --no-pause
set "DOCKER_EXIT=%ERRORLEVEL%"
if not "%DOCKER_EXIT%"=="0" (
  echo.
  echo [FAIL] Local checks passed, but Docker deployment FAILED.
  echo.
  echo Current checkout/upstream/runtime state:
  call "scripts\runtime_state.bat"
  set "EXIT_CODE=%DOCKER_EXIT%"
  goto :finish
)

echo.
echo [3/4] Verifying the deployed runtime matches the checkout version...
call "scripts\runtime_state.bat" --require-runtime-current
set "STATE_EXIT=%ERRORLEVEL%"
if not "%STATE_EXIT%"=="0" (
  echo.
  echo [FAIL] Docker reported healthy, but the deployed runtime does not match the checkout.
  set "EXIT_CODE=%STATE_EXIT%"
  goto :finish
)

echo.
echo [4/4] Running deployed-runtime functional invariants...
call "scripts\functional_qa.bat" --suite core
set "FUNCTIONAL_EXIT=%ERRORLEVEL%"
if not "%FUNCTIONAL_EXIT%"=="0" (
  echo.
  echo [FAIL] The deployed runtime is current, but functional runtime QA FAILED.
  echo Docker deployment is CURRENT; application behavior still has an actionable invariant failure.
  set "EXIT_CODE=%FUNCTIONAL_EXIT%"
  goto :finish
)

echo.
echo [OK] Backend finalization completed: local checks passed, the deployed runtime is current and healthy, and core functional invariants pass.
set "EXIT_CODE=0"

:finish
popd >nul
if "%NO_PAUSE%"=="0" pause
exit /b %EXIT_CODE%
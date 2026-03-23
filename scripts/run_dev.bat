@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "MODE=%~1"
if "%MODE%"=="" set "MODE=api"

set "WINUI_PROJECT=QbRssRulesDesktop\QbRssRulesDesktop.csproj"
set "WINUI_CONFIG=Debug"
set "WINUI_PLATFORM=x64"
set "WINUI_EXE=QbRssRulesDesktop\bin\%WINUI_PLATFORM%\%WINUI_CONFIG%\net10.0-windows10.0.19041.0\win-%WINUI_PLATFORM%\QbRssRulesDesktop.exe"
set "WINUI_SHORTCUT_SCRIPT=scripts\refresh_winui_shortcuts.ps1"
set "API_HOST=127.0.0.1"
set "API_PORT=8000"
set "API_VENV_PYTHON=.venv\Scripts\python.exe"
set "API_VENV_PYTHONW=.venv\Scripts\pythonw.exe"
if exist "%API_VENV_PYTHON%" (
  set "API_PYTHON=%PROJECT_DIR%\%API_VENV_PYTHON%"
) else (
  set "API_PYTHON=python"
)
set "API_PYTHON_WINDOWLESS=%API_PYTHON%"

set "DOTNET_CMD=%ProgramFiles%\dotnet\dotnet.exe"
if not exist "%DOTNET_CMD%" set "DOTNET_CMD=dotnet"

pushd "%PROJECT_DIR%" >nul

if /I "%MODE%"=="api" goto :run_api
if /I "%MODE%"=="desktop-build" goto :desktop_build
if /I "%MODE%"=="desktop-shortcuts" goto :desktop_shortcuts
if /I "%MODE%"=="desktop-run" goto :desktop_run
if /I "%MODE%"=="desktop" goto :desktop
if /I "%MODE%"=="full" goto :full
if /I "%MODE%"=="help" goto :usage
if /I "%MODE%"=="--help" goto :usage
if /I "%MODE%"=="-h" goto :usage

echo Unknown mode: %MODE%
echo.
goto :usage

:run_api
echo Starting API server at http://%API_HOST%:%API_PORT% ...
"%API_PYTHON%" -m uvicorn app.main:create_app --factory --host %API_HOST% --port %API_PORT% --reload
set "EXIT_CODE=!ERRORLEVEL!"
goto :finish

:desktop_build
if not exist "%WINUI_PROJECT%" (
  echo WinUI project not found: %WINUI_PROJECT%
  set "EXIT_CODE=1"
  goto :finish
)

echo Restoring WinUI dependencies...
call "%DOTNET_CMD%" restore "%WINUI_PROJECT%"
if errorlevel 1 (
  set "EXIT_CODE=!ERRORLEVEL!"
  goto :finish
)

echo Building WinUI app (%WINUI_CONFIG%/%WINUI_PLATFORM%)...
call "%DOTNET_CMD%" build "%WINUI_PROJECT%" -c %WINUI_CONFIG% --no-restore -p:Platform=%WINUI_PLATFORM%
if errorlevel 1 (
  set "EXIT_CODE=!ERRORLEVEL!"
  goto :finish
)

call "%~f0" desktop-shortcuts
if errorlevel 1 (
  echo Warning: WinUI build succeeded, but shortcut refresh failed.
)

set "EXIT_CODE=0"
goto :finish

:desktop_shortcuts
if not exist "%WINUI_EXE%" (
  echo WinUI executable not found: %WINUI_EXE%
  echo Run "scripts\run_dev.bat desktop-build" first.
  set "EXIT_CODE=1"
  goto :finish
)

if not exist "%WINUI_SHORTCUT_SCRIPT%" (
  echo Shortcut script not found: %WINUI_SHORTCUT_SCRIPT%
  set "EXIT_CODE=1"
  goto :finish
)

echo Refreshing WinUI shortcuts...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WINUI_SHORTCUT_SCRIPT%" -ProjectRoot "%PROJECT_DIR%"
set "EXIT_CODE=!ERRORLEVEL!"
goto :finish

:desktop_run
if not exist "%WINUI_EXE%" (
  echo WinUI executable not found: %WINUI_EXE%
  echo Run "scripts\run_dev.bat desktop-build" first.
  set "EXIT_CODE=1"
  goto :finish
)

echo Launching WinUI desktop app...
powershell.exe -NoProfile -Command "Start-Process -FilePath '%WINUI_EXE%'"
if errorlevel 1 (
  set "EXIT_CODE=!ERRORLEVEL!"
  goto :finish
)
set "EXIT_CODE=0"
goto :finish

:desktop
call "%~f0" desktop-build
if errorlevel 1 (
  set "EXIT_CODE=!ERRORLEVEL!"
  goto :finish
)
call "%~f0" desktop-run
set "EXIT_CODE=!ERRORLEVEL!"
goto :finish

:full
echo Starting API server in a separate process...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%API_PYTHON_WINDOWLESS%' -ArgumentList '-m','uvicorn','app.main:create_app','--factory','--host','%API_HOST%','--port','%API_PORT%','--reload' -WorkingDirectory '%PROJECT_DIR%' -WindowStyle Hidden"
if errorlevel 1 (
  set "EXIT_CODE=!ERRORLEVEL!"
  goto :finish
)
ping 127.0.0.1 -n 3 >nul
call "%~f0" desktop
set "EXIT_CODE=!ERRORLEVEL!"
goto :finish

:usage
echo Usage: scripts\run_dev.bat [mode]
echo.
echo Modes:
echo   api           Run FastAPI dev server (default)
echo   desktop-build Restore and build WinUI desktop app
echo   desktop-shortcuts Refresh Desktop/repo shortcuts for the WinUI app
echo   desktop-run   Launch previously built WinUI desktop app
echo   desktop       Build then launch WinUI desktop app
echo   full          Start API server in separate process, then build and launch desktop app
echo   help          Show this help
set "EXIT_CODE=0"
goto :finish

:finish
if "%EXIT_CODE%"=="" set "EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %EXIT_CODE%

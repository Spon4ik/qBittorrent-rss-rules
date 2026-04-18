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
set "WINUI_PACKAGE_SCRIPT=scripts\package_desktop_bundle.ps1"
set "API_HOST=127.0.0.1"
set "API_PORT=8000"
set "API_VENV_PYTHON=.venv\Scripts\python.exe"
set "API_VENV_PYTHONW=.venv\Scripts\pythonw.exe"
set "API_PYTHON=python"
set "API_PYTHON_WINDOWLESS=%API_PYTHON%"

set "DOTNET_CMD=%ProgramFiles%\dotnet\dotnet.exe"
if not exist "%DOTNET_CMD%" set "DOTNET_CMD=dotnet"

pushd "%PROJECT_DIR%" >nul

if exist "%API_VENV_PYTHON%" (
  "%PROJECT_DIR%\%API_VENV_PYTHON%" -c "import sys" >nul 2>nul
  if errorlevel 1 (
    echo Detected an unusable repo virtual environment at ".venv".
    echo Recreate it with:
    echo   rmdir /s /q .venv
    echo   python -m venv .venv
    echo   .venv\Scripts\python -m pip install -e ".[dev]"
    set "EXIT_CODE=1"
    goto :finish
  )
  set "API_PYTHON=%PROJECT_DIR%\%API_VENV_PYTHON%"
  set "API_PYTHON_WINDOWLESS=%API_PYTHON%"
)

if /I "%MODE%"=="api" goto :run_api
if /I "%MODE%"=="desktop-build" goto :desktop_build
if /I "%MODE%"=="desktop-shortcuts" goto :desktop_shortcuts
if /I "%MODE%"=="desktop-package" goto :desktop_package
if /I "%MODE%"=="desktop-run" goto :desktop_run
if /I "%MODE%"=="desktop" goto :desktop
if /I "%MODE%"=="full" (
  echo "full" now delegates to the desktop shell, which auto-starts the backend as needed.
  goto :desktop
)
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

:desktop_package
if not exist "%WINUI_PACKAGE_SCRIPT%" (
  echo Desktop bundle script not found: %WINUI_PACKAGE_SCRIPT%
  set "EXIT_CODE=1"
  goto :finish
)

echo Building Windows desktop bundle...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WINUI_PACKAGE_SCRIPT%" -ProjectRoot "%PROJECT_DIR%"
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

:desktop_stop_running
powershell.exe -NoProfile -Command "$exe = [System.IO.Path]::GetFullPath('%PROJECT_DIR%\%WINUI_EXE%'); $running = Get-Process -Name 'QbRssRulesDesktop' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }; if (-not $running) { exit 1 }; $running | Stop-Process -Force; exit 0"
set "EXIT_CODE=!ERRORLEVEL!"
goto :finish

:desktop_needs_rebuild
if not exist "%WINUI_EXE%" exit /b 0
powershell.exe -NoProfile -Command "$exe = Get-Item ([System.IO.Path]::GetFullPath('%PROJECT_DIR%\%WINUI_EXE%')); $desktopRoot = [System.IO.Path]::GetFullPath('%PROJECT_DIR%\QbRssRulesDesktop'); $sources = Get-ChildItem -Path $desktopRoot -Recurse -File -Include *.cs,*.xaml,*.csproj,*.props,*.targets; if ($sources | Where-Object { $_.LastWriteTimeUtc -gt $exe.LastWriteTimeUtc }) { exit 0 } else { exit 1 }"
exit /b %ERRORLEVEL%

:desktop
powershell.exe -NoProfile -Command "$exe = [System.IO.Path]::GetFullPath('%PROJECT_DIR%\%WINUI_EXE%'); $running = Get-Process -Name 'QbRssRulesDesktop' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }; if ($running) { exit 0 } else { exit 1 }"
if errorlevel 1 goto :desktop_check_build

call :desktop_needs_rebuild
if errorlevel 1 goto :desktop_reuse_running

echo WinUI desktop app is running but its binary is older than the current desktop sources; restarting with a rebuilt shell.
call "%~f0" desktop-stop-running
if errorlevel 1 (
  echo Could not stop the running WinUI desktop app automatically.
  set "EXIT_CODE=!ERRORLEVEL!"
  goto :finish
)
goto :desktop_build_and_run

:desktop_reuse_running
echo WinUI desktop app is already running and up to date; reusing the existing instance.
call "%~f0" desktop-run
set "EXIT_CODE=!ERRORLEVEL!"
goto :finish

:desktop_check_build
call :desktop_needs_rebuild
if errorlevel 1 goto :desktop_run

:desktop_build_and_run
call "%~f0" desktop-build
if errorlevel 1 (
  set "EXIT_CODE=!ERRORLEVEL!"
  goto :finish
)
call "%~f0" desktop-run
set "EXIT_CODE=!ERRORLEVEL!"
goto :finish

:usage
echo Usage: scripts\run_dev.bat [mode]
echo.
echo Modes:
echo   api           Run FastAPI dev server (default)
echo   desktop-build Restore and build WinUI desktop app
echo   desktop-shortcuts Refresh Desktop/repo shortcuts for the WinUI app
echo   desktop-package Build a portable Windows bundle with install script under dist\
echo   desktop-run   Launch previously built WinUI desktop app
echo   desktop       Build then launch WinUI desktop app; if already running, reuse the current instance
echo   full          Compatibility alias for "desktop"; backend auto-start is handled by the desktop app
echo   help          Show this help
set "EXIT_CODE=0"
goto :finish

:finish
if "%EXIT_CODE%"=="" set "EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %EXIT_CODE%

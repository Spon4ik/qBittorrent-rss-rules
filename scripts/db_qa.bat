@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_DIR%\logs\qa\db"
set "REPORT_FILE=%LOG_DIR%\db-qa-report.json"

pushd "%PROJECT_DIR%" >nul

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if "%~1"=="" (
  echo Usage: scripts\db_qa.bat ^<offline-db-path^> [--full]
  echo.
  echo This wrapper is for an offline database or safety copy only.
  echo For the live Docker database, run the module inside the owning container.
  popd >nul
  exit /b 2
)

set "DATABASE=%~1"
set "FULL_ARG="
if /I "%~2"=="--full" set "FULL_ARG=--full"

call "%PYTHON_EXE%" -m app.services.sqlite_maintenance "%DATABASE%" --output "%REPORT_FILE%" %FULL_ARG%
set "EXIT_CODE=%ERRORLEVEL%"

echo DB QA report: %REPORT_FILE%

popd >nul
exit /b %EXIT_CODE%

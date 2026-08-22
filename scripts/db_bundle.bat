@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_DIR%\logs\qa\db"
set "REPORT_FILE=%LOG_DIR%\db-bundle-report.json"

pushd "%PROJECT_DIR%" >nul

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if "%~1"=="" (
  echo Usage:
  echo   scripts\db_bundle.bat backup ^<database^> [--bundle ^<directory^>]
  echo   scripts\db_bundle.bat verify ^<bundle-directory^>
  echo   scripts\db_bundle.bat restore ^<bundle-directory^> ^<database^>
  popd >nul
  exit /b 2
)

call "%PYTHON_EXE%" -m app.services.sqlite_state_bundle %* --output "%REPORT_FILE%"
set "EXIT_CODE=%ERRORLEVEL%"

echo DB rollback report: %REPORT_FILE%

popd >nul
exit /b %EXIT_CODE%

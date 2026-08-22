@echo off
setlocal

set "ROOT=%~dp0.."
set "PYTHON_EXE=%ROOT%\.venv\Scripts\python.exe"
set "REPORT_DIR=%ROOT%\logs\qa\db"
set "REPORT_FILE=%REPORT_DIR%\db-recovery-report.json"

if not exist "%PYTHON_EXE%" (
    echo ERROR: Python virtual environment not found: %PYTHON_EXE%
    exit /b 2
)

if "%~1"=="" goto :usage
if /I "%~1"=="prepare" goto :prepare
if /I "%~1"=="activate" goto :activate
goto :usage

:prepare
if "%~2"=="" goto :usage
if "%~3"=="" goto :usage
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%" >nul 2>&1
call "%PYTHON_EXE%" -m app.services.sqlite_recovery prepare "%~2" "%~3" --output "%REPORT_FILE%"
set "EXIT_CODE=%ERRORLEVEL%"
echo DB recovery report: %REPORT_FILE%
exit /b %EXIT_CODE%

:activate
if "%~2"=="" goto :usage
if "%~3"=="" goto :usage
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%" >nul 2>&1
if "%~4"=="" (
    call "%PYTHON_EXE%" -m app.services.sqlite_recovery activate "%~2" "%~3" --output "%REPORT_FILE%"
) else (
    call "%PYTHON_EXE%" -m app.services.sqlite_recovery activate "%~2" "%~3" --rollback-dir "%~4" --output "%REPORT_FILE%"
)
set "EXIT_CODE=%ERRORLEVEL%"
echo DB recovery report: %REPORT_FILE%
exit /b %EXIT_CODE%

:usage
echo Usage:
echo   scripts\db_recover.bat prepare ^<source.db^> ^<candidate.db^>
echo   scripts\db_recover.bat activate ^<candidate.db^> ^<target.db^> [rollback-dir]
echo.
echo IMPORTANT: activate requires the owning SQLite service to be stopped or quiesced.
exit /b 2

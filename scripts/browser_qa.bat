@echo off
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_DIR=%%~fI"

set "PYTHON_EXE="
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
) else if exist "%PROJECT_DIR%\.venv-linux\bin\python" (
  set "PYTHON_EXE=%PROJECT_DIR%\.venv-linux\bin\python"
) else (
  where python >nul 2>nul
  if !ERRORLEVEL! EQU 0 (
    set "PYTHON_EXE=python"
  ) else (
    echo No Python interpreter found.
    exit /b 127
  )
)

set "QA_SCRIPT=browser_qa.py"
if /I "%~1"=="--suite" (
  if /I "%~2"=="ui" set "QA_SCRIPT=ui_suite_qa.py"
)
if /I "%~1"=="--check" (
  set "CHECK_ID=%~2"
  if /I "!CHECK_ID:~0,3!"=="UI-" set "QA_SCRIPT=ui_suite_qa.py"
)

"!PYTHON_EXE!" "%PROJECT_DIR%\scripts\!QA_SCRIPT!" %*
set "EXIT_CODE=!ERRORLEVEL!"
endlocal & exit /b %EXIT_CODE%

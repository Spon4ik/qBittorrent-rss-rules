@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_DIR=%%~fI"

set "PYTHON_EXE="
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
) else if exist "%PROJECT_DIR%\.venv-linux\bin\python" (
  set "PYTHON_EXE=%PROJECT_DIR%\.venv-linux\bin\python"
) else (
  where python >nul 2>nul
  if %ERRORLEVEL% EQU 0 (
    set "PYTHON_EXE=python"
  ) else (
    echo No Python interpreter found.
    exit /b 127
  )
)

"%PYTHON_EXE%" "%PROJECT_DIR%\scripts\capture_search_ui.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%

@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."

pushd "%PROJECT_DIR%" >nul

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

%PYTHON_EXE% -m ruff check .
if errorlevel 1 goto :done

%PYTHON_EXE% -m mypy app
if errorlevel 1 goto :done

call "%SCRIPT_DIR%test.bat"

:done
set "EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %EXIT_CODE%

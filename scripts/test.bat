@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_DIR%\logs\tests"
set "LOG_FILE=%LOG_DIR%\pytest-last.log"
set "XML_FILE=%LOG_DIR%\pytest-last.xml"

pushd "%PROJECT_DIR%" >nul

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

> "%LOG_FILE%" echo Command: %PYTHON_EXE% -m pytest --junitxml "%XML_FILE%" %*
>> "%LOG_FILE%" echo Started: %DATE% %TIME%
>> "%LOG_FILE%" echo.

call "%PYTHON_EXE%" -m pytest --junitxml "%XML_FILE%" %* >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

if not exist "%XML_FILE%" (
  > "%XML_FILE%" echo ^<?xml version="1.0" encoding="utf-8"?^>
  >> "%XML_FILE%" echo ^<testsuite name="pytest-wrapper" tests="1" errors="1" failures="0" skipped="0"^>
  >> "%XML_FILE%" echo   ^<testcase classname="scripts.test.bat" name="bootstrap"^>
  >> "%XML_FILE%" echo     ^<error message="pytest did not start; inspect pytest-last.log"^>pytest did not start; inspect pytest-last.log^</error^>
  >> "%XML_FILE%" echo   ^</testcase^>
  >> "%XML_FILE%" echo ^</testsuite^>
)

>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo Exit code: %EXIT_CODE%
>> "%LOG_FILE%" echo Finished: %DATE% %TIME%
>> "%LOG_FILE%" echo Text log: %LOG_FILE%
>> "%LOG_FILE%" echo JUnit XML: %XML_FILE%

type "%LOG_FILE%"
echo.
echo Text log: "%LOG_FILE%"
echo JUnit XML: "%XML_FILE%"

popd >nul
exit /b %EXIT_CODE%

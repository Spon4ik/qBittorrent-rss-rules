@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0restore_windows_migration_bundle.ps1" %*
exit /b %ERRORLEVEL%

@echo off
echo ============================================
echo  QPSS Middleware - Cleanup Pending (Remote)
echo  Remove orphaned pending JSONs on IS-APP-19
echo ============================================
echo.

set /p DAYS="Enter number of days (e.g. 90): "

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0run_remote.ps1" --cleanup-pending %DAYS%

echo.
echo ============================================
echo  Done. Press any key to close.
echo ============================================
pause > nul

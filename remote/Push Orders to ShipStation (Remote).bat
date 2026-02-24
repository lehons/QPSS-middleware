@echo off
echo ============================================
echo  QPSS Middleware - Flow 1 (Remote)
echo  QuikPAK -^> ShipStation Order Creation
echo  Running on: IS-APP-19
echo ============================================
echo.

REM Uses PowerShell remoting to run Flow 1 on IS-APP-19.
REM The -InputObject trick forwards stdin so interactive
REM prompts (held orders, Sage failure) still work.
REM
REM Requirements:
REM   - WinRM must be running on IS-APP-19 (already configured)
REM   - Your domain account must have remote execution permission
REM   - No software needs to be installed on this machine

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0run_remote.ps1" --flow1

echo.
echo ============================================
echo  Done. Press any key to close.
echo ============================================
pause > nul

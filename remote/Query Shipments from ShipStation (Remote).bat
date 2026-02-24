@echo off
echo ============================================
echo  QPSS Middleware - Flow 2 (Remote)
echo  ShipStation -^> QuikPAK Shipment Confirmation
echo  Running on: IS-APP-19
echo ============================================
echo.

REM Uses PowerShell remoting to run Flow 2 on IS-APP-19.
REM
REM Requirements:
REM   - WinRM must be running on IS-APP-19 (already configured)
REM   - Your domain account must have remote execution permission
REM   - No software needs to be installed on this machine

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0run_remote.ps1" --flow2

echo.
echo ============================================
echo  Done. Press any key to close.
echo ============================================
pause > nul

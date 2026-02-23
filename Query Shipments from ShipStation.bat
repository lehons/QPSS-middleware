@echo off
echo ============================================
echo  QPSS Middleware - Flow 2
echo  ShipStation -^> QuikPAK Shipment Confirmation
echo ============================================
echo.

cd /d "%~dp0"
python qpss_middleware.py --flow2

echo.
echo ============================================
echo  Done. Press any key to close.
echo ============================================
pause > nul

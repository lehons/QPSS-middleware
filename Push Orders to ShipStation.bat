@echo off
echo ============================================
echo  QPSS Middleware - Flow 1
echo  QuikPAK -^> ShipStation Order Creation
echo ============================================
echo.

cd /d "%~dp0"
python qpss_middleware.py --flow1

echo.
echo ============================================
echo  Done. Press any key to close.
echo ============================================
pause > nul

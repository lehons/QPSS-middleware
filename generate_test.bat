@echo off
REM ──────────────────────────────────────────────────────────────
REM  Generate test XML files for Flow 1 (QuikPAK -> ShipStation)
REM
REM  Usage:
REM    generate_test.bat                        Use defaults
REM    generate_test.bat --orderno ORD0470002   Override order #
REM    generate_test.bat --country CA --state QC  Ship to Canada
REM    generate_test.bat --help                 Show all options
REM
REM  Defaults:
REM    Order:    ORD0469657     Ship Via:  UPS
REM    Customer: HO1002         Location:  CAN
REM    Ship To:  John Smith, 100 Main Street, Buffalo NY 14201 US
REM    Comment:  BKGLKBL:Keyed Deadbolt, Black;BKGLKW:Keyed Deadbolt, White;
REM
REM  Files are placed in QuikPAKIN, ready for:
REM    run_flow1.bat  or  run_flow1_dryrun.bat
REM ──────────────────────────────────────────────────────────────

cd /d "%~dp0"
python generate_test.py %*
if errorlevel 1 (
    echo.
    echo ERROR: Test generation failed.
    pause
)

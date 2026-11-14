@echo off
REM One-shot spin check. Close Arduino IDE Serial Monitor first!
REM Default: COM6 115200, L3, T0.5, 14 angle samples.
REM Override examples:
REM   spin_test.bat -Limit 4 -Speed 1
REM   spin_test.bat -Speed 0                (stop the motor)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spin_test.ps1" %*
echo.
pause

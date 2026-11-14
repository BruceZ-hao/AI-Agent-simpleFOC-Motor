@echo off
setlocal
title ESP32-S3 DevKitC-1 - Flash SimpleFOC and run

REM esptool ships with the Arduino ESP32 board package; auto-detect its version folder.
REM Override if needed: set ESPTOOL_PATH=C:\path\to\esptool.exe
if defined ESPTOOL_PATH set "ESPTOOL=%ESPTOOL_PATH%"
if not defined ESPTOOL (
  for /d %%D in ("%LOCALAPPDATA%\Arduino15\packages\esp32\tools\esptool_py\*") do if exist "%%D\esptool.exe" set "ESPTOOL=%%D\esptool.exe"
)
if not defined ESPTOOL (
  for /d %%D in ("%USERPROFILE%\AppData\Local\Arduino15\packages\esp32\tools\esptool_py\*") do if exist "%%D\esptool.exe" set "ESPTOOL=%%D\esptool.exe"
)
set "IMG=%~dp0ESP32S3_SimpleFOC_AS5600.merged.bin"

echo.
echo ============================================================
echo  ESP32-S3 DevKitC-1 + DengFOC-Mini (MP6536) + AS5600
echo  SimpleFOC firmware - flash and run
echo ============================================================
echo  Writes the full 4MB image at 115200 baud (no baud switch),
echo  then WATCHDOG-RESET so the app actually starts.
echo  A plain hard-reset leaves the S3 in ROM download mode.
echo.
echo  BEFORE RUNNING (STAGE 3 closed-loop):
echo   - Keep 12V + all three motor phases CONNECTED and the shaft FREE.
echo     The app starts right after flashing and runs initFOC() alignment
echo     at once; it needs a powered, unloaded motor to calibrate correctly.
echo   - Close the Arduino IDE Serial Monitor AND click Disconnect in the
echo     HapticConsole web page to free the serial port.
echo   - If calibration was done with 12V off, just press RESET afterwards.
echo.
set "PORT=COM6"
set /p "PORT=Serial port (Enter = COM6): "
echo.
echo  Freeing Arduino IDE serial services...
taskkill /F /IM serial-discovery.exe >nul 2>&1
taskkill /F /IM serial-monitor.exe >nul 2>&1

if not defined ESPTOOL (echo [ERROR] esptool.exe not found. Install ESP32 board package or set ESPTOOL_PATH. & goto fail)
if not exist "%ESPTOOL%" (echo [ERROR] esptool.exe not found: %ESPTOOL% & goto fail)
if not exist "%IMG%" (echo [ERROR] merged firmware not found & goto fail)

"%ESPTOOL%" --chip esp32s3 --port %PORT% --baud 115200 --connect-attempts 3 --before default-reset --after watchdog-reset write-flash -z --flash-mode dio --flash-freq 80m --flash-size 4MB 0x0 "%IMG%"
if errorlevel 1 goto fail

echo.
echo  [OK] Flash + run done. Open Serial Monitor @115200 and press RESET.
echo       Expect: "MOT: Align sensor." / "PP check: OK!" / "Motor ready."
echo       If "PP check: fail - estimated pp: N", set POLE_PAIRS to N
echo       and recompile.
echo       Default HAPTIC v2 (quiet): single-loop PD + home deadband.
echo       Twist the shaft by hand, let go -> snaps back, no buzz at home.
echo       M1 haptic / M0 velocity (T2 to spin) / T0 stops silently.
echo       K stiffness / B damping / Z deadband / H re-zero / D diag.
echo       Velocity idle: S1/S0 silent brake, G damping, J speed deadband.
goto end

:fail
echo.
echo  [FAILED] Replug USB, or hold BOOT while plugging in, then retry.
echo           Pressing the board RESET button also starts the app.

:end
echo.
pause

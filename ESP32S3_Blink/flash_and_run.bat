@echo off
setlocal
title ESP32-S3 DevKitC-1 - Flash LED blink and run

REM esptool ships with the Arduino ESP32 board package; auto-detect its version folder.
REM Override if needed: set ESPTOOL_PATH=C:\path\to\esptool.exe
if defined ESPTOOL_PATH set "ESPTOOL=%ESPTOOL_PATH%"
if not defined ESPTOOL (
  for /d %%D in ("%LOCALAPPDATA%\Arduino15\packages\esp32\tools\esptool_py\*") do if exist "%%D\esptool.exe" set "ESPTOOL=%%D\esptool.exe"
)
if not defined ESPTOOL (
  for /d %%D in ("%USERPROFILE%\AppData\Local\Arduino15\packages\esp32\tools\esptool_py\*") do if exist "%%D\esptool.exe" set "ESPTOOL=%%D\esptool.exe"
)
set "IMG=%~dp0ESP32S3_Blink.merged.bin"

echo.
echo ============================================================
echo  ESP32-S3 DevKitC-1 / WROOM-1 : LED blink firmware
echo ============================================================
echo  Writes the full 4MB image at 115200 baud (no baud switch),
echo  then uses WATCHDOG-RESET so the app actually starts.
echo  A plain hard-reset leaves the S3 in ROM download mode and
echo  the LED will appear dead even though flashing succeeded.
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
echo  [OK] Flash + run done. The onboard RGB (GPIO48) should blink white
echo       every 500 ms. Serial Monitor @115200 prints "alive, blinks = N".
goto end

:fail
echo.
echo  [FAILED] Replug USB, or hold BOOT while plugging in, then retry.
echo           Pressing the board RESET button also starts the app.

:end
echo.
pause

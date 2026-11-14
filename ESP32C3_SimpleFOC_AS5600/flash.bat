@echo off
setlocal
title ESP32-C3 SuperMini - Flash SimpleFOC firmware

REM esptool ships with the Arduino ESP32 board package; auto-detect its version folder.
REM Override if needed: set ESPTOOL_PATH=C:\path\to\esptool.exe
if defined ESPTOOL_PATH set "ESPTOOL=%ESPTOOL_PATH%"
if not defined ESPTOOL (
  for /d %%D in ("%LOCALAPPDATA%\Arduino15\packages\esp32\tools\esptool_py\*") do if exist "%%D\esptool.exe" set "ESPTOOL=%%D\esptool.exe"
)
if not defined ESPTOOL (
  for /d %%D in ("%USERPROFILE%\AppData\Local\Arduino15\packages\esp32\tools\esptool_py\*") do if exist "%%D\esptool.exe" set "ESPTOOL=%%D\esptool.exe"
)
set "IMG=%~dp0ESP32C3_SimpleFOC_AS5600.merged.bin"

echo.
echo ============================================================
echo  ESP32-C3 SuperMini / DengFOC-Mini + AS5600 firmware flash
echo ============================================================
echo  BEFORE RUNNING:
echo   0. You may CLOSE Arduino IDE - this script does not need it.
echo   1. Disconnect driver VIN/VM 12V, AS5600 and all GPIO wires.
echo      Leave ONLY the USB cable connected.
echo   2. Use a rear USB port and a DATA cable (flip Type-C if needed).
echo   3. If sync keeps failing: hold BOOT (IO9), plug USB, then release.
echo.
set "PORT=COM3"
set /p "PORT=Serial port (Enter = COM3): "
echo.
echo  Freeing Arduino IDE serial services...
taskkill /F /IM serial-discovery.exe >nul 2>&1
taskkill /F /IM serial-monitor.exe >nul 2>&1

if not defined ESPTOOL (echo [ERROR] esptool.exe not found. Install ESP32 board package or set ESPTOOL_PATH. & goto fail)
if not exist "%ESPTOOL%" (echo [ERROR] esptool.exe not found: %ESPTOOL% & goto fail)
if not exist "%IMG%" (echo [ERROR] merged firmware not found & goto fail)

echo  Flashing at 115200 baud - no baud switch, avoids Windows error 31...
echo  Each round tries both chip states: already in download mode, or normal boot.
for /L %%i in (1,1,3) do (
  echo  --- attempt %%i / no-reset (BOOT held or chip in ROM mode) ---
  "%ESPTOOL%" --chip esp32c3 --port %PORT% --baud 115200 --connect-attempts 3 --before no-reset --after hard-reset write-flash -z --flash-mode qio --flash-freq 80m --flash-size 4MB 0x0 "%IMG%"
  if not errorlevel 1 goto ok
  echo  --- attempt %%i / default-reset (normal power-up) ---
  "%ESPTOOL%" --chip esp32c3 --port %PORT% --baud 115200 --connect-attempts 3 --before default-reset --after hard-reset write-flash -z --flash-mode qio --flash-freq 80m --flash-size 4MB 0x0 "%IMG%"
  if not errorlevel 1 goto ok
)
goto fail

:ok
echo.
echo  [OK] Flash done. Open Serial Monitor at 115200, press RESET.
echo       Expect: MOT:Enable driver. / Motor ready...
goto end

:fail
echo.
echo  [FAILED] Chip did not sync. Unplug all external wires, replug USB into a
echo           different port, or hold BOOT (IO9) while plugging in, then run
echo           this script again. The .bin file is untouched.

:end
echo.
pause

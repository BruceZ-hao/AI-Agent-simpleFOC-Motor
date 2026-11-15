@echo off
setlocal
title ESP32-S3 - Flash STAGE 0 (TFT self-test only)

REM esptool ships with the Arduino ESP32 board package; auto-detect its version folder.
REM Override if needed: set ESPTOOL_PATH=C:\path\to\esptool.exe
if defined ESPTOOL_PATH set "ESPTOOL=%ESPTOOL_PATH%"
if not defined ESPTOOL (
  for /d %%D in ("%LOCALAPPDATA%\Arduino15\packages\esp32\tools\esptool_py\*") do if exist "%%D\esptool.exe" set "ESPTOOL=%%D\esptool.exe"
)
if not defined ESPTOOL (
  for /d %%D in ("%USERPROFILE%\AppData\Local\Arduino15\packages\esp32\tools\esptool_py\*") do if exist "%%D\esptool.exe" set "ESPTOOL=%%D\esptool.exe"
)
set "IMG=%~dp0ESP32S3_SimpleFOC_AS5600.STAGE0.bin"

echo.
echo ============================================================
echo  STAGE 0 - 1.83" ST7789P3 TFT self-test ONLY
echo ============================================================
echo  Wire / driver / motor are NOT initialized: the motor will not
echo  power up or align. 12V and the 3 phase wires are NOT required.
echo  Use this to calibrate the screen before wiring the motor.
echo.
echo  After flashing: send V (test pattern), I (invert), C (RGB/BGR),
echo  N (backlight), O^<col^>,^<row^> (GRAM offset), Q^<MHz^> (SPI speed),
echo  P (freeze to one static frame), W^<px^> (rounded corner radius,
echo  default 30 = R4mm; V test pattern shows a RED arc to align it) at 115200 baud.
echo  Then write the final values back to the .ino and reflash the
echo  main firmware with flash_and_run.bat.
echo.
echo  Close the Arduino IDE Serial Monitor and click Disconnect in the
echo  HapticConsole web page to free the serial port.
echo.
set "PORT=COM6"
set /p "PORT=Serial port (Enter = COM6): "
echo.
echo  Freeing Arduino IDE serial services...
taskkill /F /IM serial-discovery.exe >nul 2>&1
taskkill /F /IM serial-monitor.exe >nul 2>&1

if not defined ESPTOOL (echo [ERROR] esptool.exe not found. Install ESP32 board package or set ESPTOOL_PATH. & goto fail)
if not exist "%ESPTOOL%" (echo [ERROR] esptool.exe not found: %ESPTOOL% & goto fail)
if not exist "%IMG%" (echo [ERROR] STAGE0 merged firmware not found & goto fail)

"%ESPTOOL%" --chip esp32s3 --port %PORT% --baud 115200 --connect-attempts 3 --before default-reset --after watchdog-reset write-flash -z --flash-mode dio --flash-freq 80m --flash-size 4MB 0x0 "%IMG%"
if errorlevel 1 goto fail

echo.
echo  [OK] STAGE 0 flashed. Screen should show the test pattern.
echo       Open Serial Monitor @115200 and send V / I / C / N / O / Q / P / W to calibrate.
echo       When done, reflash the main firmware with flash_and_run.bat.
goto end

:fail
echo.
echo  [FAILED] Replug USB, or hold BOOT while plugging in, then retry.

:end
echo.
pause

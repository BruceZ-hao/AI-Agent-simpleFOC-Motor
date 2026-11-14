@echo off
setlocal
title SimpleFOC Haptic Console
cd /d "%~dp0"

where python >nul 2>&1
if not errorlevel 1 goto RUN_PY
where py >nul 2>&1
if not errorlevel 1 goto RUN_PYLAUNCH

echo.
echo  [ERROR] Python 3 not found on PATH.
echo          Install Python 3 from python.org, or check your PATH.
echo.
pause
exit /b 1

:RUN_PY
python server.py %*
goto DONE

:RUN_PYLAUNCH
py -3 server.py %*

:DONE
echo.
echo  Service stopped. Close Arduino IDE Serial Monitor before flashing firmware.
pause

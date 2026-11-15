@echo off
chcp 65001 >nul
setlocal
REM Prefer Blender 5.3, but fall back to any installed Blender version.
REM Override if needed: set BLENDER_PATH=C:\path\to\blender.exe
set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.3\blender.exe"
if defined BLENDER_PATH set "BLENDER=%BLENDER_PATH%"
if not exist "%BLENDER%" (
  for /d %%D in ("C:\Program Files\Blender Foundation\Blender *") do if exist "%%D\blender.exe" set "BLENDER=%%D\blender.exe"
)
echo ============================================================
echo  SimpleFOC enclosure - Blender 5.3 headless generator
echo  Edit P dict in enclosure.py, then run this batch again.
echo ============================================================
echo.
if not exist "%BLENDER%" (
  echo [ERROR] Blender not found at:
  echo   %BLENDER%
  echo   Edit BLENDER path in this .bat if installed elsewhere.
  pause
  exit /b 1
)
"%BLENDER%" --background --factory-startup --python "%~dp0enclosure.py"
set "BLENDER_RC=%ERRORLEVEL%"
echo.
where python >nul 2>&1
if not errorlevel 1 (
  python "%~dp0verify_stl.py"
  python "%~dp0verify_fit.py"
) else (
  echo [SKIP] Python not found - run verify_stl.py / verify_fit.py manually.
)
echo.
if not "%BLENDER_RC%"=="0" (
  echo [FAILED] See messages above.
) else (
  echo [OK] STL / renders / Enclosure.blend / build_report.txt refreshed.
)
echo.
pause

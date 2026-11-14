@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  SimpleFOC 台架 - 改完 bracket.py 里的参数后，双击本文件重新导出
echo ============================================================
echo.
python bracket.py
echo.
if errorlevel 1 (
  echo [失败] 网格自检没通过，请看上面的 FAIL 项和参数联动约束。
) else (
  echo [完成] STL / 俯视图 / 装配图 / 自检报告 均已更新到 stl\ 目录。
)
echo.
pause

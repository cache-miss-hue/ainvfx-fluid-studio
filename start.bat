@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title AInVFX Fluid Studio
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONSTARTUP="
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
if not exist "engine\python\python.exe" (
  echo 缺少 engine\python\python.exe ，安装包不完整，请重新解压完整的软件包。
  pause
  exit /b 1
)
echo 正在启动 AInVFX Fluid Studio，浏览器会自动打开……
"engine\python\python.exe" -s -m fxstudio %*
if errorlevel 1 (
  echo.
  echo 软件异常退出，日志在 runtime\logs\ 目录。
  pause
)

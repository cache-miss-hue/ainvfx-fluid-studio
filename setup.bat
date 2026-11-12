@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title AInVFX Fluid Studio - Setup

rem 找 Git Bash（Git for Windows 自带）
set "GITBASH="
for %%P in ("%ProgramFiles%\Git\bin\bash.exe" "%ProgramFiles(x86)%\Git\bin\bash.exe" "%LocalAppData%\Programs\Git\bin\bash.exe") do (
  if exist %%~P if not defined GITBASH set "GITBASH=%%~P"
)
rem 装在非默认位置时：从 PATH 里的 git.exe 反推（...\Git\cmd\git.exe -> ...\Git\bin\bash.exe）
if not defined GITBASH (
  for /f "delims=" %%G in ('where git 2^>nul') do (
    if exist "%%~dpG..\bin\bash.exe" if not defined GITBASH set "GITBASH=%%~dpG..\bin\bash.exe"
  )
)
if not defined GITBASH (
  echo 未找到 Git Bash。请先安装 Git for Windows： https://git-scm.com/download/win
  echo Git Bash not found. Please install Git for Windows first, then run setup.bat again.
  pause
  exit /b 1
)

echo 开始安装：下载 Python、依赖、ComfyUI、FFmpeg（不含模型），需要联网，约 4GB，请耐心等待……
echo Installing engine + FFmpeg (no models). Needs internet, ~4 GB.
echo.
"%GITBASH%" "%~dp0scripts\build_engine.sh"
if errorlevel 1 (
  echo.
  echo 安装失败。可以重新运行 setup.bat（已完成的步骤会跳过）；需要代理请先设置 HTTPS_PROXY。
  echo Setup failed. Re-run setup.bat - finished steps are skipped. Set HTTPS_PROXY if you need a proxy.
  pause
  exit /b 1
)

echo.
echo 下一步：把 5 个模型下载到 models\ 对应子目录（地址见 README），放好后双击 start.bat。
echo Next: download the 5 models into models\ (see README), then double-click start.bat.
pause

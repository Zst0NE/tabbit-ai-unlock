@echo off
chcp 65001 >nul
title Tabbit AI 一键内嵌安装
cd /d "%~dp0"

echo ============================================
echo   Tabbit AI 助手 - 一键内嵌安装
echo   解锁默认浏览器限制 + 安装统一风格侧栏
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Python。请先安装 Python 3.6+ 并勾选 Add to PATH。
  echo 下载: https://www.python.org/downloads/
  pause
  exit /b 1
)

echo [1/1] 正在执行一键安装...
python "%~dp0tabbit_ai_unlock.py" --one-click
set ERR=%ERRORLEVEL%
echo.
if %ERR% neq 0 (
  echo 安装未完全成功，退出码 %ERR%。请查看上方日志。
  pause
  exit /b %ERR%
)

echo.
echo 完成。请按提示退出并重新启动 Tabbit。
pause

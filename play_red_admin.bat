@echo off
:: 请求管理员权限后启动自动下棋
cd /d "%~dp0"
net session >nul 2>&1
if %errorLevel% neq 0 (
  echo Requesting admin...
  powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
call .venv\Scripts\activate.bat
set PYTHONUNBUFFERED=1
set PYTHONPATH=%~dp0
echo [ADMIN] Starting auto-play...
python -u main.py play --side red
pause

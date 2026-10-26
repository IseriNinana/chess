@echo off
echo ============================================
echo  IMPORTANT: Do NOT start this from Cursor.
echo  Open Windows CMD like this:
echo    1) Press Win key, type cmd, Enter
echo    2) Run:
echo       cd /d D:\A_Project\chess
echo       test_cursor.ps1   (or play_red.bat)
echo ============================================
echo.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test_cursor.ps1"

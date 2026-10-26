@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set PYTHONUNBUFFERED=1
echo Starting auto-play. Keep Chinese Chess window in front.
echo IMPORTANT: Do NOT run inside Cursor terminal if mouse clicks fail.
echo Prefer: Start Menu CMD, or right-click play_red_admin.bat -^> Run as admin.
echo Stop with Ctrl+C
python -u main.py play --side red
pause

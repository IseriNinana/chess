@echo off
cd /d "%~dp0"
echo.
echo ============================================================
echo  若从 Cursor 里双击/运行，光标可能完全不动。
echo  请改用：Win 键 -^> 输入 cmd -^> 回车，然后：
echo    cd /d D:\A_Project\chess
echo    test_click.bat
echo  或先运行：run_cursor_test.bat 看箭头会不会跳。
echo ============================================================
echo.
call .venv\Scripts\activate.bat
set PYTHONUNBUFFERED=1
set PYTHONPATH=%~dp0
echo Put Chinese Chess in front. Starting click test...
python -u tools\test_click.py
pause

@echo off
cd /d "%~dp0"
start "" cmd /c "timeout /t 2 /nobreak >nul && start "" "%~dp0frontend\index.html""
python "%~dp0run.py"

@echo off
chcp 65001 >nul
title TCC - Detector de Anomalias

echo ============================================
echo   Iniciando o servidor da API...
echo ============================================

:: Abre o index.html no navegador após 3 segundos (tempo pro server subir)
start "" cmd /c "timeout /t 3 /nobreak >nul && start "" "%~dp0frontend\index.html""

:: Inicia o servidor (bloqueia o terminal enquanto roda)
python "%~dp0run.py"

pause

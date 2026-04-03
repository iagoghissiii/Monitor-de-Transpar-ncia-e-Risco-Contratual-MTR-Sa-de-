@echo off
chcp 65001 >nul
cd /d "%~dp0"
title MTR-Saude

echo ============================================
echo   MTR-Saude - Setup e Inicializacao
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale o Python 3.10+ e tente novamente.
    pause
    exit /b
)

echo [1/4] Instalando dependencias...
pip install -r "%~dp0requirements.txt" --quiet
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias.
    pause
    exit /b
)
echo       OK.
echo.

echo [2/4] Coletando contratos do Portal da Transparencia (2022-2026)...
echo       Isso pode demorar alguns minutos na primeira execucao.
python -m src.etl.pipeline
if errorlevel 1 (
    echo [AVISO] Coleta com erros. O servidor sera iniciado com os dados existentes.
)
echo.

echo [3/4] Abrindo o navegador em 4 segundos...
start "" cmd /c "timeout /t 4 /nobreak >nul && start "" "%~dp0frontend\index.html""

echo [4/4] Iniciando servidor em http://localhost:8000
echo       Pressione Ctrl+C para encerrar.
echo.
python "%~dp0run.py"

pause

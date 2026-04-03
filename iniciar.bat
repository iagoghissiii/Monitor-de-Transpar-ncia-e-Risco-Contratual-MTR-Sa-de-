@echo off
chcp 65001 >nul
cd /d "%~dp0"
title MTR-Saúde — Monitor de Transparência e Risco Contratual

echo ============================================
echo   MTR-Saúde — Setup e Inicialização
echo ============================================
echo.

:: Verifica se o Python está disponível
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale o Python 3.10+ e tente novamente.
    pause
    exit /b
)

:: Instala dependências
echo [1/4] Instalando dependências...
pip install -r "%~dp0requirements.txt" --quiet
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias.
    pause
    exit /b
)
echo       OK.
echo.

:: Coleta dados do Portal da Transparência
echo [2/4] Coletando contratos do Portal da Transparência (2022-2026)...
echo       Isso pode demorar alguns minutos na primeira execução.
python -m src.etl.pipeline
if errorlevel 1 (
    echo [AVISO] A coleta de dados teve erros. Verifique o .env e tente novamente.
    echo         O servidor será iniciado com os dados já existentes.
)
echo.

:: Abre o navegador após o servidor subir
echo [3/4] Abrindo o navegador em 4 segundos...
start "" cmd /c "timeout /t 4 /nobreak >nul && start "" "%~dp0frontend\index.html""

:: Inicia o servidor
echo [4/4] Iniciando o servidor da API em http://localhost:8000
echo       Pressione Ctrl+C para encerrar.
echo.
python "%~dp0run.py"

pause

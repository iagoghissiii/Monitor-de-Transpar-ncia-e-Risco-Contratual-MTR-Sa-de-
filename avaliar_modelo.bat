@echo off
cd /d "%~dp0"
title MTR-Saude — Avaliacao do Modelo
echo.
echo ============================================================
echo  MTR-Saude — Avaliacao de Acuracia do Modelo de IA
echo ============================================================
echo.
python -m src.ml.avaliar
echo.
pause

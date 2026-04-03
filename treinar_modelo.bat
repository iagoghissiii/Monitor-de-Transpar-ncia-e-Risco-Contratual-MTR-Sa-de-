@echo off
cd /d "%~dp0"
title MTR-Saude — Treinamento do Modelo ML
echo.
echo ============================================================
echo  MTR-Saude v2.0 — Treinamento dos Modelos de IA
echo ============================================================
echo.
echo  Pipeline:
echo    1. Carregando features dos contratos...
echo    2. Isolation Forest (deteccao de anomalias)
echo    3. SMOTE (balanceamento de classes)
echo    4. XGBoost (classificacao de risco)
echo    5. SHAP (explicabilidade)
echo    6. Salvando scores no banco de dados...
echo.
echo  Isso pode levar alguns minutos. Aguarde...
echo.
python -m src.ml.treinar
echo.
echo ============================================================
echo  Treinamento concluido! Abra a plataforma para ver os scores.
echo ============================================================
echo.
pause

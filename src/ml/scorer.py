"""
Scorea contratos individuais usando os modelos treinados.

Os modelos sao carregados uma unica vez (lazy loading) e reutilizados
durante a vida da aplicacao (singleton em memoria).
"""

import numpy as np
import joblib
from pathlib import Path
from src.ml.features import FEATURE_COLS, FEATURE_LABELS, extrair_features_contrato

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models"

LIMIAR_ALTO  = 0.65
LIMIAR_MEDIO = 0.40

# Singleton dos modelos
_if_model  = None
_if_scaler = None
_xgb_model = None
_explainer = None
_modelos_prontos = False


def modelos_disponiveis() -> bool:
    """Retorna True se os arquivos de modelo existem no disco."""
    return all(
        (MODELS_DIR / nome).exists()
        for nome in ("isolation_forest.pkl", "if_scaler.pkl",
                     "xgboost_risco.pkl", "shap_explainer.pkl")
    )


def _carregar() -> None:
    global _if_model, _if_scaler, _xgb_model, _explainer, _modelos_prontos
    if _modelos_prontos:
        return
    if not modelos_disponiveis():
        raise FileNotFoundError(
            "Modelos nao encontrados em data/models/. "
            "Execute primeiro: python -m src.ml.treinar"
        )
    _if_model  = joblib.load(MODELS_DIR / "isolation_forest.pkl")
    _if_scaler = joblib.load(MODELS_DIR / "if_scaler.pkl")
    _xgb_model = joblib.load(MODELS_DIR / "xgboost_risco.pkl")
    _explainer = joblib.load(MODELS_DIR / "shap_explainer.pkl")
    _modelos_prontos = True


def _nivel_risco(score: float) -> str:
    if score >= LIMIAR_ALTO:
        return "alto"
    if score >= LIMIAR_MEDIO:
        return "medio"
    return "baixo"


def score_contrato(contrato) -> dict:
    """
    Calcula score de anomalia de um contrato em tempo real.

    Parametro:
        contrato — ORM Contrato (com atributos valor, data_inicio, etc.)

    Retorno:
        {
            "score_anomalia": float,       # 0.0 – 1.0
            "nivel_risco":    str,         # "baixo" | "medio" | "alto"
            "fatores": [
                {
                    "feature": str,        # nome interno
                    "label":   str,        # nome legivel em portugues
                    "valor":   float,      # valor da feature para este contrato
                    "impacto": float,      # SHAP value (positivo = aumenta risco)
                },
                ...  # top 5 fatores por impacto absoluto
            ]
        }
    """
    _carregar()

    feats = extrair_features_contrato(contrato)
    X     = np.array([[feats[col] for col in FEATURE_COLS]], dtype=float)

    # Score pelo Isolation Forest
    raw   = _if_model.score_samples(X)
    score = float(np.clip(
        _if_scaler.transform((-raw).reshape(-1, 1)).flatten()[0],
        0.0, 1.0,
    ))

    nivel = _nivel_risco(score)

    # XGBoost: tipo de anomalia (normal / falha_preenchimento / fraude_intencional)
    y_pred      = int(_xgb_model.predict(X)[0])
    _LABEL_NOME = {0: "normal", 1: "falha_preenchimento", 2: "fraude_intencional"}
    tipo        = _LABEL_NOME.get(y_pred, "normal")

    # SHAP — valores para a classe XGBoost prevista
    shap_vals   = _explainer.shap_values(X)
    importances = shap_vals[y_pred][0]

    fatores = [
        {
            "feature": col,
            "label":   FEATURE_LABELS.get(col, col),
            "valor":   float(feats[col]),
            "impacto": float(importances[i]),
        }
        for i, col in enumerate(FEATURE_COLS)
    ]
    fatores.sort(key=lambda x: abs(x["impacto"]), reverse=True)

    return {
        "score_anomalia": score,
        "nivel_risco":    nivel,
        "tipo_anomalia":  tipo,
        "fatores":        fatores[:5],
    }

"""
Scorea contratos individuais usando os modelos treinados.

Carrega os modelos na primeira chamada (lazy loading) e detecta automaticamente
se os arquivos foram atualizados no disco (novo treinamento), recarregando sem
precisar reiniciar o servidor.
"""

import numpy as np
import joblib
import logging
from pathlib import Path
from src.ml.features import FEATURE_COLS, FEATURE_LABELS, extrair_features_contrato

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models"

LIMIAR_ALTO  = 0.65
LIMIAR_MEDIO = 0.40

_ARQUIVOS = ("isolation_forest.pkl", "if_scaler.pkl",
             "xgboost_risco.pkl",    "shap_explainer.pkl")

# Singleton — recarregado automaticamente se os arquivos mudarem
_cache: dict = {
    "if_model":  None,
    "if_scaler": None,
    "xgb_model": None,
    "explainer": None,
    "mtime":     0.0,   # timestamp do ultimo carregamento
}


def modelos_disponiveis() -> bool:
    return all((MODELS_DIR / a).exists() for a in _ARQUIVOS)


def _mtime_atual() -> float:
    """Retorna o timestamp mais recente dos arquivos de modelo."""
    try:
        return max((MODELS_DIR / a).stat().st_mtime for a in _ARQUIVOS)
    except Exception:
        return 0.0


def _carregar() -> None:
    """Carrega (ou recarrega) modelos se necessario."""
    if not modelos_disponiveis():
        raise FileNotFoundError(
            "Modelos nao encontrados em data/models/. "
            "Execute: treinar_modelo.bat"
        )
    mtime = _mtime_atual()
    if mtime <= _cache["mtime"]:
        return  # modelos em memoria ainda sao os mais recentes

    logger.info("Carregando modelos ML do disco (mtime=%.0f)...", mtime)
    _cache["if_model"]  = joblib.load(MODELS_DIR / "isolation_forest.pkl")
    _cache["if_scaler"] = joblib.load(MODELS_DIR / "if_scaler.pkl")
    _cache["xgb_model"] = joblib.load(MODELS_DIR / "xgboost_risco.pkl")
    _cache["explainer"] = joblib.load(MODELS_DIR / "shap_explainer.pkl")
    _cache["mtime"]     = mtime
    logger.info("Modelos ML carregados com sucesso.")


def _nivel_risco(score: float) -> str:
    if score >= LIMIAR_ALTO:
        return "alto"
    if score >= LIMIAR_MEDIO:
        return "medio"
    return "baixo"


def _extrair_shap(explainer, X: np.ndarray, classe_idx: int) -> np.ndarray:
    """
    Extrai valores SHAP para a classe `classe_idx`.

    Compativel com SHAP >= 0.40 (retorna ndarray 3D) e versoes anteriores
    (retorna lista de arrays 2D, um por classe).
    """
    vals = explainer.shap_values(X)

    if isinstance(vals, list):
        # Formato antigo: list[n_classes] de arrays shape (n_samples, n_features)
        arr = vals[classe_idx]           # (n_samples, n_features)
        return arr[0]                    # (n_features,)

    # Formato novo: ndarray shape (n_samples, n_features, n_classes)
    if vals.ndim == 3:
        return vals[0, :, classe_idx]   # (n_features,)

    # Fallback — binario ou formato inesperado
    if vals.ndim == 2:
        return vals[0]
    return vals.flatten()[:len(FEATURE_COLS)]


def score_contrato(contrato) -> dict:
    """
    Calcula score + tipo de anomalia + top 5 fatores SHAP de um contrato.

    Retorno:
        {
            "score_anomalia": float,      # 0.0 – 1.0
            "nivel_risco":    str,        # "baixo" | "medio" | "alto"
            "tipo_anomalia":  str,        # "normal" | "falha_preenchimento" | "fraude_intencional"
            "fatores": [
                {"feature": str, "label": str, "valor": float, "impacto": float},
                ...  # top 5 por |impacto|
            ]
        }
    """
    _carregar()

    feats = extrair_features_contrato(contrato)
    X     = np.array([[feats[col] for col in FEATURE_COLS]], dtype=float)

    # ── Isolation Forest → score 0-1 ────────────────────────────────────────
    raw   = _cache["if_model"].score_samples(X)
    score = float(np.clip(
        _cache["if_scaler"].transform((-raw).reshape(-1, 1)).flatten()[0],
        0.0, 1.0,
    ))
    nivel = _nivel_risco(score)

    # ── XGBoost → tipo de anomalia ───────────────────────────────────────────
    y_pred = int(_cache["xgb_model"].predict(X)[0])
    _LABEL = {0: "normal", 1: "falha_preenchimento", 2: "fraude_intencional"}
    tipo   = _LABEL.get(y_pred, "normal")

    # ── SHAP → top 5 fatores ─────────────────────────────────────────────────
    try:
        importances = _extrair_shap(_cache["explainer"], X, y_pred)
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
        fatores = fatores[:5]
    except Exception as e:
        logger.warning("SHAP falhou para contrato %s: %s", getattr(contrato, "id", "?"), e)
        fatores = []

    return {
        "score_anomalia": score,
        "nivel_risco":    nivel,
        "tipo_anomalia":  tipo,
        "fatores":        fatores,
    }

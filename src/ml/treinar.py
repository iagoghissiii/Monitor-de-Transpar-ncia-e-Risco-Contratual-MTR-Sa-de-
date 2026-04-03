"""
Pipeline de treinamento — MTR-Saude v2.1

Etapas:
    1. Carrega features dos 41k contratos reais do banco
    2. Treina Isolation Forest (deteccao nao-supervisionada)
    3. Normaliza scores IF para [0, 1]
    4. Gera dataset sintetico baseado em casos TCU/MPF
    5. Monta dataset de treino:
          real normals (IF score < 0.40)      -> classe 0 normal
          sintetico falha_preenchimento        -> classe 1
          sintetico fraude_intencional         -> classe 2
          real alto risco (IF score >= 0.65)   -> classe 2 (reforca fraude)
    6. Aplica SMOTE e treina XGBoost 3-classes
    7. Gera SHAP explainer
    8. Classifica todos os contratos reais -> tipo_anomalia
    9. Persiste score_anomalia, nivel_risco e tipo_anomalia no banco

Uso:
    python -m src.ml.treinar
"""

import logging
import numpy as np
import pandas as pd
import joblib
from pathlib import Path

from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import MinMaxScaler
from xgboost import XGBClassifier
from imblearn.over_sampling import SMOTE
import shap

from src.database.postgres import SessionLocal, Contrato, create_tables
from src.ml.features import carregar_features_df, FEATURE_COLS
from src.ml.dados_sinteticos import gerar_dataset, resumo_catalogo

# ── Config ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

LIMIAR_ALTO  = 0.65
LIMIAR_MEDIO = 0.40

LABEL_NOME = {0: "normal", 1: "falha_preenchimento", 2: "fraude_intencional"}


def _nivel_risco(score: float) -> str:
    if score >= LIMIAR_ALTO:
        return "alto"
    if score >= LIMIAR_MEDIO:
        return "medio"
    return "baixo"


# ── Pipeline ─────────────────────────────────────────────────────────────────

def treinar() -> None:
    create_tables()

    # ── 1. Features reais ────────────────────────────────────────────────────
    logger.info("Carregando features dos contratos reais...")
    db = SessionLocal()
    try:
        df_real = carregar_features_df(db)
    finally:
        db.close()

    n_real = len(df_real)
    logger.info("  %d contratos reais carregados.", n_real)

    X_real = df_real[FEATURE_COLS].values.astype(float)
    ids    = df_real["id"].values

    # ── 2. Isolation Forest ──────────────────────────────────────────────────
    logger.info("Treinando Isolation Forest (n_estimators=200, contamination=0.10)...")
    if_model = IsolationForest(
        n_estimators=200,
        contamination=0.10,
        max_samples="auto",
        random_state=42,
        n_jobs=-1,
    )
    if_model.fit(X_real)

    raw_scores  = if_model.score_samples(X_real)
    scaler      = MinMaxScaler()
    scores_norm = scaler.fit_transform((-raw_scores).reshape(-1, 1)).flatten()

    joblib.dump(if_model, MODELS_DIR / "isolation_forest.pkl")
    joblib.dump(scaler,   MODELS_DIR / "if_scaler.pkl")
    logger.info("  Isolation Forest salvo.")

    # ── 3. Dados sinteticos TCU/MPF ──────────────────────────────────────────
    resumo_catalogo()
    logger.info("Gerando dataset sintetico (casos TCU/MPF)...")
    df_sint = gerar_dataset(n_normais=300)
    logger.info("  Amostras sinteticas: %d", len(df_sint))
    logger.info("  Distribuicao:\n%s", df_sint["tipo_anomalia"].value_counts().to_string())

    X_sint = df_sint[FEATURE_COLS].values.astype(float)
    y_sint = df_sint["classe"].values.astype(int)

    # ── 4. Dataset supervisionado misto ─────────────────────────────────────
    # Pega contratos reais normais (IF score < 0.40) como classe 0
    mask_normal   = scores_norm < LIMIAR_MEDIO
    mask_alto     = scores_norm >= LIMIAR_ALTO

    X_real_normal = X_real[mask_normal]
    y_real_normal = np.zeros(mask_normal.sum(), dtype=int)

    # Contratos reais com alto risco -> reforco da classe 2 (fraude)
    X_real_alto   = X_real[mask_alto]
    y_real_alto   = np.full(mask_alto.sum(), 2, dtype=int)

    X_train = np.vstack([X_real_normal, X_real_alto, X_sint])
    y_train = np.concatenate([y_real_normal, y_real_alto, y_sint])

    logger.info("Dataset supervisionado:")
    for cls, nome in LABEL_NOME.items():
        n = (y_train == cls).sum()
        logger.info("  %s: %d", nome, n)

    # ── 5. SMOTE ─────────────────────────────────────────────────────────────
    logger.info("Aplicando SMOTE...")
    unique, counts = np.unique(y_train, return_counts=True)
    k_neighbors    = min(5, int(counts.min()) - 1)
    k_neighbors    = max(1, k_neighbors)
    smote          = SMOTE(random_state=42, k_neighbors=k_neighbors)
    X_bal, y_bal   = smote.fit_resample(X_train, y_train)
    logger.info("  Apos SMOTE: %d amostras", len(X_bal))

    # ── 6. XGBoost 3-classes ─────────────────────────────────────────────────
    logger.info("Treinando XGBoost (3 classes: normal / falha / fraude)...")
    xgb = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="mlogloss",
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )
    xgb.fit(X_bal, y_bal)
    joblib.dump(xgb, MODELS_DIR / "xgboost_risco.pkl")
    logger.info("  XGBoost salvo.")

    # ── 7. SHAP ──────────────────────────────────────────────────────────────
    logger.info("Gerando SHAP explainer (amostra de 5000)...")
    idx_s     = np.random.default_rng(42).choice(len(X_real), size=min(5000, n_real), replace=False)
    explainer = shap.TreeExplainer(xgb, data=X_real[idx_s], feature_names=FEATURE_COLS)
    joblib.dump(explainer, MODELS_DIR / "shap_explainer.pkl")
    logger.info("  SHAP explainer salvo.")

    # ── 8. Classificar todos os contratos reais ───────────────────────────────
    logger.info("Classificando todos os contratos reais...")
    y_pred      = xgb.predict(X_real)
    tipos_pred  = [LABEL_NOME[int(p)] for p in y_pred]

    # ── 9. Persistir no banco ────────────────────────────────────────────────
    logger.info("Salvando score_anomalia, nivel_risco e tipo_anomalia no banco...")
    db    = SessionLocal()
    BATCH = 500
    try:
        for start in range(0, n_real, BATCH):
            end = min(start + BATCH, n_real)
            for i in range(start, end):
                cid  = int(ids[i])
                sc   = float(scores_norm[i])
                nr   = _nivel_risco(sc)
                tipo = tipos_pred[i]
                db.query(Contrato).filter(Contrato.id == cid).update(
                    {"score_anomalia": sc, "nivel_risco": nr, "tipo_anomalia": tipo},
                    synchronize_session=False,
                )
            db.commit()
            if end % 5000 == 0 or end == n_real:
                logger.info("  Atualizados %d / %d", end, n_real)
    except Exception as e:
        db.rollback()
        logger.error("Erro ao salvar: %s", e)
        raise
    finally:
        db.close()

    # ── Resumo ───────────────────────────────────────────────────────────────
    alto  = int((scores_norm >= LIMIAR_ALTO).sum())
    medio = int(((scores_norm >= LIMIAR_MEDIO) & (scores_norm < LIMIAR_ALTO)).sum())
    baixo = int((scores_norm < LIMIAR_MEDIO).sum())

    n_fraude = tipos_pred.count("fraude_intencional")
    n_falha  = tipos_pred.count("falha_preenchimento")
    n_normal = tipos_pred.count("normal")

    logger.info("=" * 60)
    logger.info("Treinamento concluido!")
    logger.info("")
    logger.info("Score (Isolation Forest):")
    logger.info("  Alto risco   (>= 0.65): %6d  (%.1f%%)", alto,  100 * alto  / n_real)
    logger.info("  Medio risco  (0.40-0.64):%6d  (%.1f%%)", medio, 100 * medio / n_real)
    logger.info("  Baixo risco  (< 0.40) : %6d  (%.1f%%)", baixo, 100 * baixo / n_real)
    logger.info("")
    logger.info("Tipo (XGBoost + casos TCU/MPF):")
    logger.info("  fraude_intencional    : %6d  (%.1f%%)", n_fraude, 100 * n_fraude / n_real)
    logger.info("  falha_preenchimento   : %6d  (%.1f%%)", n_falha,  100 * n_falha  / n_real)
    logger.info("  normal                : %6d  (%.1f%%)", n_normal, 100 * n_normal / n_real)
    logger.info("")
    logger.info("  Modelos salvos em: %s", MODELS_DIR)
    logger.info("=" * 60)


if __name__ == "__main__":
    treinar()

"""
Treinamento dos modelos de deteccao de anomalias contratuais — MTR-Saude.

Pipeline:
    1. Carrega features de todos os contratos do banco SQLite
    2. Treina Isolation Forest  (deteccao nao-supervisionada)
    3. Normaliza scores para [0, 1]  (0 = normal, 1 = altamente anomalo)
    4. Gera pseudo-labels a partir do score IF
    5. Aplica SMOTE para balancear as classes
    6. Treina XGBoost  (classificacao baixo / medio / alto)
    7. Gera SHAP explainer e salva
    8. Persiste score_anomalia e nivel_risco no banco para todos os contratos

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

# ── Configuracao ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Limiares de risco (percentil sobre score normalizado)
LIMIAR_ALTO  = 0.65
LIMIAR_MEDIO = 0.40


# ── Helpers ───────────────────────────────────────────────────────────────────
def _nivel_risco(score: float) -> str:
    if score >= LIMIAR_ALTO:
        return "alto"
    if score >= LIMIAR_MEDIO:
        return "medio"
    return "baixo"


def _classe(score: float) -> int:
    if score >= LIMIAR_ALTO:
        return 2
    if score >= LIMIAR_MEDIO:
        return 1
    return 0


# ── Pipeline principal ────────────────────────────────────────────────────────
def treinar() -> None:
    create_tables()

    # 1. Features
    logger.info("Carregando features do banco...")
    db = SessionLocal()
    try:
        df = carregar_features_df(db)
    finally:
        db.close()

    n_total = len(df)
    logger.info("Total de contratos carregados: %d", n_total)

    X   = df[FEATURE_COLS].values.astype(float)
    ids = df["id"].values

    # 2. Isolation Forest
    logger.info("Treinando Isolation Forest (n_estimators=200, contamination=0.10)...")
    if_model = IsolationForest(
        n_estimators=200,
        contamination=0.10,
        max_samples="auto",
        random_state=42,
        n_jobs=-1,
    )
    if_model.fit(X)

    # score_samples retorna valores negativos: mais negativo = mais anomalo
    raw_scores = if_model.score_samples(X)

    # Inverter sinal e normalizar para [0, 1]
    scaler      = MinMaxScaler()
    scores_norm = scaler.fit_transform((-raw_scores).reshape(-1, 1)).flatten()

    joblib.dump(if_model, MODELS_DIR / "isolation_forest.pkl")
    joblib.dump(scaler,   MODELS_DIR / "if_scaler.pkl")
    logger.info("Modelo Isolation Forest salvo em %s", MODELS_DIR)

    # 3. Pseudo-labels
    labels = np.array([_classe(s) for s in scores_norm])
    unique, counts = np.unique(labels, return_counts=True)
    logger.info("Distribuicao de pseudo-labels (IF):")
    for u, c in zip(unique, counts):
        nomes = {0: "baixo", 1: "medio", 2: "alto"}
        logger.info("  %s: %d contratos (%.1f%%)", nomes[u], c, 100 * c / n_total)

    # 4. SMOTE
    logger.info("Aplicando SMOTE para balancear classes...")
    min_class_count = int(counts.min())
    k_neighbors     = min(5, min_class_count - 1)
    if k_neighbors < 1:
        logger.warning("Classe muito pequena — SMOTE ignorado, usando dados originais.")
        X_bal, y_bal = X, labels
    else:
        smote        = SMOTE(random_state=42, k_neighbors=k_neighbors)
        X_bal, y_bal = smote.fit_resample(X, labels)
        logger.info("  Amostras apos SMOTE: %d", len(X_bal))

    # 5. XGBoost
    logger.info("Treinando XGBoost (n_estimators=200)...")
    xgb = XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="mlogloss",
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )
    xgb.fit(X_bal, y_bal)
    joblib.dump(xgb, MODELS_DIR / "xgboost_risco.pkl")
    logger.info("Modelo XGBoost salvo.")

    # 6. SHAP
    logger.info("Gerando SHAP explainer (amostra de ate 5000 contratos)...")
    sample_size = min(5000, len(X))
    idx_sample  = np.random.default_rng(42).choice(len(X), size=sample_size, replace=False)
    explainer   = shap.TreeExplainer(xgb, data=X[idx_sample], feature_names=FEATURE_COLS)
    joblib.dump(explainer, MODELS_DIR / "shap_explainer.pkl")
    logger.info("SHAP explainer salvo.")

    # 7. Persistir no banco
    logger.info("Atualizando score_anomalia e nivel_risco no banco...")
    db = SessionLocal()
    BATCH = 500
    try:
        for start in range(0, n_total, BATCH):
            end   = min(start + BATCH, n_total)
            batch_ids     = ids[start:end]
            batch_scores  = scores_norm[start:end]
            batch_niveis  = [_nivel_risco(float(s)) for s in batch_scores]
            for cid, sc, nr in zip(batch_ids, batch_scores, batch_niveis):
                db.query(Contrato).filter(Contrato.id == int(cid)).update(
                    {"score_anomalia": float(sc), "nivel_risco": nr},
                    synchronize_session=False,
                )
            db.commit()
            if end % 5000 == 0 or end == n_total:
                logger.info("  Atualizados %d / %d", end, n_total)
    except Exception as e:
        db.rollback()
        logger.error("Erro ao salvar scores: %s", e)
        raise
    finally:
        db.close()

    # Resumo final
    alto  = int((scores_norm >= LIMIAR_ALTO).sum())
    medio = int(((scores_norm >= LIMIAR_MEDIO) & (scores_norm < LIMIAR_ALTO)).sum())
    baixo = int((scores_norm < LIMIAR_MEDIO).sum())
    score_medio = float(scores_norm.mean())

    logger.info("=" * 55)
    logger.info("Treinamento concluido com sucesso!")
    logger.info("  Score medio geral : %.4f", score_medio)
    logger.info("  Alto risco        : %d contratos (%.1f%%)", alto,  100 * alto  / n_total)
    logger.info("  Medio risco       : %d contratos (%.1f%%)", medio, 100 * medio / n_total)
    logger.info("  Baixo risco       : %d contratos (%.1f%%)", baixo, 100 * baixo / n_total)
    logger.info("  Modelos salvos em : %s", MODELS_DIR)
    logger.info("=" * 55)


if __name__ == "__main__":
    treinar()

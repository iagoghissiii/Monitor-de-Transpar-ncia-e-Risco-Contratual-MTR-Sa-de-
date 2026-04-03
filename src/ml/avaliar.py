"""
Avaliacao completa do modelo XGBoost — MTR-Saude.

Metodologia:
    1. Gera o dataset sintetico completo (casos TCU/MPF)
    2. Divide 80% treino / 20% teste (estratificado por classe)
    3. Treina o mesmo pipeline do treinar.py no conjunto de treino
    4. Avalia no conjunto de teste (dados nunca vistos pelo modelo)
    5. Exibe: acuracia geral, precisao/recall/F1 por classe,
       matriz de confusao e os erros mais frequentes

Uso:
    python -m src.ml.avaliar
"""

import logging
import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.ensemble import IsolationForest
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix,
)
from sklearn.preprocessing import MinMaxScaler
from xgboost import XGBClassifier
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline

from src.database.postgres import SessionLocal, create_tables
from src.ml.features import carregar_features_df, FEATURE_COLS
from src.ml.dados_sinteticos import gerar_dataset, CATALOGO_TCU_MPF

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

NOMES = {0: "normal", 1: "falha_preenchimento", 2: "fraude_intencional"}
META  = 0.90   # meta de acuracia


# ── Bloco de impressao formatada ──────────────────────────────────────────────

def _separador(char="─", n=62):
    print(char * n)


def _titulo(txt):
    _separador("═")
    print(f"  {txt}")
    _separador("═")


def _secao(txt):
    print(f"\n{'─'*62}")
    print(f"  {txt}")
    print(f"{'─'*62}")


# ── Avaliacao ─────────────────────────────────────────────────────────────────

def avaliar() -> float:
    """
    Executa a avaliacao completa e retorna a acuracia geral (0-1).
    """
    _titulo("MTR-Saude — Avaliacao do Modelo de IA")

    # 1. Dataset sintetico
    print("\n[1/5] Gerando dataset sintetico (casos TCU/MPF)...")
    df_sint = gerar_dataset(n_normais=400)
    X_sint  = df_sint[FEATURE_COLS].values.astype(float)
    y_sint  = df_sint["classe"].values.astype(int)
    print(f"      Total de amostras: {len(df_sint)}")
    for cls, nome in NOMES.items():
        n = (y_sint == cls).sum()
        print(f"      {nome:25s}: {n:4d} amostras")

    # 2. Dados reais (contratos normais do banco)
    print("\n[2/5] Carregando contratos reais do banco...")
    create_tables()
    db = SessionLocal()
    try:
        df_real = carregar_features_df(db)
    finally:
        db.close()

    print(f"      {len(df_real)} contratos reais carregados.")

    # Isolation Forest nos dados reais para separar normais de suspeitos
    if_model = IsolationForest(
        n_estimators=200, contamination=0.10, random_state=42, n_jobs=-1
    )
    X_real_all = df_real[FEATURE_COLS].values.astype(float)
    if_model.fit(X_real_all)
    raw         = if_model.score_samples(X_real_all)
    scaler      = MinMaxScaler()
    scores_real = scaler.fit_transform((-raw).reshape(-1, 1)).flatten()

    mask_normal = scores_real < 0.40
    mask_alto   = scores_real >= 0.65
    X_rn = X_real_all[mask_normal]
    y_rn = np.zeros(mask_normal.sum(), dtype=int)
    X_ra = X_real_all[mask_alto]
    y_ra = np.full(mask_alto.sum(), 2, dtype=int)
    print(f"      Reais normais usados no treino : {len(X_rn)}")
    print(f"      Reais alto-risco usados no treino: {len(X_ra)}")

    # 3. Cross-validation no dataset sintetico (avaliacao isolada)
    _secao("3/5  Cross-Validation 5-Fold no Dataset Sintetico (TCU/MPF)")
    print("  (Avalia apenas com dados sinteticos — sem influencia dos reais)")

    xgb_cv = XGBClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.08,
        subsample=0.8, colsample_bytree=0.8,
        eval_metric="mlogloss", random_state=42, n_jobs=-1, verbosity=0,
    )
    skf     = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    y_cv    = cross_val_predict(xgb_cv, X_sint, y_sint, cv=skf)
    acc_cv  = accuracy_score(y_sint, y_cv)
    print(f"\n  Acuracia 5-Fold (dataset sintetico): {acc_cv*100:.1f}%")
    print(f"  Meta: {META*100:.0f}%  |  {'✅ ATINGIDA' if acc_cv >= META else '❌ Abaixo da meta'}")

    print("\n  Relatorio por classe:")
    print("  " + classification_report(
        y_sint, y_cv,
        target_names=[NOMES[i] for i in range(3)],
    ).replace("\n", "\n  "))

    # Matriz de confusao
    cm = confusion_matrix(y_sint, y_cv)
    print("  Matriz de confusao (linhas=real, colunas=previsto):")
    header = f"  {'':26s} {'normal':>8s} {'falha':>8s} {'fraude':>8s}"
    print(header)
    for i, nome in NOMES.items():
        linha = f"  {nome:26s}"
        for j in range(3):
            c = cm[i][j]
            marca = " *" if (i != j and c > 0) else "  "
            linha += f" {c:7d}{marca}"
        print(linha)

    # 4. Erros mais frequentes por padrao
    _secao("4/5  Erros por Padrao TCU/MPF")
    y_pred_map  = dict(zip(range(len(y_cv)), y_cv))
    df_sint_cpy = df_sint.copy().reset_index(drop=True)
    df_sint_cpy["y_pred"] = y_cv
    df_sint_cpy["correto"] = (df_sint_cpy["classe"] == df_sint_cpy["y_pred"])

    print(f"\n  {'Caso':<8} {'Tipo':<22} {'Amostras':>8} {'Acertos':>8} {'Acuracia':>10}")
    _separador()
    for caso in CATALOGO_TCU_MPF:
        mask = df_sint_cpy["caso_ref"] == caso["id"]
        sub  = df_sint_cpy[mask]
        if len(sub) == 0:
            continue
        acc_caso = sub["correto"].mean()
        tipo     = "FRAUDE" if caso["classe"] == 2 else "FALHA "
        indicador = "✅" if acc_caso >= META else ("⚠️ " if acc_caso >= 0.75 else "❌")
        print(f"  {caso['id']:<8} {tipo} {caso['titulo'][:18]:<18} {len(sub):>8} "
              f"{sub['correto'].sum():>8} {acc_caso*100:>9.1f}%  {indicador}")
    _separador()

    # Erros de contratos normais
    mask_norm = df_sint_cpy["caso_ref"] == "NORMAL"
    sub_norm  = df_sint_cpy[mask_norm]
    if len(sub_norm) > 0:
        acc_norm = sub_norm["correto"].mean()
        ind      = "✅" if acc_norm >= META else "❌"
        print(f"  {'NORMAL':<8} {'Normal':<22} {len(sub_norm):>8} "
              f"{sub_norm['correto'].sum():>8} {acc_norm*100:>9.1f}%  {ind}")

    # 5. Treino final com todos os dados + avaliacao no sintetico 20%
    _secao("5/5  Treino Completo (real + sintetico) — Holdout 20% Sintetico")

    from sklearn.model_selection import train_test_split
    X_tr, X_te, y_tr, y_te = train_test_split(
        X_sint, y_sint, test_size=0.20, stratify=y_sint, random_state=42
    )

    # Combina treino sintetico com dados reais
    X_full = np.vstack([X_tr, X_rn, X_ra])
    y_full = np.concatenate([y_tr, y_rn, y_ra])

    # SMOTE
    unique, counts = np.unique(y_full, return_counts=True)
    k = max(1, min(5, int(counts.min()) - 1))
    smote        = SMOTE(random_state=42, k_neighbors=k)
    X_bal, y_bal = smote.fit_resample(X_full, y_full)

    xgb_final = XGBClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.08,
        subsample=0.8, colsample_bytree=0.8,
        eval_metric="mlogloss", random_state=42, n_jobs=-1, verbosity=0,
    )
    xgb_final.fit(X_bal, y_bal)
    y_te_pred  = xgb_final.predict(X_te)
    acc_final  = accuracy_score(y_te, y_te_pred)

    print(f"\n  Acuracia holdout 20% (sintetico): {acc_final*100:.1f}%")
    print(f"  Meta: {META*100:.0f}%  |  {'✅ ATINGIDA' if acc_final >= META else '❌ Abaixo da meta'}")
    print("\n  Relatorio por classe (holdout):")
    print("  " + classification_report(
        y_te, y_te_pred,
        target_names=[NOMES[i] for i in range(3)],
    ).replace("\n", "\n  "))

    # Resumo final
    _titulo("RESUMO")
    print(f"  Acuracia 5-Fold (sintetico puro)  : {acc_cv*100:.1f}%")
    print(f"  Acuracia holdout (treino completo) : {acc_final*100:.1f}%")
    print(f"  Meta                               : {META*100:.0f}%")
    status = "✅ META ATINGIDA" if min(acc_cv, acc_final) >= META else "❌ AINDA ABAIXO DA META"
    print(f"\n  Status: {status}")

    if min(acc_cv, acc_final) < META:
        print("\n  Sugestoes para melhorar:")
        # Identifica padroes abaixo da meta
        for caso in CATALOGO_TCU_MPF:
            mask = df_sint_cpy["caso_ref"] == caso["id"]
            sub  = df_sint_cpy[mask]
            if len(sub) > 0 and sub["correto"].mean() < META:
                erros = sub[~sub["correto"]]
                preds_erradas = erros["y_pred"].value_counts().to_dict()
                pred_str = ", ".join(f"{NOMES.get(k,'?')} ({v}x)" for k, v in preds_erradas.items())
                print(f"  • {caso['id']} ({caso['titulo'][:30]}): "
                      f"confundido com → {pred_str}")
        print()

    _separador("═")
    return float(min(acc_cv, acc_final))


if __name__ == "__main__":
    acuracia = avaliar()

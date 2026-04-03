"""
Engenharia de features para o modelo de risco contratual.

Features base (Isolation Forest + XGBoost):
    log_valor           : log(valor + 1) — reduz skewness
    duracao_dias        : dias entre inicio e fim da vigencia
    qtd_concorrentes    : numero de licitantes (0 se nao informado)
    mes_inicio          : mes de inicio da vigencia (1-12)
    dia_semana_inicio   : dia da semana (0=seg ... 6=dom)
    fonte_enc           : 0=pncp / 1=portal_transparencia
    tipo_fornecedor_enc : 0=PJ / 1=PF
    modalidade_enc      : categoria da modalidade de licitacao
    log_valor_por_dia   : log(valor / duracao) — intensidade diaria
    contrato_curto      : 1 se duracao < 30 dias
    contrato_longo      : 1 se duracao > 1825 dias (5 anos)

Features TCU/MPF — diferenciam fraude de falha de preenchimento:
    valor_redondo        : 1 se valor > R$10k e divisivel por R$1.000
    sem_concorrente_alto : 1 se qtd_concorrentes==0 E valor > R$100k
    dispensa_alto_valor  : 1 se modalidade dispensa/inexigib E valor > R$50k
"""

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

# ── Lista de features (ordem importa para compatibilidade com joblib) ────────
FEATURE_COLS = [
    "log_valor",
    "duracao_dias",
    "qtd_concorrentes",
    "mes_inicio",
    "dia_semana_inicio",
    "fonte_enc",
    "tipo_fornecedor_enc",
    "modalidade_enc",
    "log_valor_por_dia",
    "contrato_curto",
    "contrato_longo",
    # Features baseadas em casos TCU/MPF
    "valor_redondo",
    "sem_concorrente_alto",
    "dispensa_alto_valor",
]

# Labels para exibicao no frontend
FEATURE_LABELS = {
    "log_valor":             "Valor do Contrato",
    "duracao_dias":          "Duracao da Vigencia (dias)",
    "qtd_concorrentes":      "Numero de Licitantes",
    "mes_inicio":            "Mes de Inicio",
    "dia_semana_inicio":     "Dia da Semana de Inicio",
    "fonte_enc":             "Fonte de Dados",
    "tipo_fornecedor_enc":   "Tipo do Fornecedor (PF/PJ)",
    "modalidade_enc":        "Modalidade de Licitacao",
    "log_valor_por_dia":     "Valor por Dia de Vigencia",
    "contrato_curto":        "Contrato de Curta Duracao (<30 dias)",
    "contrato_longo":        "Contrato de Longa Duracao (>5 anos)",
    "valor_redondo":         "Valor Redondo (multiplo de R$1.000)",
    "sem_concorrente_alto":  "Sem Concorrentes em Contrato de Alto Valor",
    "dispensa_alto_valor":   "Dispensa/Inexigibilidade com Valor Elevado",
}

# Modalidades de licitacao — codificacao ordinal
_MODALIDADES = [
    "dispensa",           # enc = 1
    "inexigibilidade",    # enc = 2
    "pregao eletronico",  # enc = 3
    "pregao",             # enc = 4
    "concorrencia",       # enc = 5
    "tomada de preco",    # enc = 6
    "convite",            # enc = 7
    "concurso",           # enc = 8
    "rdc",                # enc = 9
    "credenciamento",     # enc = 10
    "acord",              # enc = 11
]

# Limiares TCU para flags de fraude
_LIMITE_DISPENSA    = 50_000.0   # R$50k — limite legal para dispensa
_LIMITE_ALTO_VALOR  = 100_000.0  # R$100k — contrato de alto valor
_LIMITE_REDONDO_MIN = 10_000.0   # R$10k — valor minimo para checar arredondamento


def _encode_modalidade(modalidade: str | None) -> float:
    if not modalidade:
        return 0.0
    m = modalidade.lower()
    for i, token in enumerate(_MODALIDADES, start=1):
        if token in m:
            return float(i)
    return float(len(_MODALIDADES) + 1)


def extrair_features_contrato(c) -> dict:
    """
    Extrai todas as features de um ORM Contrato.
    Retorna dicionario com 'id' + todos os campos de FEATURE_COLS.
    """
    # ── Valor ────────────────────────────────────────────────────────────────
    valor = c.valor if c.valor and c.valor > 0 else 1.0

    # ── Duracao ──────────────────────────────────────────────────────────────
    if c.data_inicio and c.data_fim:
        duracao = max(1, (c.data_fim - c.data_inicio).days)
    else:
        duracao = 365

    # ── Data ─────────────────────────────────────────────────────────────────
    mes     = float(c.data_inicio.month)     if c.data_inicio else 6.0
    dia_sem = float(c.data_inicio.weekday()) if c.data_inicio else 0.0

    # ── Fonte e fornecedor ───────────────────────────────────────────────────
    fonte_enc = 0.0 if (c.fonte or "").startswith("pncp") else 1.0
    tipo_enc  = 1.0 if (c.fornecedor and c.fornecedor.tipo == "PF") else 0.0

    # ── Modalidade ───────────────────────────────────────────────────────────
    modal_enc = _encode_modalidade(c.modalidade_licitacao)

    # ── Features derivadas ───────────────────────────────────────────────────
    log_valor   = float(np.log1p(valor))
    log_vpd     = float(np.log1p(valor / duracao))

    # ── Features TCU/MPF ─────────────────────────────────────────────────────
    # 1. Valor redondo: suspeito quando valor > R$10k e divisivel por R$1.000
    valor_redondo = 1.0 if (valor >= _LIMITE_REDONDO_MIN and valor % 1_000 == 0) else 0.0

    # 2. Zero concorrentes + valor alto (FI-01, FI-04, FI-06 do catalogo TCU/MPF)
    qtd_conc = float(c.qtd_concorrentes or 0)
    sem_conc_alto = 1.0 if (qtd_conc == 0 and valor > _LIMITE_ALTO_VALOR) else 0.0

    # 3. Dispensa ou inexigibilidade com valor acima do limite legal (FI-01, FI-04)
    eh_dispensa_inexig = modal_enc in (1.0, 2.0)
    dispensa_alto = 1.0 if (eh_dispensa_inexig and valor > _LIMITE_DISPENSA) else 0.0

    return {
        "id":                    c.id,
        "log_valor":             log_valor,
        "duracao_dias":          float(duracao),
        "qtd_concorrentes":      qtd_conc,
        "mes_inicio":            mes,
        "dia_semana_inicio":     dia_sem,
        "fonte_enc":             fonte_enc,
        "tipo_fornecedor_enc":   tipo_enc,
        "modalidade_enc":        modal_enc,
        "log_valor_por_dia":     log_vpd,
        "contrato_curto":        1.0 if duracao < 30   else 0.0,
        "contrato_longo":        1.0 if duracao > 1825 else 0.0,
        "valor_redondo":         valor_redondo,
        "sem_concorrente_alto":  sem_conc_alto,
        "dispensa_alto_valor":   dispensa_alto,
    }


def carregar_features_df(db: Session) -> pd.DataFrame:
    """
    Carrega todos os contratos do banco e retorna DataFrame com todas as features.
    Inclui coluna 'id' para mapear de volta ao banco.
    """
    from src.database.postgres import Contrato, Fornecedor

    contratos = (
        db.query(Contrato)
        .outerjoin(Fornecedor, Contrato.fornecedor_id == Fornecedor.id)
        .all()
    )

    rows = [extrair_features_contrato(c) for c in contratos]
    df = pd.DataFrame(rows)
    df[FEATURE_COLS] = df[FEATURE_COLS].fillna(0.0)
    return df

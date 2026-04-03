"""
Engenharia de features para o modelo de risco contratual.

Features extraidas de cada Contrato:
    - log_valor          : log(valor + 1) — reduz skewness
    - duracao_dias       : dias entre inicio e fim da vigencia
    - qtd_concorrentes   : numero de licitantes (0 se nao informado)
    - mes_inicio         : mes do inicio da vigencia (1-12)
    - dia_semana_inicio  : dia da semana do inicio (0=seg ... 6=dom)
    - fonte_enc          : 0=pncp / 1=portal_transparencia
    - tipo_fornecedor_enc: 0=PJ / 1=PF
    - modalidade_enc     : categoria da modalidade de licitacao
    - log_valor_por_dia  : log(valor / duracao) — intensidade diaria
    - contrato_curto     : 1 se duracao < 30 dias
    - contrato_longo     : 1 se duracao > 1825 dias (5 anos)
"""

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

# Nomes de colunas usados na matriz de features (ordem importa para joblib)
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
]

# Labels legíveis para exibicao no frontend (mesma ordem de FEATURE_COLS)
FEATURE_LABELS = {
    "log_valor":           "Valor do Contrato",
    "duracao_dias":        "Duracao da Vigencia",
    "qtd_concorrentes":    "Numero de Licitantes",
    "mes_inicio":          "Mes de Inicio",
    "dia_semana_inicio":   "Dia da Semana de Inicio",
    "fonte_enc":           "Fonte de Dados",
    "tipo_fornecedor_enc": "Tipo do Fornecedor",
    "modalidade_enc":      "Modalidade de Licitacao",
    "log_valor_por_dia":   "Valor por Dia de Vigencia",
    "contrato_curto":      "Contrato de Curta Duracao",
    "contrato_longo":      "Contrato de Longa Duracao",
}

# Modalidades ordenadas por frequencia esperada no setor saude
_MODALIDADES = [
    "dispensa",
    "inexigibilidade",
    "pregao eletronico",
    "pregao",
    "concorrencia",
    "tomada de preco",
    "convite",
    "concurso",
    "rdc",
    "credenciamento",
    "acord",
]


def _encode_modalidade(modalidade: str | None) -> float:
    """Codifica modalidade em inteiro (0 = nao informada)."""
    if not modalidade:
        return 0.0
    m = modalidade.lower()
    for i, token in enumerate(_MODALIDADES, start=1):
        if token in m:
            return float(i)
    return float(len(_MODALIDADES) + 1)  # "Outros"


def extrair_features_contrato(c) -> dict:
    """
    Extrai features de um ORM Contrato (ou objeto com mesmos atributos).
    Retorna dicionario com chave 'id' + todas as FEATURE_COLS.
    """
    # Valor
    valor = c.valor if c.valor and c.valor > 0 else 1.0

    # Duracao
    if c.data_inicio and c.data_fim:
        duracao = max(1, (c.data_fim - c.data_inicio).days)
    else:
        duracao = 365  # valor padrao (1 ano)

    # Data de inicio
    mes       = float(c.data_inicio.month)    if c.data_inicio else 6.0
    dia_sem   = float(c.data_inicio.weekday()) if c.data_inicio else 0.0

    # Fonte
    fonte_enc = 0.0 if (c.fonte or "").startswith("pncp") else 1.0

    # Tipo fornecedor
    tipo_enc = 1.0 if (c.fornecedor and c.fornecedor.tipo == "PF") else 0.0

    # Features derivadas
    log_valor     = float(np.log1p(valor))
    log_vpd       = float(np.log1p(valor / duracao))

    return {
        "id":                  c.id,
        "log_valor":           log_valor,
        "duracao_dias":        float(duracao),
        "qtd_concorrentes":    float(c.qtd_concorrentes or 0),
        "mes_inicio":          mes,
        "dia_semana_inicio":   dia_sem,
        "fonte_enc":           fonte_enc,
        "tipo_fornecedor_enc": tipo_enc,
        "modalidade_enc":      _encode_modalidade(c.modalidade_licitacao),
        "log_valor_por_dia":   log_vpd,
        "contrato_curto":      1.0 if duracao < 30   else 0.0,
        "contrato_longo":      1.0 if duracao > 1825 else 0.0,
    }


def carregar_features_df(db: Session) -> pd.DataFrame:
    """
    Carrega todos os contratos do banco e retorna DataFrame com features.
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

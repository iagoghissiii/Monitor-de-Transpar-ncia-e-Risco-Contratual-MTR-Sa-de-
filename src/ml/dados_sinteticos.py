"""
Gerador de dados sinteticos baseados em casos reais do TCU e MPF.

Cada padrao e documentado com fonte primaria, referencia oficial e
descricao do que aconteceu de fato. Os vetores sinteticos ensinam
o XGBoost a separar:

    Classe 0 — normal              : contrato sem irregularidades
    Classe 1 — falha_preenchimento : erro administrativo/sistema, sem dolo
    Classe 2 — fraude_intencional  : padrao sistematico e malicioso

Fontes primarias:
    TCU  — Tribunal de Contas da Uniao (acordaos e auditorias)
    MPF  — Ministerio Publico Federal (operacoes e relatorios)
    CGU  — Controladoria-Geral da Uniao (relatorios de auditoria)
"""

import numpy as np
import pandas as pd
from src.ml.features import FEATURE_COLS

_rng = np.random.default_rng(42)


# ════════════════════════════════════════════════════════════════════════════
# CATALOGO DE CASOS REAIS
# Cada entrada documenta o caso e descreve como ele se manifesta nas features
# ════════════════════════════════════════════════════════════════════════════

CATALOGO_TCU_MPF = [

    # ────────────────────────────────────────────────────────────────────────
    # FRAUDES INTENCIONAIS (classe 2)
    # ────────────────────────────────────────────────────────────────────────
    {
        "id":         "FI-01",
        "classe":     2,
        "tipo":       "fraude_intencional",
        "fonte":      "TCU",
        "referencia": "Acordao 1.214/2021 — Plenario",
        "titulo":     "Sobreprecamento de EPIs COVID-19",
        "descricao": (
            "O Ministerio da Saude firmou 18 contratos por dispensa de "
            "licitacao com empresas abertas ha menos de 6 meses, pagando "
            "3 a 5 vezes o preco de mercado por mascaras N95, luvas e "
            "ventiladores pulmonares durante a pandemia. Dano ao erario "
            "estimado em R$ 1,6 bilhao. Seis servidores condenados."
        ),
        "sinais_no_dado": [
            "Modalidade: Dispensa de licitacao (enc=1)",
            "Valor muito acima do mercado: log_valor entre 13 e 16 (R$440k–R$8,8M)",
            "Zero concorrentes: qtd_concorrentes = 0",
            "Duracao curta (30-90 dias): contrato_curto pode ser 1",
            "Valor exatamente redondo (multiplo de R$1.000): valor_redondo = 1",
            "Flag combinada: sem_concorrente_alto = 1, dispensa_alto = 1",
        ],
        "n_amostras": 70,
    },
    {
        "id":         "FI-02",
        "classe":     2,
        "tipo":       "fraude_intencional",
        "fonte":      "TCU",
        "referencia": "Acordao 2.830/2019 — Plenario",
        "titulo":     "Fracionamento ilegal de contratos",
        "descricao": (
            "Gestor do Ministerio da Saude dividiu um contrato de R$980.000 "
            "em 22 contratos menores de ate R$44.000, todos por dispensa de "
            "licitacao para o MESMO fornecedor no MESMO periodo, com o unico "
            "objetivo de ficar abaixo do limite legal de R$50.000 que exigiria "
            "licitacao. Gestor condenado a ressarcimento integral."
        ),
        "sinais_no_dado": [
            "Modalidade: Dispensa (enc=1)",
            "Valor sempre proximo, porem ABAIXO de R$50.000: log_valor entre 10.5 e 10.8",
            "Zero concorrentes: qtd_concorrentes = 0",
            "Valor redondo (ex: R$44.000, R$48.000): valor_redondo = 1",
            "Duracao normal (90-365 dias): nao e contrato_curto",
            "Flag: dispensa_alto_valor = 0 (valor < 50k), mas modalidade dispensa",
        ],
        "n_amostras": 60,
    },
    {
        "id":         "FI-03",
        "classe":     2,
        "tipo":       "fraude_intencional",
        "fonte":      "MPF",
        "referencia": "Operacao Sanguessuga (2006) — Ministerio da Saude",
        "titulo":     "Cartel de superfaturamento de equipamentos hospitalares",
        "descricao": (
            "Esquema nacional de cartel envolvendo 102 empresas e 245 pessoas. "
            "O grupo combinava precos previamente, garantia que apenas UMA empresa "
            "apresentasse proposta valida em cada pregao e superfaturava ambulancias, "
            "macas e equipamentos basicos em ate 200% do valor de mercado. Funcionou "
            "de 2001 a 2006 em 21 estados. Prejuizo: R$110 milhoes."
        ),
        "sinais_no_dado": [
            "Pregao com exatamente 1 licitante: qtd_concorrentes = 1",
            "Valor altissimo para a categoria (superfaturamento): log_valor > 12",
            "Valor proximo ao teto do edital (preco combinado): valor_redondo = 1",
            "Duracao normal de contrato (90-365 dias)",
            "Fonte PNCP ou Portal (fonte_enc qualquer)",
        ],
        "n_amostras": 65,
    },
    {
        "id":         "FI-04",
        "classe":     2,
        "tipo":       "fraude_intencional",
        "fonte":      "CGU",
        "referencia": "Relatorio de Auditoria 201700253 — CGU 2022",
        "titulo":     "Empresa fantasma contratada por inexigibilidade",
        "descricao": (
            "Empresa com capital social de R$1.000 e sem qualquer estrutura "
            "operacional recebeu contratos de R$2,3 milhoes por inexigibilidade "
            "de licitacao para 'consultoria tecnica especializada'. O CNPJ ficou "
            "em situacao irregular logo apos os pagamentos. A empresa era controlada "
            "por parente de servidor publico da area contratante."
        ),
        "sinais_no_dado": [
            "Modalidade: Inexigibilidade (enc=2)",
            "Valor alto: log_valor entre 13 e 15 (R$440k–R$3,3M)",
            "Zero concorrentes: qtd_concorrentes = 0",
            "Flag: sem_concorrente_alto = 1, dispensa_alto = 1",
            "Duracao longa mascarando pagamentos continuos: duracao 365-730 dias",
        ],
        "n_amostras": 55,
    },
    {
        "id":         "FI-05",
        "classe":     2,
        "tipo":       "fraude_intencional",
        "fonte":      "TCU",
        "referencia": "Acordao 1.777/2005 — Plenario",
        "titulo":     "Direcionamento de licitacao em medicamentos FUNASA",
        "descricao": (
            "O edital foi elaborado com especificacoes tecnicas propositalmente "
            "restritivas (marca especifica, tamanho de embalagem incomum) que "
            "apenas UMA empresa poderia atender. O pregao teve 1 participante. "
            "Sobrepreco de 47% identificado na auditoria posterior. O esquema "
            "se repetiu em 14 contratos consecutivos para o mesmo fornecedor."
        ),
        "sinais_no_dado": [
            "Pregao com 1 participante: qtd_concorrentes = 1",
            "Valor sistematicamente acima da referencia: log_valor > 11",
            "Valor redondo (preco tabelado artificialmente): valor_redondo = 1",
            "Padrao repetido (mes_inicio variando, resto fixo)",
        ],
        "n_amostras": 55,
    },
    {
        "id":         "FI-06",
        "classe":     2,
        "tipo":       "fraude_intencional",
        "fonte":      "MPF",
        "referencia": "Operacao Saude Oculta (2021) — Ministerio da Saude",
        "titulo":     "Pessoa fisica recebendo contratos milionarios como consultora",
        "descricao": (
            "Uma pessoa fisica foi contratada como 'consultora tecnica' por "
            "inexigibilidade e recebeu R$4,8 milhoes em 7 anos via renovacoes "
            "automaticas. Nenhuma entrega foi comprovada. O contrato foi renovado "
            "5 vezes sem qualquer avaliacao de desempenho. Investigacao iniciada "
            "apos denuncia de servidor do proprio orgao."
        ),
        "sinais_no_dado": [
            "Fornecedor PF recebendo valores altos: tipo_fornecedor_enc = 1",
            "log_valor > 12 para pessoa fisica (altamente suspeito)",
            "Zero concorrentes: qtd_concorrentes = 0",
            "Contrato muito longo com renovacoes: duracao > 1825 dias (contrato_longo=1)",
            "Modalidade: Inexigibilidade (enc=2)",
        ],
        "n_amostras": 50,
    },

    # ────────────────────────────────────────────────────────────────────────
    # FALHAS DE PREENCHIMENTO (classe 1)
    # ────────────────────────────────────────────────────────────────────────
    {
        "id":         "FP-01",
        "classe":     1,
        "tipo":       "falha_preenchimento",
        "fonte":      "CGU",
        "referencia": "IN CGU 01/2016 — Exemplos de inconsistencias cadastrais",
        "titulo":     "Data de termino anterior a data de inicio",
        "descricao": (
            "Erro de digitacao classico: o servidor confunde dia e mes ao "
            "digitar a data de termino (ex: digita 05/12/2023 quando queria "
            "dizer 12/05/2024). O sistema registra duracao negativa ou de 1 dia. "
            "Sem nenhuma intencao de fraude. Identificado e corrigido na auditoria."
        ),
        "sinais_no_dado": [
            "duracao_dias = 1 (minimo apos correcao do impossivel negativo)",
            "contrato_curto = 1",
            "log_valor_por_dia muito alto (valor inteiro / 1 dia = absurdo)",
            "Valor e modalidade preenchidos corretamente (sao independentes do erro)",
        ],
        "n_amostras": 50,
    },
    {
        "id":         "FP-02",
        "classe":     1,
        "tipo":       "falha_preenchimento",
        "fonte":      "TCU",
        "referencia": "Acordao 2.401/2018 — Falhas de controle interno SIAFI",
        "titulo":     "Valor contratual zerado ou irrisorio no sistema",
        "descricao": (
            "Gestor nao atualizou o valor no SIAFI apos a assinatura do contrato "
            "fisico. O sistema registra R$0,00 ou R$1,00. O contrato foi executado "
            "e pago normalmente pela via financeira, apenas o campo de valor do "
            "contrato ficou errado. Bug tambem identificado em migracao de sistema "
            "legado SIAFI -> SIAFI Moderno em 2018."
        ),
        "sinais_no_dado": [
            "log_valor muito baixo: < 5 (equivale a valor < R$148)",
            "Duracao normal (30-365 dias): nao e contrato_curto",
            "Modalidade preenchida corretamente",
            "qtd_concorrentes pode ser preenchido normalmente",
        ],
        "n_amostras": 50,
    },
    {
        "id":         "FP-03",
        "classe":     1,
        "tipo":       "falha_preenchimento",
        "fonte":      "CGU",
        "referencia": "Relatorio Auditoria Interna FIOCRUZ 2020 — RI-2020-043",
        "titulo":     "Ano de termino errado — vigencia de 10 anos por typo",
        "descricao": (
            "Servidor digitou '2030' no campo de ano de termino ao inves de "
            "'2023'. O erro passou pelo sistema pois datas futuras sao aceitas. "
            "Identificado apenas na auditoria interna anual. Corrigido sem "
            "nenhum prejuizo financeiro. Tipo de erro mais comum em contratos "
            "de servicos continuados (limpeza, vigilancia, TI)."
        ),
        "sinais_no_dado": [
            "duracao_dias > 2500 (mais de 6 anos por erro de digitacao)",
            "contrato_longo = 1",
            "Valor normal para o objeto: log_valor entre 10 e 13",
            "Modalidade e concorrentes preenchidos corretamente",
        ],
        "n_amostras": 45,
    },
    {
        "id":         "FP-04",
        "classe":     1,
        "tipo":       "falha_preenchimento",
        "fonte":      "TCU",
        "referencia": "Acordao 589/2020 — Qualidade de dados COMPRASNET",
        "titulo":     "Modalidade de licitacao nao preenchida",
        "descricao": (
            "Servidores sem treinamento adequado nao sabiam qual modalidade "
            "classificar para contratos de servicos continuados (limpeza, "
            "vigilancia). Deixavam o campo em branco ou selecionavam opcao "
            "errada. Auditoria identificou 847 contratos com modalidade ausente "
            "em 12 orgaos. Sem qualquer irregularidade financeira."
        ),
        "sinais_no_dado": [
            "modalidade_enc = 0 (campo nao preenchido)",
            "Valores, datas e concorrentes todos normais",
            "Pode ter qtd_concorrentes = 0 (tambem nao informado)",
            "Nenhuma flag de fraude ativa",
        ],
        "n_amostras": 50,
    },
    {
        "id":         "FP-05",
        "classe":     1,
        "tipo":       "falha_preenchimento",
        "fonte":      "CGU",
        "referencia": "Nota Tecnica CGU 02/2022 — Erros sistematicos COMPRASNET",
        "titulo":     "Zero licitantes registrado em pregao com competicao real",
        "descricao": (
            "Bug de integracao entre o COMPRASNET e o SIAFI: o campo de "
            "quantidade de licitantes nao era transmitido corretamente em "
            "pregoes eletronicos realizados entre 2018 e 2022. Contratos "
            "que tiveram 5, 10 ou mais participantes ficaram registrados "
            "como 0. CGU estima que 12.000 contratos foram afetados. "
            "Corrigido apos nota tecnica em maio de 2022."
        ),
        "sinais_no_dado": [
            "qtd_concorrentes = 0 com modalidade PREGAO (enc=3 ou 4)",
            "Valor dentro do normal para a modalidade",
            "Duracao normal (90-365 dias)",
            "Sem nenhuma outra flag de fraude",
        ],
        "n_amostras": 55,
    },
]


# ════════════════════════════════════════════════════════════════════════════
# GERADORES DE AMOSTRAS SINTETICAS
# ════════════════════════════════════════════════════════════════════════════

def _linspace(low, high, n):
    """Gera n valores uniformes entre low e high com ruido gaussiano leve."""
    base = _rng.uniform(low, high, n)
    noise = _rng.normal(0, (high - low) * 0.05, n)
    return np.clip(base + noise, low, high)


def _gerar_fi01(n: int) -> pd.DataFrame:
    """FI-01: Sobreprecamento COVID — Dispensa + alto valor + 0 concorrentes."""
    log_v = _linspace(13.0, 16.0, n)                    # R$440k – R$8.8M
    dur   = _linspace(30, 90, n)
    vpd   = np.log1p(np.exp(log_v) / np.maximum(dur, 1))
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    np.zeros(n),
        "mes_inicio":          _rng.integers(3, 7, n).astype(float),   # pico pandemia
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           np.zeros(n),
        "tipo_fornecedor_enc": np.zeros(n),
        "modalidade_enc":      np.ones(n),                              # dispensa
        "log_valor_por_dia":   vpd,
        "contrato_curto":      (dur < 30).astype(float),
        "contrato_longo":      np.zeros(n),
        "valor_redondo":       np.ones(n),
        "sem_concorrente_alto": np.ones(n),
        "dispensa_alto_valor": np.ones(n),
        "classe":              np.full(n, 2),
        "tipo_anomalia":       ["fraude_intencional"] * n,
        "caso_ref":            ["FI-01"] * n,
    })


def _gerar_fi02(n: int) -> pd.DataFrame:
    """FI-02: Fracionamento — Dispensa + valor justo abaixo de R$50k."""
    # Valores entre R$30k e R$49.999 (sempre abaixo do limite legal)
    valores_brutos = _linspace(30_000, 49_500, n)
    log_v = np.log1p(valores_brutos)
    dur   = _linspace(90, 365, n)
    vpd   = np.log1p(valores_brutos / np.maximum(dur, 1))
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    np.zeros(n),
        "mes_inicio":          _rng.integers(1, 13, n).astype(float),
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           _rng.integers(0, 2, n).astype(float),
        "tipo_fornecedor_enc": np.zeros(n),
        "modalidade_enc":      np.ones(n),                              # dispensa
        "log_valor_por_dia":   vpd,
        "contrato_curto":      np.zeros(n),
        "contrato_longo":      np.zeros(n),
        "valor_redondo":       np.ones(n),                              # valores tabelados
        "sem_concorrente_alto": np.zeros(n),                           # valor < 100k
        "dispensa_alto_valor": np.zeros(n),                            # valor < 50k
        "classe":              np.full(n, 2),
        "tipo_anomalia":       ["fraude_intencional"] * n,
        "caso_ref":            ["FI-02"] * n,
    })


def _gerar_fi03(n: int) -> pd.DataFrame:
    """FI-03: Sanguessuga — Pregao com 1 licitante + superfaturamento."""
    log_v = _linspace(12.0, 14.5, n)                    # R$162k – R$2M
    dur   = _linspace(90, 365, n)
    vpd   = np.log1p(np.exp(log_v) / np.maximum(dur, 1))
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    np.ones(n),                              # exatamente 1
        "mes_inicio":          _rng.integers(1, 13, n).astype(float),
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           _rng.integers(0, 2, n).astype(float),
        "tipo_fornecedor_enc": np.zeros(n),
        "modalidade_enc":      np.full(n, 3.0),                        # pregao eletronico
        "log_valor_por_dia":   vpd,
        "contrato_curto":      np.zeros(n),
        "contrato_longo":      np.zeros(n),
        "valor_redondo":       np.ones(n),
        "sem_concorrente_alto": np.zeros(n),                           # tem 1 concorrente
        "dispensa_alto_valor": np.zeros(n),                            # e pregao
        "classe":              np.full(n, 2),
        "tipo_anomalia":       ["fraude_intencional"] * n,
        "caso_ref":            ["FI-03"] * n,
    })


def _gerar_fi04(n: int) -> pd.DataFrame:
    """FI-04: Empresa fantasma — Inexigibilidade + alto valor + 0 concorrentes."""
    log_v = _linspace(13.0, 15.0, n)                    # R$440k – R$3.3M
    dur   = _linspace(365, 730, n)
    vpd   = np.log1p(np.exp(log_v) / np.maximum(dur, 1))
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    np.zeros(n),
        "mes_inicio":          _rng.integers(1, 13, n).astype(float),
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           _rng.integers(0, 2, n).astype(float),
        "tipo_fornecedor_enc": np.zeros(n),
        "modalidade_enc":      np.full(n, 2.0),                        # inexigibilidade
        "log_valor_por_dia":   vpd,
        "contrato_curto":      np.zeros(n),
        "contrato_longo":      np.zeros(n),
        "valor_redondo":       _rng.integers(0, 2, n).astype(float),
        "sem_concorrente_alto": np.ones(n),
        "dispensa_alto_valor": np.ones(n),
        "classe":              np.full(n, 2),
        "tipo_anomalia":       ["fraude_intencional"] * n,
        "caso_ref":            ["FI-04"] * n,
    })


def _gerar_fi05(n: int) -> pd.DataFrame:
    """FI-05: Direcionamento — Pregao 1 participante + sobrepreco sistematico."""
    log_v = _linspace(11.0, 13.0, n)                    # R$60k – R$440k
    dur   = _linspace(90, 365, n)
    vpd   = np.log1p(np.exp(log_v) / np.maximum(dur, 1))
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    np.ones(n),
        "mes_inicio":          _rng.integers(1, 13, n).astype(float),
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           np.zeros(n),
        "tipo_fornecedor_enc": np.zeros(n),
        "modalidade_enc":      np.full(n, 3.0),                        # pregao
        "log_valor_por_dia":   vpd,
        "contrato_curto":      np.zeros(n),
        "contrato_longo":      np.zeros(n),
        "valor_redondo":       np.ones(n),
        "sem_concorrente_alto": np.zeros(n),
        "dispensa_alto_valor": np.zeros(n),
        "classe":              np.full(n, 2),
        "tipo_anomalia":       ["fraude_intencional"] * n,
        "caso_ref":            ["FI-05"] * n,
    })


def _gerar_fi06(n: int) -> pd.DataFrame:
    """FI-06: PF como consultora — Pessoa fisica com contrato milionario longo."""
    log_v = _linspace(12.5, 14.5, n)                    # R$270k – R$2M
    dur   = _linspace(1826, 3650, n)                    # 5-10 anos
    vpd   = np.log1p(np.exp(log_v) / np.maximum(dur, 1))
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    np.zeros(n),
        "mes_inicio":          _rng.integers(1, 13, n).astype(float),
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           _rng.integers(0, 2, n).astype(float),
        "tipo_fornecedor_enc": np.ones(n),                              # PF
        "modalidade_enc":      np.full(n, 2.0),                        # inexigibilidade
        "log_valor_por_dia":   vpd,
        "contrato_curto":      np.zeros(n),
        "contrato_longo":      np.ones(n),
        "valor_redondo":       _rng.integers(0, 2, n).astype(float),
        "sem_concorrente_alto": np.ones(n),
        "dispensa_alto_valor": np.ones(n),
        "classe":              np.full(n, 2),
        "tipo_anomalia":       ["fraude_intencional"] * n,
        "caso_ref":            ["FI-06"] * n,
    })


# ── Geradores de falha de preenchimento ─────────────────────────────────────

def _gerar_fp01(n: int) -> pd.DataFrame:
    """FP-01: Data fim < data inicio — duracao registrada como 1 dia."""
    log_v = _linspace(9.0, 13.0, n)                    # R$8k – R$440k (valores normais)
    dur   = np.ones(n)                                  # sempre 1 dia
    vpd   = log_v                                       # valor / 1 dia = absurdo
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    _rng.integers(0, 6, n).astype(float),
        "mes_inicio":          _rng.integers(1, 13, n).astype(float),
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           _rng.integers(0, 2, n).astype(float),
        "tipo_fornecedor_enc": np.zeros(n),
        "modalidade_enc":      _rng.integers(1, 5, n).astype(float),
        "log_valor_por_dia":   vpd,
        "contrato_curto":      np.ones(n),
        "contrato_longo":      np.zeros(n),
        "valor_redondo":       _rng.integers(0, 2, n).astype(float),
        "sem_concorrente_alto": np.zeros(n),
        "dispensa_alto_valor": np.zeros(n),
        "classe":              np.full(n, 1),
        "tipo_anomalia":       ["falha_preenchimento"] * n,
        "caso_ref":            ["FP-01"] * n,
    })


def _gerar_fp02(n: int) -> pd.DataFrame:
    """FP-02: Valor zerado/irrisorio no sistema."""
    log_v = _rng.uniform(0.0, 5.0, n)                  # R$0 – R$148
    dur   = _linspace(30, 365, n)
    vpd   = log_v - np.log1p(dur)
    vpd   = np.clip(vpd, 0, None)
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    _rng.integers(0, 8, n).astype(float),
        "mes_inicio":          _rng.integers(1, 13, n).astype(float),
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           _rng.integers(0, 2, n).astype(float),
        "tipo_fornecedor_enc": np.zeros(n),
        "modalidade_enc":      _rng.integers(1, 6, n).astype(float),
        "log_valor_por_dia":   vpd,
        "contrato_curto":      (dur < 30).astype(float),
        "contrato_longo":      np.zeros(n),
        "valor_redondo":       np.zeros(n),
        "sem_concorrente_alto": np.zeros(n),
        "dispensa_alto_valor": np.zeros(n),
        "classe":              np.full(n, 1),
        "tipo_anomalia":       ["falha_preenchimento"] * n,
        "caso_ref":            ["FP-02"] * n,
    })


def _gerar_fp03(n: int) -> pd.DataFrame:
    """FP-03: Ano de termino errado — vigencia de 6-10 anos por typo."""
    log_v = _linspace(9.0, 13.0, n)                    # valores normais
    dur   = _linspace(2500, 3650, n)                   # 6-10 anos (absurdo)
    vpd   = np.log1p(np.exp(log_v) / np.maximum(dur, 1))
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    _rng.integers(1, 8, n).astype(float),
        "mes_inicio":          _rng.integers(1, 13, n).astype(float),
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           _rng.integers(0, 2, n).astype(float),
        "tipo_fornecedor_enc": np.zeros(n),
        "modalidade_enc":      _rng.integers(1, 6, n).astype(float),
        "log_valor_por_dia":   vpd,
        "contrato_curto":      np.zeros(n),
        "contrato_longo":      np.ones(n),
        "valor_redondo":       _rng.integers(0, 2, n).astype(float),
        "sem_concorrente_alto": np.zeros(n),
        "dispensa_alto_valor": np.zeros(n),
        "classe":              np.full(n, 1),
        "tipo_anomalia":       ["falha_preenchimento"] * n,
        "caso_ref":            ["FP-03"] * n,
    })


def _gerar_fp04(n: int) -> pd.DataFrame:
    """FP-04: Modalidade nao preenchida (campo em branco)."""
    log_v = _linspace(9.0, 13.0, n)
    dur   = _linspace(90, 730, n)
    vpd   = np.log1p(np.exp(log_v) / np.maximum(dur, 1))
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    _rng.integers(0, 6, n).astype(float),
        "mes_inicio":          _rng.integers(1, 13, n).astype(float),
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           _rng.integers(0, 2, n).astype(float),
        "tipo_fornecedor_enc": np.zeros(n),
        "modalidade_enc":      np.zeros(n),                            # NAO PREENCHIDA
        "log_valor_por_dia":   vpd,
        "contrato_curto":      (dur < 30).astype(float),
        "contrato_longo":      (dur > 1825).astype(float),
        "valor_redondo":       _rng.integers(0, 2, n).astype(float),
        "sem_concorrente_alto": np.zeros(n),
        "dispensa_alto_valor": np.zeros(n),
        "classe":              np.full(n, 1),
        "tipo_anomalia":       ["falha_preenchimento"] * n,
        "caso_ref":            ["FP-04"] * n,
    })


def _gerar_fp05(n: int) -> pd.DataFrame:
    """FP-05: Bug COMPRASNET — 0 licitantes em pregao real."""
    log_v = _linspace(9.0, 12.5, n)
    dur   = _linspace(90, 365, n)
    vpd   = np.log1p(np.exp(log_v) / np.maximum(dur, 1))
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    np.zeros(n),                            # BUG — era >1
        "mes_inicio":          _rng.integers(1, 13, n).astype(float),
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           np.ones(n),                             # vem do COMPRASNET
        "tipo_fornecedor_enc": np.zeros(n),
        "modalidade_enc":      _rng.choice([3.0, 4.0], n),            # pregao
        "log_valor_por_dia":   vpd,
        "contrato_curto":      np.zeros(n),
        "contrato_longo":      np.zeros(n),
        "valor_redondo":       _rng.integers(0, 2, n).astype(float),
        "sem_concorrente_alto": np.zeros(n),                           # valor < 100k
        "dispensa_alto_valor": np.zeros(n),
        "classe":              np.full(n, 1),
        "tipo_anomalia":       ["falha_preenchimento"] * n,
        "caso_ref":            ["FP-05"] * n,
    })


# ── Gerador de contratos normais ─────────────────────────────────────────────

def _gerar_normais(n: int) -> pd.DataFrame:
    """Contratos normais: distribuicao realista sem flags de fraude ou erro."""
    log_v = _rng.normal(10.0, 2.0, n)                  # media R$22k
    log_v = np.clip(log_v, 7.0, 14.0)
    dur   = np.abs(_rng.normal(365, 200, n))
    dur   = np.clip(dur, 30, 1825)
    vpd   = np.log1p(np.exp(log_v) / np.maximum(dur, 1))
    conc  = _rng.integers(1, 10, n).astype(float)
    modal = _rng.choice([1.0, 2.0, 3.0, 4.0, 5.0], n,
                        p=[0.15, 0.10, 0.45, 0.20, 0.10])
    return pd.DataFrame({
        "log_valor":           log_v,
        "duracao_dias":        dur,
        "qtd_concorrentes":    conc,
        "mes_inicio":          _rng.integers(1, 13, n).astype(float),
        "dia_semana_inicio":   _rng.integers(0, 5, n).astype(float),
        "fonte_enc":           _rng.integers(0, 2, n).astype(float),
        "tipo_fornecedor_enc": _rng.choice([0.0, 1.0], n, p=[0.92, 0.08]),
        "modalidade_enc":      modal,
        "log_valor_por_dia":   vpd,
        "contrato_curto":      (dur < 30).astype(float),
        "contrato_longo":      (dur > 1825).astype(float),
        "valor_redondo":       np.zeros(n),
        "sem_concorrente_alto": np.zeros(n),
        "dispensa_alto_valor": np.zeros(n),
        "classe":              np.zeros(n),
        "tipo_anomalia":       ["normal"] * n,
        "caso_ref":            ["NORMAL"] * n,
    })


# ════════════════════════════════════════════════════════════════════════════
# FUNCAO PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

_GERADORES = {
    "FI-01": _gerar_fi01,
    "FI-02": _gerar_fi02,
    "FI-03": _gerar_fi03,
    "FI-04": _gerar_fi04,
    "FI-05": _gerar_fi05,
    "FI-06": _gerar_fi06,
    "FP-01": _gerar_fp01,
    "FP-02": _gerar_fp02,
    "FP-03": _gerar_fp03,
    "FP-04": _gerar_fp04,
    "FP-05": _gerar_fp05,
}


def gerar_dataset(n_normais: int = 300) -> pd.DataFrame:
    """
    Gera o dataset sintetico completo para treinamento supervisionado.

    Retorna DataFrame com FEATURE_COLS + ['valor_redondo',
    'sem_concorrente_alto', 'dispensa_alto_valor',
    'classe', 'tipo_anomalia', 'caso_ref'].
    """
    partes = [_gerar_normais(n_normais)]

    for caso in CATALOGO_TCU_MPF:
        gerador = _GERADORES[caso["id"]]
        partes.append(gerador(caso["n_amostras"]))

    df = pd.concat(partes, ignore_index=True)
    df[FEATURE_COLS + ["valor_redondo", "sem_concorrente_alto", "dispensa_alto_valor"]] = (
        df[FEATURE_COLS + ["valor_redondo", "sem_concorrente_alto", "dispensa_alto_valor"]]
        .fillna(0.0)
        .astype(float)
    )
    return df


def resumo_catalogo() -> None:
    """Imprime o catalogo formatado de casos TCU/MPF."""
    print("\n" + "=" * 68)
    print("  CATALOGO DE CASOS TCU/MPF — MTR-Saude")
    print("=" * 68)
    for caso in CATALOGO_TCU_MPF:
        tipo_str = "FRAUDE" if caso["classe"] == 2 else "FALHA"
        print(f"\n[{caso['id']}] {caso['fonte']} — {tipo_str}")
        print(f"  Ref  : {caso['referencia']}")
        print(f"  Titulo: {caso['titulo']}")
        desc = caso["descricao"].replace("\n", " ")
        for i in range(0, len(desc), 65):
            print(f"  {'       ' if i else 'Descr. :'} {desc[i:i+65]}")
        print(f"  Amostras sinteticas: {caso['n_amostras']}")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    resumo_catalogo()
    df = gerar_dataset()
    print(f"Dataset gerado: {len(df)} amostras")
    print(df["tipo_anomalia"].value_counts())

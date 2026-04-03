"""Cliente BrasilAPI — enriquecimento de dados cadastrais via CNPJ."""

import re
import time
import logging
from datetime import date

import requests

from src.utils.config import settings

logger = logging.getLogger(__name__)

DELAY = 0.3       # segundos entre chamadas
MAX_RETRIES = 3

_cache: dict[str, dict] = {}   # cache em memória para evitar chamadas repetidas


def _limpar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


def buscar_cnpj(cnpj: str) -> dict:
    """
    Retorna dados cadastrais do CNPJ via BrasilAPI.
    Em caso de erro, retorna dict vazio.
    Campos úteis: situacao_cadastral, data_inicio_atividade, capital_social.
    """
    cnpj_limpo = _limpar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        return {}

    if cnpj_limpo in _cache:
        return _cache[cnpj_limpo]

    url = f"{settings.BRASIL_API_URL}/{cnpj_limpo}"
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                dados = resp.json()
                _cache[cnpj_limpo] = dados
                time.sleep(DELAY)
                return dados
            if resp.status_code in (404, 400):
                _cache[cnpj_limpo] = {}
                return {}
            if resp.status_code == 429:
                logger.warning("BrasilAPI rate limit — aguardando 5s...")
                time.sleep(5)
                continue
        except requests.RequestException as exc:
            logger.warning("Erro BrasilAPI (tentativa %d): %s", tentativa, exc)
            time.sleep(2 * tentativa)

    _cache[cnpj_limpo] = {}
    return {}


def extrair_dados_risco(dados_cnpj: dict) -> dict:
    """
    Extrai os campos relevantes para o modelo de risco a partir do retorno da BrasilAPI.
    Retorna dict com campos padronizados.
    """
    if not dados_cnpj:
        return {
            "situacao_cadastral": None,
            "data_abertura": None,
            "capital_social": None,
            "idade_empresa_dias": None,
            "empresa_ativa": False,
            "empresa_recente": None,
            "capital_zero": None,
        }

    situacao = dados_cnpj.get("descricao_situacao_cadastral", "").upper()
    data_abertura_str = dados_cnpj.get("data_inicio_atividade")  # "YYYY-MM-DD"
    capital_social = dados_cnpj.get("capital_social", 0) or 0

    data_abertura = None
    idade_dias = None
    empresa_recente = None

    if data_abertura_str:
        try:
            data_abertura = date.fromisoformat(data_abertura_str)
            hoje = date.today()
            idade_dias = (hoje - data_abertura).days
            empresa_recente = idade_dias < 180  # menos de 6 meses
        except ValueError:
            pass

    return {
        "situacao_cadastral": situacao,
        "data_abertura": data_abertura,
        "capital_social": float(capital_social),
        "idade_empresa_dias": idade_dias,
        "empresa_ativa": situacao == "ATIVA",
        "empresa_recente": empresa_recente,
        "capital_zero": capital_social == 0,
    }

"""Cliente para a API do Portal da Transparência — contratos públicos."""

import time
import logging
from typing import Generator
from datetime import date

import requests

from src.utils.config import settings

logger = logging.getLogger(__name__)

# Códigos SIAFI dos órgãos monitorados
ORGAOS_SAUDE = {
    "36000": {"nome": "Ministério da Saúde", "sigla": "MS"},
    "36201": {"nome": "Fundação Oswaldo Cruz", "sigla": "FIOCRUZ"},
    "36206": {"nome": "Agência Nacional de Vigilância Sanitária", "sigla": "ANVISA"},
    "36216": {"nome": "Agência Nacional de Saúde Suplementar", "sigla": "ANS"},
    "36205": {"nome": "Fundação Nacional de Saúde", "sigla": "FUNASA"},
}

PAGE_SIZE = 500          # máximo permitido pela API
DELAY_ENTRE_PAGINAS = 0.4   # segundos entre requisições
DELAY_ENTRE_ORGAOS = 1.0    # segundos entre órgãos
MAX_RETRIES = 3


class PortalClient:
    """Faz paginação automática e retorna cada contrato como dict bruto."""

    def __init__(self) -> None:
        if not settings.PORTAL_API_KEY:
            raise ValueError("PORTAL_API_KEY não configurada no .env")
        self._session = requests.Session()
        self._session.headers.update({
            "chave-api-dados": settings.PORTAL_API_KEY,
            "Accept": "application/json",
        })

    def _get(self, endpoint: str, params: dict) -> list[dict]:
        url = f"{settings.PORTAL_BASE_URL}/{endpoint}"
        for tentativa in range(1, MAX_RETRIES + 1):
            try:
                resp = self._session.get(url, params=params, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 404:
                    return []
                if resp.status_code == 429:
                    logger.warning("Rate limit atingido — aguardando 10s...")
                    time.sleep(10)
                    continue
                logger.warning("HTTP %s em %s (tentativa %d)", resp.status_code, url, tentativa)
            except requests.RequestException as exc:
                logger.warning("Erro de rede (tentativa %d): %s", tentativa, exc)
                time.sleep(2 * tentativa)
        return []

    def buscar_contratos(
        self,
        codigo_orgao: str,
        data_inicio: date,
        data_fim: date,
    ) -> Generator[dict, None, None]:
        """Gera contratos paginados de um órgão no período informado."""
        params_base = {
            "codigoOrgao": codigo_orgao,
            "dataInicio": data_inicio.strftime("%d/%m/%Y"),
            "dataFim": data_fim.strftime("%d/%m/%Y"),
            "tamanhoPagina": PAGE_SIZE,
        }
        pagina = 1
        total_retornado = 0

        while True:
            params = {**params_base, "pagina": pagina}
            logger.debug("Buscando órgão %s — página %d", codigo_orgao, pagina)

            dados = self._get("contratos", params)
            if not dados:
                break

            for contrato in dados:
                yield contrato
                total_retornado += 1

            if len(dados) < PAGE_SIZE:
                break  # última página

            pagina += 1
            time.sleep(DELAY_ENTRE_PAGINAS)

        logger.info(
            "Órgão %s: %d contratos coletados (%s → %s)",
            codigo_orgao, total_retornado,
            data_inicio.strftime("%d/%m/%Y"),
            data_fim.strftime("%d/%m/%Y"),
        )

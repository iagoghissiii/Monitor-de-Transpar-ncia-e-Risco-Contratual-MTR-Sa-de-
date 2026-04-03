"""Cliente para a API do PNCP (Portal Nacional de Contratações Públicas)."""

import time
import logging
from typing import Generator
from datetime import date

import requests

logger = logging.getLogger(__name__)

PNCP_BASE_URL = "https://pncp.gov.br/api/consulta/v1"
PAGE_SIZE = 500
DELAY_ENTRE_PAGINAS = 0.4
MAX_RETRIES = 3

# Órgãos monitorados: nome → CNPJ (identificado via PNCP)
ORGAOS_PNCP = {
    "00394544000185": {"nome": "Ministério da Saúde", "sigla": "MS"},
    "33781055000135": {"nome": "Fundação Oswaldo Cruz", "sigla": "FIOCRUZ"},
    "26989350000116": {"nome": "Fundação Nacional de Saúde", "sigla": "FUNASA"},
}


class PncpClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    def _get(self, endpoint: str, params: dict) -> dict:
        url = f"{PNCP_BASE_URL}/{endpoint}"
        for tentativa in range(1, MAX_RETRIES + 1):
            try:
                resp = self._session.get(url, params=params, timeout=60)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429:
                    logger.warning("Rate limit PNCP — aguardando 10s...")
                    time.sleep(10)
                    continue
                logger.warning("HTTP %s em %s (tentativa %d)", resp.status_code, url, tentativa)
                return {}
            except requests.RequestException as exc:
                logger.warning("Erro de rede PNCP (tentativa %d): %s", tentativa, exc)
                time.sleep(3 * tentativa)
        return {}

    def buscar_contratos(
        self,
        cnpj_orgao: str,
        data_inicio: date,
        data_fim: date,
    ) -> Generator[dict, None, None]:
        """
        Gera contratos paginados de um órgão no período informado.
        A API do PNCP limita a janela máxima a 365 dias.
        """
        params_base = {
            "cnpjOrgao": cnpj_orgao,
            "dataInicial": data_inicio.strftime("%Y%m%d"),
            "dataFinal": data_fim.strftime("%Y%m%d"),
            "tamanhoPagina": PAGE_SIZE,
        }
        pagina = 1
        total_retornado = 0

        while True:
            params = {**params_base, "pagina": pagina}
            dados = self._get("contratos", params)
            itens = dados.get("data", [])

            if not itens:
                break

            for contrato in itens:
                yield contrato
                total_retornado += 1

            total_paginas = dados.get("totalPaginas", 1)
            if pagina >= total_paginas:
                break

            pagina += 1
            time.sleep(DELAY_ENTRE_PAGINAS)

        logger.info(
            "PNCP %s: %d contratos coletados (%s → %s)",
            cnpj_orgao, total_retornado,
            data_inicio.strftime("%d/%m/%Y"),
            data_fim.strftime("%d/%m/%Y"),
        )

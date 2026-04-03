"""
Pipeline ETL — coleta contratos do Portal da Transparência (2022-2026)
e persiste no banco local.

Uso:
    python -m src.etl.pipeline                        # todos os órgãos, 2022-2026
    python -m src.etl.pipeline --ano 2024             # apenas 2024
    python -m src.etl.pipeline --orgao 36000          # apenas MS
    python -m src.etl.pipeline --sem-cnpj             # sem enriquecimento BrasilAPI
"""

import argparse
import logging
import time
from datetime import date

from tqdm import tqdm

from src.database.postgres import SessionLocal, create_tables
from src.etl.portal_client import ORGAOS_SAUDE, PortalClient
from src.etl.ingestor import salvar_contrato

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Período padrão
ANO_INICIO = 2022
ANO_FIM = 2026

# Janela de coleta por trimestre (evita timeout na API para períodos longos)
MESES_POR_JANELA = 3

DELAY_ENTRE_ORGAOS = 1.5  # segundos


def _janelas_trimestrais(ano: int):
    """Gera tuplas (data_inicio, data_fim) trimestrais para um ano."""
    trimestres = [
        (date(ano, 1, 1),  date(ano, 3, 31)),
        (date(ano, 4, 1),  date(ano, 6, 30)),
        (date(ano, 7, 1),  date(ano, 9, 30)),
        (date(ano, 10, 1), date(ano, 12, 31)),
    ]
    hoje = date.today()
    return [(ini, min(fim, hoje)) for ini, fim in trimestres if ini <= hoje]


def executar(
    anos: list[int],
    codigos_orgao: list[str],
    enriquecer_cnpj: bool = True,
) -> None:
    create_tables()
    client = PortalClient()

    total_inseridos = 0
    total_duplicados = 0

    for codigo in codigos_orgao:
        info = ORGAOS_SAUDE.get(codigo, {"nome": codigo, "sigla": ""})
        logger.info("=== Iniciando coleta: %s (%s) ===", info["nome"], codigo)

        for ano in anos:
            for data_ini, data_fim in _janelas_trimestrais(ano):
                desc = f"{info['sigla'] or codigo} | {data_ini} → {data_fim}"
                inseridos = 0
                duplicados = 0

                db = SessionLocal()
                try:
                    contratos = client.buscar_contratos(codigo, data_ini, data_fim)
                    with tqdm(contratos, desc=desc, unit="contrato", leave=False) as barra:
                        for raw in barra:
                            foi_inserido = salvar_contrato(
                                db, raw, codigo, enriquecer_cnpj=enriquecer_cnpj
                            )
                            if foi_inserido:
                                inseridos += 1
                            else:
                                duplicados += 1
                            barra.set_postfix(novos=inseridos, dup=duplicados)

                            # Commit a cada 200 registros para não acumular memória
                            if (inseridos + duplicados) % 200 == 0:
                                db.commit()

                    db.commit()
                    logger.info(
                        "%s: +%d inseridos, %d duplicados", desc, inseridos, duplicados
                    )
                except Exception as exc:
                    db.rollback()
                    logger.error("Erro em %s: %s", desc, exc, exc_info=True)
                finally:
                    db.close()

                total_inseridos += inseridos
                total_duplicados += duplicados

        time.sleep(DELAY_ENTRE_ORGAOS)

    logger.info(
        "=== Pipeline concluído: %d contratos inseridos, %d duplicados ignorados ===",
        total_inseridos, total_duplicados,
    )


def _parse_args():
    parser = argparse.ArgumentParser(description="ETL — Portal da Transparência (MTR-Saúde)")
    parser.add_argument(
        "--ano", type=int, default=None,
        help=f"Coleta apenas este ano (padrão: {ANO_INICIO}–{ANO_FIM})"
    )
    parser.add_argument(
        "--orgao", type=str, default=None,
        help=f"Código SIAFI do órgão (padrão: todos). Opções: {', '.join(ORGAOS_SAUDE)}"
    )
    parser.add_argument(
        "--sem-cnpj", action="store_true",
        help="Desativa enriquecimento BrasilAPI (mais rápido)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    anos = [args.ano] if args.ano else list(range(ANO_INICIO, ANO_FIM + 1))
    orgaos = [args.orgao] if args.orgao else list(ORGAOS_SAUDE.keys())

    executar(
        anos=anos,
        codigos_orgao=orgaos,
        enriquecer_cnpj=not args.sem_cnpj,
    )

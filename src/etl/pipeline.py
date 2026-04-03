"""
Pipeline ETL — coleta contratos de saúde via PNCP (2022-2026)
e complementa com Portal da Transparência (ANVISA/ANS).

Uso:
    python -m src.etl.pipeline                  # coleta completa
    python -m src.etl.pipeline --ano 2024       # apenas 2024
    python -m src.etl.pipeline --sem-cnpj       # sem enriquecimento BrasilAPI
    python -m src.etl.pipeline --so-portal      # apenas Portal da Transparência
    python -m src.etl.pipeline --so-pncp        # apenas PNCP
"""

import argparse
import logging
import time
from datetime import date

from tqdm import tqdm

from src.database.postgres import SessionLocal, create_tables
from src.etl.pncp_client import ORGAOS_PNCP, PncpClient
from src.etl.portal_client import ORGAOS_SAUDE, PortalClient
from src.etl.ingestor import salvar_contrato_pncp, salvar_contrato_portal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ANO_INICIO = 2022
ANO_FIM = 2026
DELAY_ENTRE_ORGAOS = 1.5

# Órgãos que SÓ existem no Portal da Transparência (ANVISA e ANS)
ORGAOS_SOMENTE_PORTAL = {k: v for k, v in ORGAOS_SAUDE.items() if k in ("36206", "36216")}


def _janelas_anuais(anos: list[int]) -> list[tuple[date, date]]:
    """Retorna janelas de no máximo 365 dias (limite do PNCP)."""
    hoje = date.today()
    janelas = []
    for ano in anos:
        ini = date(ano, 1, 1)
        fim = min(date(ano, 12, 31), hoje)
        if ini <= hoje:
            janelas.append((ini, fim))
    return janelas


def _janelas_trimestrais(ano: int):
    hoje = date.today()
    trimestres = [
        (date(ano, 1, 1),  date(ano, 3, 31)),
        (date(ano, 4, 1),  date(ano, 6, 30)),
        (date(ano, 7, 1),  date(ano, 9, 30)),
        (date(ano, 10, 1), date(ano, 12, 31)),
    ]
    return [(ini, min(fim, hoje)) for ini, fim in trimestres if ini <= hoje]


def _processar(db_session, contratos_iter, fn_salvar, desc, enriquecer_cnpj):
    inseridos = 0
    duplicados = 0
    with tqdm(contratos_iter, desc=desc, unit="contrato", leave=False) as barra:
        for raw in barra:
            if fn_salvar(db_session, raw, enriquecer_cnpj=enriquecer_cnpj):
                inseridos += 1
            else:
                duplicados += 1
            barra.set_postfix(novos=inseridos, dup=duplicados)
            if (inseridos + duplicados) % 200 == 0:
                db_session.commit()
    db_session.commit()
    return inseridos, duplicados


def executar_pncp(anos: list[int], enriquecer_cnpj: bool = True) -> None:
    """Coleta contratos via PNCP (MS, FIOCRUZ, FUNASA)."""
    client = PncpClient()
    total_inseridos = total_dup = 0

    for cnpj, info in ORGAOS_PNCP.items():
        logger.info("=== PNCP: %s ===", info["nome"])
        for ini, fim in _janelas_anuais(anos):
            desc = f"{info['sigla']} {ini.year}"
            db = SessionLocal()
            try:
                contratos = client.buscar_contratos(cnpj, ini, fim)
                ins, dup = _processar(
                    db,
                    contratos,
                    fn_salvar=lambda db_, raw, **kw: salvar_contrato_pncp(db_, raw, **kw),
                    desc=desc,
                    enriquecer_cnpj=enriquecer_cnpj,
                )
                logger.info("%s: +%d inseridos, %d duplicados", desc, ins, dup)
                total_inseridos += ins
                total_dup += dup
            except Exception as exc:
                db.rollback()
                logger.error("Erro em %s: %s", desc, exc, exc_info=True)
            finally:
                db.close()
        time.sleep(DELAY_ENTRE_ORGAOS)

    logger.info("PNCP concluido: %d inseridos, %d duplicados", total_inseridos, total_dup)


def executar_portal(anos: list[int], enriquecer_cnpj: bool = True) -> None:
    """Coleta contratos do Portal da Transparência (ANVISA e ANS)."""
    client = PortalClient()
    total_inseridos = total_dup = 0

    for codigo, info in ORGAOS_SOMENTE_PORTAL.items():
        logger.info("=== Portal: %s ===", info["nome"])
        for ano in anos:
            for ini, fim in _janelas_trimestrais(ano):
                desc = f"{info['sigla']} {ini} -> {fim}"
                db = SessionLocal()
                try:
                    contratos = client.buscar_contratos(codigo, ini, fim)
                    ins, dup = _processar(
                        db,
                        contratos,
                        fn_salvar=lambda db_, raw, **kw: salvar_contrato_portal(db_, raw, codigo, **kw),
                        desc=desc,
                        enriquecer_cnpj=enriquecer_cnpj,
                    )
                    logger.info("%s: +%d inseridos, %d duplicados", desc, ins, dup)
                    total_inseridos += ins
                    total_dup += dup
                except Exception as exc:
                    db.rollback()
                    logger.error("Erro em %s: %s", desc, exc, exc_info=True)
                finally:
                    db.close()
        time.sleep(DELAY_ENTRE_ORGAOS)

    logger.info("Portal concluido: %d inseridos, %d duplicados", total_inseridos, total_dup)


def _parse_args():
    parser = argparse.ArgumentParser(description="ETL MTR-Saude")
    parser.add_argument("--ano", type=int, default=None, help="Coleta apenas este ano")
    parser.add_argument("--sem-cnpj", action="store_true", help="Sem enriquecimento BrasilAPI")
    parser.add_argument("--so-pncp", action="store_true", help="Apenas PNCP")
    parser.add_argument("--so-portal", action="store_true", help="Apenas Portal da Transparencia")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    anos = [args.ano] if args.ano else list(range(ANO_INICIO, ANO_FIM + 1))
    enriquecer = not args.sem_cnpj

    create_tables()

    if not args.so_portal:
        executar_pncp(anos, enriquecer_cnpj=enriquecer)

    if not args.so_pncp:
        executar_portal(anos, enriquecer_cnpj=enriquecer)

    logger.info("=== Pipeline finalizado ===")

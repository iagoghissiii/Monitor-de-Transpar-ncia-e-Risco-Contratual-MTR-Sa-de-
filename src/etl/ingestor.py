"""Ingestor — mapeia dados brutos da API e persiste no banco via SQLAlchemy."""

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.database.postgres import Contrato, Fornecedor, Orgao
from src.etl.brasil_api_client import buscar_cnpj, extrair_dados_risco

logger = logging.getLogger(__name__)


def _parse_date(valor: Optional[str]) -> Optional[date]:
    """Converte strings de data nos formatos DD/MM/YYYY ou YYYY-MM-DD."""
    if not valor:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(valor[:10], fmt[:8] if "T" in fmt else fmt).date()
        except ValueError:
            continue
    return None


def _upsert_orgao(db: Session, codigo: str, nome: str, sigla: str) -> Orgao:
    orgao = db.query(Orgao).filter_by(codigo=codigo).first()
    if not orgao:
        orgao = Orgao(codigo=codigo, nome=nome, sigla=sigla)
        db.add(orgao)
        db.flush()
    return orgao


def _upsert_fornecedor(db: Session, raw_fornecedor: dict) -> Optional[Fornecedor]:
    """
    Cria ou retorna um Fornecedor existente.
    Aceita tanto o formato do Portal da Transparência quanto dict simples.
    """
    cpf_cnpj = (
        raw_fornecedor.get("cnpj")
        or raw_fornecedor.get("cpf")
        or raw_fornecedor.get("cpfCnpj")
        or ""
    ).strip()

    if not cpf_cnpj:
        return None

    fornecedor = db.query(Fornecedor).filter_by(cpf_cnpj=cpf_cnpj).first()
    if fornecedor:
        return fornecedor

    nome = (
        raw_fornecedor.get("nome")
        or raw_fornecedor.get("razaoSocial")
        or "DESCONHECIDO"
    )
    tipo = "PJ" if len(cpf_cnpj.replace(".", "").replace("/", "").replace("-", "")) == 14 else "PF"
    uf = raw_fornecedor.get("uf") or raw_fornecedor.get("ufContratado") or ""
    municipio = raw_fornecedor.get("municipio") or raw_fornecedor.get("municipioContratado") or ""

    fornecedor = Fornecedor(
        cpf_cnpj=cpf_cnpj,
        nome=nome,
        tipo=tipo,
        uf=uf,
        municipio=municipio,
    )
    db.add(fornecedor)
    db.flush()
    return fornecedor


def salvar_contrato(db: Session, raw: dict, codigo_orgao: str, enriquecer_cnpj: bool = True) -> bool:
    """
    Persiste um contrato bruto da API no banco.
    Retorna True se inserido, False se já existia (deduplicação por id_externo).
    """
    id_externo = str(raw.get("id", "")).strip()
    if not id_externo:
        return False

    if db.query(Contrato).filter_by(id_externo=id_externo).first():
        return False  # já existe

    # --- Órgão ---
    orgao_raw = (
        raw.get("unidadeGestora", {}).get("orgaoVinculado", {})
        or raw.get("orgaoSuperior", {})
        or raw.get("orgao", {})
        or {}
    )
    codigo_orgao_contrato = str(
        orgao_raw.get("codigoSIAFI")
        or orgao_raw.get("codigo")
        or codigo_orgao
    )
    nome_orgao = orgao_raw.get("nome") or orgao_raw.get("descricao") or ""
    sigla_orgao = orgao_raw.get("sigla") or ""
    orgao = _upsert_orgao(db, codigo_orgao_contrato, nome_orgao, sigla_orgao)

    # --- Fornecedor ---
    raw_forn = (
        raw.get("fornecedor")
        or raw.get("contratado")
        or {}
    )
    fornecedor = _upsert_fornecedor(db, raw_forn)

    # Enriquecimento BrasilAPI (apenas PJ)
    if enriquecer_cnpj and fornecedor and fornecedor.tipo == "PJ":
        dados_cnpj = buscar_cnpj(fornecedor.cpf_cnpj)
        _ = extrair_dados_risco(dados_cnpj)  # disponível para futura feature engineering

    # --- Contrato ---
    valor = float(
        raw.get("valorInicial")
        or raw.get("valor")
        or raw.get("valorContrato")
        or 0
    )

    modalidade_raw = raw.get("modalidadeLicitacao") or raw.get("modalidade") or {}
    if isinstance(modalidade_raw, dict):
        modalidade = modalidade_raw.get("descricao") or modalidade_raw.get("nome") or ""
    else:
        modalidade = str(modalidade_raw)

    licitacao_raw = raw.get("licitacao") or {}
    numero_licitacao = licitacao_raw.get("numero") or raw.get("numeroLicitacao") or ""

    qtd_concorrentes = raw.get("quantidadeFornecedores") or raw.get("qtdConcorrentes") or 0

    contrato = Contrato(
        id_externo=id_externo,
        numero=raw.get("numero") or raw.get("numeroContrato") or "",
        objeto=raw.get("objeto") or raw.get("descricao") or "",
        valor=valor,
        data_inicio=_parse_date(raw.get("dataInicioVigencia") or raw.get("dataInicio")),
        data_fim=_parse_date(raw.get("dataFimVigencia") or raw.get("dataFim")),
        modalidade_licitacao=modalidade[:100] if modalidade else None,
        numero_licitacao=str(numero_licitacao)[:50] if numero_licitacao else None,
        qtd_concorrentes=int(qtd_concorrentes) if qtd_concorrentes else None,
        orgao_id=orgao.id,
        fornecedor_id=fornecedor.id if fornecedor else None,
        data_coleta=datetime.utcnow(),
        fonte="portal_transparencia",
    )
    db.add(contrato)
    return True

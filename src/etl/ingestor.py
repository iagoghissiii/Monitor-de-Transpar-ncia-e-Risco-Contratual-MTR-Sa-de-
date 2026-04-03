"""Ingestor — mapeia dados brutos da API e persiste no banco via SQLAlchemy."""

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.database.postgres import Contrato, Fornecedor, Orgao
from src.etl.brasil_api_client import buscar_cnpj, extrair_dados_risco

logger = logging.getLogger(__name__)


def _parse_date(valor: Optional[str]) -> Optional[date]:
    if not valor:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(valor[:10], fmt).date()
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


def _upsert_fornecedor(db: Session, cpf_cnpj: str, nome: str, tipo: str, uf: str = "", municipio: str = "") -> Optional[Fornecedor]:
    if not cpf_cnpj:
        return None
    fornecedor = db.query(Fornecedor).filter_by(cpf_cnpj=cpf_cnpj).first()
    if not fornecedor:
        fornecedor = Fornecedor(cpf_cnpj=cpf_cnpj, nome=nome, tipo=tipo, uf=uf, municipio=municipio)
        db.add(fornecedor)
        db.flush()
    return fornecedor


def salvar_contrato_pncp(db: Session, raw: dict, enriquecer_cnpj: bool = True) -> bool:
    """
    Persiste um contrato do PNCP no banco.
    Retorna True se inserido, False se duplicado.
    """
    id_externo = raw.get("numeroControlePNCP") or raw.get("numeroControlePncpCompra") or ""
    if not id_externo:
        return False
    if db.query(Contrato).filter_by(id_externo=id_externo).first():
        return False

    # Órgão
    org_raw = raw.get("orgaoEntidade", {})
    cnpj_orgao = org_raw.get("cnpj", "")
    orgao = _upsert_orgao(db, cnpj_orgao, org_raw.get("razaoSocial", ""), "")

    # Fornecedor
    cnpj_forn = raw.get("niFornecedor", "")
    tipo_forn = raw.get("tipoPessoa", "PJ")
    nome_forn = raw.get("nomeRazaoSocialFornecedor", "DESCONHECIDO")
    fornecedor = _upsert_fornecedor(db, cnpj_forn, nome_forn, tipo_forn)

    if enriquecer_cnpj and fornecedor and fornecedor.tipo == "PJ":
        dados_cnpj = buscar_cnpj(fornecedor.cpf_cnpj)
        _ = extrair_dados_risco(dados_cnpj)

    # Modalidade: tipoContrato ou categoriaProcesso
    tipo_contrato = raw.get("tipoContrato") or {}
    categoria = raw.get("categoriaProcesso") or {}
    modalidade = tipo_contrato.get("nome") or categoria.get("nome") or ""

    contrato = Contrato(
        id_externo=id_externo,
        numero=raw.get("numeroContratoEmpenho") or "",
        objeto=raw.get("objetoContrato") or "",
        valor=float(raw.get("valorInicial") or raw.get("valorGlobal") or 0),
        data_inicio=_parse_date(raw.get("dataVigenciaInicio") or raw.get("dataAssinatura")),
        data_fim=_parse_date(raw.get("dataVigenciaFim")),
        modalidade_licitacao=modalidade[:100] if modalidade else None,
        numero_licitacao=(raw.get("processo") or "")[:50] or None,
        qtd_concorrentes=None,  # não disponível no endpoint de contratos do PNCP
        orgao_id=orgao.id,
        fornecedor_id=fornecedor.id if fornecedor else None,
        data_coleta=datetime.utcnow(),
        fonte="pncp",
    )
    db.add(contrato)
    return True


def salvar_contrato_portal(db: Session, raw: dict, codigo_orgao: str, enriquecer_cnpj: bool = True) -> bool:
    """
    Persiste um contrato do Portal da Transparência no banco.
    Retorna True se inserido, False se duplicado.
    """
    id_externo = str(raw.get("id", "")).strip()
    if not id_externo:
        return False
    if db.query(Contrato).filter_by(id_externo=id_externo).first():
        return False

    # Órgão
    orgao_raw = (
        raw.get("unidadeGestora", {}).get("orgaoVinculado", {})
        or raw.get("orgaoSuperior", {})
        or raw.get("orgao", {})
        or {}
    )
    codigo_orgao_contrato = str(orgao_raw.get("codigoSIAFI") or orgao_raw.get("codigo") or codigo_orgao)
    orgao = _upsert_orgao(db, codigo_orgao_contrato, orgao_raw.get("nome") or "", orgao_raw.get("sigla") or "")

    # Fornecedor
    raw_forn = raw.get("fornecedor") or raw.get("contratado") or {}
    cpf_cnpj = (raw_forn.get("cnpj") or raw_forn.get("cpf") or raw_forn.get("cpfCnpj") or "").strip()
    nome_forn = raw_forn.get("nome") or raw_forn.get("razaoSocial") or "DESCONHECIDO"
    tipo_forn = "PJ" if cpf_cnpj and len(cpf_cnpj.replace(".", "").replace("/", "").replace("-", "")) == 14 else "PF"
    fornecedor = _upsert_fornecedor(db, cpf_cnpj, nome_forn, tipo_forn,
                                    raw_forn.get("uf") or "", raw_forn.get("municipio") or "")

    if enriquecer_cnpj and fornecedor and fornecedor.tipo == "PJ":
        dados_cnpj = buscar_cnpj(fornecedor.cpf_cnpj)
        _ = extrair_dados_risco(dados_cnpj)

    modalidade_raw = raw.get("modalidadeLicitacao") or raw.get("modalidade") or {}
    modalidade = (modalidade_raw.get("descricao") or modalidade_raw.get("nome") or "") if isinstance(modalidade_raw, dict) else str(modalidade_raw)
    licitacao_raw = raw.get("licitacao") or {}
    numero_licitacao = licitacao_raw.get("numero") or raw.get("numeroLicitacao") or ""
    qtd = raw.get("quantidadeFornecedores") or raw.get("qtdConcorrentes") or None

    contrato = Contrato(
        id_externo=id_externo,
        numero=raw.get("numero") or raw.get("numeroContrato") or "",
        objeto=raw.get("objeto") or raw.get("descricao") or "",
        valor=float(raw.get("valorInicial") or raw.get("valor") or raw.get("valorContrato") or 0),
        data_inicio=_parse_date(raw.get("dataInicioVigencia") or raw.get("dataInicio")),
        data_fim=_parse_date(raw.get("dataFimVigencia") or raw.get("dataFim")),
        modalidade_licitacao=modalidade[:100] if modalidade else None,
        numero_licitacao=str(numero_licitacao)[:50] if numero_licitacao else None,
        qtd_concorrentes=int(qtd) if qtd else None,
        orgao_id=orgao.id,
        fornecedor_id=fornecedor.id if fornecedor else None,
        data_coleta=datetime.utcnow(),
        fonte="portal_transparencia",
    )
    db.add(contrato)
    return True

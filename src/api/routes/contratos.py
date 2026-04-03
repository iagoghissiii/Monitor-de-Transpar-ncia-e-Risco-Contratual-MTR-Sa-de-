"""Endpoints para consulta de contratos e scores de risco."""

import math
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from src.database.postgres import get_db, Contrato, Orgao, Fornecedor
from src.api.schemas import (
    ContratoResponse, ContratoListResponse, DashboardResumo, ScoreResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/contratos", tags=["contratos"])


@router.get("/", response_model=ContratoListResponse)
async def listar_contratos(
    valor_min: float | None = None,
    valor_max: float | None = None,
    nivel_risco: str | None = Query(None, pattern="^(baixo|medio|alto)$"),
    ordem: str = Query("desc", pattern="^(asc|desc)$"),
    pagina: int = Query(1, ge=1),
    limite: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Lista contratos com filtros opcionais de valor, risco e ordenacao."""
    query = db.query(Contrato).options(
        joinedload(Contrato.orgao),
        joinedload(Contrato.fornecedor),
    )

    if valor_min is not None:
        query = query.filter(Contrato.valor >= valor_min)
    if valor_max is not None:
        query = query.filter(Contrato.valor <= valor_max)
    if nivel_risco:
        query = query.filter(Contrato.nivel_risco == nivel_risco)

    if ordem == "asc":
        query = query.order_by(Contrato.data_inicio.asc().nulls_last())
    else:
        query = query.order_by(Contrato.data_inicio.desc().nulls_last())

    total = query.count()
    total_paginas = math.ceil(total / limite) if total > 0 else 1

    offset = (pagina - 1) * limite
    contratos = query.offset(offset).limit(limite).all()

    return ContratoListResponse(
        contratos=[ContratoResponse.model_validate(c) for c in contratos],
        total=total,
        pagina=pagina,
        total_paginas=total_paginas,
    )


@router.get("/dashboard", response_model=DashboardResumo)
async def dashboard_resumo(db: Session = Depends(get_db)):
    """Retorna resumo estatistico para o dashboard, incluindo metricas de risco."""
    total_contratos   = db.query(func.count(Contrato.id)).scalar()     or 0
    valor_total       = db.query(func.sum(Contrato.valor)).scalar()    or 0.0
    total_orgaos      = db.query(func.count(func.distinct(Contrato.orgao_id))).scalar()       or 0
    total_fornecedores = db.query(func.count(func.distinct(Contrato.fornecedor_id))).scalar() or 0

    score_medio = db.query(func.avg(Contrato.score_anomalia)).scalar()
    alto_risco  = db.query(func.count(Contrato.id)).filter(Contrato.nivel_risco == "alto").scalar()  or 0
    medio_risco = db.query(func.count(Contrato.id)).filter(Contrato.nivel_risco == "medio").scalar() or 0
    baixo_risco = db.query(func.count(Contrato.id)).filter(Contrato.nivel_risco == "baixo").scalar() or 0

    return DashboardResumo(
        total_contratos=total_contratos,
        valor_total=float(valor_total),
        total_orgaos=total_orgaos,
        total_fornecedores=total_fornecedores,
        score_medio=float(score_medio) if score_medio is not None else None,
        alto_risco=alto_risco,
        medio_risco=medio_risco,
        baixo_risco=baixo_risco,
    )


@router.get("/{contrato_id}", response_model=ContratoResponse)
async def detalhe_contrato(contrato_id: int, db: Session = Depends(get_db)):
    """Retorna detalhes completos de um contrato especifico."""
    contrato = (
        db.query(Contrato)
        .options(joinedload(Contrato.orgao), joinedload(Contrato.fornecedor))
        .filter(Contrato.id == contrato_id)
        .first()
    )
    if not contrato:
        raise HTTPException(status_code=404, detail="Contrato nao encontrado")
    return ContratoResponse.model_validate(contrato)


@router.get("/{contrato_id}/score", response_model=ScoreResponse)
async def score_contrato(contrato_id: int, db: Session = Depends(get_db)):
    """
    Retorna score de anomalia e os 5 principais fatores de risco (SHAP).

    Se o contrato ja foi avaliado pelo modelo, retorna o valor do banco.
    Caso contrario, calcula em tempo real.
    """
    contrato = (
        db.query(Contrato)
        .options(joinedload(Contrato.fornecedor))
        .filter(Contrato.id == contrato_id)
        .first()
    )
    if not contrato:
        raise HTTPException(status_code=404, detail="Contrato nao encontrado")

    # Tenta calcular via ML (requer modelos treinados)
    try:
        from src.ml.scorer import score_contrato as _score, modelos_disponiveis
        if not modelos_disponiveis():
            # Modelos ainda nao treinados — retorna score do banco ou zero
            return ScoreResponse(
                contrato_id=contrato_id,
                score_anomalia=contrato.score_anomalia or 0.0,
                nivel_risco=contrato.nivel_risco or "baixo",
                fatores=[],
            )
        resultado = _score(contrato)
        return ScoreResponse(
            contrato_id=contrato_id,
            score_anomalia=resultado["score_anomalia"],
            nivel_risco=resultado["nivel_risco"],
            fatores=resultado["fatores"],
        )
    except Exception as e:
        logger.warning("Erro ao calcular score ML: %s", e)
        return ScoreResponse(
            contrato_id=contrato_id,
            score_anomalia=contrato.score_anomalia or 0.0,
            nivel_risco=contrato.nivel_risco or "baixo",
            fatores=[],
        )

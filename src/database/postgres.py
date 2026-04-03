"""Conexao e modelos SQLite/PostgreSQL (BETA - apenas dados dos contratos)."""

from datetime import datetime, date
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text,
    DateTime, Date, ForeignKey, text,
)
from sqlalchemy.orm import sessionmaker, DeclarativeBase, relationship
from src.utils.config import settings

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Orgao(Base):
    __tablename__ = "orgaos"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(20), unique=True, nullable=False, index=True)
    nome = Column(String(300), nullable=False)
    sigla = Column(String(30))

    contratos = relationship("Contrato", back_populates="orgao")


class Fornecedor(Base):
    __tablename__ = "fornecedores"

    id = Column(Integer, primary_key=True, index=True)
    cpf_cnpj = Column(String(18), unique=True, nullable=False, index=True)
    nome = Column(String(300), nullable=False)
    tipo = Column(String(2))  # PF ou PJ
    uf = Column(String(2))
    municipio = Column(String(200))

    contratos = relationship("Contrato", back_populates="fornecedor")


class Contrato(Base):
    __tablename__ = "contratos"

    id = Column(Integer, primary_key=True, index=True)
    id_externo = Column(String(50), unique=True, index=True)  # ID do Portal da Transparência
    numero = Column(String(50), index=True)
    objeto = Column(Text)
    valor = Column(Float, nullable=False)
    data_inicio = Column(Date)
    data_fim = Column(Date)
    modalidade_licitacao = Column(String(100))
    numero_licitacao = Column(String(50))
    qtd_concorrentes = Column(Integer)

    orgao_id = Column(Integer, ForeignKey("orgaos.id"), index=True)
    fornecedor_id = Column(Integer, ForeignKey("fornecedores.id"), index=True)

    orgao = relationship("Orgao", back_populates="contratos")
    fornecedor = relationship("Fornecedor", back_populates="contratos")

    data_coleta = Column(DateTime, default=datetime.utcnow)
    fonte = Column(String(50))

    # Score ML (preenchido apos src.ml.treinar)
    score_anomalia = Column(Float,     nullable=True)
    nivel_risco    = Column(String(10), nullable=True)   # "baixo" | "medio" | "alto"
    tipo_anomalia  = Column(String(25), nullable=True)   # "normal" | "falha_preenchimento" | "fraude_intencional"


def create_tables() -> None:
    """Cria todas as tabelas e aplica migracoes incrementais."""
    Base.metadata.create_all(bind=engine)
    _migrar()


def _migrar() -> None:
    """Adiciona colunas novas em bancos existentes sem apagar dados."""
    migracoes = [
        "ALTER TABLE contratos ADD COLUMN id_externo VARCHAR(50)",
        "ALTER TABLE contratos ADD COLUMN score_anomalia REAL",
        "ALTER TABLE contratos ADD COLUMN nivel_risco VARCHAR(10)",
        "ALTER TABLE contratos ADD COLUMN tipo_anomalia VARCHAR(25)",
    ]
    with engine.connect() as conn:
        for sql in migracoes:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # coluna ja existe


def get_db():
    """Dependency para injecao de sessao nos endpoints FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

"""Configuracoes centralizadas do projeto (BETA)."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings:
    # Database mode: SQLite para desenvolvimento
    DB_MODE: str = "sqlite"

    # Portal da Transparência
    PORTAL_API_KEY: str = os.getenv("PORTAL_API_KEY", "")
    PORTAL_BASE_URL: str = "https://api.portaldatransparencia.gov.br/api-de-dados"

    # BrasilAPI
    BRASIL_API_URL: str = "https://brasilapi.com.br/api/cnpj/v1"

    @property
    def database_url(self) -> str:
        db_path = BASE_DIR / "data" / "contratos.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path}"


settings = Settings()

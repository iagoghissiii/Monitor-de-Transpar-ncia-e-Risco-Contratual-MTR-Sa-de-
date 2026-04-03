"""API principal do sistema - BETA 1.0."""

import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.api.routes.contratos import router as contratos_router
from src.database.postgres import create_tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(
    title="MTR-Saude — Monitor de Transparencia e Risco Contratual",
    description="Deteccao de anomalias em contratos publicos de saude com IA.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(contratos_router, prefix="/api/v1")


@app.on_event("startup")
async def startup():
    logging.info("Criando/migrando tabelas no banco...")
    create_tables()
    # Pre-carrega modelos ML se disponiveis
    try:
        from src.ml.scorer import modelos_disponiveis, _carregar
        if modelos_disponiveis():
            _carregar()  # detecta automaticamente se ha modelos novos no disco
        else:
            logging.info("Modelos ML nao encontrados — execute treinar_modelo.bat")
    except Exception as e:
        logging.warning("Nao foi possivel carregar modelos ML: %s", e)
    logging.info("MTR-Saude v2.0 iniciado!")


@app.get("/api/health")
@app.get("/health")
async def health():
    return {"status": "healthy", "version": "0.1.0-beta"}


# Servir frontend estatico
if FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
    app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
    if (FRONTEND_DIR / "pages").exists():
        app.mount("/pages", StaticFiles(directory=FRONTEND_DIR / "pages"), name="pages")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(FRONTEND_DIR / "index.html")
else:
    @app.get("/")
    async def root():
        return {
            "projeto": "Contratos Publicos - BETA",
            "versao": "0.1.0-beta",
            "docs": "/docs",
        }

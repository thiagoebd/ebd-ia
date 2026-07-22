"""Gateway FastAPI — porta de entrada HTTP do EBD.ia.

Serve frontend React (dist), /api/health, /api/me, /api/chat, /api/conversations.
Reusa core/agent.py via sys.path (mesma estrategia do bot Telegram).

Sobe com:
  cd ~/projects/ebd-ia
  uvicorn gateway.app.main:app --host 0.0.0.0 --port 8000
"""
import os
import sys
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
GATEWAY_DIR = Path(__file__).resolve().parent.parent
load_dotenv(GATEWAY_DIR / ".env")

ROOT = GATEWAY_DIR.parent
CORE_DIR = ROOT / "core"
load_dotenv(CORE_DIR / ".env")  # ANTHROPIC_API_KEY e settings do agent vivem aqui
sys.path.insert(0, str(CORE_DIR))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from gateway.app.routes import health, me, chat, conversations, artifacts
from gateway.app.routes import admin_acl
from gateway.app import db

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await db.init_db()
        log.info("Pool Postgres pronto — historico de conversas ativo")
    except Exception:
        log.exception("Falha ao conectar no Postgres — historico NAO vai persistir")
    yield
    await db.close_db()


app = FastAPI(
    title="EBD.ia Gateway",
    description="Gateway HTTP do agente comercial EBD.ia.",
    version="0.3.0",
    lifespan=lifespan,
)

origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["meta"])
app.include_router(me.router, prefix="/api", tags=["auth"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(conversations.router, prefix="/api", tags=["conversations"])
app.include_router(artifacts.router, prefix="/api", tags=["artifacts"])
app.include_router(admin_acl.router, prefix="/api", tags=["admin-acl"])


FRONTEND_DIST = ROOT / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/favicon.svg")
    async def favicon():
        return FileResponse(FRONTEND_DIST / "favicon.svg")

    @app.get("/icons.svg")
    async def icons():
        return FileResponse(FRONTEND_DIST / "icons.svg")

    @app.get("/")
    async def root():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str, request: Request):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (FRONTEND_DIST / full_path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(FRONTEND_DIST.resolve())):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    async def root_no_frontend():
        return {
            "service": "ebd-ia-gateway",
            "version": app.version,
            "frontend": "NAO BUILDADO — rode `cd frontend && npm run build`",
            "docs": "/docs",
            "health": "/api/health",
        }

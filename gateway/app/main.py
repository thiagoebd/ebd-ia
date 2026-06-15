"""Gateway FastAPI — porta de entrada HTTP do EBD.ia.

Serve:
  /              → frontend React (build estático em frontend/dist/)
  /api/health    → status público
  /api/me        → identidade do usuário logado (autenticado)
  /docs          → Swagger UI da API

Reusa core/agent.py via sys.path (mesma estratégia do bot Telegram).

Sobe com:
  cd ~/projects/ebd-ia
  uvicorn gateway.app.main:app --host 0.0.0.0 --port 8000 --reload
"""
import os
import sys
from pathlib import Path

# Carrega .env do gateway/
from dotenv import load_dotenv
GATEWAY_DIR = Path(__file__).resolve().parent.parent
load_dotenv(GATEWAY_DIR / ".env")

# Truque pra importar core/app/* (mesma estratégia do channels/telegram_bot/main.py)
ROOT = GATEWAY_DIR.parent
CORE_DIR = ROOT / "core"
sys.path.insert(0, str(CORE_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from gateway.app.routes import health, me, chat

app = FastAPI(
    title="EBD.ia Gateway",
    description="Gateway HTTP do agente comercial EBD.ia.",
    version="0.2.0",
)

# CORS — origens permitidas (frontend dev + prod + IP da DMZ)
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

# Rotas da API (vêm ANTES do static pra ter prioridade no roteamento)
app.include_router(health.router, prefix="/api", tags=["meta"])
app.include_router(me.router, prefix="/api", tags=["auth"])
app.include_router(chat.router, prefix="/api", tags=["chat"])


# ============================================================
# Frontend estático (build do Vite)
# ============================================================
FRONTEND_DIST = ROOT / "frontend" / "dist"

if FRONTEND_DIST.exists():
    # Serve os assets (JS, CSS, imagens) em /assets, /favicon.svg, etc
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/favicon.svg")
    async def favicon():
        return FileResponse(FRONTEND_DIST / "favicon.svg")

    @app.get("/icons.svg")
    async def icons():
        return FileResponse(FRONTEND_DIST / "icons.svg")

    @app.get("/")
    async def root():
        # SPA: serve o index.html (React Router cuida do resto no client)
        return FileResponse(FRONTEND_DIST / "index.html")

    # Catch-all pra rotas SPA (ex: /chat, /library) — sempre devolve index.html
    # IMPORTANTE: tem que vir POR ÚLTIMO pra não capturar /api/*
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str, request: Request):
        # Se for chamada de API que não bateu nas rotas anteriores, retorna 404 JSON
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # Se existir um arquivo real no dist/ (logo, imagens, etc), serve ele
        candidate = (FRONTEND_DIST / full_path).resolve()
        # proteção contra path traversal: candidate tem que estar DENTRO de dist/
        if candidate.is_file() and str(candidate).startswith(str(FRONTEND_DIST.resolve())):
            return FileResponse(candidate)
        # Senão, devolve o index.html (SPA cuida do roteamento)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    async def root_no_frontend():
        return {
            "service": "ebd-ia-gateway",
            "version": app.version,
            "frontend": "NÃO BUILDADO — rode `cd frontend && npm run build`",
            "docs": "/docs",
            "health": "/api/health",
        }

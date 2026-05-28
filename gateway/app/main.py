"""Gateway FastAPI — porta de entrada HTTP do EBD.ia.

Reusa core/agent.py (mesmo cérebro do bot Telegram) via sys.path.

Sobe com:
  cd ~/projects/ebd-ia
  uvicorn gateway.app.main:app --port 8000 --reload

Hoje (28/05/2026): só endpoints de health e /me (validação Entra ID).
Próximo: POST /api/chat com SSE streaming integrado ao core/agent.py.
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

from gateway.app.routes import health, me

app = FastAPI(
    title="EBD.ia Gateway",
    description="Gateway HTTP do agente comercial EBD.ia. Frontend React consome aqui.",
    version="0.1.0",
)

# CORS — só origens permitidas (frontend dev + prod)
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

# Routers
app.include_router(health.router, prefix="/api", tags=["meta"])
app.include_router(me.router, prefix="/api", tags=["auth"])


@app.get("/")
async def root():
    return {
        "service": "ebd-ia-gateway",
        "version": app.version,
        "docs": "/docs",
        "health": "/api/health",
    }

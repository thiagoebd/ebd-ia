"""Catálogo dos modelos Claude disponíveis no chat web e regras por role.

Fonte única: importado por /api/me (mostra opções pro front) e por /api/chat (valida).
"""
import os

DEFAULT_MODEL = "claude-sonnet-4-6"

ALL_MODELS = [
    {"id": "claude-haiku-4-5",  "label": "Claude Haiku 4.5",  "tier": "rápido e barato"},
    {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "tier": "equilibrado"},
    {"id": "claude-opus-4-8",   "label": "Claude Opus 4.8",   "tier": "mais capaz"},
]

USER_MODELS = ["claude-haiku-4-5"]
ADMIN_MODELS = [m["id"] for m in ALL_MODELS]

ADMIN_OIDS = {
    o.strip() for o in os.getenv("ADMIN_OIDS", "").split(",") if o.strip()
}


def is_admin(oid: str | None) -> bool:
    return bool(oid) and oid in ADMIN_OIDS


def role_for(oid: str | None) -> str:
    return "admin" if is_admin(oid) else "user"


def allowed_models(oid: str | None) -> list[str]:
    return ADMIN_MODELS if is_admin(oid) else USER_MODELS


def resolve_model(requested: str | None, oid: str | None) -> str:
    """Decide o modelo final: requested se valido pro role, senão DEFAULT_MODEL."""
    if requested and requested in allowed_models(oid):
        return requested
    return DEFAULT_MODEL


def models_payload_for(oid: str | None) -> dict:
    allowed = set(allowed_models(oid))
    return {
        "default": DEFAULT_MODEL,
        "available": [m for m in ALL_MODELS if m["id"] in allowed],
    }

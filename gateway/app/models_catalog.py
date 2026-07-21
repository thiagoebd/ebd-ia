"""Catálogo dos modelos disponíveis no chat web e regras por role.

Fonte única: importado por /api/me (mostra opções pro front) e por /api/chat (valida).
"""
import os

DEFAULT_MODEL = "deepseek-v4-flash"

ALL_MODELS = [
    {"id": "deepseek-v4-flash", "label": "DeepSeek Flash", "tier": "rápido e econômico"},
    {"id": "deepseek-v4-pro",   "label": "DeepSeek Pro",   "tier": "mais capaz"},
    # Claude fora do seletor por ora (21/07). Reabilitar = descomentar
    # (o agent ja roteia claude-* pro client Claude e o chat.py ja precifica):
    # {"id": "claude-haiku-4-5",  "label": "Claude Haiku 4.5",  "tier": "rápido e barato"},
    # {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "tier": "equilibrado"},
    # {"id": "claude-opus-4-8",   "label": "Claude Opus 4.8",   "tier": "mais capaz"},
]

USER_MODELS = [m["id"] for m in ALL_MODELS]
ADMIN_MODELS = [m["id"] for m in ALL_MODELS]

ADMIN_OIDS = {o.strip() for o in os.getenv("ADMIN_OIDS", "").split(",") if o.strip()}
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


def is_admin(oid: str | None, email: str | None = None) -> bool:
    if oid and oid in ADMIN_OIDS:
        return True
    if email and email.strip().lower() in ADMIN_EMAILS:
        return True
    return False


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
    return {"default": DEFAULT_MODEL,
            "available": [m for m in ALL_MODELS if m["id"] in allowed]}

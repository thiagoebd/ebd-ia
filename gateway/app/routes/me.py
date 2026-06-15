"""Endpoint /api/me — identidade + role + modelos disponíveis."""
from fastapi import APIRouter, Depends
from gateway.app.auth.entra import verify_token
from gateway.app.models_catalog import role_for, models_payload_for

router = APIRouter()


@router.get("/me")
async def get_me(claims: dict = Depends(verify_token)):
    oid = claims.get("oid")
    return {
        "oid": oid,
        "name": claims.get("name"),
        "email": claims.get("preferred_username") or claims.get("upn") or claims.get("unique_name") or claims.get("email"),
        "tenant_id": claims.get("tid"),
        "role": role_for(oid),
        "models": models_payload_for(oid),
        "acl": {
            "ativo": False,
            "escopo": None,
            "filiais": [],
            "msg": "ACL ainda nao configurada — Semana 3 do roadmap",
        },
    }

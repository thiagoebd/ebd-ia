"""Endpoint /api/me — identidade + role + modelos disponíveis."""
from fastapi import APIRouter, Depends
from gateway.app.auth.entra import verify_token
from gateway.app.models_catalog import role_for, models_payload_for, is_admin

router = APIRouter()


@router.get("/me")
async def get_me(claims: dict = Depends(verify_token)):
    oid = claims.get("oid")
    _email = claims.get("preferred_username") or claims.get("upn") or claims.get("unique_name") or claims.get("email")
        claims.get("name"), claims.get("oid"), claims.get("sub"),
        claims.get("preferred_username") or claims.get("upn"))
    return {
        "oid": oid,
        "name": claims.get("name"),
        "email": claims.get("preferred_username") or claims.get("upn") or claims.get("unique_name") or claims.get("email"),
        "tenant_id": claims.get("tid"),
        "role": role_for(oid),
        "models": models_payload_for(oid),
        "acl": {
            "ativo": is_admin(oid, _email),
            "escopo": "BR" if is_admin(oid, _email) else None,
            "filiais": ["*"] if is_admin(oid, _email) else [],
            "msg": None if is_admin(oid, _email) else "Seu acesso ainda nao foi configurado. Fale com o admin (TI Grupo EBD).",
        },
    }

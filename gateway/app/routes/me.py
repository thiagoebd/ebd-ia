"""Endpoint /api/me — identidade + role + modelos + ACL (fonte: acl_store)."""
from fastapi import APIRouter, Depends
from gateway.app.auth.entra import verify_token
from gateway.app.models_catalog import models_payload_for
from gateway.app import acl_store

router = APIRouter()


@router.get("/me")
async def get_me(claims: dict = Depends(verify_token)):
    oid = claims.get("oid")
    _email = (claims.get("preferred_username") or claims.get("upn")
              or claims.get("unique_name") or claims.get("email"))
    u = await acl_store.get_user(_email)
    ativo = u is not None
    return {
        "oid": oid,
        "name": claims.get("name"),
        "email": _email,
        "tenant_id": claims.get("tid"),
        "role": (u or {}).get("role", "user"),
        "super_admin": bool(u and u.get("super_admin")),
        "models": models_payload_for(oid),
        "acl": {
            "ativo": ativo,
            "escopo": (u or {}).get("scope_kind") if ativo else None,
            "filiais": (u or {}).get("filiais", []) if ativo else [],
            "msg": None if ativo else "Seu acesso ainda nao foi configurado. Fale com o admin (TI Grupo EBD).",
        },
    }

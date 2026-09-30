"""Endpoints da tela de Acessos. TODOS exigem super_admin (authz server-side)."""
from __future__ import annotations
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from gateway.app import db, acl_store
from gateway.app.auth.entra import verify_token
from app.adapters.whatsapp import normaliza_whatsapp

router = APIRouter(prefix="/admin/acl", tags=["admin-acl"])


def _email_of(claims: dict) -> str | None:
    return (claims.get("preferred_username") or claims.get("upn")
            or claims.get("unique_name") or claims.get("email"))


async def require_super_admin(claims: dict = Depends(verify_token)) -> str:
    email = _email_of(claims)
    if not await acl_store.is_super_admin(email):
        raise HTTPException(status_code=403, detail="Apenas super-admins")
    return email


class UpsertUser(BaseModel):
    email: str
    nome: str | None = None
    role: str = "admin"
    scope_kind: str
    scope_value: list[str] = []
    super_admin: bool = False
    # quem pode falar com o EBD.ia no WhatsApp; vazio = nao pode
    whatsapp: str | None = None


def _whatsapp(body: UpsertUser) -> str | None:
    """Normaliza; vazio vira NULL; invalido e 400 (nunca grava lixo)."""
    if not (body.whatsapp or "").strip():
        return None
    n = normaliza_whatsapp(body.whatsapp)
    if not n:
        raise HTTPException(400, "WhatsApp inválido. Use +55 DDD número, ex.: +55 11 99999-8888")
    return n


def _conflito_whatsapp(e: Exception) -> bool:
    return "idx_acl_users_whatsapp" in str(e)


async def _audit(actor, action, target, before, after):
    await db._pool_or_raise().execute(
        "INSERT INTO acl_audit (actor_email, action, target_email, before, after) "
        "VALUES ($1,$2,$3,$4::jsonb,$5::jsonb)",
        actor, action, target,
        json.dumps(before, default=str) if before else None,
        json.dumps(after, default=str) if after else None)


@router.get("/filiais")
async def list_filiais(_: str = Depends(require_super_admin)):
    """Estrutura filial/deposito/regional — fonte unica pra tela de Acessos."""
    return await acl_store.load_estrutura()


@router.get("")
async def list_users(_: str = Depends(require_super_admin)):
    rows = await db._pool_or_raise().fetch(
        "SELECT id, email, nome, role, scope_kind, scope_value, filiais, super_admin, "
        "active, whatsapp, created_by, created_at FROM acl_users ORDER BY active DESC, nome")
    return [dict(r) for r in rows]


@router.post("")
async def create_user(body: UpsertUser, actor: str = Depends(require_super_admin)):
    if body.scope_kind not in ("brasil","regional","filiais","filial"):
        raise HTTPException(400, "scope_kind inválido")
    filiais = await acl_store.resolve_filiais(body.scope_kind, body.scope_value)
    wpp = _whatsapp(body)
    try:
        row = await db._pool_or_raise().fetchrow(
            "INSERT INTO acl_users (email,nome,role,scope_kind,scope_value,filiais,super_admin,created_by,whatsapp) "
            "VALUES (lower($1),$2,$3,$4,$5::jsonb,$6::jsonb,$7,$8,$9) RETURNING id, email",
            body.email, body.nome, body.role, body.scope_kind,
            json.dumps(body.scope_value), json.dumps(filiais), body.super_admin, actor, wpp)
    except Exception as e:
        if _conflito_whatsapp(e):
            raise HTTPException(409, "Esse WhatsApp já está cadastrado para outro usuário.")
        raise HTTPException(409, f"Falha ao criar (email já existe?): {str(e)[:120]}")
    await _audit(actor, "create", body.email.lower(), None,
                 {**body.model_dump(), "whatsapp": wpp, "filiais": filiais})
    acl_store.invalidate(body.email)
    return dict(row)


@router.patch("/{uid}")
async def update_user(uid: str, body: UpsertUser, actor: str = Depends(require_super_admin)):
    pool = db._pool_or_raise()
    before = await pool.fetchrow("SELECT * FROM acl_users WHERE id=$1", uid)
    if not before:
        raise HTTPException(404, "não encontrado")
    filiais = await acl_store.resolve_filiais(body.scope_kind, body.scope_value)
    if dict(before).get("super_admin") and not body.super_admin:
        n = await pool.fetchval("SELECT COUNT(*) FROM acl_users WHERE super_admin AND active AND id<>$1", uid)
        if not n:
            raise HTTPException(400, "Não pode remover o último super-admin")
    wpp = _whatsapp(body)
    try:
        await pool.execute(
            "UPDATE acl_users SET nome=$2, role=$3, scope_kind=$4, scope_value=$5::jsonb, "
            "filiais=$6::jsonb, super_admin=$7, whatsapp=$8, updated_at=now() WHERE id=$1",
            uid, body.nome, body.role, body.scope_kind,
            json.dumps(body.scope_value), json.dumps(filiais), body.super_admin, wpp)
    except Exception as e:
        if _conflito_whatsapp(e):
            raise HTTPException(409, "Esse WhatsApp já está cadastrado para outro usuário.")
        raise
    await _audit(actor, "update", body.email.lower(), dict(before),
                 {**body.model_dump(), "whatsapp": wpp, "filiais": filiais})
    acl_store.invalidate(body.email)
    return {"ok": True}


@router.patch("/{uid}/active")
async def set_active(uid: str, active: bool, actor: str = Depends(require_super_admin)):
    pool = db._pool_or_raise()
    before = await pool.fetchrow("SELECT * FROM acl_users WHERE id=$1", uid)
    if not before:
        raise HTTPException(404, "não encontrado")
    b = dict(before)
    if b.get("super_admin") and b.get("active") and not active:
        n = await pool.fetchval("SELECT COUNT(*) FROM acl_users WHERE super_admin AND active AND id<>$1", uid)
        if not n:
            raise HTTPException(400, "Não pode desativar o último super-admin")
    await pool.execute("UPDATE acl_users SET active=$2, updated_at=now() WHERE id=$1", uid, active)
    await _audit(actor, "reactivate" if active else "deactivate", b.get("email"), b, {"active": active})
    acl_store.invalidate(b.get("email"))
    return {"ok": True}

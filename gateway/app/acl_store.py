"""Fonte única de ACL (Postgres) com cache curto e break-glass."""
from __future__ import annotations
import os, time, json
from gateway.app import db

_BREAK_GLASS = {
    e.strip().lower()
    for e in os.getenv("BREAK_GLASS_SUPERADMINS", "thiago.parreira@ebdgrupo.com.br").split(",")
    if e.strip()
}

_TTL = 30.0
_cache: dict[str, tuple[float, dict | None]] = {}

# Estrutura filial/deposito/regional vem da tabela acl_filiais (fonte unica).
_ESTRUT_TTL = 300.0
_estrut_cache: tuple[float, list[dict]] | None = None


async def load_estrutura() -> list[dict]:
    """[{codigo, nome, tipo, filial_mae, regional}] das filiais ativas."""
    global _estrut_cache
    now = time.time()
    if _estrut_cache and now - _estrut_cache[0] < _ESTRUT_TTL:
        return _estrut_cache[1]
    rows = await db._pool_or_raise().fetch(
        "SELECT codigo, nome, tipo, filial_mae, regional FROM acl_filiais_resolvido "
        "WHERE ativa ORDER BY codigo")
    data = [dict(r) for r in rows]
    _estrut_cache = (now, data)
    return data


def invalidate_estrutura() -> None:
    global _estrut_cache
    _estrut_cache = None


async def resolve_filiais(scope_kind: str, scope_value: list[str]) -> str | list[str]:
    """Expande o escopo em lista de CODFILIAL. Deposito acompanha a filial-mae:
    escopo RJ1 -> 10, 13 e 17; escopo filial 10 -> 10 e 17."""
    if scope_kind == "brasil":
        return "*"
    est = await load_estrutura()
    if scope_kind == "regional":
        alvo = {str(r).upper() for r in (scope_value or [])}
        return sorted(f["codigo"] for f in est if (f["regional"] or "").upper() in alvo)
    sel = {str(f).zfill(2) for f in (scope_value or [])}
    out = set(sel)
    for f in est:
        if f["filial_mae"] in sel:
            out.add(f["codigo"])
    return sorted(out)


def invalidate(email: str | None = None) -> None:
    if email:
        _cache.pop(email.strip().lower(), None)
    else:
        _cache.clear()


async def _fetch(email: str) -> dict | None:
    row = await db._pool_or_raise().fetchrow(
        "SELECT id, email, oid, nome, role, scope_kind, scope_value, filiais, "
        "super_admin, active FROM acl_users WHERE lower(email) = lower($1)", email)
    if not row:
        return None
    d = dict(row)
    for k in ("scope_value", "filiais"):
        if isinstance(d.get(k), str):
            try: d[k] = json.loads(d[k])
            except Exception: pass
    return d


async def get_user(email: str | None) -> dict | None:
    if not email:
        return None
    key = email.strip().lower()
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _TTL:
        u = hit[1]
    else:
        u = await _fetch(key)
        _cache[key] = (now, u)
    if u and not u.get("active"):
        u = None
    if key in _BREAK_GLASS:
        u = u or {"email": key, "nome": "break-glass", "role": "admin"}
        u = {**u, "super_admin": True, "scope_kind": "brasil", "filiais": "*", "active": True}
    return u


async def is_allowed(email: str | None) -> bool:
    return (await get_user(email)) is not None


async def is_super_admin(email: str | None) -> bool:
    u = await get_user(email)
    return bool(u and u.get("super_admin"))

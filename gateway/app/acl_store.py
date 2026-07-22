"""Fonte única de ACL (Postgres) com cache curto e break-glass."""
from __future__ import annotations
import os, time, json
from gateway.app import db

_BREAK_GLASS = {
    e.strip().lower()
    for e in os.getenv("BREAK_GLASS_SUPERADMINS", "thiago.parreira@ebdgrupo.com.br").split(",")
    if e.strip()
}

REGIONAIS: dict[str, list[str]] = {
    "NE1": ["04","12"], "NE2": ["03","09","21"], "NE3": ["52","53"],
    "NO1": ["06","08","11"], "NO2": ["01","07"],
    "RJ1": ["10","13"], "RJ2": ["05","14"],
    "SP1": ["02","16"], "SP2": ["15","18"],
}

_TTL = 30.0
_cache: dict[str, tuple[float, dict | None]] = {}


def resolve_filiais(scope_kind: str, scope_value: list[str]) -> str | list[str]:
    if scope_kind == "brasil":
        return "*"
    if scope_kind == "regional":
        out: list[str] = []
        for r in scope_value or []:
            out += REGIONAIS.get(str(r).upper(), [])
        return sorted(set(out))
    return sorted({str(f).zfill(2) for f in (scope_value or [])})


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

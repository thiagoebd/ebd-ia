"""
acl.py — Resolução de ACL (Access Control List) de usuários.

Fase 1: usuários hardcoded em TEST_USERS (homologação).
Fase 2: lookup em EBD.FILIAL_ACL_CHATBOT no Oracle.
"""

from __future__ import annotations

from .models import UserContext
import os
import json as _json
import logging as _logging

_pglog = _logging.getLogger(__name__)

# Mapa regional p/ resolver escopo vindo do Postgres (mesmo do gateway acl_store)
_PG_REGIONAIS = {
    "NE1": ["04","12"], "NE2": ["03","09","21"], "NE3": ["52","53"],
    "NO1": ["06","08","11"], "NO2": ["01","07"],
    "RJ1": ["10","13"], "RJ2": ["05","14"],
    "SP1": ["02","16"], "SP2": ["15","18"],
}
_ALL_FILIAIS = ["01","02","03","04","05","06","07","08","09","10","11","12","13","14","15","16","18","21","52","53"]

def _pg_resolve_filiais(scope_kind, scope_value, filiais):
    """Traduz o escopo do acl_users em lista de CODFILIAL (ou todas p/ brasil)."""
    if filiais == "*" or scope_kind == "brasil":
        return list(_ALL_FILIAIS)
    if scope_kind == "regional":
        out = []
        for r in (scope_value or []):
            out += _PG_REGIONAIS.get(str(r).upper(), [])
        return sorted(set(out)) or list(_ALL_FILIAIS)
    # filiais/filial: usa a lista resolvida `filiais` se houver, senão scope_value
    base = filiais if isinstance(filiais, list) and filiais else scope_value
    return sorted({str(f).zfill(2) for f in (base or [])})

def _pg_lookup_user(identifier: str, canal=None):
    """Fase 2: busca o usuário na tabela acl_users do Postgres local.

    Retorna UserContext ou None. Falha silenciosa (loga) → cai no fallback.
    """
    try:
        import psycopg
    except Exception as e:
        _pglog.warning("psycopg indisponivel: %s", e)
        return None
    dsn = (f"host={os.getenv('POSTGRES_HOST','postgres')} "
           f"port={os.getenv('POSTGRES_PORT','5432')} "
           f"dbname={os.getenv('POSTGRES_DB')} "
           f"user={os.getenv('POSTGRES_USER')} "
           f"password={os.getenv('POSTGRES_PASSWORD')}")
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT nome, role, scope_kind, scope_value, filiais, active "
                    "FROM acl_users WHERE lower(email)=lower(%s)", (identifier,))
                row = cur.fetchone()
    except Exception as e:
        _pglog.warning("pg_lookup falhou (%s): %s", identifier, e)
        return None
    if not row:
        return None
    nome, role, scope_kind, scope_value, filiais, active = row
    if not active:
        return None
    # jsonb pode vir como str ou list dependendo do driver
    if isinstance(scope_value, str):
        try: scope_value = _json.loads(scope_value)
        except Exception: scope_value = []
    if isinstance(filiais, str):
        try: filiais = _json.loads(filiais)
        except Exception: filiais = filiais
    allowed = _pg_resolve_filiais(scope_kind, scope_value, filiais)
    if not allowed:
        allowed = list(_ALL_FILIAIS)
    _role = role if role in ("admin","gerente","supervisor") else "admin"
    return UserContext(
        user_id=identifier, nome=nome or identifier.split("@")[0],
        role=_role, codusur=None, allowed_filiais=allowed, canal=canal,
    )


REGIONAL_TO_FILIAIS: dict[str, list[str]] = {
    "NE1": ["04", "12"],
    "NE2": ["03", "09", "21"],
    "NE3": ["52", "53"],
    "NO1": ["06", "08", "11"],
    "NO2": ["01", "07"],
    "RJ1": ["10", "13"],
    "RJ2": ["05", "14"],
    "SP1": ["02", "16"],
    "SP2": ["15", "18"],
}

ALL_FILIAIS: list[str] = [
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "18", "21", "52", "53",
]


def resolve_allowed_filiais(
    filiais_csv: str | None,
    regionais_csv: str | None,
) -> list[str]:
    """Expande FILIAIS + REGIONAIS (CSV) em lista única ordenada de CODFILIAL."""
    if filiais_csv == "*":
        return list(ALL_FILIAIS)

    resultado: set[str] = set()

    if filiais_csv:
        for f in filiais_csv.split(","):
            f = f.strip()
            if f:
                resultado.add(f)

    if regionais_csv:
        for reg in regionais_csv.split(","):
            reg = reg.strip()
            if not reg:
                continue
            if reg not in REGIONAL_TO_FILIAIS:
                raise ValueError(
                    f"Regional desconhecida: '{reg}'. "
                    f"Válidas: {list(REGIONAL_TO_FILIAIS.keys())}"
                )
            resultado.update(REGIONAL_TO_FILIAIS[reg])

    if not resultado:
        raise ValueError("Nenhuma filial resolvida. Forneça FILIAIS ou REGIONAIS.")

    return sorted(resultado)


# ============================================================
# Usuários hardcoded — HOMOLOGAÇÃO
# Em produção: SELECT em FILIAL_ACL_CHATBOT.
# ============================================================

TEST_USERS_RAW: list[dict] = [
    # ============================================================
    # IDENTIDADE POR EMAIL (03->06/07/2026). Email = chave unica,
    # verificado criptograficamente pelo Entra (claim do JWT).
    # ============================================================
    {"user_id": 1, "celular": None, "email": "thiago.parreira@ebdgrupo.com.br",
     "nome": "Thiago Parreira", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 2, "celular": None, "email": "smoraes@ebdgrupo.com.br",
     "nome": "S. Moraes", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 3, "celular": None, "email": "rosana.cesario@ebdgrupo.com.br",
     "nome": "Rosana Cesario", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 4, "celular": None, "email": "filipe@ebdgrupo.com.br",
     "nome": "Filipe", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 5, "celular": None, "email": "enrico.montini@ebdgrupo.com.br",
     "nome": "Enrico Montini", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 6, "celular": None, "email": "andre@ebdgrupo.com.br",
     "nome": "Andre Andrade", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 7, "celular": None, "email": "abel.nau@ebdgrupo.com.br",
     "nome": "Abel Nau", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 8, "celular": None, "email": "viviane.pedroso@ebdgrupo.com.br",
     "nome": "Viviane Pedroso", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 9, "celular": None, "email": "fernanda@ebdgrupo.com.br",
     "nome": "Fernanda", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 10, "celular": None, "email": "tercio.quatroni@ebdgrupo.com.br",
     "nome": "Tercio Quatroni", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 11, "celular": None, "email": "fabio.alves@ebdgrupo.com.br",
     "nome": "Fabio Alves", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 12, "celular": None, "email": "hudson.coutinho@ebdgrupo.com.br",
     "nome": "Hudson Coutinho", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 13, "celular": None, "email": "thomaz.farha@ebdgrupo.com.br",
     "nome": "Thomaz Solis Farha", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    {"user_id": 14, "celular": None, "email": "alberto.araujo@ebdgrupo.com.br",
     "nome": "Alberto Araujo", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    # Identidade de SERVICO (canal Telegram / fallback interno).
    # LEGACY: celular mantido como alias de transicao — bot em producao tem o
    # default antigo em memoria. REMOVER quando o bot migrar pra systemd.
    {"user_id": 99, "celular": "+5511999990001", "email": "service@ebd.ia",
     "nome": "EBD.ia Servico", "role": "admin", "codusur": None, "filiais": "*", "regionais": None},
    # Usuarios de TESTE de escopo (Opcao B / enforcement futuro) — email-only
    {"user_id": 104, "celular": None, "email": "gerente.rj@ebdgrupo.com.br",
     "nome": "Gerente Teste RJ1", "role": "gerente", "codusur": None, "filiais": None, "regionais": "RJ1"},
    {"user_id": 105, "celular": None, "email": "supervisor.ne@ebdgrupo.com.br",
     "nome": "Supervisor Teste NE", "role": "supervisor", "codusur": None, "filiais": None, "regionais": "NE1,NE2,NE3"},
]


def _build_user_context(raw: dict, canal: str | None = None) -> UserContext:
    """Constrói UserContext a partir de um registro raw (dict ou linha de tabela)."""
    allowed = resolve_allowed_filiais(raw.get("filiais"), raw.get("regionais"))
    return UserContext(
        user_id=raw["user_id"],
        nome=raw["nome"],
        role=raw["role"],
        codusur=raw.get("codusur"),
        allowed_filiais=allowed,
        canal=canal,
    )


def resolve_user_by_identifier(
    identifier: str,
    canal: str | None = None,
) -> UserContext | None:
    """
    Lookup de usuário por celular (E.164) ou email.

    Fase 1: busca em TEST_USERS_RAW (memória).
    Fase 2: SELECT em FILIAL_ACL_CHATBOT (Oracle, cached em Redis).

    Args:
        identifier: celular E.164 (ex: '+5511999998888') ou email.
        canal: canal de origem (whatsapp, telegram, web, test).

    Returns:
        UserContext ou None se não encontrado.
    """
    identifier = identifier.strip().lower()
    # Fase 2: Postgres acl_users (fonte de verdade da tela de Acessos)
    ctx = _pg_lookup_user(identifier, canal=canal)
    if ctx is not None:
        return ctx
    # Fallback: TEST_USERS_RAW (usuários baked, compatibilidade)
    for raw in TEST_USERS_RAW:
        if raw.get("celular") == identifier or (raw.get("email") or "").lower() == identifier:
            return _build_user_context(raw, canal=canal)
    return None


def list_test_users() -> list[dict]:
    """Helper de debug: lista todos os usuários de teste sem expandir filiais."""
    return [
        {
            "user_id": u["user_id"],
            "celular": u["celular"],
            "nome": u["nome"],
            "role": u["role"],
            "filiais": u.get("filiais"),
            "regionais": u.get("regionais"),
        }
        for u in TEST_USERS_RAW
    ]

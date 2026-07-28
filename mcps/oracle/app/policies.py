"""Politica de acesso por PERFIL — ortogonal ao escopo de filial.

O escopo de filial responde "quais filiais este usuario ve".
Esta camada responde "quais RECURSOS este perfil pode consultar", seja qual for
a filial. As duas se aplicam juntas e de forma independente.

Desenho:
  - um RECURSO agrupa tabelas por padrao (ex.: comissao -> PCGM%, PCCOMISSAOUSUR)
  - cada recurso lista os ROLES permitidos
  - o SQL e recusado se tocar tabela de um recurso que o role nao pode ver

As politicas vivem na tabela Postgres `acl_politicas` (dado em runtime, muda
sem rebuild). Se o Postgres nao responder, cai no DEFAULT_POLITICAS abaixo —
que e restritivo de proposito: na duvida, nega.

Para criar uma restricao nova NAO se mexe em codigo: insere uma linha em
acl_politicas.
"""
from __future__ import annotations

# Hierarquia, do maior para o menor. Usada so para leitura humana e para
# ordenar mensagens — a permissao e SEMPRE por lista explicita, nunca por
# nivel, para evitar que um role novo herde acesso sem alguem decidir.
NIVEL_ROLE: dict[str, int] = {
    "admin": 5,
    "diretor": 4,
    "gerente": 3,
    "supervisor": 2,
    "analista": 1,
}

ROLES_VALIDOS = tuple(NIVEL_ROLE.keys())

# Menor privilegio. Role desconhecido, nulo ou com erro de digitacao cai aqui —
# NUNCA em admin.
ROLE_PADRAO = "analista"


DEFAULT_POLITICAS: list[dict] = [
    {
        "recurso": "comissao",
        "descricao": "Premio, comissao e Gestao de Metas (rotina 3388)",
        "tabelas": ["PCGM%", "PCCOMISSAOUSUR"],
        "roles_permitidos": ["admin", "diretor"],
    },
]


def _casa_padrao(tabela: str, padrao: str) -> bool:
    """Padrao aceita sufixo % como prefixo-livre. 'PCGM%' casa 'PCGMMETACOMB'."""
    t = (tabela or "").upper()
    p = (padrao or "").upper()
    if not t or not p:
        return False
    if p.endswith("%"):
        return t.startswith(p[:-1])
    return t == p


def normaliza_role(role) -> str:
    """Role valido ou ROLE_PADRAO. Nunca devolve admin por omissao."""
    r = (role or "").strip().lower()
    return r if r in ROLES_VALIDOS else ROLE_PADRAO


def recursos_violados(tabelas, role, politicas=None) -> list[dict]:
    """Recursos que este role NAO pode ver entre as tabelas do SQL."""
    pol = DEFAULT_POLITICAS if politicas is None else politicas
    r = normaliza_role(role)
    fora: list[dict] = []
    for p in pol:
        if not p.get("tabelas") or not p.get("roles_permitidos"):
            continue
        if r in [x.lower() for x in p["roles_permitidos"]]:
            continue
        atingidas = [t for t in (tabelas or [])
                     if any(_casa_padrao(t, pad) for pad in p["tabelas"])]
        if atingidas:
            fora.append({**p, "tabelas_atingidas": sorted(set(atingidas))})
    return fora


def mensagem_recusa(violados, role) -> str:
    """Mensagem para o agente: e restricao de PERFIL, nao falha de banco."""
    if not violados:
        return ""
    r = normaliza_role(role)
    nomes = ", ".join(v["recurso"] for v in violados)
    tabs = sorted({t for v in violados for t in v["tabelas_atingidas"]})
    quem = sorted({p for v in violados for p in v["roles_permitidos"]},
                  key=lambda x: -NIVEL_ROLE.get(x, 0))
    return (
        f"ACESSO RESTRITO POR PERFIL. A consulta toca dados de "
        f"'{nomes}' ({', '.join(tabs)}), que o perfil '{r}' nao pode ver.\n"
        f"Liberado para: {', '.join(quem)}.\n\n"
        f"NAO e falha do banco e NAO e erro de SQL — a consulta nem foi "
        f"executada. Diga ao usuario, de forma curta e sem constrangimento, "
        f"que esse dado nao esta disponivel para o perfil dele e que ele pode "
        f"pedir a liberacao a TI. NAO tente contornar por outra tabela, NAO "
        f"estime o valor e NUNCA invente numeros."
    )


# ============================================================
# Carregamento do Postgres, com cache e fallback em codigo.
# Mesmo padrao do acl.py: dado em runtime, muda sem rebuild.
# ============================================================
import os
import time as _time

_CACHE: dict = {"ts": 0.0, "politicas": None}
_TTL_S = 300.0


def carrega_politicas(force: bool = False) -> list[dict]:
    """Le acl_politicas do Postgres. Cai no DEFAULT_POLITICAS se falhar.

    NUNCA devolve lista vazia por erro de conexao: lista vazia liberaria tudo.
    """
    agora = _time.time()
    if (not force and _CACHE["politicas"] is not None
            and (agora - _CACHE["ts"]) < _TTL_S):
        return _CACHE["politicas"]
    try:
        import psycopg
        dsn = (f"host={os.getenv('POSTGRES_HOST','postgres')} "
               f"port={os.getenv('POSTGRES_PORT','5432')} "
               f"dbname={os.getenv('POSTGRES_DB')} "
               f"user={os.getenv('POSTGRES_USER')} "
               f"password={os.getenv('POSTGRES_PASSWORD')}")
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT recurso, descricao, tabelas, "
                            "roles_permitidos FROM acl_politicas WHERE ativa")
                linhas = cur.fetchall()
        pol = []
        for recurso, desc, tabelas, roles in linhas:
            if isinstance(tabelas, str):
                import json as _j
                tabelas = _j.loads(tabelas)
            if isinstance(roles, str):
                import json as _j
                roles = _j.loads(roles)
            pol.append({"recurso": recurso, "descricao": desc,
                        "tabelas": tabelas, "roles_permitidos": roles})
        if pol:
            _CACHE.update(ts=agora, politicas=pol)
            return pol
        # tabela existe mas esta vazia -> ninguem cadastrou politica ainda;
        # usa o default, que e restritivo
        _CACHE.update(ts=agora, politicas=DEFAULT_POLITICAS)
        return DEFAULT_POLITICAS
    except Exception:
        # sem Postgres, NAO libera: mantem o default restritivo
        _CACHE.update(ts=agora, politicas=DEFAULT_POLITICAS)
        return DEFAULT_POLITICAS

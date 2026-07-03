"""
server.py — Servidor MCP HTTP streamable para Oracle Winthor.

Expõe ferramentas read-only do Winthor via MCP HTTP streamable.
Autenticação via Bearer token (MCP_ORACLE_TOKEN).

Fase 1: apenas 1 tool (oracle_query), 2 hardcoded users.
Fase 2: 3 tools + ACL via Oracle table FILIAL_ACL_CHATBOT.

Uso (host):
    cd ~/projects/ebd-ia
    python3 -m mcps.oracle.app.server
"""

from __future__ import annotations

import asyncio
import oracledb

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# ============================================================
# Setup .env + paths
# ============================================================

def _setup_environment() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        env_file = parent / ".env"
        if env_file.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_file)
                print(f"[setup] .env carregado de: {env_file}", file=sys.stderr)
                return parent
            except ImportError:
                return parent
    return here.parent.parent.parent.parent

PROJECT_ROOT = _setup_environment()

# ============================================================
# Imports do app (após .env carregado)
# ============================================================

try:
    from app.pool import get_pool, close_pool, get_config
    from app.acl import resolve_user_by_identifier
    from app.models import UserContext, ToolResponse
except ImportError:
    sys.path.insert(0, str(PROJECT_ROOT))
    from mcps.oracle.app.pool import get_pool, close_pool, get_config
    from mcps.oracle.app.acl import resolve_user_by_identifier
    from mcps.oracle.app.models import UserContext, ToolResponse

import structlog
from mcp.server.fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# ============================================================
# Configuração
# ============================================================

MCP_HOST = os.environ.get("MCP_ORACLE_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_ORACLE_PORT", "8989"))
MCP_TOKEN = os.environ.get("MCP_ORACLE_TOKEN", "")
MCP_LOG_DIR = Path(os.environ.get("MCP_ORACLE_LOG_DIR", str(PROJECT_ROOT / "logs" / "mcp-oracle")))
MCP_LOG_DIR.mkdir(parents=True, exist_ok=True)
MCP_LOG_FILE = MCP_LOG_DIR / "queries.jsonl"

DEFAULT_MAX_ROWS = 1000
ABSOLUTE_MAX_ROWS = 5000
QUERY_TIMEOUT_S = 30

# Palavras-chave proibidas (case-insensitive, fora de strings)
FORBIDDEN_KEYWORDS = [
    r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b",
    r"\bALTER\b", r"\bMERGE\b", r"\bGRANT\b", r"\bREVOKE\b",
    r"\bTRUNCATE\b", r"\bEXECUTE\b", r"\bCALL\b",
    r"\bCOMMIT\b", r"\bROLLBACK\b", r"\bSAVEPOINT\b",
    r"\bCREATE\b",
]


# ============================================================
# Logging estruturado (JSONL no arquivo + console pra dev)
# ============================================================

def _jsonl_writer(_logger, _method_name, event_dict):
    """Processor final que escreve JSONL no arquivo de queries."""
    try:
        with open(MCP_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_dict, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
    return event_dict


structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _jsonl_writer,
        structlog.dev.ConsoleRenderer(colors=False),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger("mcp-oracle")


# ============================================================
# SQL Guard mínimo (Fase 1)
# ============================================================

def _strip_sql_comments(sql: str) -> str:
    """Remove comentários SQL (-- e /* */) pra análise."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def validate_sql(sql: str) -> tuple[bool, str | None]:
    """
    Valida SQL antes de executar.

    Returns:
        (is_valid, error_message)
    """
    if not sql or not sql.strip():
        return False, "SQL vazio"

    clean = _strip_sql_comments(sql).strip()

    # Deve começar com SELECT ou WITH
    first_word = clean.split(None, 1)[0].upper() if clean else ""
    if first_word not in ("SELECT", "WITH"):
        return False, f"Apenas SELECT/WITH permitidos. Detectado: '{first_word}'"

    # Múltiplos statements?
    if ";" in clean.rstrip(";"):
        return False, "Múltiplos statements detectados (apenas 1 query por chamada)"

    # Palavras-chave proibidas
    upper = clean.upper()
    for pattern in FORBIDDEN_KEYWORDS:
        if re.search(pattern, upper):
            return False, f"Palavra-chave proibida detectada: {pattern}"

    return True, None


def inject_row_limit(sql: str, max_rows: int) -> str:
    """Injeta FETCH FIRST se ausente, pra hard cap."""
    clean = _strip_sql_comments(sql).strip().rstrip(";")
    if re.search(r"\bFETCH\s+(FIRST|NEXT)\b", clean, re.IGNORECASE):
        return clean
    return f"{clean} FETCH FIRST {max_rows} ROWS ONLY"


# ============================================================
# Auth middleware
# ============================================================

class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Valida header Authorization: Bearer <MCP_ORACLE_TOKEN>."""

    async def dispatch(self, request: Request, call_next):
        # Health check público
        if request.url.path == "/health":
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"error": "missing_bearer_token"},
                status_code=401,
            )
        token = auth[7:].strip()
        if not MCP_TOKEN or token != MCP_TOKEN:
            log.warning("auth_failed", path=request.url.path, token_prefix=token[:8])
            return JSONResponse(
                {"error": "invalid_token"},
                status_code=401,
            )
        return await call_next(request)


# ============================================================
# MCP server
# ============================================================

mcp = FastMCP(
    name="mcp-oracle-ebd",
    instructions="Servidor MCP read-only para o Winthor Oracle da EBD.",
)


@mcp.tool(
    name="oracle_query",
    description=(
        "Executa SELECT read-only no Oracle Winthor da EBD. "
        "Apenas SELECT/WITH permitidos. Cap automático de linhas. "
        "Sempre forneça user_identifier (celular E.164 ou email) pra resolver ACL."
    ),
)
async def oracle_query(
    sql: str,
    user_identifier: str,
    bind_vars: dict[str, Any] | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    canal: str = "test",
) -> dict[str, Any]:
    """
    Executa SELECT no Oracle Winthor.

    Args:
        sql: Query SELECT (única, sem ; final).
        user_identifier: Celular E.164 (ex: '+5511999990001') ou email.
        bind_vars: Bind variables (ex: {"userFilial": "01"}).
        max_rows: Máximo de linhas (default 1000, cap 5000).
        canal: Origem da chamada (whatsapp, telegram, web, test).

    Returns:
        ToolResponse serializado como dict.
    """
    start = time.perf_counter()
    bind_vars = bind_vars or {}
    max_rows = min(max(1, max_rows), ABSOLUTE_MAX_ROWS)

    # 1. Resolver ACL
    user = resolve_user_by_identifier(user_identifier, canal=canal)
    if user is None:
        elapsed = (time.perf_counter() - start) * 1000
        log.warning("acl_denied", user_identifier=user_identifier, canal=canal)
        return ToolResponse.failure(
            tool="oracle_query",
            code="ACL_USER_NOT_FOUND",
            message=f"Usuário '{user_identifier}' não autorizado.",
            elapsed_ms=elapsed,
        ).model_dump()

    # 2. SQL Guard
    valid, err = validate_sql(sql)
    if not valid:
        elapsed = (time.perf_counter() - start) * 1000
        log.warning("sql_guard_blocked", user_id=user.user_id, reason=err, sql_prefix=sql[:80])
        return ToolResponse.failure(
            tool="oracle_query",
            code="SQL_GUARD_VIOLATION",
            message=err or "SQL inválido",
            elapsed_ms=elapsed,
            user_context=user,
        ).model_dump()

    # 3. Injetar row limit
    final_sql = inject_row_limit(sql, max_rows)

    # 4. Executar
    pool = get_pool()
    call_timeout_ms = get_config().query_timeout_ms  # agora APLICADO de verdade

    def _run_query() -> tuple[list, list]:
        conn = pool.acquire()
        try:
            conn.call_timeout = call_timeout_ms  # estourou -> break no SERVIDOR (DPY-4024)
            with conn.cursor() as cur:
                cur.execute(final_sql, bind_vars)
                _cols = [d[0] for d in cur.description] if cur.description else []
                _rows = cur.fetchall()
            conn.call_timeout = 0
            pool.release(conn)
            return _cols, _rows
        except Exception:
            try:
                conn.call_timeout = 0
                conn.ping()
                pool.release(conn)   # sã: volta ao pool
            except Exception:
                try:
                    pool.drop(conn)  # quebrada: descarta (pool repõe)
                except Exception:
                    pass
            raise

    try:
        cols, rows = await asyncio.to_thread(_run_query)  # event loop LIVRE durante a query
        elapsed = (time.perf_counter() - start) * 1000

        # Serializa rows como list[dict]
        rows_dict = [dict(zip(cols, [str(c) if hasattr(c, "isoformat") else c for c in row])) for row in rows]
        truncated = len(rows) >= max_rows

        log.info(
            "oracle_query_ok",
            user_id=user.user_id,
            user_nome=user.nome,
            user_role=user.role,
            rows=len(rows),
            truncated=truncated,
            elapsed_ms=round(elapsed, 1),
            sql_prefix=final_sql[:200],
        )

        return ToolResponse.success(
            tool="oracle_query",
            result={
                "columns": cols,
                "rows": rows_dict,
                "sql_executed": final_sql,
            },
            elapsed_ms=elapsed,
            user_context=user,
            rows_returned=len(rows),
            truncated=truncated,
        ).model_dump()

    except oracledb.Error as e:
        elapsed = (time.perf_counter() - start) * 1000
        _err = e.args[0] if e.args else None
        full_code = getattr(_err, "full_code", "") or ""
        if full_code in ("DPY-4024", "DPY-4011"):
            log.warning("oracle_query_timeout", user_id=user.user_id,
                        full_code=full_code, elapsed_ms=round(elapsed, 1),
                        sql_prefix=final_sql[:200])
            return ToolResponse.failure(
                tool="oracle_query",
                code="ORACLE_TIMEOUT",
                message=(f"Consulta excedeu o tempo limite ({call_timeout_ms // 1000}s) "
                         "e foi cancelada no banco. Refine o período, filial ou agrupamento."),
                elapsed_ms=elapsed,
                user_context=user,
                details={"sql_executed": final_sql},
            ).model_dump()
        log.error("oracle_query_error", user_id=user.user_id, error=str(e)[:300],
                  full_code=full_code, sql_prefix=final_sql[:200])
        return ToolResponse.failure(
            tool="oracle_query",
            code="ORACLE_ERROR",
            message=str(e)[:500],
            elapsed_ms=elapsed,
            user_context=user,
            details={"sql_executed": final_sql},
        ).model_dump()

    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        err_str = str(e)
        log.error("oracle_query_error", user_id=user.user_id, error=err_str, sql_prefix=final_sql[:200])
        return ToolResponse.failure(
            tool="oracle_query",
            code="ORACLE_ERROR",
            message=err_str[:500],
            elapsed_ms=elapsed,
            user_context=user,
            details={"sql_executed": final_sql},
        ).model_dump()


# ============================================================
# Custom routes (health) — adicionado depois do FastMCP
# ============================================================

@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Health check real: SELECT 1 FROM DUAL com timeout curto."""
    def _ping_oracle():
        pool = get_pool()
        conn = pool.acquire()
        try:
            conn.call_timeout = 5000
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM DUAL")
                cur.fetchone()
            conn.call_timeout = 0
            pool.release(conn)
        except Exception:
            try:
                pool.drop(conn)
            except Exception:
                pass
            raise
    try:
        await asyncio.wait_for(asyncio.to_thread(_ping_oracle), timeout=8)
        return JSONResponse({"status": "healthy", "service": "mcp-oracle", "oracle": "ok"})
    except Exception as e:
        return JSONResponse(
            {"status": "unhealthy", "service": "mcp-oracle", "error": str(e)[:200]},
            status_code=503,
        )


# ============================================================
# Main
# ============================================================

def main() -> int:
    if not MCP_TOKEN:
        log.error("startup_failed", reason="MCP_ORACLE_TOKEN não configurado no .env")
        print("ERRO: MCP_ORACLE_TOKEN não está definido no .env", file=sys.stderr)
        return 1

    # Aquece pool antes de aceitar conexões
    try:
        pool = get_pool()
        cfg = get_config()
        log.info(
            "startup",
            host=MCP_HOST,
            port=MCP_PORT,
            log_file=str(MCP_LOG_FILE),
            oracle=cfg.safe_repr(),
            tools=["oracle_query"],
        )
    except Exception as e:
        log.error("oracle_pool_init_failed", error=str(e))
        return 1

    # FastMCP via streamable-http
    # host/port são configurados via Settings
    mcp.settings.host = MCP_HOST
    mcp.settings.port = MCP_PORT

    # Adiciona middleware de auth no app Starlette interno
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware)

    import uvicorn
    try:
        uvicorn.run(
            app,
            host=MCP_HOST,
            port=MCP_PORT,
            log_level="info",
            access_log=False,
        )
    finally:
        close_pool()

    return 0


if __name__ == "__main__":
    sys.exit(main())

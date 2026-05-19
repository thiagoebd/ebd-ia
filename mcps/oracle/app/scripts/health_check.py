"""
health_check.py — Validação end-to-end da conexão Oracle.

Roda 3 queries que confirmam:
1. Conectividade + autenticação (SELECT 1 FROM DUAL)
2. Versão do Oracle servidor (V$VERSION)
3. Acesso à tabela alvo do permissionamento (EBD.PCLIB)

Funciona em DOIS ambientes:
- Host de desenvolvimento (~/projects/ebd-ia/mcps/oracle/app/scripts/health_check.py)
  rodado como: python3 -m mcps.oracle.app.scripts.health_check
- Container Docker (/app/app/scripts/health_check.py)
  rodado como: python -m app.scripts.health_check

Auto-detecta o ambiente e ajusta imports + carregamento de .env.
"""

import logging
import os
import sys
import time
from pathlib import Path


# ============================================================
# Setup: detecta ambiente e ajusta imports + .env
# ============================================================

def _setup_environment() -> None:
    """Detecta se está rodando no host ou no container e configura."""
    # Caminho deste arquivo
    here = Path(__file__).resolve()

    # Procura o arquivo .env subindo na árvore de pastas
    # No host: sobe até ~/projects/ebd-ia/.env
    # No container: não acha (env vars já vêm do docker compose)
    for parent in here.parents:
        env_file = parent / ".env"
        if env_file.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_file)
                print(f"[setup] .env carregado de: {env_file}")
            except ImportError:
                print("[setup] python-dotenv não disponível, usando env vars existentes")
            break
    else:
        # Não achou .env — assume container (env vars vêm do compose)
        print("[setup] Sem .env encontrado, usando env vars do ambiente")


_setup_environment()


# ============================================================
# Import do pool — tenta os dois caminhos possíveis
# ============================================================

try:
    # Container: estrutura é /app/app/scripts/...
    # PYTHONPATH=/app, então módulo é app.pool
    from app.pool import get_pool, close_pool, get_config
except ImportError:
    # Host: estrutura é ~/projects/ebd-ia/mcps/oracle/app/scripts/...
    # Precisa adicionar a raiz do projeto ao path
    HERE = Path(__file__).resolve()
    # Sobe 4 níveis: scripts -> app -> oracle -> mcps -> raiz_do_projeto
    PROJECT_ROOT = HERE.parents[4]
    sys.path.insert(0, str(PROJECT_ROOT))
    from mcps.oracle.app.pool import get_pool, close_pool, get_config


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("health_check")


# ============================================================
# Lógica do health check
# ============================================================

def run_query(conn, sql: str, description: str) -> tuple[bool, str]:
    """Executa uma query, mede latência, retorna (sucesso, resultado_str)."""
    start = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        elapsed_ms = (time.perf_counter() - start) * 1000
        result_str = f"{len(rows)} linha(s) em {elapsed_ms:.1f}ms"
        if rows:
            result_str += f" → primeira linha: {rows[0]}"
        logger.info("✓ %s — %s", description, result_str)
        return True, result_str
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.error("✗ %s falhou após %.1fms: %s", description, elapsed_ms, e)
        return False, str(e)


def main() -> int:
    print("=" * 70)
    print("Oracle MCP Health Check — EBD.ia")
    print("=" * 70)

    try:
        pool = get_pool()
        cfg = get_config()
        print(f"Config: {cfg.safe_repr()}\n")
    except Exception as e:
        logger.error("Falha ao inicializar pool: %s", e)
        return 1

    queries = [
        ("SELECT 1 FROM DUAL", "Teste 1: Conectividade básica"),
        ("SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1", "Teste 2: Versão Oracle"),
        ("SELECT COUNT(*) FROM EBD.PCLIB", "Teste 3: Acesso a EBD.PCLIB (permissionamento)"),
    ]

    results = []
    try:
        with pool.acquire() as conn:
            for sql, desc in queries:
                ok, msg = run_query(conn, sql, desc)
                results.append((ok, desc, msg))
    finally:
        close_pool()

    # Sumário final
    print("\n" + "=" * 70)
    print("Sumário")
    print("=" * 70)
    for ok, desc, msg in results:
        status = "✓" if ok else "✗"
        print(f"  {status} {desc}")
        print(f"    {msg}")

    all_ok = all(ok for ok, _, _ in results)
    print("\n" + ("✅ Todos os testes passaram." if all_ok else "❌ Algum teste falhou."))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""
config.py — Configuração do MCP Oracle.

Lê variáveis de ambiente (do .env via docker compose ou shell) e expõe
como dataclass imutável. Falha cedo (no import) se algo essencial faltar.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class OracleConfig:
    """Configuração de conexão Oracle (read-only, herdada de .env)."""

    user: str
    password: str
    dsn: str
    pool_min: int = 2
    pool_max: int = 10
    pool_increment: int = 1
    query_timeout_ms: int = 30_000
    default_row_limit: int = 10_000

    @classmethod
    def from_env(cls) -> "OracleConfig":
        """Carrega config das variáveis de ambiente. Falha se algo crítico faltar."""
        required = ["ORACLE_USER", "ORACLE_PASSWORD", "ORACLE_DSN"]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise RuntimeError(
                f"Variáveis de ambiente Oracle faltando: {missing}. "
                f"Verifique o .env do projeto."
            )

        return cls(
            user=os.environ["ORACLE_USER"],
            password=os.environ["ORACLE_PASSWORD"],
            dsn=os.environ["ORACLE_DSN"],
            pool_min=int(os.environ.get("ORACLE_POOL_MIN", "2")),
            pool_max=int(os.environ.get("ORACLE_POOL_MAX", "10")),
            query_timeout_ms=int(os.environ.get("ORACLE_QUERY_TIMEOUT_MS", "30000")),
            default_row_limit=int(os.environ.get("ORACLE_DEFAULT_ROW_LIMIT", "10000")),
        )

    def safe_repr(self) -> str:
        """Representação segura para logs (sem senha)."""
        return (
            f"OracleConfig(user={self.user}, dsn={self.dsn}, "
            f"pool={self.pool_min}-{self.pool_max}, "
            f"timeout_ms={self.query_timeout_ms})"
        )

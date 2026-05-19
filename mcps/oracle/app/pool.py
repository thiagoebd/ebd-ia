"""
pool.py — Connection pool Oracle.

Singleton de pool de conexões via python-oracledb modo Thin (sem Instant Client).
Pool é inicializado preguiçosamente (lazy) na primeira chamada de get_pool().
"""

import logging
from typing import Optional

import oracledb

from .config import OracleConfig

logger = logging.getLogger(__name__)

_pool: Optional[oracledb.ConnectionPool] = None
_config: Optional[OracleConfig] = None


def get_pool() -> oracledb.ConnectionPool:
    """Retorna o pool singleton. Inicializa na primeira chamada."""
    global _pool, _config

    if _pool is not None:
        return _pool

    _config = OracleConfig.from_env()
    logger.info("Inicializando pool Oracle: %s", _config.safe_repr())

    _pool = oracledb.create_pool(
        user=_config.user,
        password=_config.password,
        dsn=_config.dsn,
        min=_config.pool_min,
        max=_config.pool_max,
        increment=_config.pool_increment,
        # Sessão read-only por padrão (defensive — usuário já deve ser RO no Oracle)
        session_callback=_session_init,
    )

    logger.info("Pool Oracle pronto (min=%d, max=%d)", _config.pool_min, _config.pool_max)
    return _pool


def _session_init(conn: oracledb.Connection, requested_tag: str) -> None:
    """Callback executado em cada nova sessão do pool.

    Define defaults da sessão. Por enquanto só timezone — depois podemos
    adicionar ALTER SESSION para NLS_DATE_FORMAT, etc.
    """
    with conn.cursor() as cur:
        cur.execute("ALTER SESSION SET TIME_ZONE = 'America/Sao_Paulo'")


def close_pool() -> None:
    """Fecha o pool. Chamar em shutdown da aplicação."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        logger.info("Pool Oracle fechado")


def get_config() -> OracleConfig:
    """Retorna a config carregada (após get_pool() ter rodado)."""
    if _config is None:
        raise RuntimeError("Pool ainda não foi inicializado. Chame get_pool() primeiro.")
    return _config

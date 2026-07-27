"""Ambiente de teste do MCP Oracle SEM banco.

O server.py importa fora do container; o que falta e a conexao. Aqui ela e
substituida por um pool falso que devolve linhas de ALL_TAB_COLUMNS iguais as
que o Oracle da EBD devolve de verdade (numeros medidos em 27/07/2026).
"""
import datetime
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

# mcps/oracle/app e core/app tem o MESMO nome de pacote ("app"): importar um
# sequestra o outro. Cada um e carregado isolado e guardado sob alias proprio.
import importlib
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("MCP_ORACLE_URL", "http://localhost:8989/mcp")
os.environ.setdefault("MCP_ORACLE_TOKEN", "test")
os.environ.setdefault("EBD_IA_KB_PATH", str(RAIZ / "docs"))
os.environ.setdefault("EBD_IA_REPO_PATH", str(RAIZ))


def _importa_isolado(raiz_pkg, dotted):
    salvos = {k: v for k, v in sys.modules.items()
              if k == "app" or k.startswith("app.")}
    for k in list(salvos):
        del sys.modules[k]
    sys.path.insert(0, str(raiz_pkg))
    try:
        return importlib.import_module(dotted)
    finally:
        try:
            sys.path.remove(str(raiz_pkg))
        except ValueError:
            pass
        for k in list(sys.modules):
            if k == "app" or k.startswith("app."):
                del sys.modules[k]
        sys.modules.update(salvos)


SERVER = _importa_isolado(RAIZ / "mcps" / "oracle", "app.server")
BRIDGE = _importa_isolado(RAIZ / "core", "app.tools.oracle_bridge")

HOJE = datetime.datetime.now()
RECENTE = HOJE - datetime.timedelta(days=17)
VELHA = HOJE - datetime.timedelta(days=400)

# (TABLE_NAME, COLUMN_NAME, NUM_DISTINCT, NUM_NULLS, NUM_ROWS, LAST_ANALYZED)
DICIONARIO = [
    ("PCCARREG", "CODFILIALSAIDA", 0, 1143784, 1153949, RECENTE),
    ("PCCARREG", "CODPERFILVEICULO", 4, 1153940, 1153949, RECENTE),
    ("PCCARREG", "DTSAIDA", 2626, 1, 1153949, RECENTE),
    ("PCCARREG", "DTRETORNO", 3, 1143781, 1153949, RECENTE),
    ("PCCARREG", "KMINICIAL", 1, 751557, 1153949, RECENTE),
    ("PCCARREG", "NUMCAR", 1153949, 0, 1153949, RECENTE),
    ("PCCARREG", "DT_CANCEL", 3900, 703622, 1153949, RECENTE),
    ("PCROTAEXP", "CODROTA", 223, 0, 227, RECENTE),
    ("PCROTAEXP", "KMROTA", 0, 223, 227, RECENTE),
    ("PCROTAEXP", "KMEXCLUIDO", 0, 223, 227, RECENTE),
    ("PCROTAEXP", "DESCRICAO", 221, 0, 227, RECENTE),
    ("PCPEDC", "NUMTRANSWMS", 0, 11540482, 11540482, RECENTE),
    ("PCPEDC", "NUMCAR", 704640, 4, 11540482, RECENTE),
    ("PCMOVENDPEND", "CODFUNCCOFERENTE", 1400, 20000, 97310791, VELHA),
]


class FakeCursor:
    def __init__(self, linhas):
        self._linhas = linhas
        self._resultado = []
        self.description = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, binds=None):
        alvo = {str(v).upper() for v in (binds or {}).values()}
        self._resultado = [r for r in self._linhas if r[0].upper() in alvo]
        self.description = [("TABLE_NAME",), ("COLUMN_NAME",), ("NUM_DISTINCT",),
                            ("NUM_NULLS",), ("NUM_ROWS",), ("LAST_ANALYZED",)]

    def fetchall(self):
        return list(self._resultado)


class FakeConn:
    def __init__(self, linhas):
        self._linhas = linhas
        self.call_timeout = 0

    def cursor(self):
        return FakeCursor(self._linhas)


class FakePool:
    def __init__(self, linhas=None, explode=False):
        self._linhas = DICIONARIO if linhas is None else linhas
        self._explode = explode
        self.liberou = 0

    def acquire(self):
        if self._explode:
            raise RuntimeError("pool esgotado (simulado)")
        return FakeConn(self._linhas)

    def release(self, conn):
        self.liberou += 1


@pytest.fixture
def srv(monkeypatch):
    """server.py do MCP com o pool trocado por um falso."""
    monkeypatch.setattr(SERVER, "get_pool", lambda: FakePool())
    return SERVER


@pytest.fixture
def bridge():
    """oracle_bridge do core (classificacao de erro)."""
    return BRIDGE


@pytest.fixture
def srv_sem_banco(monkeypatch):
    """pool que estoura — a sugestao pode sumir, mas nunca derrubar."""
    monkeypatch.setattr(SERVER, "get_pool", lambda: FakePool(explode=True))
    return SERVER

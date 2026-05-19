"""
mcp_smoke_test.py — Smoke test do servidor MCP via HTTP.

Testa:
1. Health check (sem auth)
2. Auth rejeita token errado
3. Tool oracle_query com user válido (Thiago)
4. Tool oracle_query com user inválido (ACL deny)
5. SQL Guard bloqueia INSERT

Uso:
    cd ~/projects/ebd-ia
    python3 -m mcps.oracle.app.scripts.mcp_smoke_test
"""

import os
import sys
import json
import asyncio
from pathlib import Path

def _setup():
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".env").exists():
            from dotenv import load_dotenv
            load_dotenv(parent / ".env")
            return parent
    return here.parent

PROJECT_ROOT = _setup()

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


MCP_URL = "http://127.0.0.1:8989/mcp"
HEALTH_URL = "http://127.0.0.1:8989/health"
TOKEN = os.environ.get("MCP_ORACLE_TOKEN", "")


def section(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


async def test_with_session(headers, test_fn):
    """Abre uma sessão MCP e roda test_fn(session)."""
    async with streamablehttp_client(MCP_URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await test_fn(session)


async def main():
    if not TOKEN:
        print("ERRO: MCP_ORACLE_TOKEN não está no .env")
        return 1

    print(f"MCP URL: {MCP_URL}")
    print(f"TOKEN: {TOKEN[:16]}...")

    # 1) Health
    section("1) Health check (sem auth)")
    async with httpx.AsyncClient() as client:
        r = await client.get(HEALTH_URL)
        print(f"   GET /health → {r.status_code} {r.json()}")
        assert r.status_code == 200

    # 2) Auth rejeita
    section("2) Token errado → 401")
    async with httpx.AsyncClient() as client:
        r = await client.post(
            MCP_URL,
            headers={"Authorization": "Bearer TOKEN_ERRADO"},
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
        )
        print(f"   POST /mcp (token errado) → {r.status_code}")
        assert r.status_code == 401

    headers = {"Authorization": f"Bearer {TOKEN}"}

    # 3) List tools
    section("3) List tools com token válido")

    async def list_tools(session):
        tools = await session.list_tools()
        for t in tools.tools:
            print(f"   tool: {t.name} — {t.description[:60]}...")
        return tools

    await test_with_session(headers, list_tools)

    # 4) oracle_query com Thiago (admin, * filiais)
    section("4) oracle_query: SELECT 1 FROM DUAL (Thiago admin)")

    async def call_dual(session):
        result = await session.call_tool(
            "oracle_query",
            {
                "sql": "SELECT 1 AS UM FROM DUAL",
                "user_identifier": "+5511999990001",
                "canal": "test",
            },
        )
        payload = json.loads(result.content[0].text)
        print(f"   status: {payload['status']}")
        print(f"   elapsed: {payload['elapsed_ms']:.1f}ms")
        print(f"   rows: {payload.get('rows_returned')}")
        print(f"   user: {payload['metadata']['user_context']['nome']}")
        print(f"   request_id: {payload['request_id']}")
        return payload

    p = await test_with_session(headers, call_dual)
    assert p["status"] == "ok"

    # 5) oracle_query lista filiais (Thiago)
    section("5) oracle_query: SELECT da PCFILIAL (5 filiais)")

    async def call_filiais(session):
        result = await session.call_tool(
            "oracle_query",
            {
                "sql": "SELECT CODIGO, RAZAOSOCIAL, CIDADE, UF FROM EBD.PCFILIAL ORDER BY CODIGO FETCH FIRST 5 ROWS ONLY",
                "user_identifier": "thiago.parreira@ebdgrupo.com.br",
                "canal": "web",
            },
        )
        payload = json.loads(result.content[0].text)
        print(f"   status: {payload['status']}")
        print(f"   rows: {payload.get('rows_returned')}")
        if payload["status"] == "ok":
            for row in payload["result"]["rows"]:
                print(f"     {row}")
        else:
            print(f"   error: {payload['error']}")
        return payload

    p = await test_with_session(headers, call_filiais)
    assert p["status"] == "ok"

    # 6) ACL deny — usuário desconhecido
    section("6) oracle_query com usuário desconhecido → ACL deny")

    async def call_unknown(session):
        result = await session.call_tool(
            "oracle_query",
            {
                "sql": "SELECT 1 FROM DUAL",
                "user_identifier": "+5599999999999",
            },
        )
        payload = json.loads(result.content[0].text)
        print(f"   status: {payload['status']}")
        print(f"   code: {payload['error']['code']}")
        print(f"   msg: {payload['error']['message']}")
        return payload

    p = await test_with_session(headers, call_unknown)
    assert p["status"] == "error"
    assert p["error"]["code"] == "ACL_USER_NOT_FOUND"

    # 7) SQL Guard bloqueia INSERT
    section("7) SQL Guard bloqueia INSERT")

    async def call_insert(session):
        result = await session.call_tool(
            "oracle_query",
            {
                "sql": "INSERT INTO X VALUES (1)",
                "user_identifier": "+5511999990001",
            },
        )
        payload = json.loads(result.content[0].text)
        print(f"   status: {payload['status']}")
        print(f"   code: {payload['error']['code']}")
        print(f"   msg: {payload['error']['message']}")
        return payload

    p = await test_with_session(headers, call_insert)
    assert p["status"] == "error"
    assert p["error"]["code"] == "SQL_GUARD_VIOLATION"

    section("✅ TODOS OS TESTES PASSARAM")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

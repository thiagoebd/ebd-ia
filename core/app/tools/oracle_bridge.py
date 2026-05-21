"""Ponte pro MCP Oracle local. Expoe oracle_query como tool do Claude SDK."""
import asyncio
import json
from typing import Any
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from app.config import settings


ORACLE_QUERY_TOOL = {
    "name": "oracle_query",
    "description": (
        "Executa uma query SQL READ-ONLY contra o Oracle Winthor (EBD). "
        "Use as views GD_FATO_* / GD_DIM_* e tabelas PC* documentadas no system prompt. "
        "SEMPRE filtre por CODFILIAL quando aplicavel. "
        "Retorna ate 1000 linhas. Timeout 60s."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "Query SQL SELECT valida."},
            "max_rows": {"type": "integer", "default": 100},
        },
        "required": ["sql"],
    },
}


def _unwrap_exception(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return " | ".join(_unwrap_exception(e) for e in exc.exceptions)
    return f"{type(exc).__name__}: {str(exc)[:300]}"


async def execute_oracle_query(
    sql: str,
    max_rows: int = 100,
    user_identifier: str = "+5511999990001",
    canal: str = "test",  # MCP aceita: whatsapp|telegram|web|test
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {settings.mcp_oracle_token}"}
    try:
        async with streamablehttp_client(settings.mcp_oracle_url, headers=headers) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await asyncio.wait_for(
                    s.call_tool(
                        "oracle_query",
                        {
                            "sql": sql,
                            "user_identifier": user_identifier,
                            "canal": canal,
                            "max_rows": max_rows,
                        },
                    ),
                    timeout=60,
                )
                # MCP devolveu erro? (isError flag)
                if getattr(res, "isError", False):
                    text = res.content[0].text if res.content else "?"
                    return {"status": "error", "error": {"code": "MCP_ERROR", "message": text[:500]}}
                payload = json.loads(res.content[0].text)
                return payload
    except BaseException as e:
        msg = _unwrap_exception(e)
        return {"status": "error", "error": {"code": "BRIDGE_ERROR", "message": msg}}


def format_result_for_claude(payload: dict) -> str:
    status = payload.get("status", "unknown")
    if status != "ok":
        err = payload.get("error", {})
        return f"ERRO: {err.get('code','?')} - {err.get('message','?')}"
    result = payload.get("result", {})
    rows = result.get("rows", [])
    elapsed = payload.get("elapsed_ms", 0)
    truncated = result.get("truncated", False)
    if not rows:
        return f"OK (0 linhas, {elapsed:.0f}ms)"
    cols = list(rows[0].keys())
    lines = [f"OK ({len(rows)} linhas, {elapsed:.0f}ms){' [TRUNCATED]' if truncated else ''}"]
    lines.append(" | ".join(cols))
    lines.append("-" * 80)
    for r in rows[:50]:
        vals = [str(r.get(c, "")) for c in cols]
        lines.append(" | ".join(vals))
    if len(rows) > 50:
        lines.append(f"... e mais {len(rows)-50} linhas")
    return "\n".join(lines)


if __name__ == "__main__":
    async def main():
        sql = "SELECT 1 AS PING, SYSDATE AS AGORA FROM DUAL"
        print(f"Testando MCP em {settings.mcp_oracle_url}...")
        result = await execute_oracle_query(sql)
        print(f"Status: {result.get('status')}")
        print(format_result_for_claude(result))

    asyncio.run(main())

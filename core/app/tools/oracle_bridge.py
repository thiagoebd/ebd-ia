"""Ponte pro MCP Oracle local. Expoe oracle_query como tool do Claude SDK."""
import asyncio
import json
from typing import Any
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from app.config import settings
import logging
_log = logging.getLogger("uvicorn.error")


ORACLE_QUERY_TOOL = {
    "name": "oracle_query",
    "description": (
        "Executa uma query SQL READ-ONLY contra o Oracle Winthor (EBD). "
        "Use as views GD_FATO_* / GD_DIM_* e tabelas PC* documentadas no system prompt. "
        "SEMPRE filtre por CODFILIAL quando aplicavel. "
        "Retorna ate 1000 linhas. Timeout 20s — se passar disso, refine o periodo/filtro."
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
    user_identifier: str = "service@ebd.ia",
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
                    timeout=90,
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
        code = err.get("code", "?")
        msg = err.get("message", "?")
        _log.warning("oracle_query FAIL code=%s msg=%s", code, str(msg)[:200])
        # Marcador inequivoco que o agent/gateway detectam pra BLOQUEAR fabulacao
        return (f"__ORACLE_ERROR__ A consulta ao Winthor FALHOU ({code}: {msg}). "
                f"Voce NAO TEM dados. NUNCA invente numeros. Responda exatamente: "
                f"'Nao consegui consultar o Winthor agora — tenta de novo daqui a pouco?'")
    result = payload.get("result", {})
    rows = result.get("rows", [])
    elapsed = payload.get("elapsed_ms", 0)
    truncated = result.get("truncated", False)
    if not rows:
        _log.info("oracle_query OK rows=0 elapsed=%.0fms", elapsed)
        return f"OK (0 linhas, {elapsed:.0f}ms)"
    _log.info("oracle_query OK rows=%d elapsed=%.0fms truncated=%s", len(rows), elapsed, truncated)
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



# ─── Variante streaming pra o agente web ──────────────────────────────────
# Roda a query em task paralela e yielda heartbeat a cada HEARTBEAT_SECS
# enquanto ela não termina. Telegram continua usando execute_oracle_query
# normal (call único). Web usa esta pra ter feedback vivo no SSE.

HEARTBEAT_SECS = 15
ORACLE_TIMEOUT = 90


async def execute_oracle_query_streaming(
    sql: str,
    max_rows: int = 100,
    user_identifier: str = "service@ebd.ia",
    canal: str = "web",
):
    """Async generator. Yielda:
      {"type":"progress","elapsed":N} a cada 15s
      {"type":"result","payload":{...}} no fim (sucesso ou erro)
    """
    import time
    task = asyncio.create_task(execute_oracle_query(
        sql=sql, max_rows=max_rows,
        user_identifier=user_identifier, canal=canal,
    ))
    t0 = time.monotonic()
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=HEARTBEAT_SECS)
        except asyncio.TimeoutError:
            elapsed = int(time.monotonic() - t0)
            yield {"type": "progress", "elapsed": elapsed}
            if elapsed >= ORACLE_TIMEOUT + 5:
                task.cancel()
                yield {"type": "result", "payload": {
                    "status": "error",
                    "error": {"code": "TIMEOUT", "message": f"Query passou de {ORACLE_TIMEOUT}s — interrompida."},
                }}
                return
    yield {"type": "result", "payload": task.result()}

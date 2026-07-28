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


_ORA_INFRA = ("ORA-03113", "ORA-03114", "ORA-12541", "ORA-12170", "ORA-01033",
              "ORA-00028", "ORA-12514", "DPY-", "TNS-")

_DICAS = {
    "ORA-00904": ("Coluna INEXISTENTE. NAO tente variacoes do nome — descubra o "
                  "nome real primeiro: SELECT COLUMN_NAME FROM ALL_TAB_COLUMNS "
                  "WHERE OWNER='EBD' AND TABLE_NAME='<TABELA>'. Cheque tambem o "
                  "sql-corrections.md: varias colunas do Winthor tem grafia "
                  "inesperada (DT_CANCEL com underscore, CODFUNCCOFERENTE com "
                  "erro de digitacao)."),
    "ORA-00942": ("Tabela ou view nao existe (ou sem permissao). Confira o nome e "
                  "o prefixo EBD. Tabelas terminadas em 6 digitos de data sao "
                  "fotografias antigas e nao devem ser usadas."),
    "ORA-30076": ("EXTRACT(HOUR/MINUTE FROM ...) so funciona em TIMESTAMP. Em "
                  "coluna DATE use TO_CHAR(coluna,'HH24'). Ver cicatriz #66."),
    "ORA-01722": ("Conversao numerica invalida. Coluna VARCHAR2 com texto sendo "
                  "comparada a NUMBER — converta o lado NUMBER com TO_CHAR."),
    "ORA-01481": ("Mascara de formato invalida no TO_CHAR/TO_NUMBER. Cheque a "
                  "mascara e o tipo do argumento."),
    "ORA-00979": ("Coluna fora do GROUP BY. Toda coluna nao agregada do SELECT "
                  "precisa estar no GROUP BY."),
    "ORA-01858": ("Formato de data nao bate com o valor. Use TO_DATE com mascara "
                  "explicita ou literais DATE 'YYYY-MM-DD'."),
    "ORA-00918": "Coluna ambigua: qualifique com o alias da tabela.",
    "ORA-00936": "Expressao ausente: SELECT/WHERE incompleto.",
    "ORA-00933": "Comando SQL nao termina corretamente.",
}


def _instrucao_por_erro(code: str, msg: str) -> str:
    """Traduz o erro do Oracle em instrucao acionavel para o agente.

    SQL malformado e RECUPERAVEL: o agente deve corrigir e chamar a tool de
    novo. So infra/timeout justifica dizer ao usuario que o banco falhou.
    """
    m = (msg or "").upper()
    c = (code or "").upper()

    if c == "SQL_PREFLIGHT":
        # A mensagem do pre-voo ja e a instrucao: lista o que esta errado e
        # qual e o nome certo. Repassar inteira, sem envelope de "falhou".
        return (f"{msg}\n\nNUNCA invente numeros e NUNCA diga ao usuario que "
                f"o banco falhou — a consulta nem chegou no Oracle.")

    base = f"A consulta ao Winthor FALHOU ({code}: {msg}). NUNCA invente numeros."

    if c == "TIMEOUT" or "TIMEOUT" in m or "PASSOU DE" in m:
        return (f"{base} Causa: a query demorou demais. REESCREVA mais leve e "
                f"tente de novo: filtre CODFILIAL, encurte o periodo, evite "
                f"varrer tabela grande sem indice. NAO diga que o banco caiu.")

    if any(t in m for t in ("ESCOPO", "PERMISS", "NAO AUTORIZ", "FORA DO ESCOPO",
                            "ACL", "RECUSAD", "BLOQUEAD")):
        return (f"{base} Isso NAO e falha do banco: a consulta foi barrada pelo "
                f"escopo de acesso do usuario. Explique que o dado pedido esta "
                f"fora do escopo dele e ofereca o recorte que ele pode ver.")

    if any(t in m for t in _ORA_INFRA):
        return (f"{base} Causa: indisponibilidade de conexao com o banco. "
                f"Responda que o Winthor esta indisponivel no momento e peca "
                f"para tentar daqui a pouco.")

    ora = ""
    for k in _DICAS:
        if k in m:
            ora = k
            break

    if ora or "ORA-" in m:
        dica = _DICAS.get(ora, "Revise a sintaxe e os nomes de coluna do SQL.")
        return (f"{base} Isso e ERRO NA SUA CONSULTA, nao no banco — o Winthor "
                f"esta no ar. {dica} CORRIJA o SQL e chame a tool NOVAMENTE. "
                f"NAO diga ao usuario que o banco falhou e NAO desista na "
                f"primeira tentativa.")

    return (f"{base} Causa nao identificada. Tente UMA correcao do SQL; se "
            f"falhar de novo, explique ao usuario o que voce tentou consultar e "
            f"peca para ele reformular a pergunta.")


def format_result_for_claude(payload: dict) -> str:
    status = payload.get("status", "unknown")
    if status != "ok":
        err = payload.get("error", {})
        code = err.get("code", "?")
        msg = err.get("message", "?")
        _log.warning("oracle_query FAIL code=%s msg=%s", code, str(msg)[:200])
        # Marcador inequivoco que o agent/gateway detectam pra BLOQUEAR fabulacao.
        # A CLASSE do erro decide a instrucao: erro de SQL e RECUPERAVEL (o agente
        # corrige e tenta de novo); infra nao e.
        return "__ORACLE_ERROR__ " + _instrucao_por_erro(code, msg)
    result = payload.get("result", {})
    rows = result.get("rows", [])
    elapsed = payload.get("elapsed_ms", 0)
    truncated = result.get("truncated", False)
    if not rows:
        _log.info("oracle_query OK rows=0 elapsed=%.0fms", elapsed)
        # o MCP anexa aviso quando ZERO linhas vem de consulta de CADASTRO:
        # seguir a analise sobre conjunto vazio produz conclusao falsa com
        # aparencia de dado real
        _aviso = result.get("aviso") or ""
        return f"OK (0 linhas, {elapsed:.0f}ms){_aviso}"
    _log.info("oracle_query OK rows=%d elapsed=%.0fms truncated=%s", len(rows), elapsed, truncated)
    cols = list(rows[0].keys())
    lines = [f"OK ({len(rows)} linhas, {elapsed:.0f}ms){' [TRUNCATED]' if truncated else ''}"]
    if len(rows) > 50:
        lines.append(f"[PREVIEW: voce esta vendo 50 de {len(rows)} linhas — as demais "
                     f"NAO estao no seu contexto. Para gerar Excel/artefato com TODAS "
                     f"as linhas, chame create_excel com use_last_result=true "
                     f"(NUNCA re-digite as linhas).]")
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

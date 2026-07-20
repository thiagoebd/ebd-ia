import re


# ============================================================
# Cache do ultimo resultado Oracle por conversa (passagem por REFERENCIA).
# Motivo (bug 06/07): format_result_for_claude mostra so 50 linhas ao modelo;
# re-emitir N linhas como tokens na tool call estoura max_tokens (~50-70k tokens
# para 1.200 linhas). Aqui o dado flui handler->handler sem passar pelo modelo:
# integridade byte a byte + custo ~200 tokens em vez de dezenas de milhares.
# ============================================================
_LAST_RESULT_CACHE: dict[str, dict] = {}


def _store_last_result(payload: dict | None) -> None:
    try:
        if not payload or payload.get("status") != "ok":
            return
        rows = (payload.get("result") or {}).get("rows") or []
        if not rows:
            return
        if len(_LAST_RESULT_CACHE) > 100:  # bound de memoria; rotacao simples
            _LAST_RESULT_CACHE.clear()
        _LAST_RESULT_CACHE[_conv_id_ctx.get() or "_"] = {
            "rows": rows,
            "count": len(rows),
        }
    except Exception:
        pass  # cache e best-effort; nunca derruba o turno


def _classify_sql_subject(sql: str) -> str:
    """SQL -> assunto em linguagem de negocio (status vivo, sem cozinha tecnica)."""
    s = (sql or "").upper()
    if "FORNEC" in s:
        return "Analisando fornecedores (consulta detalhada)"
    if "REGIONAL" in s:
        return "Consolidando visao regional"
    if "ESTOQUE" in s or "PCEST" in s:
        return "Verificando estoque"
    if "CONTASRECEBER" in s or "PCPREST" in s or "INADIMPL" in s:
        return "Analisando carteira e inadimplencia"
    if "RUPTURA" in s:
        return "Analisando ruptura"
    if "META" in s:
        return "Cruzando com metas"
    if "VISITA" in s:
        return "Verificando visitas"
    if "POSITIV" in s:
        return "Analisando positivacao"
    if "FATURAMENTO" in s or "VLATEND" in s or "VENDA" in s:
        return "Consultando faturamento"
    return "Consultando dados comerciais"
"""Loop principal do agente EBD.ia.

Otimizacoes:
- Modelo: Sonnet 4.6 (5x mais barato que Opus 4.7)
- Prompt caching no system prompt (-80% custo)
- Historico limitado a ultimas 6 trocas
- Tools: oracle_query, knowledge_append, list_proposals
"""
import asyncio
from anthropic import AsyncAnthropic
from app.config import settings
from app.system_prompt import build_system_prompt
from app.tools.oracle_bridge import (
    ORACLE_QUERY_TOOL,
    execute_oracle_query,
    execute_oracle_query_streaming,
    format_result_for_claude,
)
from app.tools.artifact_tools import CREATE_EXCEL_TOOL, CREATE_PDF_TOOL, CREATE_PPTX_TOOL, CREATE_CHART_TOOL
from app.tools.chart_builder import build_chart
from app.tools.template_catalog import (
    LIST_TEMPLATES_TOOL, GET_TEMPLATE_TOOL, tool_list_templates, tool_get_template,
)
from app.tools.excel_builder import build_excel
from app.tools.pdf_builder import build_pdf
from app.tools.pptx_builder import build_pptx
import contextvars as _contextvars
_conv_id_ctx: _contextvars.ContextVar = _contextvars.ContextVar("ebd_conv_id", default=None)
from app.artifacts import now_br_str
from app.tools.knowledge_append import (
    KNOWLEDGE_APPEND_TOOL,
    LIST_PROPOSALS_TOOL,
    tool_knowledge_append,
    tool_list_proposals,
)

_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
_system_prompt = build_system_prompt()
_tools = [ORACLE_QUERY_TOOL, KNOWLEDGE_APPEND_TOOL, LIST_PROPOSALS_TOOL, CREATE_EXCEL_TOOL, CREATE_PDF_TOOL, CREATE_PPTX_TOOL, CREATE_CHART_TOOL, LIST_TEMPLATES_TOOL, GET_TEMPLATE_TOOL]


def reload_system_prompt() -> int:
    """Reconstrói o system prompt em memória (relê os .md do disco).
    Chamado após /aprovar fazer merge na main, pra knowledge nova 'pegar'
    sem precisar reiniciar o processo. Retorna tamanho em chars."""
    global _system_prompt
    _system_prompt = build_system_prompt()
    return len(_system_prompt)


def current_date_line() -> str:
    """Linha de data/hora recalculada A CADA TURNO (nunca congela no boot).
    Vai no ctx_suffix, fora do _system_prompt estatico que fica em cache."""
    from datetime import datetime
    import zoneinfo
    _now = datetime.now(zoneinfo.ZoneInfo("America/Sao_Paulo"))
    _dia = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"][_now.weekday()]
    return (
        f"Data atual: {_now.strftime('%d/%m/%Y')} ({_dia}), "
        f"{_now.strftime('%H:%M')} (Sao Paulo, UTC-3).\n"
    )

MAX_HISTORY_PAIRS = 10


from app.tools.gate_template import checar_gate


async def _run_tool(tool_name: str, tool_input: dict, user_id: str, user_role: str,
                    consultou_catalogo: bool = False) -> str:
    if tool_name == "oracle_query":
        sql = tool_input.get("sql", "")
        _acao, _txt = checar_gate(sql, consultou_catalogo)
        if _acao == "bloquear":
            return _txt
        max_rows = tool_input.get("max_rows", 100)
        result = await execute_oracle_query(sql, max_rows=max_rows)
        _out = format_result_for_claude(result)
        return _out + _txt if _acao == "dica" else _out
    if tool_name == "knowledge_append":
        return tool_knowledge_append(
            tipo=tool_input.get("tipo", ""),
            titulo=tool_input.get("titulo", ""),
            conteudo=tool_input.get("conteudo", ""),
            justificativa=tool_input.get("justificativa", ""),
            user_id=user_id,
            user_role=user_role,
        )
    if tool_name == "list_proposals":
        return tool_list_proposals(user_id=user_id)
    if tool_name == "create_excel":
        return await _run_create_excel(tool_input, user_id)
    if tool_name == "create_pdf":
        return await _run_create_pdf(tool_input, user_id)
    if tool_name == "create_pptx":
        return await _run_create_pptx(tool_input, user_id)
    if tool_name == "create_chart":
        return await _run_create_chart(tool_input, user_id)
    if tool_name == "list_templates":
        return tool_list_templates(familia=tool_input.get("familia"))
    if tool_name == "get_template":
        return tool_get_template(code=tool_input.get("code", ""))
    return f"ERRO: tool '{tool_name}' nao implementada"


def _trim_history(messages: list, max_pairs: int = MAX_HISTORY_PAIRS) -> list:
    """Trim history preservando integridade tool_use/tool_result.
    
    Regras:
    1. Cap em max_pairs * 2 mensagens
    2. Primeira mensagem SEMPRE deve ser 'user' SEM tool_result órfão
    3. Última mensagem DEVE ter todos os tool_use respondidos
       (se tem tool_use no fim sem tool_result, descarta esse par)
    """
    if not messages or len(messages) <= max_pairs * 2:
        # Mesmo assim verifica integridade do fim
        return _drop_orphan_tool_use_at_end(messages)
    
    candidate = messages[-(max_pairs * 2):]
    
    # Avança o início até achar user "limpo" (sem tool_result órfão)
    while candidate:
        first = candidate[0]
        if first.get("role") != "user":
            candidate = candidate[1:]
            continue
        content = first.get("content")
        if isinstance(content, str):
            break
        if isinstance(content, list):
            has_tool_result = any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if has_tool_result:
                candidate = candidate[1:]
                continue
            break
        candidate = candidate[1:]
    
    # Remove tool_use órfão no FIM (se assistant terminou com tool_use mas 
    # próximo turn não retornou tool_result — pode acontecer em truncamento)
    return _drop_orphan_tool_use_at_end(candidate)


def _drop_orphan_tool_use_at_end(messages: list) -> list:
    """Se a última mensagem assistant tem tool_use sem tool_result na próxima,
    remove o par inteiro pra não corromper o histórico."""
    if len(messages) < 2:
        return messages
    
    # Última mensagem deve ser assistant pra checar
    while messages and messages[-1].get("role") == "assistant":
        content = messages[-1].get("content")
        if isinstance(content, list):
            has_tool_use = any(
                isinstance(b, dict) and (b.get("type") == "tool_use" or hasattr(b, 'type') and b.type == "tool_use")
                for b in content
            )
            if has_tool_use:
                # Última msg é assistant com tool_use sem tool_result depois → drop
                messages = messages[:-1]
                continue
        break
    
    return messages

async def run_turn(
    user_message: str,
    conversation_history: list | None = None,
    user_id: str = "thiago",
    user_role: str = "admin",
    user_filiais: str = "*",
    channel: str = "cli",
 model: str | None = None) -> dict:
    messages = list(conversation_history or [])
    messages = _trim_history(messages)
    messages.append({"role": "user", "content": user_message})

    ctx_suffix = (
        f"\n\n## CONTEXTO DA CONVERSA ATUAL\n"
        f"- User ID: {user_id}\n"
        f"- Role: {user_role}\n"
        f"- Filiais permitidas: {user_filiais}\n"
        f"- CANAL: {channel}  ← APLIQUE AS REGRAS DE FORMATAÇÃO DO CANAL\n"
    )
    if user_role == "admin":
        ctx_suffix += (
            "- Voce PODE propor auto-append na knowledge base via tool knowledge_append "
            "quando descobrir fato novo util (template SQL validado, cicatriz, regra de negocio). "
            "NAO use pra dados volateis. Sempre peca '/aprovar PROP-XXXX' depois de propor.\n"
        )
    else:
        ctx_suffix += (
            "- Voce NAO TEM permissao pra propor auto-append (apenas admin). "
            "Se descobrir algo util, sugira ao usuario contatar um admin.\n"
        )

    system_blocks = [{
        "type": "text",
        "text": current_date_line() + _system_prompt + ctx_suffix,
        "cache_control": {"type": "ephemeral", "ttl": "1h"},  # 1h em vez de 5min default
    }]

    tool_calls_log = []
    iterations = 0
    consultou_catalogo = False

    while iterations < settings.max_iterations:
        iterations += 1
        response = await _client.messages.create(
            model=model or settings.claude_model,
            max_tokens=settings.max_tokens,
            system=system_blocks,
            tools=_tools,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return {
                "text": "\n".join(text_blocks),
                "tool_calls": tool_calls_log,
                "iterations": iterations,
                "history": messages,
                "stop_reason": response.stop_reason,
                "model": getattr(response, "model", ""),
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
                    "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
                },
            }

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_calls_log.append({"name": block.name, "input": block.input, "id": block.id})
                if block.name in ("list_templates", "get_template"):
                    consultou_catalogo = True
                result_str = await _run_tool(block.name, block.input, user_id, user_role, consultou_catalogo)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })
        messages.append({"role": "user", "content": tool_results})

    return {
        "text": "[Agent atingiu limite de iteracoes]",
        "tool_calls": tool_calls_log,
        "iterations": iterations,
        "history": messages,
        "stop_reason": "max_iterations",
        "usage": {},
    }



async def run_turn_stream(
    user_message: str,
    conversation_history: list | None = None,
    user_id: str = "thiago",
    user_role: str = "admin",
    user_filiais: str = "*",
    channel: str = "web",
    model: str | None = None,
    user_email: str | None = None,
):
    """Versao streaming de run_turn. Em vez de retornar dict no fim,
    da yield de eventos conforme processa:
      {"type": "status",  "text": "..."}       -> fase (consultando, analisando)
      {"type": "token",   "text": "..."}       -> pedaco de texto da resposta final
      {"type": "tool",    "name": "...", "input": {...}} -> tool sendo chamada
      {"type": "done",    "history": [...], "usage": {...}, "tool_calls": [...]}

    NAO substitui run_turn (Telegram continua usando o original).
    """
    messages = list(conversation_history or [])
    messages = _trim_history(messages)
    messages.append({"role": "user", "content": user_message})

    ctx_suffix = (
        f"\n\n## CONTEXTO DA CONVERSA ATUAL\n"
        f"- User ID: {user_id}\n"
        f"- Role: {user_role}\n"
        f"- Filiais permitidas: {user_filiais}\n"
        f"- CANAL: {channel}  <- APLIQUE AS REGRAS DE FORMATACAO DO CANAL\n"
    )
    if user_role == "admin":
        ctx_suffix += (
            "- Voce PODE propor auto-append na knowledge base via tool knowledge_append "
            "quando descobrir fato novo util (template SQL validado, cicatriz, regra de negocio). "
            "NAO use pra dados volateis. Sempre peca '/aprovar PROP-XXXX' depois de propor.\n"
        )
    else:
        ctx_suffix += (
            "- Voce NAO TEM permissao pra propor auto-append (apenas admin). "
            "Se descobrir algo util, sugira ao usuario contatar um admin.\n"
        )

    system_blocks = [{
        "type": "text",
        "text": current_date_line() + _system_prompt + ctx_suffix,
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }]

    tool_calls_log = []
    iterations = 0
    final_usage = {}
    _usage_acc = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    consultou_catalogo = False
    tool_outcomes = []  # [(tool_name, success_bool), ...] desta turn

    while iterations < settings.max_iterations:
        iterations += 1

        # Streaming da chamada ao Claude
        text_acc = ""
        tool_uses = []  # blocks tool_use desta iteracao
        async with _client.messages.stream(
            model=model or settings.claude_model,
            max_tokens=settings.max_tokens,
            system=system_blocks,
            tools=_tools,
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if getattr(delta, "type", None) == "text_delta":
                        text_acc += delta.text
                        yield {"type": "token", "text": delta.text}
            final_message = await stream.get_final_message()

        # Registra a mensagem do assistant no historico.
        # Serializa SO os campos que a API aceita na ENTRADA (whitelist por tipo).
        # model_dump() cru vaza campos de saida (parsed_output, etc) que a API
        # rejeita quando o historico e reenviado no proximo turno -> erro 400.
        assistant_content = []
        for b in final_message.content:
            btype = getattr(b, "type", None)
            if btype == "text":
                assistant_content.append({"type": "text", "text": b.text})
            elif btype == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": b.id,
                    "name": b.name,
                    "input": b.input,
                })
            # outros tipos (thinking, etc) sao ignorados no historico reenviado
        messages.append({"role": "assistant", "content": assistant_content})

        # Acumula usage de TODAS as iteracoes (a API cobra cada chamada do loop;
        # cache_write aparece so na iteracao que grava, cache_read nas que leem — somar da o total certo)
        _usage_acc["input_tokens"] += final_message.usage.input_tokens
        _usage_acc["output_tokens"] += final_message.usage.output_tokens
        _usage_acc["cache_creation_input_tokens"] += getattr(final_message.usage, "cache_creation_input_tokens", 0)
        _usage_acc["cache_read_input_tokens"] += getattr(final_message.usage, "cache_read_input_tokens", 0)
        final_usage = {
            "input_tokens": _usage_acc["input_tokens"],
            "output_tokens": _usage_acc["output_tokens"],
            "cache_creation_input_tokens": _usage_acc["cache_creation_input_tokens"],
            "cache_read_input_tokens": _usage_acc["cache_read_input_tokens"],
        }

        # Terminou? (sem tool_use) -> emite done e encerra
        if final_message.stop_reason != "tool_use":
            yield {
                "type": "done",
                "history": messages,
                "tool_calls": tool_calls_log,
                "tool_outcomes": tool_outcomes,
                "iterations": iterations,
                "usage": final_usage,
                "stop_reason": final_message.stop_reason,
            }
            return

        # Tem tool_use -> executa cada tool e emite status
        tool_results = []
        for block in final_message.content:
            if block.type == "tool_use":
                tool_calls_log.append({"name": block.name, "input": block.input, "id": block.id})
                if block.name in ("list_templates", "get_template"):
                    consultou_catalogo = True
                # status amigavel por tipo de tool
                if block.name == "oracle_query":
                    sql = (block.input or {}).get("sql", "")
                    _assunto = _classify_sql_subject(sql)
                    _passo = len([t for t in tool_calls_log if t["name"] == "oracle_query"])
                    yield {"type": "status", "text": f"Passo {_passo} — {_assunto}..."}
                    yield {"type": "tool", "name": block.name, "input": block.input}
                    _acao_g, _txt_g = checar_gate(sql, consultou_catalogo)
                    if _acao_g == "bloquear":
                        result_str = _txt_g
                        tool_outcomes.append((block.name, False))
                        yield {"type": "tool_done", "name": block.name, "success": False}
                        tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_str})
                        continue
                    # roda em modo streaming pra emitir progresso
                    final_payload = None
                    async for ev in execute_oracle_query_streaming(
                        sql=sql,
                        max_rows=(block.input or {}).get("max_rows", 100),
                        user_identifier=user_email or "service@ebd.ia",
                        canal="web",
                    ):
                        if ev["type"] == "progress":
                            _extra = " · consulta detalhada, pode levar ate 1 min" if ev["elapsed"] >= 20 else ""
                            yield {"type": "status",
                                   "text": f"Passo {_passo} — {_assunto}... {ev['elapsed']}s{_extra}"}
                        else:
                            final_payload = ev["payload"]
                    _store_last_result(final_payload)
                    result_str = format_result_for_claude(final_payload)
                    if _acao_g == "dica":
                        result_str = result_str + _txt_g
                    import logging as _fl
                    _fl.getLogger("uvicorn.error").info("ORACLE_FORENSE sql=%r >>> result=%r", sql[:300], result_str[:400])
                    _ok = not (isinstance(result_str, str) and result_str.startswith("__ORACLE_ERROR__"))
                    tool_outcomes.append((block.name, _ok))
                    yield {"type": "tool_done", "name": block.name, "success": _ok}
                else:
                    if block.name == "knowledge_append":
                        yield {"type": "status", "text": "Registrando conhecimento..."}
                    elif block.name == "list_proposals":
                        yield {"type": "status", "text": "Listando propostas..."}
                    elif block.name == "create_excel":
                        yield {"type": "status", "text": "Montando a planilha Excel..."}
                    elif block.name == "create_pdf":
                        yield {"type": "status", "text": "Gerando o documento PDF..."}
                    elif block.name == "create_pptx":
                        yield {"type": "status", "text": "Montando a apresentação..."}
                    elif block.name == "create_chart":
                        yield {"type": "status", "text": "Montando o gráfico..."}
                    elif block.name in ("list_templates", "get_template"):
                        yield {"type": "status", "text": "Selecionando a consulta padrão..."}
                    else:
                        yield {"type": "status", "text": f"Executando {block.name}..."}
                    yield {"type": "tool", "name": block.name, "input": block.input}
                    result_str = await _run_tool(block.name, block.input, user_id, user_role)
                    _ok = not (isinstance(result_str, str) and (result_str.startswith("ERRO") or result_str.startswith("__ORACLE_ERROR__")))
                    tool_outcomes.append((block.name, _ok))
                    yield {"type": "tool_done", "name": block.name, "success": _ok}

                # Se a tool retornou ARTEFATO_CRIADO, emite evento pro frontend
                if isinstance(result_str, str) and result_str.startswith('ARTEFATO_CRIADO'):
                    _m_id = re.search(r'id=(\S+)', result_str)
                    _m_fn = re.search(r'filename="([^"]+)"', result_str)
                    _m_sz = re.search(r'size_bytes=(\d+)', result_str)
                    _m_kd = re.search(r'type=(\S+)', result_str)
                    if _m_id and _m_fn:
                        yield {
                            'type': 'artifact',
                            'id': _m_id.group(1),
                            'kind': _m_kd.group(1) if _m_kd else 'xlsx',
                            'filename': _m_fn.group(1),
                            'size_bytes': int(_m_sz.group(1)) if _m_sz else 0,
                        }
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })
        messages.append({"role": "user", "content": tool_results})
        yield {"type": "status", "text": "Analisando os dados..."}

    # Esgotou iteracoes
    yield {
        "type": "done",
        "history": messages,
        "tool_calls": tool_calls_log,
        "iterations": iterations,
        "usage": final_usage,
        "stop_reason": "max_iterations",
    }


if __name__ == "__main__":
    async def main():
        print(f"Modelo: {settings.claude_model}")
        print(f"Tools: {[t['name'] for t in _tools]}")
        print()
        question = "Quais tools voce tem disponiveis e quando deve usar cada uma?"
        print(f">>> {question}")
        result = await run_turn(question)
        print()
        print(f"<<< {result['text']}")
        u = result.get("usage", {})
        print(f"\nTokens: in={u.get('input_tokens',0)} out={u.get('output_tokens',0)} cache_r={u.get('cache_read_input_tokens',0):,}")
    asyncio.run(main())


async def _run_create_excel(tool_input: dict, user_id: str) -> str:
    """Executa a tool create_excel: gera o XLSX e registra no Postgres.

    Retorna texto pro Claude (1-2 linhas) com o ID do artefato.
    O frontend renderiza o card a partir do evento {type:"artifact"} emitido
    em run_turn_stream após esta função retornar.
    """
    import logging
    logger = logging.getLogger("uvicorn.error")
    try:
        title = tool_input.get("title", "Planilha EBD")
        subtitle = tool_input.get("subtitle")
        sheets = tool_input.get("sheets", [])
        metadata = tool_input.get("metadata", {})

        if not sheets:
            return "ERRO: nenhuma aba fornecida (parâmetro 'sheets' vazio)"

        # PASSAGEM POR REFERENCIA: injeta as rows completas da ultima oracle_query
        if tool_input.get("use_last_result"):
            _cached = _LAST_RESULT_CACHE.get(_conv_id_ctx.get() or "_")
            if not _cached:
                return ("ERRO: use_last_result=true mas nao ha resultado de "
                        "oracle_query nesta conversa. Rode a consulta primeiro.")
            if len(sheets) != 1:
                return ("ERRO: use_last_result suporta exatamente 1 aba nesta "
                        "versao. Envie 1 aba (as colunas mapeiam o resultado).")
            sheets[0]["rows"] = _cached["rows"]
            logger.info("create_excel use_last_result: %d linhas injetadas do cache",
                        _cached["count"])

        # Gera o arquivo
        artifact_id, file_path, filename, size_bytes = build_excel(
            title=title,
            sheets=sheets,
            subtitle=subtitle,
            metadata=metadata,
        )

        # Registra no Postgres via gateway.db (requer pool já inicializado)
        from gateway.app import db as gw_db
        row = await gw_db.create_artifact(
            conversation_id=_conv_id_ctx.get(),
            user_oid=str(user_id),
            kind="xlsx",
            filename=filename,
            title=title,
            file_path=str(file_path),
            size_bytes=size_bytes,
            metadata={
                "source_label": metadata.get("source_label", ""),
                "period": metadata.get("period", ""),
                "scope": metadata.get("scope", ""),
                "subtitle": subtitle or "",
                "rows_total": sum(len(sh.get("rows", [])) for sh in sheets),
            },
        )
        # Devolve um payload bem direto pro Claude — ele só precisa saber que deu certo + ID
        # para mencionar na resposta. O card vem por evento SSE separado.
        return (
            f"ARTEFATO_CRIADO type=xlsx id={row['id']} "
            f'filename="{filename}" size_bytes={size_bytes}'
        )
    except Exception as e:
        logger.exception("Erro ao gerar Excel")
        return f"ERRO ao gerar planilha: {type(e).__name__}: {str(e)[:200]}"


async def _run_create_chart(tool_input: dict, user_id: str) -> str:
    """create_chart: valida spec (line|bar, max 2 series, max 60 pontos, footer
    obrigatorio — Cleveland & McGill 1984; Few 2004), grava JSON, registra no PG."""
    import logging
    logger = logging.getLogger("uvicorn.error")
    try:
        title = tool_input.get("title", "Grafico EBD")
        artifact_id, file_path, filename, size_bytes = build_chart(tool_input)
        from gateway.app import db as gw_db
        row = await gw_db.create_artifact(
            conversation_id=_conv_id_ctx.get(),
            user_oid=str(user_id),
            kind="chart",
            filename=filename,
            title=title,
            file_path=str(file_path),
            size_bytes=size_bytes,
            metadata={
                "chart_type": tool_input.get("chart_type", ""),
                "points": len(tool_input.get("data", [])),
                "series": len(tool_input.get("series", [])),
                "footer": tool_input.get("footer", ""),
            },
        )
        return (
            f"ARTEFATO_CRIADO type=chart id={row['id']} "
            f'filename="{filename}" size_bytes={size_bytes}'
        )
    except ValueError as e:
        return f"ERRO na spec do grafico: {e}"
    except Exception as e:
        logger.exception("Erro ao gerar grafico")
        return f"ERRO ao gerar grafico: {type(e).__name__}: {str(e)[:200]}"


async def _run_create_pdf(tool_input: dict, user_id: str) -> str:
    """Executa a tool create_pdf: gera o PDF e registra no Postgres."""
    import logging
    logger = logging.getLogger("uvicorn.error")
    try:
        title = tool_input.get("title", "Relatório EBD")
        subtitle = tool_input.get("subtitle")
        markdown_body = tool_input.get("markdown_body", "")
        metadata = tool_input.get("metadata", {})

        if not markdown_body.strip():
            return "ERRO: markdown_body vazio"

        artifact_id, file_path, filename, size_bytes = build_pdf(
            title=title,
            markdown_body=markdown_body,
            subtitle=subtitle,
            metadata=metadata,
        )

        from gateway.app import db as gw_db
        row = await gw_db.create_artifact(
            conversation_id=_conv_id_ctx.get(),
            user_oid=str(user_id),
            kind="pdf",
            filename=filename,
            title=title,
            file_path=str(file_path),
            size_bytes=size_bytes,
            metadata={
                "source_label": metadata.get("source_label", ""),
                "period": metadata.get("period", ""),
                "scope": metadata.get("scope", ""),
                "subtitle": subtitle or "",
            },
        )
        return (
            f"ARTEFATO_CRIADO type=pdf id={row['id']} "
            f'filename="{filename}" size_bytes={size_bytes}'
        )
    except Exception as e:
        logger.exception("Erro ao gerar PDF")
        return f"ERRO ao gerar PDF: {type(e).__name__}: {str(e)[:200]}"



async def _run_create_pptx(tool_input: dict, user_id: str) -> str:
    """Executa a tool create_pptx: gera o deck PPTX e registra no Postgres."""
    import logging
    logger = logging.getLogger("uvicorn.error")
    try:
        title         = tool_input.get("title", "Apresentação EBD")
        subtitle      = tool_input.get("subtitle", "")
        footer_author = tool_input.get("footer_author", "EBD.ia")
        slides        = tool_input.get("slides", [])

        if not slides:
            return "ERRO: lista 'slides' está vazia"
        if not any(s.get("kind") == "cover" for s in slides):
            return "ERRO: deck obrigatoriamente começa com kind='cover'"

        # Gera path no /var/ebd-ia/artifacts (mesmo helper do Excel/PDF)
        from app.artifacts import new_artifact_path
        _artifact_id_disk, file_path = new_artifact_path("pptx")

        # Constrói o deck no path certo
        _, fp, filename, size_bytes = build_pptx(
            title=title,
            subtitle=subtitle,
            slides=slides,
            footer_author=footer_author,
            output_path=file_path,
        )

        # Registra no Postgres via gateway (cicatriz 4: usa row['id'])
        from gateway.app import db as gw_db
        row = await gw_db.create_artifact(
            conversation_id=_conv_id_ctx.get(),
            user_oid=str(user_id),
            kind="pptx",
            filename=filename,
            title=title,
            file_path=str(fp),
            size_bytes=size_bytes,
            metadata={
                "subtitle": subtitle,
                "slides_count": len(slides),
                "kinds": [s.get("kind") for s in slides],
            },
        )
        return (
            f"ARTEFATO_CRIADO type=pptx id={row['id']} "
            f'filename="{filename}" size_bytes={size_bytes}'
        )
    except Exception as e:
        logger.exception("Erro ao gerar PPTX")
        return f"ERRO ao gerar PPTX: {type(e).__name__}: {str(e)[:200]}"

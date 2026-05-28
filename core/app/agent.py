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
    format_result_for_claude,
)
from app.tools.knowledge_append import (
    KNOWLEDGE_APPEND_TOOL,
    LIST_PROPOSALS_TOOL,
    tool_knowledge_append,
    tool_list_proposals,
)

_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
_system_prompt = build_system_prompt()
_tools = [ORACLE_QUERY_TOOL, KNOWLEDGE_APPEND_TOOL, LIST_PROPOSALS_TOOL]

MAX_HISTORY_PAIRS = 10


async def _run_tool(tool_name: str, tool_input: dict, user_id: str, user_role: str) -> str:
    if tool_name == "oracle_query":
        sql = tool_input.get("sql", "")
        max_rows = tool_input.get("max_rows", 100)
        result = await execute_oracle_query(sql, max_rows=max_rows)
        return format_result_for_claude(result)
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
) -> dict:
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
        "text": _system_prompt + ctx_suffix,
        "cache_control": {"type": "ephemeral", "ttl": "1h"},  # 1h em vez de 5min default
    }]

    tool_calls_log = []
    iterations = 0

    while iterations < settings.max_iterations:
        iterations += 1
        response = await _client.messages.create(
            model=settings.claude_model,
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
                result_str = await _run_tool(block.name, block.input, user_id, user_role)
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

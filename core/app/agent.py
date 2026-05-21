"""Loop principal do agente EBD.ia.

Otimizacoes:
- Modelo: Sonnet 4.6 (5x mais barato que Opus 4.7)
- Prompt caching no system prompt (-80% custo, ttl 5min default)
- Historico limitado a ultimas 6 trocas pra reduzir tokens
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


_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
_system_prompt = build_system_prompt()
_tools = [ORACLE_QUERY_TOOL]

# Limite de historico (em pares user/assistant) — evita inflar tokens em chats longos
MAX_HISTORY_PAIRS = 6  # = 12 mensagens (6 perguntas + 6 respostas)


async def _run_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "oracle_query":
        sql = tool_input.get("sql", "")
        max_rows = tool_input.get("max_rows", 100)
        result = await execute_oracle_query(sql, max_rows=max_rows)
        return format_result_for_claude(result)
    return f"ERRO: tool '{tool_name}' nao implementada"


def _trim_history(messages: list, max_pairs: int = MAX_HISTORY_PAIRS) -> list:
    """Mantem apenas ultimas N trocas (preserva inicio se quiser system context)."""
    if len(messages) <= max_pairs * 2:
        return messages
    # Pega ultimas N * 2 mensagens
    return messages[-(max_pairs * 2):]


async def run_turn(
    user_message: str,
    conversation_history: list | None = None,
    user_role: str = "admin",
    user_filiais: str = "*",
) -> dict:
    """Roda um turn do agente."""
    messages = list(conversation_history or [])
    messages = _trim_history(messages)
    messages.append({"role": "user", "content": user_message})

    ctx_suffix = (
        f"\n\n## CONTEXTO DA CONVERSA ATUAL\n"
        f"- Role: {user_role}\n"
        f"- Filiais permitidas: {user_filiais}\n"
    )

    # Prompt caching: marca system prompt como cacheavel (vale 5min, depois renova)
    system_blocks = [
        {
            "type": "text",
            "text": _system_prompt + ctx_suffix,
            "cache_control": {"type": "ephemeral"},
        }
    ]

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
            final_text = "\n".join(text_blocks)
            return {
                "text": final_text,
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
                tool_calls_log.append({
                    "name": block.name,
                    "input": block.input,
                    "id": block.id,
                })
                result_str = await _run_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })

        messages.append({"role": "user", "content": tool_results})

    return {
        "text": "[Agent atingiu limite de iteracoes sem resposta final]",
        "tool_calls": tool_calls_log,
        "iterations": iterations,
        "history": messages,
        "stop_reason": "max_iterations",
        "usage": {},
    }


if __name__ == "__main__":
    async def main():
        print(f"Modelo: {settings.claude_model}")
        print(f"System prompt: {len(_system_prompt):,} chars (com prompt caching ativo)")
        print()
        question = "Quanto faturou Manaus hoje?"
        print(f">>> {question}")
        result = await run_turn(question)
        print()
        print(f"<<< {result['text']}")
        u = result.get("usage", {})
        print()
        print(f"Tokens: input={u.get('input_tokens',0):,} | output={u.get('output_tokens',0):,}")
        print(f"Cache:  criado={u.get('cache_creation_input_tokens',0):,} | lido={u.get('cache_read_input_tokens',0):,}")

    asyncio.run(main())

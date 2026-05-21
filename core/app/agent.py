"""Loop principal do agente EBD.ia.

Recebe input do usuario, chama Claude Opus 4.7, executa tools conforme
o modelo decidir, devolve resposta final. Suporta multi-turn (tool_use
em loop ate Claude responder sem mais tool_use).
"""
import asyncio
from typing import AsyncIterator
from anthropic import AsyncAnthropic
from app.config import settings
from app.system_prompt import build_system_prompt
from app.tools.oracle_bridge import (
    ORACLE_QUERY_TOOL,
    execute_oracle_query,
    format_result_for_claude,
)


# Inicializa cliente Claude (lazy: 1 vez por processo)
_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
_system_prompt = build_system_prompt()
_tools = [ORACLE_QUERY_TOOL]


async def _run_tool(tool_name: str, tool_input: dict) -> str:
    """Despacha tool call do Claude pra implementacao real."""
    if tool_name == "oracle_query":
        sql = tool_input.get("sql", "")
        max_rows = tool_input.get("max_rows", 100)
        result = await execute_oracle_query(sql, max_rows=max_rows)
        return format_result_for_claude(result)
    return f"ERRO: tool '{tool_name}' nao implementada"


async def run_turn(
    user_message: str,
    conversation_history: list | None = None,
    user_role: str = "admin",
    user_filiais: str = "*",
) -> dict:
    """Roda um turn completo do agente.

    Args:
        user_message: input do usuario
        conversation_history: lista de mensagens anteriores (multi-turn)
        user_role: papel do usuario (vendedor|gerente|supervisor|diretor|admin)
        user_filiais: filiais permitidas (CSV ou "*")

    Returns:
        {"text": resposta_final, "tool_calls": [...], "iterations": N, "history": [...]}
    """
    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": user_message})

    # Contexto do usuario apendado ao system prompt
    ctx_suffix = f"\n\n## CONTEXTO DA CONVERSA ATUAL\n- Role: {user_role}\n- Filiais permitidas: {user_filiais}\n"
    system_full = _system_prompt + ctx_suffix

    tool_calls_log = []
    iterations = 0

    while iterations < settings.max_iterations:
        iterations += 1

        response = await _client.messages.create(
            model=settings.claude_model,
            max_tokens=settings.max_tokens,
            system=system_full,
            tools=_tools,
            messages=messages,
        )

        # Acumula resposta do assistente no historico
        messages.append({"role": "assistant", "content": response.content})

        # Se nao tem tool_use, terminou
        if response.stop_reason != "tool_use":
            text_blocks = [b.text for b in response.content if b.type == "text"]
            final_text = "\n".join(text_blocks)
            return {
                "text": final_text,
                "tool_calls": tool_calls_log,
                "iterations": iterations,
                "history": messages,
                "stop_reason": response.stop_reason,
            }

        # Executa cada tool_use que veio
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

        # Devolve resultados de tools pro proximo turn
        messages.append({"role": "user", "content": tool_results})

    # Atingiu max_iterations
    return {
        "text": "[Agent atingiu limite de iteracoes sem resposta final]",
        "tool_calls": tool_calls_log,
        "iterations": iterations,
        "history": messages,
        "stop_reason": "max_iterations",
    }


# Smoke test
if __name__ == "__main__":
    async def main():
        print(f"Modelo: {settings.claude_model}")
        print(f"System prompt: {len(_system_prompt):,} chars")
        print(f"Tools: {[t['name'] for t in _tools]}")
        print()
        question = "Quanto faturou a filial Manaus hoje? Use oracle_query."
        print(f">>> Pergunta: {question}")
        print()

        result = await run_turn(question)
        print(f"<<< Resposta ({result['iterations']} iteracoes, {len(result['tool_calls'])} tool calls):")
        print(result["text"])
        print()
        print("Tool calls executadas:")
        for tc in result["tool_calls"]:
            sql = tc["input"].get("sql", "")[:200]
            print(f"  - {tc['name']}: {sql}")

    asyncio.run(main())

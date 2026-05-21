"""CLI interativo do agent EBD.ia.

Loop de chat no terminal. Suporta:
- multi-turn (mantem historico)
- /reset (limpa historico)
- /historico (mostra o historico)
- /sair (encerra)
- Ctrl+C (encerra)
"""
import asyncio
import sys
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from app.agent import run_turn
from app.config import settings

console = Console()


async def chat_loop():
    console.print(Panel.fit(
        f"[bold cyan]EBD.ia[/bold cyan] — agente comercial conversacional\n"
        f"Modelo: {settings.claude_model}\n"
        f"Comandos: [yellow]/reset[/yellow] limpa historico | [yellow]/historico[/yellow] mostra | [yellow]/sair[/yellow] encerra",
        border_style="cyan",
    ))
    historico = []
    while True:
        try:
            pergunta = Prompt.ask("\n[bold green]>>>[/bold green]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Encerrando...[/dim]")
            break

        if not pergunta:
            continue
        if pergunta == "/sair":
            break
        if pergunta == "/reset":
            historico = []
            console.print("[yellow]Historico limpo.[/yellow]")
            continue
        if pergunta == "/historico":
            console.print(f"[dim]Mensagens no historico: {len(historico)}[/dim]")
            for i, msg in enumerate(historico):
                role = msg.get("role", "?")
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = f"[{len(content)} blocks]"
                else:
                    content = str(content)[:80]
                console.print(f"  [{i}] {role}: {content}")
            continue

        with console.status("[cyan]pensando...[/cyan]"):
            result = await run_turn(pergunta, conversation_history=historico)

        historico = result["history"]
        console.print()
        console.print(Markdown(result["text"]))
        console.print(
            f"[dim]({result['iterations']} iteracoes, "
            f"{len(result['tool_calls'])} tool calls)[/dim]"
        )


if __name__ == "__main__":
    asyncio.run(chat_loop())

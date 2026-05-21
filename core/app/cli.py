"""CLI interativo do agent EBD.ia — com tracking de custo."""
import asyncio
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from app.agent import run_turn
from app.config import settings

console = Console()

# Pricing Sonnet 4.6 (US$ por MTok) — out abr/2026
PRICE_INPUT = 3.00 / 1_000_000
PRICE_OUTPUT = 15.00 / 1_000_000
PRICE_CACHE_WRITE = 3.75 / 1_000_000  # +25% sobre input
PRICE_CACHE_READ = 0.30 / 1_000_000   # -90% (10x mais barato)
USD_BRL = 5.20  # ~


def calc_cost_usd(u: dict) -> float:
    return (
        u.get("input_tokens", 0) * PRICE_INPUT
        + u.get("output_tokens", 0) * PRICE_OUTPUT
        + u.get("cache_creation_input_tokens", 0) * PRICE_CACHE_WRITE
        + u.get("cache_read_input_tokens", 0) * PRICE_CACHE_READ
    )


async def chat_loop():
    console.print(Panel.fit(
        f"[bold cyan]EBD.ia[/bold cyan] — agente comercial conversacional\n"
        f"Modelo: {settings.claude_model} (prompt cache ATIVO)\n"
        f"Comandos: [yellow]/reset[/yellow] | [yellow]/historico[/yellow] | [yellow]/sair[/yellow]",
        border_style="cyan",
    ))
    historico = []
    total_usd = 0.0
    while True:
        try:
            pergunta = Prompt.ask("\n[bold green]>>>[/bold green]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[dim]Total da sessao: US$ {total_usd:.4f} (R$ {total_usd*USD_BRL:.4f})[/dim]")
            break

        if not pergunta:
            continue
        if pergunta == "/sair":
            console.print(f"[dim]Total da sessao: US$ {total_usd:.4f} (R$ {total_usd*USD_BRL:.4f})[/dim]")
            break
        if pergunta == "/reset":
            historico = []
            console.print("[yellow]Historico limpo.[/yellow]")
            continue
        if pergunta == "/historico":
            console.print(f"[dim]Mensagens: {len(historico)}[/dim]")
            continue

        with console.status("[cyan]pensando...[/cyan]"):
            result = await run_turn(pergunta, conversation_history=historico)

        historico = result["history"]
        u = result.get("usage", {})
        cost_usd = calc_cost_usd(u)
        total_usd += cost_usd

        console.print()
        console.print(Markdown(result["text"]))
        console.print(
            f"[dim]({result['iterations']} iter, {len(result['tool_calls'])} tools | "
            f"in={u.get('input_tokens',0):,} out={u.get('output_tokens',0):,} "
            f"cache_w={u.get('cache_creation_input_tokens',0):,} cache_r={u.get('cache_read_input_tokens',0):,} | "
            f"US$ {cost_usd:.4f} = R$ {cost_usd*USD_BRL:.4f} | "
            f"total: R$ {total_usd*USD_BRL:.4f})[/dim]"
        )


if __name__ == "__main__":
    asyncio.run(chat_loop())

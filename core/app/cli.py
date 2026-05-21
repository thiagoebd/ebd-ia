"""CLI interativo do agent EBD.ia.

Comandos:
  /reset                  - limpa historico
  /historico              - mostra mensagens
  /aprovar PROP-XXXX      - aprova proposta de auto-append (grava+commit+push)
  /descartar PROP-XXXX    - descarta proposta pendente
  /sair                   - encerra
"""
import asyncio
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from app.agent import run_turn
from app.config import settings
from app.tools.knowledge_append import approve_proposal, discard_proposal

console = Console()

PRICE_INPUT = 3.00 / 1_000_000
PRICE_OUTPUT = 15.00 / 1_000_000
PRICE_CACHE_WRITE = 3.75 / 1_000_000
PRICE_CACHE_READ = 0.30 / 1_000_000
USD_BRL = 5.20

# Hardcoded enquanto nao tem ACL real
USER_ID = "thiago"
USER_ROLE = "admin"
USER_FILIAIS = "*"


def calc_cost_usd(u: dict) -> float:
    return (
        u.get("input_tokens", 0) * PRICE_INPUT
        + u.get("output_tokens", 0) * PRICE_OUTPUT
        + u.get("cache_creation_input_tokens", 0) * PRICE_CACHE_WRITE
        + u.get("cache_read_input_tokens", 0) * PRICE_CACHE_READ
    )


async def chat_loop():
    console.print(Panel.fit(
        f"[bold cyan]EBD.ia[/bold cyan] - agente comercial conversacional\n"
        f"Modelo: {settings.claude_model} (prompt cache ATIVO)\n"
        f"User: {USER_ID} | Role: {USER_ROLE}\n"
        f"Comandos: [yellow]/reset /historico /aprovar PROP-X /descartar PROP-X /sair[/yellow]",
        border_style="cyan",
    ))
    historico = []
    total_usd = 0.0
    while True:
        try:
            pergunta = Prompt.ask("\n[bold green]>>>[/bold green]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[dim]Total sessao: R$ {total_usd*USD_BRL:.4f}[/dim]")
            break

        if not pergunta:
            continue
        if pergunta == "/sair":
            console.print(f"[dim]Total sessao: R$ {total_usd*USD_BRL:.4f}[/dim]")
            break
        if pergunta == "/reset":
            historico = []
            console.print("[yellow]Historico limpo.[/yellow]")
            continue
        if pergunta == "/historico":
            console.print(f"[dim]Mensagens: {len(historico)}[/dim]")
            continue

        # /aprovar PROP-XXXX
        if pergunta.startswith("/aprovar "):
            pid = pergunta.split(maxsplit=1)[1].strip()
            with console.status(f"[cyan]Aprovando {pid}...[/cyan]"):
                r = approve_proposal(pid, user_name=USER_ID)
            color = "green" if r["ok"] else "red"
            console.print(f"[{color}]{r['msg']}[/{color}]")
            continue

        # /descartar PROP-XXXX
        if pergunta.startswith("/descartar "):
            pid = pergunta.split(maxsplit=1)[1].strip()
            r = discard_proposal(pid)
            color = "yellow" if r["ok"] else "red"
            console.print(f"[{color}]{r['msg']}[/{color}]")
            continue

        with console.status("[cyan]pensando...[/cyan]"):
            result = await run_turn(
                pergunta,
                conversation_history=historico,
                user_id=USER_ID,
                user_role=USER_ROLE,
                user_filiais=USER_FILIAIS,
            )

        historico = result["history"]
        u = result.get("usage", {})
        cost_usd = calc_cost_usd(u)
        total_usd += cost_usd

        console.print()
        console.print(Markdown(result["text"]))
        console.print(
            f"[dim]({result['iterations']} iter, {len(result['tool_calls'])} tools | "
            f"in={u.get('input_tokens',0):,} out={u.get('output_tokens',0):,} "
            f"cache_r={u.get('cache_read_input_tokens',0):,} | "
            f"R$ {cost_usd*USD_BRL:.4f} | total: R$ {total_usd*USD_BRL:.4f})[/dim]"
        )


if __name__ == "__main__":
    asyncio.run(chat_loop())

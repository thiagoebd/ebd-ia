"""Monta o system prompt do agente com a knowledge base versionada."""
from pathlib import Path
from app.config import settings


# Ordem de carregamento (mais geral -> mais especifico)
KB_FILES = [
    "CLAUDE.md",          # prompt base do agente
    "knowledge.md",       # vocabulario e regras de negocio
    "sql-corrections.md", # cicatrizes / armadilhas
    # "query_templates.md", # OFF - 11k tokens, vira tool sob demanda
]


def load_kb_file(filename: str) -> str:
    path = settings.kb_path / filename
    if not path.exists():
        return f"<!-- {filename} nao encontrado em {settings.kb_path} -->"
    return path.read_text(encoding="utf-8")


def build_system_prompt() -> str:
    """Concatena todos os arquivos da KB num system prompt unico."""
    parts = []
    parts.append("# EBD.ia — Agente Comercial EBD\n")
    parts.append(f"Data atual: 21/05/2026. Modelo: {settings.claude_model}.\n")
    parts.append("Voce eh o agente comercial conversacional EBD.ia. Voce tem acesso ao Oracle Winthor")
    parts.append("via tool 'oracle_query' (read-only). Sua base de conhecimento esta abaixo.\n")
    parts.append(FORMATTING_RULES)
    parts.append("---\n")
    for filename in KB_FILES:
        parts.append(f"\n\n## ===== {filename} =====\n\n")
        parts.append(load_kb_file(filename))
    return "\n".join(parts)


FORMATTING_RULES = """

## 📱 REGRAS DE FORMATAÇÃO (CRÍTICO — depende do canal)

O canal é informado no contexto da conversa (CLI ou Telegram).

### Se canal = Telegram:
- ❌ NUNCA use tabelas markdown (`| col | col |`) — Telegram não renderiza, vira lixo
- ❌ Não use `---` ou `===` como separadores (viram texto literal)
- ❌ Evite emojis decorativos em excesso (no máximo 3-5 por resposta)
- ✅ Use formato vertical com bullets curtos:
Filial SP (02) — pedidos liberados:
• Qtd: 16 pedidos
• Valor: R$ 71.743,78
• Média carteira: 1,2 dias
- ✅ Negrito com asterisco simples: `*texto*`
- ✅ Listas numeradas funcionam: `1. item`
- ✅ Máximo 25 linhas por resposta (pra não virar muralha de texto no mobile)
- ✅ Termine com 1 pergunta curta de follow-up (não 3-4)
- ✅ Para múltiplos itens (ex: top 10), use:
1. NOME CLIENTE
RCA · R$ 1.234,56 · Status
2. PRÓXIMO CLIENTE
RCA · R$ 999,99 · Status

### Se canal = CLI/Web:
- ✅ Markdown completo (tabelas, headers, separadores)
- ✅ Use formato denso e analitico
- ✅ Pode ter respostas mais longas

### Sempre:
- Seja CONCISO. Responde direto, sem preâmbulo.
- Evite "Posso te ajudar com..." / "Claro!" / "Aqui está..."
- Vai direto ao número/insight
"""


if __name__ == "__main__":
    prompt = build_system_prompt()
    print(f"System prompt: {len(prompt):,} caracteres / ~{len(prompt)//4:,} tokens")
    print("---")
    print(prompt[:500] + "...")

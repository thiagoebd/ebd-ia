"""Monta o system prompt do agente com a knowledge base versionada."""
from pathlib import Path
from app.config import settings


# Ordem de carregamento (mais geral -> mais especifico)
KB_FILES = [
    "CLAUDE.md",          # prompt base do agente
    "knowledge.md",       # vocabulario e regras de negocio
    "sql-corrections.md", # cicatrizes / armadilhas
    "query_templates.md", # 51 templates validados
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
    parts.append("---\n")
    for filename in KB_FILES:
        parts.append(f"\n\n## ===== {filename} =====\n\n")
        parts.append(load_kb_file(filename))
    return "\n".join(parts)


if __name__ == "__main__":
    prompt = build_system_prompt()
    print(f"System prompt: {len(prompt):,} caracteres / ~{len(prompt)//4:,} tokens")
    print("---")
    print(prompt[:500] + "...")

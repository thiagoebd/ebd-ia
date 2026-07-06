"""
template_catalog.py — recuperacao DETERMINISTICA de templates SQL canonicos.

Motivacao (medida em producao 06/07/2026): 12/17 erros das ultimas 200 queries
eram ORA-00904 de discovery por tentativa-erro; recuperacao de templates do meio
de um prompt de 13,5k tokens degrada sistematicamente (Liu et al., "Lost in the
Middle", TACL 2024). Aqui a recuperacao e por codigo: sem curva de atencao.

Fonte: core/app/data/templates.json — DERIVADO de docs/query_templates.md
(regenerar com o build_catalog apos editar o .md; nunca editar o json na mao).
"""

from __future__ import annotations

import json
from pathlib import Path

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "templates.json"
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    return _cache


def tool_list_templates(familia: str | None = None) -> str:
    """Indice compacto: codigo, familia, validacao, titulo, binds."""
    try:
        cat = _load()
    except Exception as e:
        return f"ERRO ao carregar catalogo: {type(e).__name__}"
    ts = cat["templates"]
    fams = sorted({t["familia"] for t in ts})
    if familia:
        familia = familia.strip().lower()
        sel = [t for t in ts if t["familia"] == familia]
        if not sel:
            return (f"Nenhum template na familia '{familia}'. "
                    f"Familias disponiveis: {', '.join(fams)}")
    else:
        sel = ts
    linhas = [f"{len(sel)} templates" + (f" na familia '{familia}'" if familia else "")
              + f" (familias: {', '.join(fams)}):"]
    for t in sel:
        val = " [VALIDADO vs BI/ERP]" if t["validated"] else ""
        binds = ", ".join(t["binds"]) if t["binds"] else "nenhum (BR consolidado)"
        linhas.append(f"- {t['code']}{val} — {t['title']} | binds: {binds}")
    linhas.append("Use get_template(codigo) para obter o SQL exato.")
    return "\n".join(linhas)


def tool_get_template(code: str) -> str:
    """SQL canonico exato de um template. Executar SEM modificar (so preencher binds)."""
    try:
        cat = _load()
    except Exception as e:
        return f"ERRO ao carregar catalogo: {type(e).__name__}"
    code = (code or "").strip().upper()
    for t in cat["templates"]:
        if t["code"] == code:
            cab = [f"-- {t['code']} — {t['title']}"]
            if t["validated"] and t.get("validation_note"):
                cab.append(f"-- VALIDADO: {t['validation_note']}")
            if t.get("latency_note"):
                cab.append(f"-- Latencia esperada: {t['latency_note']}")
            cab.append(f"-- Binds a preencher: {', '.join(t['binds']) or 'nenhum'}")
            cab.append("-- EXECUTE EXATAMENTE como esta. Nao renomeie colunas/aliases.")
            return "\n".join(cab) + "\n" + t["sql"]
    disponiveis = ", ".join(t["code"] for t in cat["templates"])
    return f"ERRO: template '{code}' nao existe. Disponiveis: {disponiveis}"


LIST_TEMPLATES_TOOL = {
    "name": "list_templates",
    "description": (
        "Indice dos templates SQL CANONICOS e VALIDADOS do Winthor. "
        "OBRIGATORIO chamar ANTES de escrever qualquer SQL novo: se existir template "
        "da familia da pergunta, use get_template e execute-o em vez de improvisar. "
        "Instantaneo (leitura local, nao toca o banco)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "familia": {
                "type": "string",
                "description": ("Filtro opcional: faturamento, fornecedores, pedidos, "
                                "inadimplencia, equipe_campo, clientes, estoque, "
                                "regionais, metas. Omitir = indice completo."),
            },
        },
    },
}

GET_TEMPLATE_TOOL = {
    "name": "get_template",
    "description": (
        "Retorna o SQL canonico EXATO de um template (ex: 'T210'). Execute-o sem "
        "modificar a estrutura — apenas preencha os binds indicados. Templates "
        "marcados VALIDADO batem centavo com BI/ERP. Instantaneo (local)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Codigo do template, ex: T210"},
        },
        "required": ["code"],
    },
}

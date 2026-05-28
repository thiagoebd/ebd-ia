"""Tools de auto-append na knowledge base.

SEGURANCA:
- Apenas role='admin' pode propor (validado no _run_tool do agent)
- Whitelist de arquivos: query_templates, sql-corrections, knowledge
- Append-only, nunca UPDATE/DELETE
- Approval loop obrigatorio (cria proposta, aguarda /aprovar)
- Commit em branch 'agent-proposals' (nunca main)
- Cada commit assinado por 'ebd-ia-bot via <user>'
"""
import subprocess
from pathlib import Path
from app.config import settings
from app.tools.proposals import (
    create_proposal,
    get_proposal,
    mark_approved,
    mark_discarded,
    list_pending,
)

# Whitelist absoluta — apenas estes 3 arquivos podem ser appendados
ARQUIVOS_PERMITIDOS = {
    "template": "query_templates.md",
    "cicatriz": "sql-corrections.md",
    "conhecimento": "knowledge.md",
}

BRANCH_PROPOSTAS = "agent-proposals"


# ============================================================
# Schemas das tools (formato Claude API)
# ============================================================

KNOWLEDGE_APPEND_TOOL = {
    "name": "knowledge_append",
    "description": (
        "PROPOE (nao grava direto) um append na base de conhecimento. "
        "USE APENAS quando descobriu fato novo util e usuario tem role='admin'. "
        "Tipos: 'template' (SQL validada), 'cicatriz' (erro+correcao), 'conhecimento' (regra negocio). "
        "Apos chamar, mostre preview ao usuario e peca '/aprovar PROP-XXXX' pra gravar. "
        "NAO use pra dados volateis (faturamento de hoje nao vira knowledge!)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tipo": {
                "type": "string",
                "enum": ["template", "cicatriz", "conhecimento"],
                "description": "Tipo do append.",
            },
            "titulo": {
                "type": "string",
                "description": "Titulo curto da proposta (max 80 chars).",
            },
            "conteudo": {
                "type": "string",
                "description": "Markdown completo a ser appendado no arquivo destino.",
            },
            "justificativa": {
                "type": "string",
                "description": "Por que isso vale virar knowledge persistente.",
            },
        },
        "required": ["tipo", "titulo", "conteudo", "justificativa"],
    },
}

LIST_PROPOSALS_TOOL = {
    "name": "list_proposals",
    "description": (
        "Lista propostas pendentes de auto-append do usuario atual. "
        "Util quando usuario pergunta o que esta pra aprovar."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


# ============================================================
# Implementacoes das tools (chamadas pelo agent)
# ============================================================

def tool_knowledge_append(
    tipo: str,
    titulo: str,
    conteudo: str,
    justificativa: str,
    user_id: str,
    user_role: str,
) -> str:
    """Cria proposta pendente. Retorna mensagem pro Claude mostrar ao usuario."""
    if user_role != "admin":
        return (
            f"PERMISSAO_NEGADA: apenas 'admin' pode propor auto-append. "
            f"Role atual: '{user_role}'."
        )
    if tipo not in ARQUIVOS_PERMITIDOS:
        return f"ERRO: tipo invalido '{tipo}'. Use: template, cicatriz, conhecimento."
    if not conteudo.strip() or len(conteudo) < 20:
        return "ERRO: conteudo muito curto. Append precisa ser substancial."

    pid = create_proposal(tipo, titulo, conteudo, justificativa, user_id)
    arquivo = ARQUIVOS_PERMITIDOS[tipo]

    return (
        f"PROPOSTA_CRIADA: {pid}\n"
        f"Tipo: {tipo}\n"
        f"Arquivo destino: docs/{arquivo}\n"
        f"Titulo: {titulo}\n"
        f"Justificativa: {justificativa}\n"
        f"---PREVIEW---\n"
        f"{conteudo}\n"
        f"---FIM PREVIEW---\n"
        f"Para gravar: usuario deve responder '/aprovar {pid}' no chat.\n"
        f"Para descartar: '/descartar {pid}'.\n"
        f"Proposta expira em 30min."
    )


def tool_list_proposals(user_id: str) -> str:
    pending = list_pending(user_id=user_id)
    if not pending:
        return "Nenhuma proposta pendente."
    lines = [f"{len(pending)} proposta(s) pendente(s):"]
    for p in pending:
        lines.append(
            f"  {p['id']} | {p['tipo']} | {p['titulo'][:60]}"
        )
    return "\n".join(lines)


# ============================================================
# Aprovacao real (chamada pelo CLI quando user digita /aprovar)
# ============================================================

def _run_git(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    """Roda comando git e retorna (sucesso, output)."""
    try:
        r = subprocess.run(
            ["git"] + cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = (r.stdout + r.stderr).strip()
        return (r.returncode == 0, out)
    except Exception as e:
        return (False, f"EXCEPTION: {e}")


def approve_proposal(pid: str, user_name: str = "Thiago") -> dict:
    """Aprova proposta:
    1. Checkout/cria branch agent-proposals
    2. Append no arquivo
    3. git add + commit assinado
    4. push da branch
    5. Retorna URL pra PR manual
    """
    prop = get_proposal(pid)
    if not prop:
        return {"ok": False, "msg": f"Proposta {pid} nao encontrada ou expirada."}
    if prop["status"] != "pending":
        return {"ok": False, "msg": f"Proposta {pid} ja foi {prop['status']}."}

    tipo = prop["tipo"]
    arquivo_rel = f"docs/{ARQUIVOS_PERMITIDOS[tipo]}"
    arquivo_abs = settings.repo_path / arquivo_rel

    if not arquivo_abs.exists():
        return {"ok": False, "msg": f"Arquivo destino nao existe: {arquivo_abs}"}

    repo = settings.repo_path

    # 1) Garantir branch agent-proposals
    ok, _ = _run_git(["rev-parse", "--verify", BRANCH_PROPOSTAS], repo)
    if ok:
        ok, msg = _run_git(["checkout", BRANCH_PROPOSTAS], repo)
    else:
        ok, msg = _run_git(["checkout", "-b", BRANCH_PROPOSTAS], repo)
    if not ok:
        return {"ok": False, "msg": f"Falha ao trocar branch: {msg}"}

    # Sync com main pra nao ficar atrasada
    _run_git(["merge", "main", "--no-edit"], repo)

    # 2) Append no arquivo
    with arquivo_abs.open("a", encoding="utf-8") as f:
        f.write(f"\n\n<!-- AUTO-APPEND {pid} aprovado por {user_name} -->\n\n")
        f.write(prop["conteudo"])
        f.write("\n")

    # 3) git add + commit
    ok, msg = _run_git(["add", arquivo_rel], repo)
    if not ok:
        return {"ok": False, "msg": f"Falha git add: {msg}"}

    commit_msg = (
        f"feat(kb): {prop['titulo']}\n\n"
        f"Auto-append via ebd-ia-bot, aprovado por {user_name}.\n"
        f"Tipo: {tipo}\n"
        f"ID: {pid}\n"
        f"Justificativa: {prop['justificativa']}\n\n"
        f"Co-Authored-By: ebd-ia-bot <bot@ebd.ia.br>"
    )
    ok, msg = _run_git(["commit", "-m", commit_msg], repo)
    if not ok:
        return {"ok": False, "msg": f"Falha git commit: {msg}"}

    # 4) push
    ok, msg = _run_git(["push", "origin", BRANCH_PROPOSTAS], repo)
    if not ok:
        # Tenta com -u na primeira vez
        ok, msg = _run_git(["push", "-u", "origin", BRANCH_PROPOSTAS], repo)
    push_ok = ok
    push_msg = msg

    # 5) Volta pra main e faz MERGE automatico da branch aprovada
    ok, msg = _run_git(["checkout", "main"], repo)
    if not ok:
        return {"ok": False, "msg": f"Commit OK mas falha ao voltar pra main: {msg}"}

    # 5a) Merge da agent-proposals na main (fast-forward, branches sincronizadas)
    merge_ok, merge_msg = _run_git(
        ["merge", BRANCH_PROPOSTAS, "--no-edit"], repo
    )

    # 5b) Push da main (so se merge deu certo)
    main_push_ok = False
    main_push_msg = ""
    if merge_ok:
        main_push_ok, main_push_msg = _run_git(["push", "origin", "main"], repo)

    # 5c) Reload do system prompt em memoria (knowledge nova 'pega' sem restart)
    reload_ok = False
    reload_info = ""
    if merge_ok:
        try:
            from app.agent import reload_system_prompt
            novo_tamanho = reload_system_prompt()
            reload_ok = True
            reload_info = f"prompt recarregado ({novo_tamanho:,} chars)"
        except Exception as e:
            reload_info = f"reload falhou: {e}"

    mark_approved(pid)

    # Monta mensagem de status honesta (cada etapa reportada)
    linhas = [f"OK - {pid} aprovado e gravado."]
    linhas.append(f"Branch '{BRANCH_PROPOSTAS}': {'commit+push OK' if push_ok else 'push falhou: ' + push_msg}")
    if merge_ok:
        linhas.append(f"Main: merge OK + {'push OK' if main_push_ok else 'push FALHOU: ' + main_push_msg}")
    else:
        linhas.append(f"Main: merge FALHOU ({merge_msg}) - knowledge NAO esta ativa ainda")
    if reload_ok:
        linhas.append(f"Bot: {reload_info} - JA esta usando o conhecimento novo")
    elif merge_ok:
        linhas.append(f"Bot: {reload_info} - pode precisar restart manual")

    return {
        "ok": True,
        "msg": "\n".join(linhas),
        "merge_ok": merge_ok,
        "reload_ok": reload_ok,
    }


def discard_proposal(pid: str) -> dict:
    prop = get_proposal(pid)
    if not prop:
        return {"ok": False, "msg": f"Proposta {pid} nao encontrada."}
    mark_discarded(pid)
    return {"ok": True, "msg": f"Proposta {pid} descartada."}

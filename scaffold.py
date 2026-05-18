#!/usr/bin/env python3
"""
scaffold.py — Cria o esqueleto inicial do projeto EBD.ia.
Idempotente: pode rodar várias vezes sem quebrar nada.
NUNCA sobrescreve arquivos existentes.
"""

from pathlib import Path

ROOT = Path(__file__).parent

# ============================================================
# PASTAS A CRIAR
# ============================================================
DIRS = [
    "infra/traefik",
    "infra/postgres/init",
    "infra/otel",
    "infra/prometheus",
    "infra/loki",
    "infra/grafana/provisioning",
    "gateway/app/auth",
    "gateway/app/routes",
    "gateway/app/queue",
    "worker/app/prompts",
    "worker/app/subagents",
    "worker/app/memory/shared",
    "worker/app/memory/users",
    "mcps/oracle/app",
    "mcps/excel/app",
    "mcps/pptx/app",
    "frontend/app/(auth)",
    "frontend/app/chat",
    "frontend/app/library",
    "frontend/app/admin/audit",
    "frontend/app/settings",
    "bots/telegram",
    "bots/whatsapp",
    "scripts",
    "docs/adr",
    "docs/runbooks",
    "docs/api",
]

# ============================================================
# ARQUIVOS A CRIAR (path: conteúdo)
# ============================================================
FILES = {
    # ---- Compose principal (placeholder Fase 0.5) ----
    "compose.yaml": """# EBD.ia — Docker Compose principal
# TODO Fase 0.5: adicionar serviços (traefik, postgres, redis, otel, prometheus, grafana, loki)
# TODO Fase 1: adicionar gateway, worker, mcps
# TODO Fase 2: adicionar frontend, metabase
# TODO Fase 3: adicionar bots
""",

    # ---- README por pasta principal ----
    "infra/README.md": "# infra — Configurações de infraestrutura\n\nTraefik, Postgres init, OpenTelemetry, Prometheus, Loki, Grafana.\n",
    "gateway/README.md": "# gateway — FastAPI gateway\n\nWebhooks dos 3 canais (Telegram, WhatsApp, chat web). Autenticação via PCLIB (rotina 131 Winthor). Enfileira jobs no Redis.\n",
    "worker/README.md": "# worker — Núcleo do agente\n\nConsome fila do Redis e executa o Claude Agent SDK. Hospeda subagentes (SQL, Excel, PPTX, Pandas) e memory stores.\n",
    "mcps/README.md": "# mcps — Servidores MCP\n\n- `oracle/` — Winthor read-only com SQL Guard\n- `excel/` — openpyxl\n- `pptx/` — python-pptx\n",
    "frontend/README.md": "# frontend — Chat web (Next.js 15)\n\nSSE streaming, artefato lateral (planilha/doc/slides/gráfico), audit log do diretor.\n\nDomínio de produção: `chat.ebd.ia.br`\n",
    "bots/README.md": "# bots — Bots de mensageria\n\n- `telegram/` — python-telegram-bot 21.x\n- `whatsapp/` — WhatsApp Cloud API (Meta)\n",
    "scripts/README.md": "# scripts — Scripts operacionais\n\n- `deploy.sh` — build e up dos containers\n- `backup.sh` — dump diário\n- `seed-memory-shared.py` — popular memory store compartilhado\n",
    "docs/README.md": """# docs — Documentação técnica

- `architecture.md` — referência completa da arquitetura (cópia da proposta + atualizações)
- `adr/` — Architecture Decision Records
- `runbooks/` — procedimentos operacionais
- `api/` — contratos OpenAPI
""",

    # ---- Prompts de sistema (4 papéis) ----
    "worker/app/prompts/system_vendedor.md": "# Prompt de sistema — Vendedor\n\nTODO Fase 1.4: definir prompt do papel vendedor.\n\nEscopo: 1 filial (`:userFilial` único, herdado de PCLIB).\nFoco: análises operacionais, top clientes, ruptura, planilhas.\n",
    "worker/app/prompts/system_rca.md": "# Prompt de sistema — RCA\n\nTODO Fase 1.4: definir prompt do papel RCA.\n\nEscopo: clientes próprios + filial.\nFoco: carteira, pedidos pendentes, margem, mix.\n",
    "worker/app/prompts/system_manager.md": "# Prompt de sistema — Manager\n\nTODO Fase 1.4: definir prompt do papel manager (descoberto nos mockups).\n\nEscopo: 1 filial ou conjunto (a confirmar com Ramon).\nFoco: gestão de equipe, performance dos RCAs subordinados.\n",
    "worker/app/prompts/system_diretor.md": "# Prompt de sistema — Diretor\n\nTODO Fase 1.4: definir prompt do papel diretor.\n\nEscopo: 1 a N filiais ou grupo todo (popover seletor, MFA exigido).\nModelo: Claude Opus 4.7 (análises agregadas).\nFoco: comparativos entre filiais, decisões estratégicas, decks executivos.\n",

    # ---- Memory stores ----
    "worker/app/memory/shared/README.md": "# Memory store compartilhado (read-only)\n\nPolíticas comerciais, catálogo, glossário, schema Winthor, playbooks.\n\nAtualizado apenas via scripts administrativos com revisão humana.\n",
    "worker/app/memory/users/README.md": "# Memory stores por usuário (read-write)\n\nUm subdiretório por usuário (`{user_id}/`). Preferências, contexto de clientes, deals em andamento, handoffs entre sessões.\n",

    # ---- ADRs ----
    "docs/adr/README.md": """# Architecture Decision Records (ADRs)

Cada ADR documenta uma decisão arquitetural relevante: contexto, opções avaliadas, decisão tomada, consequências.

Formato baseado em https://adr.github.io/
""",

    "docs/adr/0001-claude-agent-sdk.md": """# ADR 0001 — Camada LLM via Claude Agent SDK

**Data:** 2026-05-12
**Status:** Aceito

## Contexto
Três opções avaliadas para a camada LLM: Claude Code CLI com plano, API Anthropic crua, ou Claude Agent SDK.

## Decisão
Claude Agent SDK em Python.

## Consequências
- ✅ Reaproveita runtime do Claude Code como biblioteca embarcável
- ✅ Já traz: agent loop ReAct, Memory Tool, subagentes, MCP nativo, context compaction
- ✅ Evita reimplementar o que foi feito manualmente no agent.py v6.3 do health-mcp
- ⚠️ Depende da estabilidade da API do SDK (≥ 0.2.x)
""",

    "docs/adr/0002-rotina-131-pclib.md": """# ADR 0002 — Permissionamento via rotina 131 (PCLIB)

**Data:** 2026-05-18
**Status:** Aceito

## Contexto
Como controlar quais filiais cada usuário do agente pode consultar?

## Decisão
Reusar a tabela `EBD.PCLIB` do Winthor (alimentada pela rotina 131). Gateway consulta PCLIB no login, cacheia em Redis (TTL 15 min) e injeta `:userFilial` como bind variable em toda query.

## Consequências
- ✅ Single source of truth: TI já administra acessos no Winthor
- ✅ Onboarding/revogação automáticos via ERP
- ✅ Auditoria coerente (Winthor + audit log do agente)
- ⚠️ Dependência da estrutura `PCLIB` (validar com DBA)
- ⚠️ Cache de 15 min: revogação não é instantânea
""",

    "docs/adr/0003-sonnet-opus-por-perfil.md": """# ADR 0003 — Segmentação Sonnet 4.6 / Opus 4.7 por perfil

**Data:** 2026-05-12
**Status:** Aceito

## Decisão
- Vendedor / RCA / Manager → Claude Sonnet 4.6 (padrão)
- Diretor → Claude Opus 4.7 (análises agregadas multi-filial)

## Consequências
- ✅ Custo controlado: maioria dos usuários no modelo mais barato
- ✅ Análise estratégica do diretor justifica o custo maior
- ⚠️ Mantém 2 endpoints/configs de modelo
""",

    "docs/adr/0004-ssh-server-vpn-only.md": """# ADR 0004 — SSH do servidor nunca exposto à internet

**Data:** 2026-05-18
**Status:** Aceito

## Decisão
A porta 22 (SSH) do servidor `ssp06iac01` **nunca** será exposta à internet pública. Fica sempre atrás da VPN corporativa.

## Consequências
- ✅ Elimina vetor de ataque por força bruta SSH
- ✅ Senha SSH é aceitável (já que só rede interna acessa)
- ⚠️ Em produção, apenas portas 80/443 acessíveis externamente, via Traefik + TLS
""",

    "docs/adr/0005-worker-separado-do-gateway.md": """# ADR 0005 — Worker separado do gateway

**Data:** 2026-05-18
**Status:** Aceito

## Decisão
Gateway (FastAPI) e Worker (Claude Agent SDK) são serviços separados, comunicando via fila Redis.

## Consequências
- ✅ Gateway leve responde webhooks rapidamente (não bloqueia esperando o LLM)
- ✅ Worker pode escalar horizontalmente (proposta sugere 2 réplicas iniciais)
- ✅ Falha no agente não derruba recepção de mensagens
- ⚠️ Maior complexidade operacional (2 serviços, fila, idempotência)
""",

    # ---- Runbooks placeholder ----
    "docs/runbooks/deploy.md": "# Runbook — Deploy\n\nTODO Fase 0.5.\n\n## Padrão (herdado do health-mcp)\n```bash\ndocker compose build --no-cache <service>\ndocker compose up -d --force-recreate <service>\n```\n",
    "docs/runbooks/adicionar-vendedor.md": "# Runbook — Adicionar vendedor\n\nTODO Fase 1.5.\n",
    "docs/runbooks/recuperacao-de-incidente.md": "# Runbook — Recuperação de incidente\n\nTODO Fase 0.5.\n",
    "docs/runbooks/backup-restore.md": "# Runbook — Backup e restore\n\nTODO Fase 0.5.\n",

    # ---- API placeholder ----
    "docs/api/gateway.openapi.yaml": "# OpenAPI spec do gateway FastAPI\n# TODO Fase 1.2\n",

    # ---- Subagents placeholder ----
    "worker/app/subagents/README.md": "# Subagentes do worker\n\n- `sql.py` — consultas via mcp-oracle\n- `excel.py` — geração via mcp-excel\n- `pptx.py` — geração via mcp-pptx\n- `pandas_analysis.py` — análise nativa (não MCP)\n",
}


def main() -> None:
    created_dirs = 0
    created_files = 0
    skipped_files = 0

    print(f"📂 Raiz: {ROOT}\n")

    # Criar pastas
    print("=== Criando pastas ===")
    for d in DIRS:
        path = ROOT / d
        if path.exists():
            print(f"  → já existe: {d}")
        else:
            path.mkdir(parents=True, exist_ok=True)
            created_dirs += 1
            print(f"  ✅ criada:    {d}")

    # Criar .gitkeep em pastas vazias
    print("\n=== Adicionando .gitkeep em pastas vazias ===")
    gitkeeps = 0
    for d in DIRS:
        path = ROOT / d
        # se a pasta está vazia (nenhum arquivo nela), adiciona .gitkeep
        if path.exists() and not any(path.iterdir()):
            (path / ".gitkeep").touch()
            gitkeeps += 1
            print(f"  ✅ .gitkeep:  {d}/.gitkeep")

    # Criar arquivos
    print("\n=== Criando arquivos ===")
    for rel_path, content in FILES.items():
        path = ROOT / rel_path
        if path.exists():
            skipped_files += 1
            print(f"  ⏭️  já existe: {rel_path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            created_files += 1
            print(f"  ✅ criado:    {rel_path}")

    # Resumo
    print(f"\n{'='*50}")
    print(f"📊 Resumo:")
    print(f"   {created_dirs} pastas criadas")
    print(f"   {created_files} arquivos criados")
    print(f"   {gitkeeps} .gitkeep adicionados")
    print(f"   {skipped_files} arquivos pulados (já existiam)")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()

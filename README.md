# EBD.ia

Agente comercial conversacional baseado em **Claude (Anthropic)** para a rede comercial EBD.

## Visão geral

Atende 30 usuários comerciais (vendedores, RCAs, diretores) em 3 canais:

- **Chat web** (Next.js + SSE)
- **WhatsApp** (Cloud API)
- **Telegram** (Bot API)

Consulta o Winthor (Oracle TOTVS) em modo somente-leitura com escopo automático por filial herdado da rotina 131. Gera planilhas e apresentações, realiza análises de dados e publica dashboards.

## Status do projeto

🔄 **Fase 0 — Fundação** (em andamento)

Próximas fases: PoC no Telegram → Excel/PPT → WhatsApp+Web → Dashboards.

## Stack

- **Runtime**: Ubuntu Server 24.04.4 LTS, Docker 29.x + Compose v2
- **LLM**: Claude Sonnet 4.6 (padrão) / Opus 4.7 (diretor)
- **Linguagem**: Python 3.12 + Node.js 22 LTS
- **Dados**: Winthor (Oracle) read-only via python-oracledb 4.0
- **Backend**: FastAPI + Redis + PostgreSQL 16
- **Frontend**: Next.js 15
- **Observabilidade**: OpenTelemetry + Grafana + Prometheus + Loki

## Arquitetura

Ver `docs/` para documentação técnica completa.

## Domínio de produção

`ebd.ia.br` — `chat.ebd.ia.br`, `api.ebd.ia.br`, `bi.ebd.ia.br`

## Responsáveis

- **Autor**: Thiago Martins Parreira
- **Aprovador**: Ramon Tenório

---

*Projeto interno EBD Grupo — repositório privado.*

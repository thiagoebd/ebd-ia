# ADR 0001 — Camada LLM via Claude Agent SDK

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

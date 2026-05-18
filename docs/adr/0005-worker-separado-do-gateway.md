# ADR 0005 — Worker separado do gateway

**Data:** 2026-05-18
**Status:** Aceito

## Decisão
Gateway (FastAPI) e Worker (Claude Agent SDK) são serviços separados, comunicando via fila Redis.

## Consequências
- ✅ Gateway leve responde webhooks rapidamente (não bloqueia esperando o LLM)
- ✅ Worker pode escalar horizontalmente (proposta sugere 2 réplicas iniciais)
- ✅ Falha no agente não derruba recepção de mensagens
- ⚠️ Maior complexidade operacional (2 serviços, fila, idempotência)

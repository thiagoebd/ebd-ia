# ADR 0002 — Permissionamento via rotina 131 (PCLIB)

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

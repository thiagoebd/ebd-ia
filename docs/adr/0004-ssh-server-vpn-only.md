# ADR 0004 — SSH do servidor nunca exposto à internet

**Data:** 2026-05-18
**Status:** Aceito

## Decisão
A porta 22 (SSH) do servidor `ssp06iac01` **nunca** será exposta à internet pública. Fica sempre atrás da VPN corporativa.

## Consequências
- ✅ Elimina vetor de ataque por força bruta SSH
- ✅ Senha SSH é aceitável (já que só rede interna acessa)
- ⚠️ Em produção, apenas portas 80/443 acessíveis externamente, via Traefik + TLS

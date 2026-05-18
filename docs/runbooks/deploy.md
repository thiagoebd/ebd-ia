# Runbook — Deploy

TODO Fase 0.5.

## Padrão (herdado do health-mcp)
```bash
docker compose build --no-cache <service>
docker compose up -d --force-recreate <service>
```

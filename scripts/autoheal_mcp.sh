#!/usr/bin/env bash
# Reinicia ebdia_mcp_oracle se o Docker o marcar unhealthy. Roda via cron a cada minuto.
ST=$(docker inspect -f '{{.State.Health.Status}}' ebdia_mcp_oracle 2>/dev/null)
if [ "$ST" = "unhealthy" ]; then
  echo "$(date '+%F %T') unhealthy -> docker restart" >> /home/thiago/projects/ebd-ia/logs/autoheal.log
  docker restart ebdia_mcp_oracle >> /home/thiago/projects/ebd-ia/logs/autoheal.log 2>&1
fi

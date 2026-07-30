#!/bin/bash
# Espera o MCP Oracle ficar saudavel antes do gateway subir.
#
# Motivo: em 30/07/2026 o gateway subiu no boot ANTES do Docker terminar,
# travou no startup esperando conexao, e o systemd o marcou como 'active'
# porque o processo continuava vivo. Ninguem percebeu.
#
# NUNCA falha: se estourar o tempo, sai 0 e deixa o gateway subir assim mesmo.
# Bloquear o boot seria pior que subir cedo.

LIMITE=${1:-30}     # tentativas
INTERVALO=${2:-2}   # segundos entre elas

for i in $(seq 1 "$LIMITE"); do
    estado=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' ebdia_mcp_oracle 2>/dev/null)
    case "$estado" in
        healthy|running)
            echo "mcp-oracle pronto em ${i}x${INTERVALO}s (estado: $estado)"
            exit 0
            ;;
    esac
    sleep "$INTERVALO"
done

echo "mcp-oracle nao ficou pronto em $((LIMITE*INTERVALO))s (ultimo estado: ${estado:-desconhecido}) — subindo assim mesmo"
exit 0

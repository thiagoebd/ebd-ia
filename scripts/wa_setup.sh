#!/usr/bin/env bash
# Configuracao do numero do EBD.ia na Evolution (piloto WhatsApp em grupo).
#
#   bash scripts/wa_setup.sh status              estado da conexao
#   bash scripts/wa_setup.sh parear              recria a instancia e mostra
#                                                como parear pelo QR (painel)
#   bash scripts/wa_setup.sh webhook             liga o webhook -> gateway
#   bash scripts/wa_setup.sh grupos              lista os grupos (pegar o JID)
#
# Le EVO_URL, EVO_APIKEY, EVO_INSTANCE e WA_WEBHOOK_TOKEN do gateway/.env.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVF="$REPO/gateway/.env"
le_env() { grep -E "^$1=" "$ENVF" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"; }

EVO_URL="$(le_env EVO_URL)"; EVO_URL="${EVO_URL:-http://127.0.0.1:8081}"
EVO_APIKEY="$(le_env EVO_APIKEY)"
INST="$(le_env EVO_INSTANCE)"; INST="${INST:-ebdia}"
TOKEN="$(le_env WA_WEBHOOK_TOKEN)"

[ -n "$EVO_APIKEY" ] || { echo "EVO_APIKEY vazio em $ENVF"; exit 1; }
api() {  # api METODO caminho [json]
    curl -sS -X "$1" "$EVO_URL$2" -H "apikey: $EVO_APIKEY" \
         -H "Content-Type: application/json" ${3:+-d "$3"}
}
py() { python3 -c "import sys,json; d=json.load(sys.stdin); $1"; }

case "${1:-status}" in
  status)
    echo -n "  instancia $INST -> estado: "
    api GET "/instance/connectionState/$INST" | py 'print((d.get("instance") or d).get("state") or d)'
    ;;

  parear)
    # Aprendido em 30/09/2026 (Evolution v2.3.7): o codigo de 8 digitos veio
    # REPETIDO e ja expirado, e o celular recusou. O que funcionou foi o QR
    # pelo painel da Evolution, aberto no Mac por tunel SSH. O "nao foi
    # possivel conectar" no celular apos ler o QR e o intervalo da reconexao
    # (codigo 515) — confira o estado com "status" antes de repetir.
    ESTADO=$(api GET "/instance/connectionState/$INST" | python3 -c "import sys,json; d=json.load(sys.stdin); print((d.get('instance') or d).get('state',''))" 2>/dev/null)
    if [ "$ESTADO" = "open" ] && [ "${2:-}" != "--forcar" ]; then
        echo "  A instancia $INST esta CONECTADA (open). Recriar derruba o bot."
        echo "  Se for isso mesmo:  bash scripts/wa_setup.sh parear --forcar"
        exit 1
    fi
    echo "== recriando a instancia $INST limpa, em modo QR"
    api DELETE "/instance/delete/$INST" >/dev/null 2>&1
    sleep 3
    api POST /instance/create "{\"instanceName\":\"$INST\",\"integration\":\"WHATSAPP-BAILEYS\",\"qrcode\":true}" >/dev/null
    api POST "/settings/set/$INST" '{"rejectCall":true,"msgCall":"","groupsIgnore":false,"alwaysOnline":false,"readMessages":false,"readStatus":false,"syncFullHistory":false}' >/dev/null
    cat <<TXT

  1. No MAC (nao no servidor), deixe aberto:
       ssh -N -L 18081:127.0.0.1:8081 $(whoami)@$(hostname -I | awk '{print $1}')
  2. Navegador do Mac: http://localhost:18081/manager
       Server URL: http://localhost:18081    API Key Global: o EVO_APIKEY
  3. Instancia $INST > conectar > escaneie com o celular do chip
       (WhatsApp > Aparelhos conectados > Conectar um aparelho)
  4. Aqui:  bash scripts/wa_setup.sh status   -> tem que dar "open"

TXT
    ;;

  webhook)
    [ ${#TOKEN} -ge 16 ] || { echo "WA_WEBHOOK_TOKEN ausente ou curto em $ENVF"; exit 1; }
    URL="http://host.docker.internal:8000/api/whatsapp/webhook"
    api POST "/webhook/set/$INST" "{\"webhook\":{\"enabled\":true,\"url\":\"$URL\",\"headers\":{\"x-ebdia-token\":\"$TOKEN\"},\"byEvents\":false,\"base64\":true,\"events\":[\"MESSAGES_UPSERT\"]}}" | py '
print("  webhook:", (d.get("webhook") or d).get("url") or json.dumps(d)[:200])'
    ;;

  grupos)
    api GET "/group/fetchAllGroups/$INST?getParticipants=false" | py '
for g in (d if isinstance(d,list) else []):
    print("  %-34s %s" % (g.get("id"), g.get("subject", "")))
print("\n  Copie o JID do grupo para WA_GRUPOS no gateway/.env") '
    ;;

  *) echo "uso: status | parear [--forcar] | webhook | grupos"; exit 1 ;;
esac

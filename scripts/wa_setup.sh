#!/usr/bin/env bash
# Configuracao do numero do EBD.ia na Evolution (piloto WhatsApp em grupo).
#
#   bash scripts/wa_setup.sh status              estado da conexao
#   bash scripts/wa_setup.sh parear 5511988887777 cria a instancia e mostra o
#                                                codigo de pareamento
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
    NUM="${2:-}"; [ -n "$NUM" ] || { echo "uso: parear 55DDDNUMERO (numero do chip do bot)"; exit 1; }
    echo "== criando a instancia $INST (se ja existir, segue)"
    api POST /instance/create "{\"instanceName\":\"$INST\",\"integration\":\"WHATSAPP-BAILEYS\",\"qrcode\":false}" >/dev/null
    api POST "/settings/set/$INST" '{"rejectCall":true,"msgCall":"","groupsIgnore":false,"alwaysOnline":false,"readMessages":false,"readStatus":false,"syncFullHistory":false}' >/dev/null
    echo "== pedindo codigo de pareamento para $NUM"
    api GET "/instance/connect/$INST?number=$NUM" | py '
c=d.get("pairingCode"); b=d.get("base64") or d.get("code")
if c: print("\n  CODIGO:", c, "\n\n  No celular do chip: WhatsApp > Aparelhos conectados > Conectar aparelho\n  > Conectar com numero de telefone > digite o codigo.\n")
elif b and str(b).startswith("data:image"):
    import base64; open("/tmp/ebdia-qr.png","wb").write(base64.b64decode(b.split(",",1)[1]))
    print("  sem codigo; QR salvo em /tmp/ebdia-qr.png (scp para ver)")
else: print("  resposta:", json.dumps(d)[:300])'
    ;;

  webhook)
    [ ${#TOKEN} -ge 16 ] || { echo "WA_WEBHOOK_TOKEN ausente ou curto em $ENVF"; exit 1; }
    URL="http://host.docker.internal:8000/api/whatsapp/webhook"
    api POST "/webhook/set/$INST" "{\"webhook\":{\"enabled\":true,\"url\":\"$URL\",\"headers\":{\"x-ebdia-token\":\"$TOKEN\"},\"byEvents\":false,\"base64\":false,\"events\":[\"MESSAGES_UPSERT\"]}}" | py '
print("  webhook:", (d.get("webhook") or d).get("url") or json.dumps(d)[:200])'
    ;;

  grupos)
    api GET "/group/fetchAllGroups/$INST?getParticipants=false" | py '
for g in (d if isinstance(d,list) else []):
    print(f"  {g.get(\"id\"):<32} {g.get(\"subject\",\"\")}")
print("\n  Copie o JID do grupo para WA_GRUPOS no gateway/.env") '
    ;;

  *) echo "uso: status | parear NUMERO | webhook | grupos"; exit 1 ;;
esac

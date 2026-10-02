#!/usr/bin/env bash
# Vigia do modelo DeepSeek — troca sozinho para o pro quando o flash cai, e
# volta para o flash quando ele estabiliza. Serve ao EBD.ia e ao Dealer.ia.
#
# Por que: em 14/09 e 01/10/2026 o deepseek-flash travou do lado do DeepSeek,
# sem erro, e os agentes ficaram "pensando" sem responder.
#
# Mecanismo: liga/desliga FLASH_SUBSTITUTO no gateway/.env. O agente le essa
# variavel e manda para o pro quem pede flash — a tela continua mostrando Flash.
#
# HISTERESE (para nao ficar alternando e reiniciando o gateway):
#   - troca para o pro NA HORA: flash fora e sistema parado
#   - volta para o flash so com DUAS checagens boas seguidas (1 hora)
#
#   sudo bash vigia_modelo.sh instalar ebdia-gateway     (no 108)
#   sudo bash vigia_modelo.sh instalar concia-gateway    (no 109)
#   sudo bash vigia_modelo.sh checar                     (roda uma vez, na mao)
#   sudo bash vigia_modelo.sh desinstalar
set -uo pipefail

CONF=/etc/vigia-modelo.conf
DESTINO=/usr/local/bin/vigia-modelo.sh
ESTADO=/var/lib/vigia-modelo
SUBSTITUTO=deepseek-v4-pro
OKS_PARA_VOLTAR=2

# no systemd a saida padrao ja vai para o journal: imprimir E chamar o logger
# duplicava cada linha. So imprime quando ha terminal (rodando na mao).
log() { logger -t vigia-modelo "$*"; [ -t 1 ] && echo "$*"; return 0; }

instalar() {
    local servico="${1:?informe o servico: ebdia-gateway ou concia-gateway}"
    local repo
    repo=$(systemctl show "$servico" -p WorkingDirectory --value)
    [ -n "$repo" ] && [ -d "$repo" ] || repo=$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)
    for d in "$repo" "$HOME/projects/ebd-ia" "$HOME/projects/ebd-ia-conc" \
             /home/*/projects/ebd-ia /home/*/projects/ebd-ia-conc; do
        if [ -f "$d/core/app/agent.py" ] && [ -f "$d/gateway/.env" ]; then repo="$d"; break; fi
    done
    [ -f "$repo/core/app/agent.py" ] || { echo "repositorio nao encontrado"; exit 1; }
    grep -q FLASH_SUBSTITUTO "$repo/core/app/agent.py" || {
        echo "o agente em $repo nao tem a substituicao FLASH_SUBSTITUTO — aplique antes"; exit 1; }
    systemctl cat "$servico" >/dev/null 2>&1 || { echo "servico $servico nao existe"; exit 1; }

    install -m 0755 "$0" "$DESTINO"
    mkdir -p "$ESTADO"
    printf 'REPO=%s\nSERVICO=%s\n' "$repo" "$servico" > "$CONF"
    cat > /etc/systemd/system/vigia-modelo.service <<EOF
[Unit]
Description=Vigia do modelo DeepSeek (flash -> pro e volta)
After=network-online.target

[Service]
Type=oneshot
ExecStart=$DESTINO checar
EOF
    cat > /etc/systemd/system/vigia-modelo.timer <<EOF
[Unit]
Description=Vigia do modelo DeepSeek a cada 30 minutos

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now vigia-modelo.timer
    echo "instalado: $repo · servico $servico · a cada 30 min"
    echo "primeira checagem agora:"
    systemctl start vigia-modelo.service
    journalctl -u vigia-modelo --since "2 min ago" --no-pager -o cat | tail -6
}

desinstalar() {
    systemctl disable --now vigia-modelo.timer 2>/dev/null
    rm -f /etc/systemd/system/vigia-modelo.{service,timer} "$DESTINO" "$CONF"
    systemctl daemon-reload
    echo "removido (o FLASH_SUBSTITUTO ficou como estava no .env)"
}

testa() {   # $1 = modelo -> 0 se respondeu
    curl -s -m 30 -o "$ESTADO/teste.json" \
        https://api.deepseek.com/anthropic/v1/messages \
        -H "x-api-key: $CHAVE" -H "anthropic-version: 2023-06-01" \
        -H "content-type: application/json" \
        -d "{\"model\":\"$1\",\"max_tokens\":10,\"messages\":[{\"role\":\"user\",\"content\":\"responda so: ok\"}]}" \
        >/dev/null 2>&1
    grep -q '"type":"message"' "$ESTADO/teste.json" 2>/dev/null
}

avisa() {   # WhatsApp pela Evolution, se este servidor tiver uma (so o 108)
    local key
    key=$(grep ^EVO_APIKEY= "$REPO/gateway/.env" 2>/dev/null | cut -d= -f2-)
    local num="${ALERTA_WA:-5511983540470}"
    [ -n "$key" ] || return 0
    printf '{"number":"%s","text":"%s"}' "$num" "🔧 $(hostname): $*" |
        curl -s -m 15 -o /dev/null -X POST "http://127.0.0.1:8081/message/sendText/${EVO_INSTANCE:-ebdia}" \
            -H "apikey: $key" -H "Content-Type: application/json" -d @- || true
}

substituicao_ligada() { grep -q "^FLASH_SUBSTITUTO=" "$REPO/gateway/.env"; }

liga() {
    if grep -q "^# *FLASH_SUBSTITUTO=" "$REPO/gateway/.env"; then
        sed -i "s|^# *FLASH_SUBSTITUTO=.*|FLASH_SUBSTITUTO=$SUBSTITUTO|" "$REPO/gateway/.env"
    else
        echo "FLASH_SUBSTITUTO=$SUBSTITUTO" >> "$REPO/gateway/.env"
    fi
    systemctl restart "$SERVICO"
}

desliga() {
    sed -i "s|^FLASH_SUBSTITUTO=|# FLASH_SUBSTITUTO=|" "$REPO/gateway/.env"
    systemctl restart "$SERVICO"
}

checar() {
    # shellcheck disable=SC1090
    . "$CONF"
    mkdir -p "$ESTADO"
    CHAVE=$(grep ^DEEPSEEK_API_KEY= "$REPO/core/.env" | cut -d= -f2-)
    [ -n "$CHAVE" ] || { log "sem DEEPSEEK_API_KEY em $REPO/core/.env"; exit 1; }

    local flash=0 pro=0
    testa deepseek-flash && flash=1 || { sleep 20; testa deepseek-flash && flash=1; }
    testa "$SUBSTITUTO" && pro=1
    local oks
    oks=$(cat "$ESTADO/oks" 2>/dev/null || echo 0)

    if substituicao_ligada; then
        if [ "$flash" = 1 ]; then
            oks=$((oks + 1))
            if [ "$oks" -ge "$OKS_PARA_VOLTAR" ]; then
                desliga; echo 0 > "$ESTADO/oks"; rm -f "$ESTADO/ambos"
                log "VOLTOU: flash estavel em $oks checagens seguidas — substituicao desligada, $SERVICO reiniciado"
                avisa "flash estavel de novo: voltei o EBD para o deepseek-flash (lê imagem)."
            else
                echo "$oks" > "$ESTADO/oks"
                log "flash respondeu ($oks/$OKS_PARA_VOLTAR) — mantendo o pro ate confirmar"
            fi
        else
            echo 0 > "$ESTADO/oks"
            log "flash ainda fora — mantendo o pro (pro: $([ $pro = 1 ] && echo ok || echo FORA))"
        fi
    else
        if [ "$flash" = 1 ]; then
            echo 0 > "$ESTADO/oks"; rm -f "$ESTADO/ambos"
            log "ok: flash respondendo"
        elif [ "$pro" = 1 ]; then
            liga; echo 0 > "$ESTADO/oks"
            log "TROCOU: flash fora, pro respondendo — substituicao ligada, $SERVICO reiniciado"
            avisa "deepseek-flash fora do ar. Troquei para o pro por tras (a tela segue Flash). Foto nao e lida ate voltar."
        else
            log "AMBOS FORA: flash e pro sem resposta — nada trocado (trocar nao ajudaria)"
            [ -f "$ESTADO/ambos" ] || { avisa "DeepSeek fora: flash E pro sem resposta. Nada a trocar — verificar rede/chave."; touch "$ESTADO/ambos"; }
        fi
    fi
}

case "${1:-}" in
    instalar)    instalar "${2:-}" ;;
    desinstalar) desinstalar ;;
    checar)      checar ;;
    *) echo "uso: sudo bash $0 instalar <ebdia-gateway|concia-gateway> | checar | desinstalar"; exit 1 ;;
esac

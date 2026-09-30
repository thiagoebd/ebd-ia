#!/usr/bin/env bash
# Troca o modelo do DeepSeek em TODOS os pontos de um projeto.
#
# POR QUE
#   O nome do modelo vive espalhado em 5 lugares — .env, models_catalog,
#   config, db (DEFAULT da coluna) e o frontend. Trocar em um so deixa o
#   sistema inconsistente: ja aconteceu duas vezes (11/09 e 14/09).
#
#   Em 14/09/2026 o `deepseek-flash` parou de responder (requisicao trava
#   sem erro, 60s+), enquanto o `deepseek-v4-pro` respondia em 1,7s. Os dois
#   estao na lista oficial de /models — e problema do lado do DeepSeek.
#
# ATENCAO
#   deepseek-flash   LE IMAGEM
#   deepseek-v4-pro  NAO le imagem — foto de veiculo/print deixa de funcionar
#
# Uso:
#   bash troca_modelo.sh                      # testa e mostra o estado
#   bash troca_modelo.sh deepseek-v4-pro      # troca
#   bash troca_modelo.sh deepseek-flash       # volta
set -uo pipefail

NOVO="${1:-}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$REPO/core/.env" ] || REPO="$HOME/projects/ebd-ia"
[ -f "$REPO/core/.env" ] || REPO="$HOME/projects/ebd-ia-conc"
if [ ! -f "$REPO/core/.env" ]; then
    echo "  nao achei core/.env — rode de dentro do projeto"; exit 1
fi
cd "$REPO"
NOME="$(basename "$REPO")"
CHAVE="$(grep ^DEEPSEEK_API_KEY= core/.env | cut -d= -f2)"
BASE="$(grep ^DEEPSEEK_BASE_URL= core/.env | cut -d= -f2)"
BASE="${BASE:-https://api.deepseek.com/anthropic}"

testa() {   # testa($1=modelo) -> imprime http e tempo
    local m="$1" out code
    out=$(timeout 30 curl -s -o /dev/null -X POST "$BASE/v1/messages" \
        -H "x-api-key: $CHAVE" -H "anthropic-version: 2023-06-01" \
        -H "content-type: application/json" \
        -d "{\"model\":\"$m\",\"max_tokens\":20,\"messages\":[{\"role\":\"user\",\"content\":\"oi\"}]}" \
        -w "%{http_code} %{time_total}" 2>/dev/null)
    if [ -z "$out" ]; then echo "TRAVOU (30s sem resposta)"; return 1; fi
    code="${out%% *}"
    if [ "$code" = "200" ]; then echo "OK em ${out##* }s"; return 0; fi
    echo "http=$code"; return 1
}

echo "=================================================================="
echo "  $NOME"
echo "=================================================================="
echo "  modelo atual:"
grep -H ^DEEPSEEK_MODEL= core/.env 2>/dev/null | sed 's/^/    /'
grep -Hn 'DEFAULT_MODEL = ' gateway/app/models_catalog.py 2>/dev/null | sed 's/^/    /'

echo
echo "  testando os modelos na API:"
for m in deepseek-flash deepseek-v4-pro; do
    printf "    %-18s " "$m"
    testa "$m"
done

if [ -z "$NOVO" ]; then
    echo
    echo "  (so diagnostico — passe o modelo para trocar)"
    echo "    bash troca_modelo.sh deepseek-v4-pro"
    exit 0
fi

echo
echo "  ------------------------------------------------------------"
printf "  verificando %s antes de trocar... " "$NOVO"
if ! testa "$NOVO"; then
    echo "  ABORTADO: o modelo destino nao respondeu."
    echo "  (use --forcar como 2o argumento se quiser trocar assim mesmo)"
    [ "${2:-}" = "--forcar" ] || exit 1
    echo "  --forcar: trocando mesmo assim"
fi

echo
echo "  trocando para $NOVO:"
ts=$(date +%Y%m%d-%H%M%S)
mudou=0

troca() {   # troca($1=arquivo, $2=regex sed, $3=rotulo)
    local f="$1" expr="$2" rotulo="$3"
    [ -f "$f" ] || { printf "    %-34s (nao existe)\n" "$rotulo"; return; }
    if grep -qE "deepseek-(flash|v4-pro|v4-flash)" "$f"; then
        cp "$f" "$f.bak-$ts"
        sed -i -E "$expr" "$f"
        printf "    %-34s OK\n" "$rotulo"
        mudou=1
    else
        printf "    %-34s (sem modelo)\n" "$rotulo"
    fi
}

troca core/.env \
      "s/^DEEPSEEK_MODEL=.*/DEEPSEEK_MODEL=$NOVO/" "core/.env"
troca gateway/app/models_catalog.py \
      "s/DEFAULT_MODEL = \"deepseek-[a-z0-9.-]+\"/DEFAULT_MODEL = \"$NOVO\"/" \
      "gateway/app/models_catalog.py"
troca core/app/config.py \
      "s/Field\(\"deepseek-[a-z0-9.-]+\", alias=\"DEEPSEEK_MODEL\"\)/Field(\"$NOVO\", alias=\"DEEPSEEK_MODEL\")/" \
      "core/app/config.py"
troca gateway/app/db.py \
      "s/DEFAULT 'deepseek-[a-z0-9.-]+'/DEFAULT '$NOVO'/" "gateway/app/db.py"
troca frontend/src/App.tsx \
      "s/useState<string>\(\"deepseek-[a-z0-9.-]+\"\)/useState<string>(\"$NOVO\")/" \
      "frontend/src/App.tsx"
# o Telegram so existe no EBD.ia
troca core/.env \
      "s/^TELEGRAM_MODEL=.*/TELEGRAM_MODEL=$NOVO/" "core/.env (telegram)"

echo
echo "  conferindo:"
grep -rhoE "deepseek-(flash|v4-pro|v4-flash)" \
     core/.env gateway/app/models_catalog.py core/app/config.py \
     gateway/app/db.py frontend/src/App.tsx 2>/dev/null \
  | sort | uniq -c | sed 's/^/    /'

if [ "$mudou" = "1" ] && [ -d frontend ]; then
    echo
    echo "  buildando o frontend..."
    (cd frontend && npm run build >/dev/null 2>&1) \
        && echo "    OK" || echo "    FALHOU — rode 'npm run build' manualmente"
fi

echo
echo "  reiniciando os servicos:"
for svc in ebdia-gateway concia-gateway ebdia-telegram; do
    if systemctl list-unit-files 2>/dev/null | grep -q "^$svc.service"; then
        # matar o processo orfao antes: ja travou a porta 8000 em 11/09
        sudo systemctl stop "$svc" 2>/dev/null
        sudo pkill -f "uvicorn gateway.app.main" 2>/dev/null
        sleep 3
        sudo systemctl start "$svc" 2>/dev/null
        sleep 6
        printf "    %-20s %s\n" "$svc" "$(systemctl is-active $svc)"
    fi
done

echo
echo "  backups: *.bak-$ts"
echo "  ⚠️  deepseek-v4-pro NAO le imagem — foto deixa de ser interpretada."
echo "  Ctrl+Shift+R no navegador."

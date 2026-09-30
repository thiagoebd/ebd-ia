#!/usr/bin/env bash
# Voz do EBD.ia no WhatsApp: Whisper (ouvir) e Piper (falar), no servidor.
# Nada sai da rede. Portado do canal de voz do Dealer.ia.
#
#   bash scripts/instala_voz_wa.sh
set -euo pipefail
VOZ_DIR=/opt/piper-vozes
VOZ=pt_BR-faber-medium

echo "== 1. ffmpeg"
command -v ffmpeg >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg; }
ffmpeg -version | head -1

echo "== 2. bibliotecas no Python do gateway (/usr/bin/python3)"
sudo /usr/bin/python3 -m pip install --break-system-packages -q "faster-whisper>=1.0" "piper-tts>=1.2"
command -v piper >/dev/null || ls /usr/local/bin/piper

echo "== 3. voz pt_BR"
sudo mkdir -p "$VOZ_DIR"
if [ ! -f "$VOZ_DIR/$VOZ.onnx" ]; then
    BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium
    sudo curl -fsSL -o "$VOZ_DIR/$VOZ.onnx"      "$BASE/$VOZ.onnx"
    sudo curl -fsSL -o "$VOZ_DIR/$VOZ.onnx.json" "$BASE/$VOZ.onnx.json"
fi
sudo chmod -R a+r "$VOZ_DIR"; ls -la "$VOZ_DIR"

echo "== 4. teste de ida e volta (fala -> ouve)"
cd "$(dirname "$0")/.."
/usr/bin/python3 - <<'PY'
import sys, time
sys.path.insert(0, "core")
from app.adapters import whatsapp_voz as v
t0 = time.time()
wav = v.sintetizar("O faturamento de agosto foi de trezentos e quarenta e quatro milhões de reais.")
print(f"  falou: {len(wav)} bytes em {time.time()-t0:.1f}s")
t0 = time.time()
txt = v.transcrever(wav, ".wav")
print(f"  ouviu em {time.time()-t0:.1f}s (1a vez carrega o modelo): {txt!r}")
ok = "faturamento" in txt.lower() and "agosto" in txt.lower()
print("  RESULTADO:", "OK" if ok else "CONFERIR A TRANSCRICAO")
PY

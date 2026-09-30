#!/usr/bin/env bash
# Voz do EBD.ia no WhatsApp: Whisper (ouvir) e Piper (falar), no servidor.
# Nada sai da rede. Aprendido na primeira instalacao (30/09/2026):
#   - pacote do apt sem RECORD (idna) trava o pip: passa SO ele para o pip
#   - a biblioteca do Hugging Face baixa por Xet e trava no firewall:
#     os modelos vem por curl, que passa
#   - o PyAV instalado e incompativel: o audio chega ao Whisper em memoria
set -euo pipefail
cd "$(dirname "$0")/.."
PIPER=/opt/piper-vozes; VOZ=pt_BR-faber-medium
WHISPER=/opt/whisper-modelos/small

echo "== 1. ffmpeg"
command -v ffmpeg >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg; }

echo "== 2. bibliotecas no Python do gateway"
for i in 1 2 3 4 5 6; do
    out=$(sudo /usr/bin/python3 -m pip install --break-system-packages -q "faster-whisper>=1.0" "piper-tts>=1.2" 2>&1) && break
    pkg=$(echo "$out" | grep -oP "Cannot uninstall \K[A-Za-z0-9_.-]+")
    [ -z "$pkg" ] && { echo "$out" | tail -8; exit 1; }
    echo "  $pkg veio do apt — passando para o pip"
    sudo /usr/bin/python3 -m pip install --break-system-packages -q --ignore-installed "$pkg"
done

echo "== 3. voz pt_BR (Piper)"
sudo mkdir -p "$PIPER"
BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium
for f in "$VOZ.onnx" "$VOZ.onnx.json"; do
    [ -s "$PIPER/$f" ] || sudo curl -fsSL -o "$PIPER/$f" "$BASE/$f"
done

echo "== 4. modelo do Whisper (small, por curl)"
sudo mkdir -p "$WHISPER"
for f in config.json model.bin tokenizer.json vocabulary.txt; do
    [ -s "$WHISPER/$f" ] || { echo "  baixando $f..."; sudo curl -fsSL -o "$WHISPER/$f" "https://huggingface.co/Systran/faster-whisper-small/resolve/main/$f"; }
done
sudo chmod -R a+r "$PIPER" /opt/whisper-modelos
grep -q "^VOZ_STT_MODELO=" gateway/.env && sed -i "s|^VOZ_STT_MODELO=.*|VOZ_STT_MODELO=$WHISPER|" gateway/.env || echo "VOZ_STT_MODELO=$WHISPER" >> gateway/.env

echo "== 5. teste de ida e volta (fala -> ouve)"
VOZ_STT_MODELO=$WHISPER /usr/bin/python3 - <<'PY'
import sys, time
sys.path.insert(0, "core")
from app.adapters import whatsapp_voz as v
t0 = time.time(); wav = v.sintetizar("O faturamento de agosto foi de trezentos e quarenta e quatro milhões de reais.")
print(f"  falou: {len(wav)} bytes em {time.time()-t0:.1f}s")
t0 = time.time(); txt = v.transcrever(wav, ".wav")
print(f"  ouviu em {time.time()-t0:.1f}s: {txt!r}")
print("  RESULTADO:", "OK" if "faturamento" in txt.lower() and "agosto" in txt.lower() else "CONFERIR")
PY

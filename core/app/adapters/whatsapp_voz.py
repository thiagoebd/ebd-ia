"""Voz no WhatsApp — transcricao (Whisper) e sintese (Piper) no proprio servidor.

Portado do canal de voz do Dealer.ia. Nada sai da rede: sao conversas sobre
faturamento. Modelos carregam sob demanda e ficam em memoria — o primeiro
audio paga uns 10 s, os seguintes sao rapidos.

RESUMO FALADO
    Ler tabela em voz alta e insuportavel. Quando a resposta vai em audio, o
    agente escreve a resposta normal E um bloco <FALA>...</FALA> com 2-3
    frases arredondadas. O texto vai sem o bloco; so o bloco vira audio.

Sem as bibliotecas instaladas (scripts/instala_voz_wa.sh), levanta
VozIndisponivel e o bot avisa que ainda nao ouve/fala — nunca derruba.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("uvicorn.error")

MODELO_STT = os.getenv("VOZ_STT_MODELO", "small")        # tiny|base|small|medium
VOZ_TTS = os.getenv("VOZ_TTS_MODELO", "/opt/piper-vozes/pt_BR-faber-medium.onnx")

# vocabulario que o Whisper erra sem ajuda
_PROMPT_EBD = (
    "EBD, Winthor, faturamento, positivacao, ruptura, mix, RCA, supervisor, "
    "filial, regional, meta, atingimento, devolucao, carteira, Nissin, Red Bull, "
    "Ferrero, Ajinomoto, PepsiCo, Kibon, Duque, Taquara, Sao Goncalo, Caruaru, "
    "Fortaleza, Manaus, Boa Vista, Sao Luis, Teresina, Juazeiro, Santarem, "
    "Itapevi, SBC, Pirai, Matriz."
)

_whisper = None


class VozIndisponivel(RuntimeError):
    """Bibliotecas de voz nao instaladas neste servidor."""


def _modelo_stt():
    global _whisper
    if _whisper is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise VozIndisponivel("faster-whisper nao instalado") from e
        log.info("voz: carregando Whisper %s (cpu/int8)...", MODELO_STT)
        _whisper = WhisperModel(MODELO_STT, device="cpu", compute_type="int8")
        log.info("voz: Whisper pronto")
    return _whisper


def transcrever(audio: bytes, sufixo: str = ".ogg") -> str:
    """Audio do WhatsApp (ogg/opus) -> texto."""
    if not shutil.which("ffmpeg"):
        raise VozIndisponivel("ffmpeg nao instalado")
    with tempfile.NamedTemporaryFile(suffix=sufixo, delete=False) as f:
        f.write(audio)
        bruto = f.name
    wav = bruto + ".wav"
    try:
        # o ffmpeg entrega PCM 16 kHz mono direto em memoria. Passar o ARQUIVO
        # ao Whisper faria ele decodificar pelo PyAV — e a versao do PyAV
        # instalada recusa o parametro que o faster-whisper usa (30/09/2026).
        pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", bruto,
                              "-f", "s16le", "-acodec", "pcm_s16le",
                              "-ar", "16000", "-ac", "1", "-"],
                             check=True, timeout=60, capture_output=True).stdout
        import numpy as np
        amostras = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segs, info = _modelo_stt().transcribe(
            amostras, language="pt", beam_size=1, vad_filter=True,
            initial_prompt=_PROMPT_EBD)
        texto = " ".join(s.text.strip() for s in segs).strip()
        log.info("voz: transcrito %.1fs (%d chars)", info.duration, len(texto))
        return texto
    finally:
        for p in (bruto, wav):
            try:
                os.unlink(p)
            except OSError:
                pass


_SIMBOLOS = [
    (r"R\$\s*([\d.,]+)\s*mi\b", r"\1 milhões de reais"),
    (r"R\$\s*([\d.,]+)\s*M\b", r"\1 milhões de reais"),
    (r"R\$\s*([\d.,]+)\s*mil\b", r"\1 mil reais"),
    (r"R\$\s*", " "),
    (r"\bp\.p\.", "pontos percentuais"),
    (r"%", " por cento"),
    (r"−|–|—", ", "),
    (r"[*_#`>|~]", " "),
    (r"\s{2,}", " "),
]


def preparar_fala(texto: str) -> str:
    """Tira markdown e expande simbolos para o TTS nao soletrar."""
    t = texto
    for pad, rep in _SIMBOLOS:
        t = re.sub(pad, rep, t)
    return t.strip()


def sintetizar(texto: str) -> bytes:
    """Texto -> WAV (bytes). A Evolution converte para nota de voz."""
    binario = shutil.which("piper") or "/usr/local/bin/piper"
    if not Path(binario).exists() or not Path(VOZ_TTS).exists():
        raise VozIndisponivel("piper ou voz pt_BR nao instalados")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        destino = f.name
    try:
        proc = subprocess.run([binario, "--model", VOZ_TTS, "--output_file", destino],
                              input=preparar_fala(texto).encode("utf-8"),
                              capture_output=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"piper falhou: {proc.stderr.decode()[:300]}")
        return Path(destino).read_bytes()
    finally:
        try:
            os.unlink(destino)
        except OSError:
            pass


def extrair_fala(resposta: str) -> str:
    """O bloco <FALA>; sem ele, as primeiras frases sem tabela nem markdown."""
    m = re.search(r"<FALA>(.*?)</FALA>", resposta, re.S | re.I)
    if m:
        return m.group(1).strip()
    limpo = re.sub(r"^\s*\|.*$", " ", resposta, flags=re.M)      # tira tabelas
    limpo = re.sub(r"[#*_`>]", " ", limpo)
    limpo = re.sub(r"\s{2,}", " ", limpo).strip()
    return " ".join(limpo.split(". ")[:3])[:400]


def limpar_texto_visual(resposta: str) -> str:
    """A resposta escrita, sem o bloco <FALA>."""
    return re.sub(r"<FALA>.*?</FALA>", "", resposta, flags=re.S | re.I).strip()


_PEDIU_AUDIO = re.compile(
    r"(\b(manda|mande|envia|envie|responde|responda|grava|grave|me fala|fala)\b"
    r".{0,30}\b(audio|áudio|voz)\b)|\b(em|por|via|num|no) (audio|áudio)\b",
    re.I)


def pediu_audio(texto: str) -> bool:
    """'manda em áudio', 'responde por voz', 'me fala num áudio'..."""
    return bool(_PEDIU_AUDIO.search(texto or ""))


MARCA_AUDIO = ("[RESPONDA TAMBEM EM AUDIO: alem da resposta normal, termine com "
               "um bloco <FALA>...</FALA> de 2 a 3 frases curtas para ser OUVIDO — "
               "numeros arredondados, sem tabela, sem simbolos]")

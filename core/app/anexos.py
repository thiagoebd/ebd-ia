"""Preparo de anexos para o modelo.

MEDIDO em 10/09/2026 contra o endpoint compativel do DeepSeek:

  deepseek-flash    imagem: LE (respondeu o valor escrito no PNG)
  deepseek-v4-pro   imagem: nao le
  ambos             PDF:    [Unsupported Document]

Entao: imagem vai NATIVA; PDF e planilha viram texto extraido pelo gateway.

O limite de aceite e 20 MB, mas a imagem e REDUZIDA antes de ir ao modelo:
foto de celular tem resolucao muito acima do que o modelo aproveita, e
token de imagem e proporcional ao tamanho. O usuario manda o que quiser;
nos mandamos o que serve.
"""
from __future__ import annotations

import base64
import io
import logging

logger = logging.getLogger("uvicorn.error")

MAX_BYTES = 20 * 1024 * 1024        # aceite: 20 MB
MAX_LADO = 1568                      # maior lado apos reducao
QUALIDADE = 85
TIPOS_IMAGEM = {"image/jpeg", "image/png", "image/gif", "image/webp"}


class AnexoInvalido(Exception):
    """Anexo recusado — a mensagem e mostrada ao usuario."""


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def prepara_imagem(dados: bytes, media_type: str = "image/jpeg") -> dict:
    """bytes -> bloco `image` pronto para a API.

    Reduz para no maximo MAX_LADO no maior lado. Imagem pequena passa
    intacta (recomprimir so degradaria).
    """
    if not dados:
        raise AnexoInvalido("A imagem chegou vazia.")
    if len(dados) > MAX_BYTES:
        raise AnexoInvalido(
            f"A imagem tem {_mb(len(dados))} e o limite e {_mb(MAX_BYTES)}. "
            f"Manda uma versao menor?")

    try:
        from PIL import Image
    except ImportError:
        logger.warning("pillow ausente: imagem enviada sem reducao")
        return _bloco(dados, media_type)

    try:
        img = Image.open(io.BytesIO(dados))
        larg, alt = img.size
        if max(larg, alt) <= MAX_LADO and len(dados) < 900_000:
            return _bloco(dados, media_type)

        escala = MAX_LADO / max(larg, alt)
        if escala < 1:
            img = img.resize((int(larg * escala), int(alt * escala)),
                             Image.LANCZOS)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=QUALIDADE, optimize=True)
        novo = buf.getvalue()
        logger.info("anexo: imagem %dx%d %s -> %dx%d %s",
                    larg, alt, _mb(len(dados)),
                    img.size[0], img.size[1], _mb(len(novo)))
        return _bloco(novo, "image/jpeg")
    except AnexoInvalido:
        raise
    except Exception as e:
        logger.warning("anexo: reducao falhou (%s); enviando original",
                       type(e).__name__)
        return _bloco(dados, media_type)


def _bloco(dados: bytes, media_type: str) -> dict:
    if media_type not in TIPOS_IMAGEM:
        media_type = "image/jpeg"
    return {"type": "image",
            "source": {"type": "base64", "media_type": media_type,
                       "data": base64.b64encode(dados).decode()}}


def monta_conteudo(texto: str, imagens: list[dict] | None = None):
    """Devolve string (sem anexo) ou lista de blocos (com anexo).

    Imagem ANTES do texto: e o que a API recomenda e o que rendeu melhor
    resposta no teste.
    """
    if not imagens:
        return texto
    blocos = list(imagens)
    blocos.append({"type": "text", "text": texto or "O que voce ve nesta imagem?"})
    return blocos

"""Preparo de anexos — imagem nativa, limite e reducao."""
import base64
import io
import sys

import pytest

from conftest import RAIZ

sys.path.insert(0, str(RAIZ / "core"))
from app.anexos import (MAX_BYTES, AnexoInvalido, monta_conteudo,  # noqa: E402
                        prepara_imagem)


def png(larg=100, alt=100) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (larg, alt), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_imagem_vira_bloco_image():
    b = prepara_imagem(png(), "image/png")
    assert b["type"] == "image"
    assert b["source"]["type"] == "base64"
    assert b["source"]["media_type"].startswith("image/")
    base64.b64decode(b["source"]["data"])          # decodifica sem erro


def test_imagem_grande_e_reduzida():
    """Foto de celular tem resolucao muito acima do que o modelo aproveita."""
    grande = png(4000, 3000)
    b = prepara_imagem(grande, "image/png")
    novo = base64.b64decode(b["source"]["data"])
    assert len(novo) < len(grande)
    from PIL import Image
    assert max(Image.open(io.BytesIO(novo)).size) <= 1568


def test_imagem_pequena_passa_intacta():
    p = png(200, 200)
    b = prepara_imagem(p, "image/png")
    assert base64.b64decode(b["source"]["data"]) == p


def test_acima_de_20mb_e_recusado():
    with pytest.raises(AnexoInvalido) as e:
        prepara_imagem(b"x" * (MAX_BYTES + 1))
    assert "20" in str(e.value)


def test_vazio_e_recusado():
    with pytest.raises(AnexoInvalido):
        prepara_imagem(b"")


def test_lixo_nao_derruba():
    """Bytes que nao sao imagem: envia como veio, sem estourar."""
    b = prepara_imagem(b"nao sou imagem", "image/png")
    assert b["type"] == "image"


# --- monta_conteudo ---

def test_sem_anexo_devolve_string():
    assert monta_conteudo("quanto vendemos") == "quanto vendemos"


def test_com_anexo_devolve_lista_com_imagem_primeiro():
    c = monta_conteudo("o que e isso?", [prepara_imagem(png(), "image/png")])
    assert isinstance(c, list) and len(c) == 2
    assert c[0]["type"] == "image"
    assert c[1] == {"type": "text", "text": "o que e isso?"}


def test_texto_vazio_com_imagem_ganha_pergunta_padrao():
    c = monta_conteudo("", [prepara_imagem(png(), "image/png")])
    assert c[1]["text"].strip() != ""


def test_varias_imagens():
    c = monta_conteudo("compare", [prepara_imagem(png(), "image/png")] * 3)
    assert sum(1 for b in c if b["type"] == "image") == 3


# ===================================================================
# Integracao: o agente e o bot repassam a imagem
# ===================================================================

def _fonte(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_run_turn_e_run_turn_stream_aceitam_imagens():
    s = _fonte("core/app/agent.py")
    assert s.count("imagens: list | None = None") == 2
    assert s.count("monta_conteudo(user_message, imagens)") == 2


def test_adapter_repassa_imagens():
    s = _fonte("core/app/adapters/telegram.py")
    assert "imagens: list | None = None" in s
    assert "imagens=imagens," in s


def test_bot_escuta_foto_e_documento():
    """Antes so filters.TEXT — foto era ignorada em silencio."""
    s = _fonte("channels/telegram_bot/main.py")
    assert "filters.PHOTO" in s
    assert "filters.Document.ALL" in s


def test_bot_usa_a_maior_resolucao_da_foto():
    """msg.photo vem em varios tamanhos; [-1] e o maior."""
    assert "msg.photo[-1]" in _fonte("channels/telegram_bot/main.py")


def test_bot_recusa_acima_de_20mb_antes_de_baixar():
    """Checa file_size ANTES do download — nao gasta banda a toa."""
    s = _fonte("channels/telegram_bot/main.py")
    i = s.index("file_size")
    j = s.index("download_as_bytearray")
    assert i < j, "o limite tem que ser checado antes do download"


def test_bot_explica_que_pdf_ainda_nao():
    """PDF devolve [Unsupported Document] no modelo — avisar, nao falhar."""
    s = _fonte("channels/telegram_bot/main.py")
    assert "PDF e planilha ainda nao" in s


def test_caption_da_foto_vira_a_pergunta():
    assert "msg.caption" in _fonte("channels/telegram_bot/main.py")

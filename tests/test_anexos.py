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


# ===================================================================
# Endpoint web (10/09/2026)
# ===================================================================

def test_chatrequest_aceita_imagens():
    s = _fonte("gateway/app/routes/chat.py")
    assert "imagens: list[str] | None = None" in s


def test_rota_prepara_e_repassa():
    s = _fonte("gateway/app/routes/chat.py")
    assert "_prepara_imagens" in s
    assert "imagens=_imgs or None" in s


def test_helper_esta_no_nivel_do_modulo():
    """Ja quebrou uma vez: o helper entrou ENTRE o decorador e a funcao."""
    s = _fonte("gateway/app/routes/chat.py")
    assert s.index("def _prepara_imagens") < s.index('@router.post("/chat")')


def test_rota_avisa_em_vez_de_quebrar():
    """Imagem invalida vira mensagem no stream, nao exception."""
    s = _fonte("gateway/app/routes/chat.py")
    i = s.index("_erro_img")
    assert "anexo_invalido" in s[i:i + 500]


def test_limite_de_5_imagens():
    assert "MAX_IMAGENS = 5" in _fonte("gateway/app/routes/chat.py")


def test_front_envia_imagens_no_corpo():
    s = _fonte("frontend/src/App.tsx")
    assert "imagens: imgs.length ? imgs : undefined" in s


def test_front_aceita_colar_imagem():
    """Ctrl+V de print e o caso mais comum no uso real."""
    assert "onPaste" in _fonte("frontend/src/App.tsx")


def test_front_limita_20mb_e_so_imagem():
    s = _fonte("frontend/src/App.tsx")
    assert "MAX_ANEXO_MB = 20" in s
    assert 'f.type.startsWith("image/")' in s


def test_front_permite_enviar_so_imagem():
    """Sem texto, com anexo, tem que enviar."""
    s = _fonte("frontend/src/App.tsx")
    assert "(!question && anexos.length === 0 && !planilha)" in s


def test_front_limpa_anexos_apos_enviar():
    assert "setAnexos([]);" in _fonte("frontend/src/App.tsx")


def test_botao_enviar_considera_anexos():
    """Bug de 10/09: disabled={!input.trim()} travava o envio so-imagem."""
    s = _fonte("frontend/src/App.tsx")
    assert "disabled={!input.trim() && anexos.length === 0 && !planilha}" in s


def test_front_reduz_a_imagem_antes_de_enviar():
    """Sem isso o nginx devolve 413 e o upload fica lento."""
    s = _fonte("frontend/src/App.tsx")
    assert "canvas" in s and "toDataURL" in s
    assert "MAX = 1568" in s


def test_front_aceita_heic():
    """iPhone manda HEIC por padrao."""
    s = _fonte("frontend/src/App.tsx")
    assert "heic" in s.lower()


def test_historico_guarda_as_imagens():
    """Sem isso a proxima pergunta chega ao modelo com a mensagem VAZIA."""
    s = _fonte("gateway/app/routes/chat.py")
    assert '_cont_user["imagens"]' in s


def test_janela_devolve_a_imagem_da_ultima_troca():
    s = _fonte("gateway/app/db.py")
    assert "ult_img" in s
    assert "[imagem enviada nesta conversa]" in s


def test_bolha_do_usuario_mostra_a_imagem():
    s = _fonte("frontend/src/App.tsx")
    assert "msg-imagens" in s
    assert "imagens?: string[]" in s


def test_api_de_conversa_devolve_as_imagens():
    """O db.get_messages devolve `content` inteiro, mas quem monta o objeto
    do front e o conversations.py — foi la que faltou o campo."""
    s = _fonte("gateway/app/routes/conversations.py")
    assert '"imagens"' in s


def test_titulo_da_conversa_com_so_imagem():
    """Titulo vazio virava 'Nova conversa' repetida na barra lateral."""
    assert '"Imagem enviada"' in _fonte("frontend/src/App.tsx")


def test_titulo_sai_da_imagem_quando_nao_ha_texto():
    """Mensagem so com foto enchia a barra lateral de 'Nova conversa'."""
    s = _fonte("gateway/app/routes/chat.py")
    assert "_titulo_da_imagem" in s
    assert "_titulo" in s


def test_evento_de_observabilidade_nunca_tem_pergunta_vazia():
    """No painel do Grafana a linha aparecia em branco."""
    s = _fonte("gateway/app/routes/chat.py")
    i = s.index('"pergunta":')
    assert "imagem(ns)" in s[i:i + 300]


def test_evento_registra_quantidade_de_imagens():
    assert '"imagens": len(_imgs)' in _fonte("gateway/app/routes/chat.py")


def test_precos_do_deepseek_atualizados():
    """Estavam em 0.14/0.28; o V4.1 Flash e 0.15/0.60."""
    s = _fonte("gateway/app/routes/chat.py")
    assert "0.15, 0.60, 0.003" in s
    assert "0.14, 0.28" not in s


def test_titulo_da_imagem_usa_cliente_assincrono():
    """`with` sincrono num AsyncAnthropic estoura e cai no fallback —
    era por isso que o titulo ficava sempre 'Imagem enviada'."""
    s = _fonte("gateway/app/routes/chat.py")
    i = s.index("_titulo_da_imagem")
    bloco = s[i:i + 1800]
    assert "async with cli.messages.stream" in bloco
    assert "async for _ in st.text_stream" in bloco
    assert "await st.get_final_message()" in bloco


def test_front_aceita_o_titulo_do_backend_sempre():
    """O titulo so era atualizado quando o id mudava — em conversa so com
    imagem o provisorio 'Imagem enviada' ficava para sempre."""
    s = _fonte("frontend/src/App.tsx")
    i = s.index('if (ev.type === "conversation")')
    bloco = s[i:i + 700]
    j = bloco.index("title: ev.title")
    k = bloco.index("if (realId !== oldId)")
    assert j < k, "o titulo tem que ser aplicado ANTES do if de id diferente"


def test_titulo_tem_max_tokens_folgado():
    """Com teto baixo o modelo termina em max_tokens SEM texto — o titulo
    vinha vazio, caia no fallback e NAO registrava erro (intermitente)."""
    s = _fonte("gateway/app/routes/chat.py")
    i = s.index("_titulo_da_imagem")
    assert "max_tokens=4000" in s[i:i + 1800]


def test_titulo_vazio_e_registrado():
    s = _fonte("gateway/app/routes/chat.py")
    assert "titulo da imagem veio VAZIO" in s


def test_dolar_uniforme_em_520():
    """Havia 5,40 em dois arquivos e 5,20 em outro — o painel dava valores
    diferentes conforme o canal."""
    for rel in ("gateway/app/routes/chat.py", "core/app/adapters/telegram.py"):
        s = _fonte(rel)
        assert "5.40" not in s, f"{rel} ainda tem 5,40"


def test_precos_do_deepseek_nao_caem_no_else_do_claude():
    """`if 'pro' in _mstr` nao pega 'deepseek-flash' — o nome novo caia no
    else final, que usa os precos do Claude Sonnet (3,0/15,0) e inflava 4x."""
    s = _fonte("gateway/app/routes/chat.py")
    i = s.index("_mstr = str(model_used).lower()")
    bloco = s[i:i + 900]
    assert bloco.count("0.15, 0.60, 0.003") >= 2, \
        "os dois ramos do deepseek precisam ter o preco do V4.1 Flash"


def test_telegram_tem_ramo_do_deepseek_no_evento():
    """O registro do bot so tinha haiku/opus/else — o deepseek caia no else
    com precos do Claude Sonnet. Turnos a R$ 2,14 que custavam R$ 0,10."""
    s = _fonte("core/app/adapters/telegram.py")
    i = s.index("_mstr = str(")
    bloco = s[i:i + 900]
    assert "'deepseek' in _mstr" in bloco
    assert "0.15, 0.60, 0.003" in bloco


def test_nenhum_canal_usa_preco_do_sonnet_para_deepseek():
    for rel in ("gateway/app/routes/chat.py", "core/app/adapters/telegram.py"):
        s = _fonte(rel)
        i = s.index("'deepseek' in _mstr")
        # o ramo do deepseek vem ANTES do else do sonnet
        assert i < s.index("3.0, 15.0, 0.30, 6.0"), rel

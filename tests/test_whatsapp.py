"""WhatsApp em grupo: parsing, gatilho, identidade, formato e a rota.

O teste de ponta a ponta sobe a rota real do FastAPI com o agente e a
Evolution simulados, e confere as quatro portas de seguranca.
"""
import asyncio
import sys
import time
import types

import pytest

from conftest import RAIZ

sys.path.insert(0, str(RAIZ / "core"))
from app.adapters import whatsapp as wa  # noqa: E402

GRUPO = "120363000000000001@g.us"
BOT = "5511888887777"
THIAGO = "5511999998888"


def evento(texto, *, grupo=GRUPO, participant=f"{THIAGO}@s.whatsapp.net",
           mencoes=None, responde_a=None, from_me=False, alt=None, formato="ext"):
    ctx = {}
    if mencoes:
        ctx["mentionedJid"] = mencoes
    if responde_a:
        ctx["participant"] = responde_a
    if formato == "conv":
        msg = {"conversation": texto}
    else:
        msg = {"extendedTextMessage": {"text": texto, "contextInfo": ctx}}
    key = {"remoteJid": grupo, "fromMe": from_me, "id": "ABC123",
           "participant": participant}
    if alt:
        key["participantAlt"] = alt
    return {"event": "messages.upsert", "instance": "ebdia",
            "data": {"key": key, "pushName": "Thiago", "message": msg}}


# ─── parsing ───

def test_parse_texto_com_mencao():
    m = wa.parse_evento(evento(f"@{BOT} faturamento hoje",
                               mencoes=[f"{BOT}@s.whatsapp.net"]))
    assert m.grupo == GRUPO and m.telefone == THIAGO and m.msg_id == "ABC123"
    assert m.mencionados == [f"{BOT}@s.whatsapp.net"]


def test_parse_formato_conversation():
    assert wa.parse_evento(evento("oi", formato="conv")).texto == "oi"


def privado(texto, de=f"{THIAGO}@s.whatsapp.net", alt=None, from_me=False):
    key = {"remoteJid": de, "fromMe": from_me, "id": "PRIV1"}
    if alt:
        key["remoteJidAlt"] = alt
    return {"event": "messages.upsert",
            "data": {"key": key, "pushName": "Thiago",
                     "message": {"conversation": texto}}}


def test_conversa_privada_e_lida():
    m = wa.parse_evento(privado("como estamos?"))
    assert m.privado and m.telefone == THIAGO and m.grupo == f"{THIAGO}@s.whatsapp.net"


def test_privado_nao_precisa_de_mencao():
    assert wa.foi_chamado(wa.parse_evento(privado("faturamento hoje")), {BOT})


def test_privado_por_lid_com_telefone_alternativo():
    m = wa.parse_evento(privado("oi", de="99887766@lid", alt=f"{THIAGO}@s.whatsapp.net"))
    assert m.privado and m.telefone == THIAGO and m.lid == "99887766"


@pytest.mark.parametrize("jid", ["status@broadcast", "120363@newsletter", "123@broadcast"])
def test_status_canal_e_broadcast_ignorados(jid):
    assert wa.parse_evento(evento("oi", grupo=jid)) is None


def test_privado_nao_cita():
    m = wa.parse_evento(privado("pergunta"))
    assert "quoted" not in wa.payload_texto(m.grupo, "resposta", m)


def test_outros_eventos_ignorados():
    ev = evento("oi"); ev["event"] = "connection.update"
    assert wa.parse_evento(ev) is None


def test_data_como_lista():
    ev = evento("oi"); ev["data"] = [ev["data"]]
    assert wa.parse_evento(ev).texto == "oi"


def test_remetente_lid_com_telefone_alternativo():
    m = wa.parse_evento(evento("oi", participant="99887766@lid",
                               alt=f"{THIAGO}@s.whatsapp.net"))
    assert m.telefone == THIAGO and m.lid == "99887766"


def test_remetente_so_lid():
    m = wa.parse_evento(evento("oi", participant="99887766@lid"))
    assert m.telefone is None and m.lid == "99887766"


# ─── gatilho ───

@pytest.mark.parametrize("texto,mencoes,resp,esperado", [
    (f"@{BOT} como estamos", [f"{BOT}@s.whatsapp.net"], None, True),
    ("@ebd.ia como estamos", None, None, True),
    ("@EBD.IA como estamos", None, None, True),
    ("e aí, e a filial 05?", None, f"{BOT}@s.whatsapp.net", True),
    ("bom dia pessoal", None, None, False),
    ("@5511777 olha isso", ["5511777@s.whatsapp.net"], None, False),
])
def test_foi_chamado(texto, mencoes, resp, esperado):
    m = wa.parse_evento(evento(texto, mencoes=mencoes, responde_a=resp))
    assert wa.foi_chamado(m, {f"{BOT}@s.whatsapp.net"}) is esperado


def test_nunca_responde_a_si_mesmo():
    m = wa.parse_evento(evento("@ebd.ia teste", from_me=True))
    assert wa.foi_chamado(m, {BOT}) is False


def test_mencao_com_sufixo_de_dispositivo():
    m = wa.parse_evento(evento("x", mencoes=[f"{BOT}:12@s.whatsapp.net"]))
    assert wa.foi_chamado(m, {f"{BOT}@s.whatsapp.net"})


def test_limpa_pergunta():
    assert wa.limpa_pergunta(f"@{BOT} como está o faturamento?") == "como está o faturamento?"
    assert wa.limpa_pergunta("@ebd.ia, ranking das filiais") == "ranking das filiais"
    assert wa.limpa_pergunta("@ebd.ia") == ""


# ─── identidade ───

def test_mapa_de_numeros(monkeypatch):
    monkeypatch.setenv("WA_NUMEROS", f"+55 (11) 99999-8888=Thiago@EBD.com , lid:998877=ana@ebd.com, lixo")
    mapa = wa.mapa_numeros()
    assert mapa == {THIAGO: "thiago@ebd.com", "lid:998877": "ana@ebd.com"}


def test_email_por_telefone_e_por_lid():
    mapa = {THIAGO: "t@e", "lid:99887766": "l@e"}
    assert wa.email_do_remetente(wa.parse_evento(evento("x")), mapa) == "t@e"
    so_lid = wa.parse_evento(evento("x", participant="99887766@lid"))
    assert wa.email_do_remetente(so_lid, mapa) == "l@e"
    estranho = wa.parse_evento(evento("x", participant="5521000@s.whatsapp.net"))
    assert wa.email_do_remetente(estranho, mapa) is None


# ─── formato ───

def test_negrito_italico_titulo_link():
    s = wa.md_para_whatsapp("## Resumo\n**R$ 344M** e *parcial*\n[painel](https://x.y)")
    assert "*Resumo*" in s and "*R$ 344M*" in s and "_parcial_" in s
    assert "painel (https://x.y)" in s and "**" not in s and "#" not in s


def test_tabela_vira_lista():
    md = "| Filial | Líquido | % Meta |\n|---|---:|---:|\n| **05 DUQUE** | R$ 46,9M | 99,4% |\n| 13 TAQUARA | R$ 37,9M | 89,4% |"
    s = wa.md_para_whatsapp(md)
    assert "|" not in s
    assert "*05 DUQUE* — Líquido: R$ 46,9M · % Meta: 99,4%" in s


def test_codigo_preservado():
    s = wa.md_para_whatsapp("```\n**nao mexe** | a | b |\n```")
    assert "**nao mexe**" in s


def test_lista_markdown_vira_bullet():
    assert wa.md_para_whatsapp("- um\n- dois") == "• um\n• dois"


def test_fatiar_respeita_limite():
    # 3 paragrafos de 900 + separadores = 2.704; o 4o estouraria 3.500
    partes = wa.fatiar("\n\n".join(["x" * 900] * 10), limite=3500)
    assert all(len(p) <= 3500 for p in partes) and len(partes) == 4


def test_payload_cita_a_pergunta():
    m = wa.parse_evento(evento("pergunta"))
    p = wa.payload_texto(GRUPO, "resposta", m)
    assert p["number"] == GRUPO and p["quoted"]["key"]["id"] == "ABC123"
    assert "quoted" not in wa.payload_texto(GRUPO, "sem citar")


# ─── a rota, de ponta a ponta ───

@pytest.fixture
def rota(monkeypatch):
    pytest.importorskip("httpx", reason="TestClient precisa de httpx no .venv")
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import gateway.app as gw
    from gateway.app.routes import whatsapp as r

    enviados = []

    async def envia(grupo, texto, citar=None):
        enviados.append((grupo, texto, citar.msg_id if citar else None))
        return True

    perguntas = []
    atraso = {"s": 0.0}

    saida = {"eventos": None}

    async def run_turn_stream(**kw):
        perguntas.append(kw)
        if atraso["s"]:
            await asyncio.sleep(atraso["s"])
        for ev in saida["eventos"] or [
            {"type": "token", "text": "Vou consultar."},
            {"type": "tool", "name": "oracle_query"},
            {"type": "token", "text": "**R$ 242,9M** no mês"},
        ]:
            yield ev
        yield {"type": "done", "history": [{"role": "user", "content": "x"}]}

    tabela = {"+5511999998888": {"email": "thiago@ebd.com", "role": "admin"}}

    async def get_user_by_whatsapp(numero):
        return tabela.get(numero)

    async def get_user(email):
        return {"email": email} if email == "lid@ebd.com" else None

    monkeypatch.setattr(r, "envia_texto", envia)

    audios, arquivos = [], []

    async def envia_audio(chat, wav, citar=None):
        audios.append((chat, wav))
        return True

    async def envia_arquivo(chat, dados, nome, legenda=""):
        arquivos.append((chat, nome, dados))
        return True

    async def baixa_midia(m):
        return b"BYTES-DA-MIDIA"

    monkeypatch.setattr(r, "envia_audio", envia_audio)
    monkeypatch.setattr(r, "envia_arquivo", envia_arquivo)
    monkeypatch.setattr(r, "baixa_midia", baixa_midia)
    monkeypatch.setattr(r.voz, "transcrever", lambda dados, sufixo=".ogg": "como estamos em setembro")
    monkeypatch.setattr(r.voz, "sintetizar", lambda texto: b"WAV:" + texto.encode())
    monkeypatch.setitem(sys.modules, "app.agent",
                        types.SimpleNamespace(run_turn_stream=run_turn_stream))
    acl = types.SimpleNamespace(get_user_by_whatsapp=get_user_by_whatsapp,
                                get_user=get_user)
    monkeypatch.setitem(sys.modules, "gateway.app.acl_store", acl)
    monkeypatch.setattr(gw, "acl_store", acl, raising=False)

    async def ids():
        return {f"{BOT}@s.whatsapp.net"}
    monkeypatch.setattr(r, "_ids_do_bot", ids)
    r._hist.clear()
    r._avisados.clear()
    r._vistos.clear()

    monkeypatch.setenv("WA_ENABLED", "true")
    monkeypatch.setenv("WA_WEBHOOK_TOKEN", "segredo-com-mais-de-16")
    monkeypatch.setenv("WA_GRUPOS", GRUPO)
    # telefone no .env NAO libera (a regra e a tabela); so a chave de LID
    monkeypatch.setenv("WA_NUMEROS", "5521000=furou@ebd.com,lid:77665544=lid@ebd.com")

    app = FastAPI()
    app.include_router(r.router, prefix="/api")
    with TestClient(app) as c:
        c.enviados, c.perguntas, c.r, c.atraso = enviados, perguntas, r, atraso
        c.saida, c.audios, c.arquivos = saida, audios, arquivos
        yield c


H = {"x-ebdia-token": "segredo-com-mais-de-16"}


def _espera(c, n, t=3.0):
    fim = time.time() + t
    while len(c.enviados) < n and time.time() < fim:
        time.sleep(0.02)


def test_rota_sem_token_401(rota):
    assert rota.post("/api/whatsapp/webhook", json=evento("@ebd.ia x")).status_code == 401


def test_rota_via_nginx_404(rota):
    h = dict(H, **{"x-forwarded-for": "8.8.8.8"})
    assert rota.post("/api/whatsapp/webhook", json=evento("@ebd.ia x"), headers=h).status_code == 404


def test_rota_desligada_nao_processa(rota, monkeypatch):
    monkeypatch.setenv("WA_ENABLED", "false")
    r = rota.post("/api/whatsapp/webhook", json=evento("@ebd.ia x"), headers=H)
    assert r.json().get("ignorado") == "desligado"


def test_grupo_nao_autorizado_e_mensagem_comum_descartadas(rota):
    rota.post("/api/whatsapp/webhook", json=evento("@ebd.ia x", grupo="999@g.us"), headers=H)
    rota.post("/api/whatsapp/webhook", json=evento("bom dia a todos"), headers=H)
    time.sleep(0.2)
    assert rota.enviados == [] and rota.perguntas == []


def test_numero_sem_acesso_recebe_aviso_e_nao_consulta(rota):
    rota.post("/api/whatsapp/webhook",
              json=evento("@ebd.ia faturamento", participant="5521000@s.whatsapp.net"), headers=H)
    _espera(rota, 1)
    assert rota.perguntas == []
    assert "não tem permissão" in rota.enviados[0][1]


def test_pergunta_roda_como_a_pessoa_e_responde_citando(rota):
    r = rota.post("/api/whatsapp/webhook",
                  json=evento(f"@{BOT} como estamos em setembro?",
                              mencoes=[f"{BOT}@s.whatsapp.net"]), headers=H)
    assert r.json().get("aceito") is True
    _espera(rota, 1)
    kw = rota.perguntas[0]
    assert kw["user_email"] == "thiago@ebd.com" and kw["channel"] == "whatsapp"
    assert kw["user_role"] != "admin"            # grupo nunca propoe auto-append
    # no grupo a pergunta vai marcada: o agente precisa saber que todos leem
    assert kw["user_message"] == f"{rota.r.MARCA_GRUPO}\ncomo estamos em setembro?"
    # agente rapido: vai direto a resposta, sem aviso intermediario
    assert len(rota.enviados) == 1
    resposta = rota.enviados[0]
    assert resposta[1] == "*R$ 242,9M* no mês"   # so o texto depois da ferramenta, formatado
    assert resposta[2] == "ABC123"               # cita a pergunta


def test_historico_e_por_pessoa(rota):
    rota.post("/api/whatsapp/webhook", json=evento("@ebd.ia a"), headers=H)
    _espera(rota, 1)
    assert (GRUPO, "thiago@ebd.com") in rota.r._hist
    assert all(k[1] == "thiago@ebd.com" for k in rota.r._hist)


# ─── identidade pela tabela de Acessos ───

@pytest.mark.parametrize("entrada,esperado", [
    ("+55 (11) 99999-8888", "+5511999998888"),
    ("11999998888", "+5511999998888"),
    ("5511999998888", "+5511999998888"),
    ("553188887777", "+5531988887777"),     # WhatsApp manda sem o nono digito
    ("(31) 8888-7777", "+5531988887777"),
    ("551133334444", "+551133334444"),      # fixo nao ganha 9
    ("+1 415 555 2671", "+14155552671"),    # com + o pais e respeitado
    ("123", None), ("", None), (None, None), ("55119999988887777", None),
])
def test_normaliza_whatsapp(entrada, esperado):
    assert wa.normaliza_whatsapp(entrada) == esperado


def test_nono_digito_casa_nos_dois_sentidos():
    """A tela grava com o 9; o webhook pode trazer sem. Tem que bater."""
    assert wa.normaliza_whatsapp("+55 31 98888-7777") == wa.normaliza_whatsapp("553188887777")


def test_telefone_no_env_nao_libera(rota):
    """5521000 esta em WA_NUMEROS mas NAO na tabela: sem permissao."""
    rota.post("/api/whatsapp/webhook",
              json=evento("@ebd.ia x", participant="5521000@s.whatsapp.net"), headers=H)
    _espera(rota, 1)
    assert rota.perguntas == [] and "não tem permissão" in rota.enviados[0][1]


def test_lid_sem_telefone_usa_a_excecao(rota):
    rota.post("/api/whatsapp/webhook",
              json=evento("@ebd.ia x", participant="77665544@lid"), headers=H)
    _espera(rota, 1)
    assert rota.perguntas and rota.perguntas[0]["user_email"] == "lid@ebd.com"


def test_webhook_sem_o_nono_digito_acha_o_cadastrado(rota):
    """Cadastro +5511999998888; o WhatsApp manda 551199998888 (sem o 9)."""
    rota.post("/api/whatsapp/webhook",
              json=evento("@ebd.ia x", participant="551199998888@s.whatsapp.net"), headers=H)
    _espera(rota, 1)
    assert rota.perguntas and rota.perguntas[0]["user_email"] == "thiago@ebd.com"


# ─── tela de Acessos ───

ADMIN = (RAIZ / "gateway/app/routes/admin_acl.py").read_text(encoding="utf-8")
MIG = (RAIZ / "infra/postgres/migrations/006_acl_whatsapp.sql").read_text(encoding="utf-8")
TELA = (RAIZ / "frontend/src/AccessAdmin.tsx").read_text(encoding="utf-8")


def test_api_grava_normalizado_e_recusa_invalido():
    assert "whatsapp: str | None = None" in ADMIN
    assert "normaliza_whatsapp(body.whatsapp)" in ADMIN
    assert "raise HTTPException(400" in ADMIN


def test_api_trata_numero_duplicado():
    assert ADMIN.count("_conflito_whatsapp(e)") == 2      # create e update


def test_listagem_devolve_o_whatsapp():
    assert "active, whatsapp, created_by" in ADMIN


def test_migration_idempotente_com_formato_e_unicidade():
    assert "ADD COLUMN IF NOT EXISTS whatsapp" in MIG
    assert "DROP CONSTRAINT IF EXISTS acl_users_whatsapp_e164" in MIG
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_acl_users_whatsapp" in MIG


def test_tela_tem_campo_e_coluna():
    assert 'placeholder="WhatsApp +55 11 99999-8888"' in TELA
    assert "<th>WhatsApp</th>" in TELA


# ─── rota: conversa privada ───

def test_privado_com_permissao_responde_sem_mencao(rota):
    rota.post("/api/whatsapp/webhook", json=privado("como estamos em setembro?"), headers=H)
    _espera(rota, 1)
    kw = rota.perguntas[0]
    assert kw["user_email"] == "thiago@ebd.com"
    assert kw["user_message"] == "como estamos em setembro?"     # sem a marca de grupo
    assert rota.enviados[0][0] == f"{THIAGO}@s.whatsapp.net"      # responde na conversa


def test_grupo_leva_a_marca_para_o_agente(rota):
    rota.post("/api/whatsapp/webhook", json=evento("@ebd.ia ranking"), headers=H)
    _espera(rota, 1)
    msg = rota.perguntas[0]["user_message"]
    assert msg.startswith("[GRUPO de WhatsApp") and msg.endswith("ranking")


def test_privado_sem_permissao_avisa_uma_vez_so(rota):
    estranho = "5521000000000@s.whatsapp.net"
    for _ in range(3):
        rota.post("/api/whatsapp/webhook", json=privado("oi", de=estranho), headers=H)
    time.sleep(0.4)
    avisos = [e for e in rota.enviados if e[0] == estranho]
    assert len(avisos) == 1 and "não tem permissão" in avisos[0][1]
    assert rota.perguntas == []


def test_privado_desligado_ignora(rota, monkeypatch):
    monkeypatch.setenv("WA_PRIVADO", "false")
    rota.post("/api/whatsapp/webhook", json=privado("oi"), headers=H)
    time.sleep(0.2)
    assert rota.enviados == [] and rota.perguntas == []


def test_mensagem_do_proprio_bot_no_privado_ignorada(rota):
    rota.post("/api/whatsapp/webhook", json=privado("resposta minha", from_me=True), headers=H)
    time.sleep(0.2)
    assert rota.enviados == []


def test_parear_nao_derruba_instancia_conectada():
    sh = (RAIZ / "scripts/wa_setup.sh").read_text(encoding="utf-8")
    i = sh.index("parear)")
    bloco = sh[i:sh.index("webhook)")]
    assert bloco.index('"open"') < bloco.index("/instance/delete/"), \
        "tem que checar o estado ANTES de apagar a instancia"
    assert "--forcar" in bloco


# ─── aviso "ja te retorno": contextual e so quando demora ───

sys.path.insert(0, str(RAIZ / "core"))
from app.adapters import whatsapp_ack as ack  # noqa: E402


@pytest.mark.parametrize("pergunta,esperado", [
    ("emite pra mim um painel da diretoria de agosto/25", "painel"),
    ("relatório geral de vendas", "painel"),
    ("como estamos em setembro?", "agora"),
    ("como está a regional do gerente Fabio?", "agora"),   # "gerente" nao e "gerar"
    ("como está contra a meta?", "meta"),                  # meta antes de comparacao
    ("compara agosto com agosto do ano passado", "compara"),
    ("top 10 indústrias do mês", "ranking"),
    ("tem ruptura de Nissin em Manaus?", "estoque"),
    ("quanto faturou a filial 05 ontem?", "generica"),
    ("tá aí?", None), ("valeu!", None), ("oi", None), ("bom dia", None),
    ("e ai doutor?", None), ("fala meu querido", None), ("tudo certo por ai?", None),
    ("me ajuda com uma coisa rapida", None),
])
def test_intencao(pergunta, esperado):
    assert ack.intencao(pergunta) == esperado


def test_frase_usa_o_primeiro_nome():
    import random
    f = ack.frase_de_aviso("emite o painel", "Thiago", random.Random(0))
    assert "Thiago" in f and "{n}" not in f


def test_frase_sem_nome_nao_deixa_virgula_solta():
    import random
    for semente in range(20):
        f = ack.frase_de_aviso("como estamos hoje?", "", random.Random(semente))
        assert ", ," not in f and ",." not in f and ",!" not in f and "{n}" not in f


def test_nenhuma_frase_promete_arquivo():
    """Arquivo nao chega pelo WhatsApp: o aviso nao pode prometer PDF/Excel."""
    todas = [f for _, _, pool in ack.INTENCOES for f in pool] + ack.GENERICAS
    assert not any(p in f.lower() for f in todas for p in ("pdf", "excel", "planilha", "arquivo", "ppt"))


def test_primeiro_nome():
    assert ack.primeiro_nome("thiago parreira") == "Thiago"
    assert ack.primeiro_nome("") == "" and ack.primeiro_nome("🙂") == ""


def test_demorou_manda_aviso_contextual_e_depois_a_resposta(rota, monkeypatch):
    monkeypatch.setenv("WA_ACK_APOS_S", "0.05")
    rota.atraso["s"] = 0.4
    rota.post("/api/whatsapp/webhook", json=evento("@ebd.ia emite o painel de agosto"), headers=H)
    _espera(rota, 2)
    aviso, resposta = rota.enviados[0][1], rota.enviados[1][1]
    assert "Consultando" not in aviso
    assert any(p in aviso for p in ("pra já", "comigo", "preparar"))   # frase de painel
    assert resposta == "*R$ 242,9M* no mês"


def test_conversa_curta_demorada_nao_ganha_aviso(rota, monkeypatch):
    monkeypatch.setenv("WA_ACK_APOS_S", "0.05")
    rota.atraso["s"] = 0.3
    rota.post("/api/whatsapp/webhook", json=privado("tá aí?"), headers=H)
    _espera(rota, 1)
    time.sleep(0.2)
    assert len(rota.enviados) == 1                     # so a resposta


# ─── midia: foto, audio, planilha, arquivos ───

from app.adapters import whatsapp_voz as voz  # noqa: E402


def midia(tipo, *, grupo=GRUPO, participant=f"{THIAGO}@s.whatsapp.net", legenda="",
          nome="", mimetype="", responde_a=None, b64=None, com_legenda_doc=False):
    ctx = {"participant": responde_a} if responde_a else {}
    corpo = {"mimetype": mimetype, "contextInfo": ctx}
    if tipo == "imageMessage":
        corpo["caption"] = legenda
    if tipo == "documentMessage":
        corpo.update({"fileName": nome, "caption": legenda})
    if tipo == "audioMessage":
        corpo["ptt"] = True
    msg = {tipo: corpo}
    if com_legenda_doc:
        msg = {"documentWithCaptionMessage": {"message": msg}}
    if b64:
        msg["base64"] = b64
    key = {"remoteJid": grupo, "fromMe": False, "id": "MID1"}
    if not grupo.endswith("@s.whatsapp.net"):
        key["participant"] = participant
    return {"event": "messages.upsert", "data": {"key": key, "pushName": "Thiago", "message": msg}}


def test_parse_foto_com_legenda():
    m = wa.parse_evento(midia("imageMessage", legenda="@ebd.ia que produto é esse?", mimetype="image/jpeg"))
    assert m.midia["tipo"] == "imagem" and m.texto == "@ebd.ia que produto é esse?"


def test_parse_audio_sem_texto_nao_e_descartado():
    m = wa.parse_evento(midia("audioMessage", grupo=f"{THIAGO}@s.whatsapp.net",
                              mimetype="audio/ogg; codecs=opus"))
    assert m is not None and m.midia["tipo"] == "audio" and m.midia["voz"]
    assert m.midia["mimetype"] == "audio/ogg"


def test_parse_documento_com_legenda_e_base64():
    m = wa.parse_evento(midia("documentMessage", nome="frota.xlsx", legenda="@ebd.ia cruza isso",
                              com_legenda_doc=True, b64="QUJD"))
    assert m.midia["nome"] == "frota.xlsx" and m.midia["base64"] == "QUJD"
    assert m.texto == "@ebd.ia cruza isso"


def test_audio_no_grupo_so_respondendo_ao_bot():
    ids = {f"{BOT}@s.whatsapp.net"}
    solto = wa.parse_evento(midia("audioMessage"))
    resposta = wa.parse_evento(midia("audioMessage", responde_a=f"{BOT}@s.whatsapp.net"))
    assert not wa.foi_chamado(solto, ids)
    assert wa.foi_chamado(resposta, ids)


def test_foto_no_grupo_precisa_de_mencao_na_legenda():
    ids = {f"{BOT}@s.whatsapp.net"}
    assert not wa.foi_chamado(wa.parse_evento(midia("imageMessage", legenda="olha isso")), ids)
    assert wa.foi_chamado(wa.parse_evento(midia("imageMessage", legenda="@ebd.ia olha")), ids)


@pytest.mark.parametrize("texto,esperado", [
    ("me manda em áudio o faturamento", True), ("responde por voz", True),
    ("manda um audio com o ranking", True), ("grava um áudio pra mim", True),
    ("como estamos hoje?", False), ("auditoria de estoque", False),
])
def test_pediu_audio(texto, esperado):
    assert voz.pediu_audio(texto) is esperado


def test_fala_e_texto_visual_separados():
    r = "Faturou **R$ 344M**.\n\n| a | b |\n\n<FALA>Agosto fechou em trezentos e quarenta e quatro milhões.</FALA>"
    assert voz.extrair_fala(r) == "Agosto fechou em trezentos e quarenta e quatro milhões."
    assert "<FALA>" not in voz.limpar_texto_visual(r) and "R$ 344M" in voz.limpar_texto_visual(r)


def test_sem_bloco_fala_usa_resumo_sem_tabela():
    f = voz.extrair_fala("Setembro está em 69,8%.\n| Filial | Valor |\n|---|---|\n| 05 | 36M |")
    assert "|" not in f and "69,8" in f


def test_preparar_fala_expande_simbolos():
    f = voz.preparar_fala("**R$ 344 mi** e 102,8% da meta")
    assert "milhões de reais" in f and "por cento" in f and "*" not in f


def test_audio_privado_transcreve_confirma_e_responde_em_audio(rota):
    rota.saida["eventos"] = [{"type": "token", "text": "**R$ 242,9M** no mês.\n<FALA>Setembro vai em duzentos e quarenta e três milhões.</FALA>"}]
    rota.post("/api/whatsapp/webhook", json=midia("audioMessage", grupo=f"{THIAGO}@s.whatsapp.net",
              mimetype="audio/ogg"), headers=H)
    _espera(rota, 1)
    time.sleep(0.2)
    assert not any("Entendi" in e[1] for e in rota.enviados)   # eco desligado por padrao
    kw = rota.perguntas[0]
    assert kw["user_message"].startswith("como estamos em setembro") and "<FALA>" in kw["user_message"]
    assert rota.audios and rota.audios[0][1] == "WAV:Setembro vai em duzentos e quarenta e três milhões.".encode()
    assert "<FALA>" not in rota.enviados[-1][1] and "R$ 242,9M" in rota.enviados[-1][1]


def test_texto_pedindo_audio_responde_em_audio(rota):
    rota.post("/api/whatsapp/webhook", json=privado("me manda em áudio como estamos"), headers=H)
    _espera(rota, 1)
    time.sleep(0.2)
    assert rota.audios, "pediu audio por escrito e nao recebeu"


def test_voz_nao_instalada_avisa(rota, monkeypatch):
    def sem_voz(*a, **k):
        raise voz.VozIndisponivel("x")
    monkeypatch.setattr(rota.r.voz, "transcrever", sem_voz)
    rota.post("/api/whatsapp/webhook", json=midia("audioMessage", grupo=f"{THIAGO}@s.whatsapp.net"), headers=H)
    _espera(rota, 1)
    assert "não consigo ouvir" in rota.enviados[0][1] and rota.perguntas == []


def test_foto_privada_vai_ao_agente_como_imagem(rota, monkeypatch):
    import app.anexos as anexos
    monkeypatch.setattr(anexos, "prepara_imagem", lambda dados, mime: {"type": "image", "mime": mime})
    rota.post("/api/whatsapp/webhook", json=midia("imageMessage", grupo=f"{THIAGO}@s.whatsapp.net",
              mimetype="image/jpeg"), headers=H)
    _espera(rota, 1)
    kw = rota.perguntas[0]
    assert kw["imagens"] == [{"type": "image", "mime": "image/jpeg"}]
    assert "O que é isto" in kw["user_message"]


def test_planilha_privada_passa_contexto_ao_agente(rota, monkeypatch):
    async def recebe(m, email, dados):
        return {"conversation_id": "C1"}, "[aviso planilha]", None
    monkeypatch.setattr(rota.r, "_recebe_planilha", recebe)
    rota.post("/api/whatsapp/webhook", json=midia("documentMessage", grupo=f"{THIAGO}@s.whatsapp.net",
              nome="vendas.xlsx"), headers=H)
    _espera(rota, 1)
    kw = rota.perguntas[0]
    assert kw["planilha_ctx"] == {"conversation_id": "C1"} and kw["aviso_planilha"] == "[aviso planilha]"


def test_documento_nao_suportado_avisa(rota):
    rota.post("/api/whatsapp/webhook", json=midia("documentMessage", grupo=f"{THIAGO}@s.whatsapp.net",
              nome="contrato.pdf", mimetype="application/pdf"), headers=H)
    _espera(rota, 1)
    assert "ainda não" in rota.enviados[0][1] and rota.perguntas == []


def test_arquivo_gerado_vai_como_documento(rota, monkeypatch, tmp_path):
    (tmp_path / "abc123.xlsx").write_bytes(b"PK-EXCEL")
    monkeypatch.setitem(sys.modules, "app.artifacts", types.SimpleNamespace(ARTIFACTS_DIR=tmp_path))
    rota.saida["eventos"] = [{"type": "artifact", "id": "abc123", "kind": "xlsx",
                              "filename": "Faturamento_Agosto.xlsx"},
                             {"type": "token", "text": "Segue a planilha."}]
    rota.post("/api/whatsapp/webhook", json=privado("gera a planilha de agosto"), headers=H)
    _espera(rota, 1)
    time.sleep(0.3)
    assert rota.arquivos == [(f"{THIAGO}@s.whatsapp.net", "Faturamento_Agosto.xlsx", b"PK-EXCEL")]


def test_wa_setup_grupos_sem_barra_em_aspas_simples():
    """Dentro de aspas simples do bash, \\" chega literal ao Python e quebra
    (bug de 30/09/2026 no comando grupos)."""
    sh = (RAIZ / "scripts/wa_setup.sh").read_text(encoding="utf-8")
    i = sh.index("  grupos)")
    assert '\\"' not in sh[i:sh.index(";;", i)]



def test_mesmo_evento_duas_vezes_responde_uma_so(rota):
    ev = privado("como estamos em setembro?")
    rota.post("/api/whatsapp/webhook", json=ev, headers=H)
    r2 = rota.post("/api/whatsapp/webhook", json=ev, headers=H)
    time.sleep(0.4)
    assert r2.json().get("repetido") is True
    assert len(rota.perguntas) == 1


def test_aviso_padrao_e_15s(monkeypatch):
    monkeypatch.delenv("WA_ACK_APOS_S", raising=False)
    assert ack.espera_antes_do_aviso() == 15.0


def test_aviso_desligavel(rota, monkeypatch):
    monkeypatch.setenv("WA_ACK_APOS_S", "0.05")
    monkeypatch.setenv("WA_ACK", "false")
    rota.atraso["s"] = 0.3
    rota.post("/api/whatsapp/webhook", json=privado("emite o painel de agosto"), headers=H)
    _espera(rota, 1)
    time.sleep(0.4)
    assert len(rota.enviados) == 1



def test_eco_da_transcricao_religavel(rota, monkeypatch):
    monkeypatch.setenv("WA_VOZ_ECO", "true")
    rota.post("/api/whatsapp/webhook", json=midia("audioMessage", grupo=f"{THIAGO}@s.whatsapp.net"), headers=H)
    _espera(rota, 1)
    assert rota.enviados[0][1] == "🎙️ Entendi: «como estamos em setembro»"



def test_conversor_preserva_o_padrao_visual():
    molde = ("📊 Faturamento — Março/2026\n\n💰 **R$ 10.810.107**\n"
             "↔️ vs Fev/26: -5,3% 🔴 | vs Mar/25: +11,9% 🟢\n\n"
             "━━━━━━━━━━━━━━━━━━━━━━\n🎯 DIAGNÓSTICO — AÇÕES PRIORITÁRIAS\n"
             "━━━━━━━━━━━━━━━━━━━━━━\n\n1️⃣ Nissin — ruptura com venda ativa\n"
             "Responsável: Compras\n\nQuer aprofundar?\n- \"Margem por RCA\"")
    s = wa.md_para_whatsapp(molde)
    assert "💰 *R$ 10.810.107*" in s
    for trecho in ("━━━━━━━━━━━━━━━━━━━━━━", "1️⃣ Nissin", "↔️ vs Fev/26: -5,3% 🔴",
                   "🎯 DIAGNÓSTICO", '• "Margem por RCA"'):
        assert trecho in s, trecho


def test_claude_md_tem_os_moldes_e_a_trava():
    s = (RAIZ / "docs/CLAUDE.md").read_text(encoding="utf-8")
    assert "### Padrao visual do WhatsApp" in s
    assert "NUNCA justifica completar dado" in s
    assert "Nunca invente nome" in s

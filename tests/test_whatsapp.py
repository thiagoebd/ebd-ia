"""WhatsApp em grupo: parsing, gatilho, identidade, formato e a rota.

O teste de ponta a ponta sobe a rota real do FastAPI com o agente e a
Evolution simulados, e confere as quatro portas de seguranca.
"""
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


def test_conversa_privada_e_ignorada():
    assert wa.parse_evento(evento("oi", grupo=f"{THIAGO}@s.whatsapp.net")) is None


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

    async def run_turn_stream(**kw):
        perguntas.append(kw)
        yield {"type": "token", "text": "Vou consultar."}
        yield {"type": "tool", "name": "oracle_query"}
        yield {"type": "token", "text": "**R$ 242,9M** no mês"}
        yield {"type": "done", "history": [{"role": "user", "content": "x"}]}

    tabela = {"+5511999998888": {"email": "thiago@ebd.com", "role": "admin"}}

    async def get_user_by_whatsapp(numero):
        return tabela.get(numero)

    async def get_user(email):
        return {"email": email} if email == "lid@ebd.com" else None

    monkeypatch.setattr(r, "envia_texto", envia)
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

    monkeypatch.setenv("WA_ENABLED", "true")
    monkeypatch.setenv("WA_WEBHOOK_TOKEN", "segredo-com-mais-de-16")
    monkeypatch.setenv("WA_GRUPOS", GRUPO)
    # telefone no .env NAO libera (a regra e a tabela); so a chave de LID
    monkeypatch.setenv("WA_NUMEROS", "5521000=furou@ebd.com,lid:77665544=lid@ebd.com")

    app = FastAPI()
    app.include_router(r.router, prefix="/api")
    with TestClient(app) as c:
        c.enviados, c.perguntas, c.r = enviados, perguntas, r
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
    _espera(rota, 2)
    kw = rota.perguntas[0]
    assert kw["user_email"] == "thiago@ebd.com" and kw["channel"] == "whatsapp"
    assert kw["user_role"] != "admin"            # grupo nunca propoe auto-append
    assert kw["user_message"] == "como estamos em setembro?"
    ack, resposta = rota.enviados[0], rota.enviados[1]
    assert "Consultando" in ack[1] and ack[2] == "ABC123"
    assert resposta[1] == "*R$ 242,9M* no mês"   # so o texto depois da ferramenta, formatado
    assert resposta[2] == "ABC123"               # cita a pergunta


def test_historico_e_por_pessoa(rota):
    rota.post("/api/whatsapp/webhook", json=evento("@ebd.ia a"), headers=H)
    _espera(rota, 2)
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
    _espera(rota, 2)
    assert rota.perguntas and rota.perguntas[0]["user_email"] == "lid@ebd.com"


def test_webhook_sem_o_nono_digito_acha_o_cadastrado(rota):
    """Cadastro +5511999998888; o WhatsApp manda 551199998888 (sem o 9)."""
    rota.post("/api/whatsapp/webhook",
              json=evento("@ebd.ia x", participant="551199998888@s.whatsapp.net"), headers=H)
    _espera(rota, 2)
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

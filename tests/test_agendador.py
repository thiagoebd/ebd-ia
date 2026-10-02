"""Agendador de tarefas e envio delegado de mensagens.

Duas camadas:
  - pura (cron, calendario, confirmacao, escopo): roda sempre
  - integracao contra Postgres REAL (SKIP LOCKED, unique de idempotencia,
    travas do envio, execucao do job): roda se PG_TESTE_DSN estiver definido,
    ex. PG_TESTE_DSN=postgresql://postgres@/postgres?host=/tmp/pgsock&port=5433
"""
import asyncio
import os
import sys
import types
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from conftest import RAIZ

sys.path.insert(0, str(RAIZ / "core"))
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("BREAK_GLASS_SUPERADMINS", "ninguem@teste.local")

from gateway.app import calendario_winthor as cal  # noqa: E402
from gateway.app import confirmacoes, cron_simples  # noqa: E402
from gateway.app import envio_delegado as env  # noqa: E402

SP = ZoneInfo("America/Sao_Paulo")


def sp(*a):
    return datetime(*a, tzinfo=SP)


# ─── cron ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("expr,depois,esperado", [
    ("0 23 * * *", sp(2026, 9, 30, 22, 0), sp(2026, 9, 30, 23, 0)),
    ("0 23 * * *", sp(2026, 9, 30, 23, 0), sp(2026, 10, 1, 23, 0)),       # estritamente depois
    ("0 8 * * 1-5", sp(2026, 10, 2, 9, 0), sp(2026, 10, 5, 8, 0)),        # sexta -> segunda
    ("*/15 9-10 * * *", sp(2026, 10, 1, 9, 1), sp(2026, 10, 1, 9, 15)),
    ("30 6 1 * *", sp(2026, 12, 15, 0, 0), sp(2027, 1, 1, 6, 30)),        # vira o ano
    ("0 7 1 * 1", sp(2026, 10, 2, 0, 0), sp(2026, 10, 5, 7, 0)),          # dia 1 OU segunda
    ("0 9 * * 7", sp(2026, 10, 1, 0, 0), sp(2026, 10, 4, 9, 0)),          # 7 = domingo
])
def test_cron_proxima(expr, depois, esperado):
    assert cron_simples.proxima(expr, depois) == esperado


def test_cron_calcula_no_fuso_de_sao_paulo_mesmo_vindo_utc():
    utc = datetime(2026, 10, 1, 1, 0, tzinfo=ZoneInfo("UTC"))       # 22:00 de 30/09 em SP
    assert cron_simples.proxima("0 23 * * *", utc) == sp(2026, 9, 30, 23, 0)


@pytest.mark.parametrize("expr", ["", "0 23 * *", "60 1 * * *", "0 24 * * *", "x 1 * * *",
                                  "0 1 * * 8", "*/0 1 * * *", "5-2 1 * * *"])
def test_cron_invalido(expr):
    with pytest.raises(cron_simples.CronInvalido):
        cron_simples.proxima(expr, sp(2026, 10, 1, 0, 0))


def test_cron_de_horario():
    from gateway.app import agendamentos as ag
    assert ag.cron_de(None, "23:00", None) == "0 23 * * *"
    assert ag.cron_de(None, "08:05", "seg-sex") == "5 8 * * 1-5"
    for ruim in ("25:00", "8h", None):
        with pytest.raises(cron_simples.CronInvalido):
            ag.cron_de(None, ruim, None)


# ─── calendario do Winthor ───────────────────────────────────────────────

def _setembro(feriado_regional: date | None = None, filial: str = "BR"):
    """PCDIASUTEIS falso de set/2026: seg-sex vende, sabado/domingo e 07/09 nao."""
    async def consulta(sql, max_rows=40):
        linhas = []
        for d in range(1, 31):
            dia = date(2026, 9, d)
            vende = dia.weekday() < 5 and dia != date(2026, 9, 7) and dia != feriado_regional
            total = 21 if filial == "BR" else 1
            linhas.append({"DIA": dia.isoformat(), "VENDE": total if vende else 0, "TOTAL": total})
        return {"result": {"rows": linhas}}
    return consulta


@pytest.fixture(autouse=True)
def _limpa_cache_cal():
    cal._cache.clear()
    yield
    cal._cache.clear()


@pytest.mark.parametrize("regra,dia,esperado", [
    ("DIA_UTIL", date(2026, 9, 5), False),          # sabado
    ("DIA_UTIL", date(2026, 9, 7), False),          # feriado nacional
    ("DIA_UTIL", date(2026, 9, 8), True),
    ("ULTIMO_DIA_UTIL", date(2026, 9, 30), True),
    ("ULTIMO_DIA_UTIL", date(2026, 9, 29), False),
    ("TODO_DIA", date(2026, 9, 6), True),
])
def test_regra_do_dia(regra, dia, esperado):
    assert asyncio.run(cal.passa_regra(regra, dia, "BR", _setembro())) is esperado


def test_feriado_regional_da_filial():
    consulta = _setembro(feriado_regional=date(2026, 9, 8), filial="04")
    assert asyncio.run(cal.passa_regra("DIA_UTIL", date(2026, 9, 8), "04", consulta)) is False


def test_calendario_fora_do_ar_nao_vira_silencio():
    async def quebrado(sql, max_rows=40):
        return {"error": "ORA-12541: sem listener"}
    with pytest.raises(cal.CalendarioIndisponivel):
        asyncio.run(cal.passa_regra("DIA_UTIL", date(2026, 9, 8), "BR", quebrado))


# ─── confirmacao que o modelo nao pula ───────────────────────────────────

def test_confirmacao_exige_turno_seguinte_e_mesmo_usuario():
    c = confirmacoes.cria("enviar", "a@x", "turno-1", {"k": 1})
    with pytest.raises(confirmacoes.ConfirmacaoInvalida, match="nova mensagem"):
        confirmacoes.consome(c, "enviar", "a@x", "turno-1")
    with pytest.raises(confirmacoes.ConfirmacaoInvalida, match="outro usuario"):
        confirmacoes.consome(c, "enviar", "b@x", "turno-2")
    with pytest.raises(confirmacoes.ConfirmacaoInvalida):
        confirmacoes.consome(c, "agendar", "a@x", "turno-2")       # tipo errado
    assert confirmacoes.consome(c, "enviar", "a@x", "turno-2") == {"k": 1}
    with pytest.raises(confirmacoes.ConfirmacaoInvalida):
        confirmacoes.consome(c, "enviar", "a@x", "turno-3")       # uso unico


def test_confirmacao_expira(monkeypatch):
    c = confirmacoes.cria("agendar", "a@x", "t1", {})
    monkeypatch.setattr(confirmacoes, "VALIDADE_S", -1)
    with pytest.raises(confirmacoes.ConfirmacaoInvalida, match="expirado"):
        confirmacoes.consome(c, "agendar", "a@x", "t2")


# ─── escopo ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("usuario,escopo,esperado", [
    ("*", ["BR"], True), (["05"], ["BR"], False), (["05", "14"], ["5"], True),
    (["05"], ["05", "14"], False), (["05"], ["NENHUM"], True), ("*", ["18"], True),
])
def test_escopo_cobre(usuario, escopo, esperado):
    tipo, cods = env.normaliza_escopo(escopo)
    assert env.cobre(usuario, tipo, cods) is esperado


def test_escopo_vazio_e_recusado():
    with pytest.raises(ValueError):
        env.normaliza_escopo([])


def test_ferramentas_sem_identidade_ou_vindas_de_job_recusam():
    from app.tools import agenda_envio_tools as t
    r = asyncio.run(t.executa("enviar_mensagem", {}, {"canal": "telegram"}, "t"))
    assert "SEM_IDENTIDADE" in r
    r = asyncio.run(t.executa("agendar_tarefa", {}, {"canal": "agendador", "email": "a@x"}, "t"))
    assert "SEM_PERMISSAO" in r


def test_atribuicao_sem_parametro_de_impersonacao():
    """A ferramenta nao tem como receber o nome de quem 'assina'."""
    from app.tools.agenda_envio_tools import ENVIAR_MENSAGEM_TOOL
    props = ENVIAR_MENSAGEM_TOOL["input_schema"]["properties"]
    assert not {"atribuicao", "remetente", "assinatura", "solicitante"} & set(props)


# ─── integracao com Postgres real ────────────────────────────────────────

DSN = os.getenv("PG_TESTE_DSN")
pg = pytest.mark.skipif(not DSN, reason="sem PG_TESTE_DSN (Postgres de teste)")
BANCO = "ebdia_teste_agenda"

SUPER = "super@teste.local"
COMUM = "comum@teste.local"
ANDREA = "andrea.sbc@teste.local"
ANDREIA = "andreia.rj@teste.local"
GRUPO = "120363000000000001@g.us"


async def _prepara_banco():
    import asyncpg
    adm = await asyncpg.connect(DSN)
    await adm.execute(f"DROP DATABASE IF EXISTS {BANCO} WITH (FORCE)")
    await adm.execute(f"CREATE DATABASE {BANCO}")
    await adm.close()
    con = await asyncpg.connect(DSN.replace("/postgres?", f"/{BANCO}?"))
    from gateway.app import db
    await con.execute(db.SCHEMA_SQL)
    mig = RAIZ / "infra/postgres/migrations"
    for f in ("003_acl_users.sql", "006_acl_whatsapp.sql", "007_agendador_envio.sql",
              "007_agendador_envio.sql"):                     # 007 duas vezes: idempotente
        await con.execute(f.endswith(".sql") and (mig / f).read_text())
    await con.execute("""CREATE TABLE IF NOT EXISTS artifacts (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_oid text, conversation_id uuid,
        kind text, filename text, title text, file_path text, size_bytes int,
        metadata jsonb, created_at timestamptz DEFAULT now())""")
    await con.execute(
        """INSERT INTO acl_users (email, oid, nome, role, scope_kind, filiais, super_admin, whatsapp) VALUES
           ($1, 'oid-super', 'Super Teste', 'admin', 'brasil', '"*"', true, '+5511990000001'),
           ($2, 'oid-comum', 'Comum Teste', 'gerente', 'filiais', '["05"]', false, '+5511990000002'),
           ($3, NULL, 'Andrea SBC', 'gerente', 'filiais', '["18"]', false, '+5511990000003'),
           ($4, NULL, 'Andreia RJ', 'gerente', 'filiais', '["05"]', false, '+5521990000004')""",
        SUPER, COMUM, ANDREA, ANDREIA)
    await con.close()


@pytest.fixture(scope="module")
def banco():
    if not DSN:
        pytest.skip("sem PG_TESTE_DSN")
    asyncio.run(_prepara_banco())
    return DSN.replace("/postgres?", f"/{BANCO}?")


@pytest.fixture
def ambiente(banco, monkeypatch):
    """Roda uma corotina com o pool apontado para o banco de teste e a
    entrega pelo WhatsApp substituida por um registro."""
    from gateway.app import acl_store, db, entrega

    enviados = []
    estado = {"online": True}

    async def wa_falso(chat, texto, arquivos=None):
        if not estado["online"]:
            raise entrega.EntregaFalhou("INSTANCIA_OFFLINE", "sessao caiu")
        enviados.append((chat, texto, [a.nome for a in arquivos or []]))
        return entrega.Resultado(ok=True, message_id="MSG1",
                                 arquivos_enviados=[a.nome for a in arquivos or []])

    monkeypatch.setattr(entrega, "whatsapp", wa_falso)
    monkeypatch.setenv("WA_GRUPOS", GRUPO)
    acl_store.invalidate()

    def roda(fn):
        async def _r():
            import asyncpg
            pool = await asyncpg.create_pool(banco, min_size=1, max_size=4)
            monkeypatch.setattr(db, "_pool", pool)
            try:
                return await fn(pool)
            finally:
                await pool.close()
        return asyncio.run(_r())

    return types.SimpleNamespace(roda=roda, enviados=enviados, estado=estado)


async def _limpa(pool):
    await pool.execute("TRUNCATE ebdia_agendamento_log, ebdia_agendamento, "
                       "ebdia_envio_delegado RESTART IDENTITY CASCADE")
    await pool.execute("DELETE FROM messages; DELETE FROM conversations; DELETE FROM artifacts")


# — reivindicacao e idempotencia —

async def _job(pool, **k):
    d = dict(titulo="Teste", criado_por=SUPER, canal="whatsapp", entrega="grupo", destino=GRUPO,
             pergunta="como estamos?", cron="0 23 * * *", regra_dia="TODO_DIA",
             proxima_exec=datetime.now(SP) - timedelta(minutes=1))
    d.update(k)
    return await pool.fetchval(
        "INSERT INTO ebdia_agendamento (titulo, criado_por, canal, entrega, destino, pergunta, cron, "
        "regra_dia, proxima_exec) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id",
        d["titulo"], d["criado_por"], d["canal"], d["entrega"], d["destino"], d["pergunta"],
        d["cron"], d["regra_dia"], d["proxima_exec"])


@pg
def test_dois_workers_ao_mesmo_tempo_nao_duplicam(ambiente):
    from gateway.app import agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        await _job(pool)
        a, b = await asyncio.gather(ag.reivindicar(pool), ag.reivindicar(pool))
        assert len(a) + len(b) == 1
        assert await pool.fetchval("SELECT count(*) FROM ebdia_agendamento_log") == 1
        prox = await pool.fetchval("SELECT proxima_exec FROM ebdia_agendamento")
        assert prox > datetime.now(SP)                        # janela ja avancou
    ambiente.roda(t)


@pg
def test_janela_repetida_e_descartada_pela_unique(ambiente):
    from gateway.app import agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        janela = (datetime.now(SP) - timedelta(minutes=1)).replace(second=0, microsecond=0)
        await _job(pool, proxima_exec=janela)
        assert len(await ag.reivindicar(pool)) == 1
        await pool.execute("UPDATE ebdia_agendamento SET proxima_exec = $1", janela)   # worker reinicia
        assert await ag.reivindicar(pool) == []
        assert await pool.fetchval("SELECT count(*) FROM ebdia_agendamento_log") == 1
    ambiente.roda(t)


# — cadastro —

@pg
def test_so_super_admin_agenda(ambiente):
    from gateway.app import agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        r = await ag.preparar(pool, COMUM, "t1", {"canal": "web"}, titulo="x", pergunta="y", horario="08:00")
        assert r["erro"] == "SEM_PERMISSAO"
    ambiente.roda(t)


@pg
def test_agendar_do_grupo_com_previa_e_confirmacao(ambiente):
    from gateway.app import agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        origem = {"canal": "whatsapp", "chat": GRUPO, "privado": False}
        r = await ag.preparar(pool, SUPER, "t1", origem, titulo="Painel de fechamento",
                              pergunta="painel da diretoria parcial", horario="23:00",
                              regra_dia="ULTIMO_DIA_UTIL")
        assert r["status"] == "PREVIA" and "ULTIMO dia util" in r["previa"]
        assert await pool.fetchval("SELECT count(*) FROM ebdia_agendamento") == 0   # nada gravado
        mesmo = await ag.confirmar(pool, SUPER, "t1", r["codigo_confirmacao"])
        assert mesmo["erro"] == "CONFIRMACAO_INVALIDA"
        r = await ag.preparar(pool, SUPER, "t2", origem, titulo="Painel de fechamento",
                              pergunta="painel da diretoria parcial", horario="23:00",
                              regra_dia="ULTIMO_DIA_UTIL")
        ok = await ag.confirmar(pool, SUPER, "t3", r["codigo_confirmacao"])
        assert ok["status"] == "AGENDADO"
        row = await pool.fetchrow("SELECT * FROM ebdia_agendamento WHERE id = $1", ok["id"])
        assert (row["canal"], row["entrega"], row["destino"], row["cron"]) == \
            ("whatsapp", "grupo", GRUPO, "0 23 * * *")
    ambiente.roda(t)


@pg
def test_gerir_pausar_reativar_excluir_e_historico(ambiente):
    from gateway.app import agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        i = await _job(pool)
        assert (await ag.gerir(pool, COMUM, "listar"))["erro"] == "SEM_PERMISSAO"
        assert len((await ag.gerir(pool, SUPER, "listar"))["agendamentos"]) == 1
        assert (await ag.gerir(pool, SUPER, "pausar", i))["ativo"] is False
        assert await ag.reivindicar(pool) == []                       # pausado nao roda
        r = await ag.gerir(pool, SUPER, "reativar", i)
        assert r["ativo"] is True
        prox = await pool.fetchval("SELECT proxima_exec FROM ebdia_agendamento WHERE id=$1", i)
        assert prox > datetime.now(SP)                                 # nao dispara atrasado
        assert (await ag.gerir(pool, SUPER, "excluir", i))["excluido"] is True
        assert (await ag.gerir(pool, SUPER, "listar"))["agendamentos"] == []
        assert (await ag.gerir(pool, SUPER, "historico", i))["status"] == "OK"
    ambiente.roda(t)


# — execucao —

async def _reivindica_um(pool, **k):
    from gateway.app import agendamentos as ag
    await _job(pool, **k)
    jobs = await ag.reivindicar(pool)
    assert len(jobs) == 1
    return jobs[0]


async def _agente_ok(job, usuario):
    return "**R$ 293,6M** no mês", []


@pg
def test_execucao_ok_entrega_no_grupo(ambiente):
    from gateway.app import agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        job = await _reivindica_um(pool)
        st = await ag.executar(pool, job, roda_agente=_agente_ok, consulta_cal=_setembro())
        assert st == "OK"
        chat, texto, _ = ambiente.enviados[-1]
        assert chat == GRUPO and texto.startswith("📅 *Teste*") and "R$ 293,6M" in texto
        assert await pool.fetchval("SELECT status FROM ebdia_agendamento_log") == "OK"
    ambiente.roda(t)


@pg
def test_fora_do_dia_util_pula_em_silencio_mas_registra(ambiente):
    from gateway.app import agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        ambiente.enviados.clear()
        job = await _reivindica_um(pool, regra_dia="DIA_UTIL")
        job["janela"] = sp(2026, 9, 5, 23, 0)                       # sabado
        st = await ag.executar(pool, job, roda_agente=_agente_ok, consulta_cal=_setembro(),
                               agora=sp(2026, 9, 5, 23, 1))
        assert st == "PULADO_NAO_DIA_UTIL" and ambiente.enviados == []
    ambiente.roda(t)


@pg
def test_janela_atrasada_nao_roda_fora_de_hora_e_avisa(ambiente):
    from gateway.app import agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        ambiente.enviados.clear()
        job = await _reivindica_um(pool)
        job["janela"] = sp(2026, 9, 30, 23, 0)
        chamou = []

        async def agente(j, u):
            chamou.append(1)
            return "x", []
        st = await ag.executar(pool, job, roda_agente=agente, consulta_cal=_setembro(),
                               agora=sp(2026, 10, 1, 8, 0))
        assert st == "PULADO_ATRASADO" and chamou == []
        assert "não rodou" in ambiente.enviados[-1][1]
    ambiente.roda(t)


@pg
def test_timeout_avisa_no_destino(ambiente, monkeypatch):
    from gateway.app import agendamentos as ag
    monkeypatch.setenv("AGENDA_TIMEOUT_S", "1")

    async def lento(job, u):
        await asyncio.sleep(3)
        return "tarde", []

    async def t(pool):
        await _limpa(pool)
        job = await _reivindica_um(pool)
        st = await ag.executar(pool, job, roda_agente=lento, consulta_cal=_setembro())
        assert st == "TIMEOUT" and "tempo limite" in ambiente.enviados[-1][1]
    ambiente.roda(t)


@pg
def test_instancia_caida_cai_na_conversa_web_do_dono(ambiente):
    from gateway.app import agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        ambiente.estado["online"] = False
        try:
            job = await _reivindica_um(pool)
            st = await ag.executar(pool, job, roda_agente=_agente_ok, consulta_cal=_setembro())
        finally:
            ambiente.estado["online"] = True
        assert st == "FALHA_ENTREGA"
        conv = await pool.fetchrow("SELECT id, pinned FROM conversations WHERE user_oid = 'oid-super'")
        assert conv and conv["pinned"]
        msg = await pool.fetchval("SELECT content->>'text' FROM messages WHERE conversation_id = $1", conv["id"])
        assert "INSTANCIA_OFFLINE" in msg and "R$ 293,6M" in msg
    ambiente.roda(t)


@pg
def test_dono_revogado_pausa_o_job(ambiente):
    from gateway.app import acl_store, agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        job = await _reivindica_um(pool, criado_por=COMUM, canal="web", entrega="conversa", destino=None)
        await pool.execute("UPDATE acl_users SET active = false WHERE email = $1", COMUM)
        acl_store.invalidate()
        try:
            st = await ag.executar(pool, job, roda_agente=_agente_ok, consulta_cal=_setembro())
        finally:
            await pool.execute("UPDATE acl_users SET active = true WHERE email = $1", COMUM)
            acl_store.invalidate()
        assert st == "ERRO"
        assert await pool.fetchval("SELECT ativo FROM ebdia_agendamento WHERE id = $1", job["id"]) is False
    ambiente.roda(t)


# — envio delegado —

async def _solic(email):
    from gateway.app import acl_store
    return await acl_store.get_user(email)


@pg
def test_envio_fora_da_whitelist_e_auditado(ambiente):
    async def t(pool):
        await _limpa(pool)
        r = await env.preparar(pool, await _solic(COMUM), "t1", "fulano inexistente", "oi", [], ["NENHUM"])
        assert r["erro"] == "FORA_DA_WHITELIST"
        assert await pool.fetchval("SELECT status FROM ebdia_envio_delegado") == "RECUSADO"
    ambiente.roda(t)


@pg
def test_envio_nome_ambiguo_pergunta(ambiente):
    async def t(pool):
        await _limpa(pool)
        r = await env.preparar(pool, await _solic(SUPER), "t1", "andr", "oi", [], ["NENHUM"])
        assert r["erro"] == "DESTINATARIO_AMBIGUO" and len(r["candidatos"]) == 2
    ambiente.roda(t)


@pg
def test_envio_escopo_do_destinatario_bloqueia(ambiente):
    async def t(pool):
        await _limpa(pool)
        r = await env.preparar(pool, await _solic(SUPER), "t1", ANDREA, "vendas RJ", [], ["05"])
        assert r["erro"] == "ESCOPO_NEGADO"
        r = await env.preparar(pool, await _solic(SUPER), "t1", ANDREA, "Brasil", [], ["BR"])
        assert r["erro"] == "ESCOPO_NEGADO"
        assert await pool.fetchval(
            "SELECT count(*) FROM ebdia_envio_delegado WHERE status = 'BLOQUEADO_ESCOPO'") == 2
    ambiente.roda(t)


@pg
def test_envio_fora_do_escopo_de_quem_pede(ambiente):
    async def t(pool):
        await _limpa(pool)
        r = await env.preparar(pool, await _solic(COMUM), "t1", ANDREA, "SBC", [], ["18"])
        assert r["erro"] == "ESCOPO_NEGADO" and "SEU escopo" in r["mensagem"]
    ambiente.roda(t)


@pg
def test_envio_completo_previa_confirmacao_atribuicao_idempotencia(ambiente):
    async def t(pool):
        await _limpa(pool)
        ambiente.enviados.clear()
        s = await _solic(SUPER)
        r = await env.preparar(pool, s, "t1", ANDREA, "Red Bull SBC: R$ 1,2M", [], ["18"], "REDBULL_FILIAL")
        assert r["status"] == "PREVIA" and "Conforme solicitado por Super Teste" in r["previa"]
        assert "•••••-0003" in r["previa"] and ambiente.enviados == []      # nada saiu
        assert (await env.confirmar(pool, s, "t1", r["codigo_confirmacao"]))["erro"] == "CONFIRMACAO_INVALIDA"
        r = await env.preparar(pool, s, "t2", ANDREA, "Red Bull SBC: R$ 1,2M", [], ["18"], "REDBULL_FILIAL")
        ok = await env.confirmar(pool, s, "t3", r["codigo_confirmacao"])
        assert ok["status"] == "ENVIADO"
        chat, texto, _ = ambiente.enviados[-1]
        assert chat == "5511990000003@s.whatsapp.net"
        assert texto.startswith("📨 _Conforme solicitado por Super Teste:_")
        assert await pool.fetchval("SELECT status FROM ebdia_envio_delegado WHERE status='ENVIADO'") == "ENVIADO"
        r = await env.preparar(pool, s, "t4", ANDREA, "Red Bull SBC: R$ 1,2M", [], ["18"], "REDBULL_FILIAL")
        de_novo = await env.confirmar(pool, s, "t5", r["codigo_confirmacao"])
        assert de_novo["status"] == "JA_ENVIADO" and len(ambiente.enviados) == 1
    ambiente.roda(t)


@pg
def test_envio_rate_limit(ambiente, monkeypatch):
    monkeypatch.setenv("ENVIO_MAX_HORA", "1")

    async def t(pool):
        await _limpa(pool)
        s = await _solic(SUPER)
        r = await env.preparar(pool, s, "t1", ANDREA, "primeira", [], ["NENHUM"])
        assert (await env.confirmar(pool, s, "t2", r["codigo_confirmacao"]))["status"] == "ENVIADO"
        r = await env.preparar(pool, s, "t3", ANDREA, "segunda", [], ["NENHUM"])
        assert r["erro"] == "RATE_LIMIT"
    ambiente.roda(t)


@pg
def test_envio_artefato_de_outro_usuario_nao_sai(ambiente, tmp_path):
    async def t(pool):
        await _limpa(pool)
        f = tmp_path / "a.xlsx"
        f.write_bytes(b"PK")
        alheio = await pool.fetchval("INSERT INTO artifacts (user_oid, filename, file_path) "
                                     "VALUES ('oid-comum', 'a.xlsx', $1) RETURNING id::text", str(f))
        meu = await pool.fetchval("INSERT INTO artifacts (user_oid, filename, file_path) "
                                  "VALUES ($1, 'meu.xlsx', $2) RETURNING id::text", SUPER, str(f))
        s = await _solic(SUPER)
        r = await env.preparar(pool, s, "t1", ANDREA, "segue", [alheio], ["18"])
        assert r["erro"] == "ARTEFATO_NAO_ENCONTRADO"
        r = await env.preparar(pool, s, "t1", ANDREA, "segue", [meu], ["NENHUM"])
        assert r["erro"] == "ESCOPO_INVALIDO"                   # arquivo tem dado
        r = await env.preparar(pool, s, "t1", ANDREA, "segue", [meu], ["18"])
        assert r["status"] == "PREVIA" and "meu.xlsx" in r["previa"]
    ambiente.roda(t)


@pg
def test_envio_com_instancia_caida_registra_falha(ambiente):
    async def t(pool):
        await _limpa(pool)
        s = await _solic(SUPER)
        r = await env.preparar(pool, s, "t1", ANDREA, "oi", [], ["NENHUM"])
        ambiente.estado["online"] = False
        try:
            f = await env.confirmar(pool, s, "t2", r["codigo_confirmacao"])
        finally:
            ambiente.estado["online"] = True
        assert f["erro"] == "INSTANCIA_OFFLINE"
        assert await pool.fetchval("SELECT status FROM ebdia_envio_delegado") == "FALHA_CANAL"
    ambiente.roda(t)


# ─── a mensagem do usuario precisa concordar ─────────────────────────────

@pytest.mark.parametrize("msg,esperado", [
    ("sim", True), ("confirmo", True), ("pode mandar", True), ("ok, manda pro André", True),
    ("pode mandar para o André", True),                       # "para" e preposicao
    ("👍", True), ("4F9A2C", True),                            # o proprio codigo
    ("[GRUPO de WhatsApp — todos leem]\nsim, pode", True),      # marca do sistema ignorada
    ("[RESPONDA TAMBEM EM AUDIO: frases curtas para ser OUVIDO]\nconfirmo", True),
    ("não confirmo", False), ("nao, espera", False), ("cancela", False),
    ("muda o horário para 22h", False), ("qual o faturamento de hoje?", False), ("", False),
])
def test_parece_confirmacao(msg, esperado):
    assert confirmacoes.parece_confirmacao(msg, "4F9A2C") is esperado


def test_confirmacao_recusa_mensagem_que_nao_concorda():
    c = confirmacoes.cria("enviar", "a@x", "t1", {"k": 1})
    with pytest.raises(confirmacoes.ConfirmacaoInvalida, match="nao confirma"):
        confirmacoes.consome(c, "enviar", "a@x", "t2", "não, muda o texto")
    assert confirmacoes.consome(c, "enviar", "a@x", "t2", "pode enviar") == {"k": 1}


@pg
def test_previa_mostra_o_codigo_para_a_web_conseguir_confirmar(ambiente):
    """No web o historico volta so com o TEXTO: o codigo tem que estar na previa."""
    from gateway.app import agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        r = await ag.preparar(pool, SUPER, "t1", {"canal": "web"}, titulo="x", pergunta="y", horario="08:00")
        assert r["codigo_confirmacao"] in r["previa"]
        e = await env.preparar(pool, await _solic(SUPER), "t1", ANDREA, "oi", [], ["NENHUM"])
        assert e["codigo_confirmacao"] in e["previa"]
    ambiente.roda(t)


@pg
def test_entrega_na_web_exige_ter_entrado_no_chat_web(ambiente):
    from gateway.app import agendamentos as ag

    async def t(pool):
        await _limpa(pool)
        await pool.execute("UPDATE acl_users SET super_admin = true WHERE email = $1", ANDREA)
        from gateway.app import acl_store
        acl_store.invalidate()
        try:
            r = await ag.preparar(pool, ANDREA, "t1", {"canal": "whatsapp", "privado": True, "chat": "x"},
                                  titulo="x", pergunta="y", horario="08:00", entrega_pedida="web")
        finally:
            await pool.execute("UPDATE acl_users SET super_admin = false WHERE email = $1", ANDREA)
            acl_store.invalidate()
        assert r["erro"] == "DADOS_INVALIDOS" and "chat web" in r["mensagem"]
    ambiente.roda(t)


@pg
def test_caminho_do_agente_pela_ferramenta_ponta_a_ponta(ambiente):
    """O mesmo caminho do agente: executa() com origem, turno e a mensagem do usuario."""
    import json
    from app.tools import agenda_envio_tools as t

    async def r(pool):
        await _limpa(pool)
        ambiente.enviados.clear()
        grupo = {"canal": "whatsapp", "chat": GRUPO, "privado": False, "email": SUPER}
        p = json.loads(await t.executa("agendar_tarefa", {
            "titulo": "Fechamento", "pergunta": "painel da diretoria parcial",
            "horario": "23:00", "regra_dia": "ULTIMO_DIA_UTIL"},
            {**grupo, "mensagem": "[GRUPO de WhatsApp]\nme manda todo ultimo dia util as 23h o painel"}, "t1"))
        assert p["status"] == "PREVIA"
        recusa = json.loads(await t.executa("agendar_tarefa", {
            "titulo": "Fechamento", "pergunta": "x", "codigo_confirmacao": p["codigo_confirmacao"]},
            {**grupo, "mensagem": "[GRUPO de WhatsApp]\nnão, muda para 22h"}, "t2"))
        assert recusa["erro"] == "CONFIRMACAO_INVALIDA"
        p = json.loads(await t.executa("agendar_tarefa", {
            "titulo": "Fechamento", "pergunta": "painel da diretoria parcial",
            "horario": "23:00", "regra_dia": "ULTIMO_DIA_UTIL"}, {**grupo, "mensagem": "de novo"}, "t3"))
        ok = json.loads(await t.executa("agendar_tarefa", {
            "titulo": "Fechamento", "pergunta": "x", "codigo_confirmacao": p["codigo_confirmacao"]},
            {**grupo, "mensagem": "[GRUPO de WhatsApp]\nsim, pode agendar"}, "t4"))
        assert ok["status"] == "AGENDADO"

        priv = {"canal": "whatsapp", "chat": "5511990000002@s.whatsapp.net", "privado": True, "email": COMUM}
        e = json.loads(await t.executa("enviar_mensagem", {
            "destinatario": "Andreia", "texto": "Duque fechou bem", "escopo_filiais": ["05"]},
            {**priv, "mensagem": "manda pra Andreia que a Duque fechou bem"}, "t5"))
        assert e["status"] == "PREVIA"
        f = json.loads(await t.executa("enviar_mensagem", {
            "destinatario": "Andreia", "texto": "x", "escopo_filiais": ["05"],
            "codigo_confirmacao": e["codigo_confirmacao"]}, {**priv, "mensagem": "confirmo"}, "t6"))
        assert f["status"] == "ENVIADO" and ambiente.enviados[-1][0] == "5521990000004@s.whatsapp.net"
        assert ambiente.enviados[-1][1].startswith("📨 _Conforme solicitado por Comum Teste:_")
    ambiente.roda(r)

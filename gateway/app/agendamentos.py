"""Agendador de tarefas — cadastro, gestao e execucao dos jobs.

Spec "Agendador de Tarefas EBD.ia" (set/2026), com as decisoes:
  - so SUPER ADMIN cadastra e gere (decisao do Thiago, 01/10/2026)
  - o job e uma PERGUNTA respondida pelo MESMO agente do chat, como quem
    cadastrou — a "regra de ouro" da spec: sem reimplementar analise nem
    formato, e o escopo do dono e aplicado pelo MCP (sem porta lateral)
  - regra do dia pelo calendario do Winthor (calendario_winthor.py)
  - entrega pela camada unica (entrega.py)
  - idempotencia pela unique (id_agend, janela_agendada)
  - janela atrasada demais (worker parado) NAO roda fora de hora: o painel
    das 23h nao sai as 8h com dado de outro dia — registra e avisa
  - nenhuma falha em silencio: erro, timeout e atraso avisam o destino
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from gateway.app import calendario_winthor, confirmacoes, cron_simples, entrega

log = logging.getLogger("uvicorn.error")
TZ = "America/Sao_Paulo"
REGRAS = ("TODO_DIA", "DIA_UTIL", "ULTIMO_DIA_UTIL", "DIA_FIXO")
FORMATOS = ("TEXTO", "EXCEL", "PDF", "PPTX")
_INSTRUCAO_FORMATO = {
    "EXCEL": "Entregue o resultado em Excel (create_excel), alem de um resumo curto em texto.",
    "PDF": "Entregue o resultado em PDF (create_pdf), alem de um resumo curto em texto.",
    "PPTX": "Entregue o resultado em PowerPoint (create_pptx), alem de um resumo curto em texto.",
}


def _int_env(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except ValueError:
        return padrao


def tolerancia_atraso() -> timedelta:
    return timedelta(minutes=_int_env("AGENDA_TOLERANCIA_MIN", 20))


def cron_de(cron: str | None, horario: str | None, dias: str | None) -> str:
    """Aceita cron pronto, ou horario HH:MM + dias (todos | seg-sex | seg-sab)."""
    if cron:
        cron_simples.parse(cron)
        return cron.strip()
    if not horario or ":" not in horario:
        raise cron_simples.CronInvalido("informe o horario (HH:MM) ou um cron")
    h, m = horario.strip().split(":", 1)
    if not (h.isdigit() and m.isdigit() and 0 <= int(h) <= 23 and 0 <= int(m) <= 59):
        raise cron_simples.CronInvalido(f"horario invalido: {horario!r}")
    sem = {"todos": "*", "seg-sex": "1-5", "seg-sab": "1-6"}.get((dias or "todos").lower())
    if sem is None:
        raise cron_simples.CronInvalido("dias: use todos, seg-sex ou seg-sab")
    expr = f"{int(m)} {int(h)} * * {sem}"
    cron_simples.parse(expr)
    return expr


def _descreve_regra(regra: str, filial: str) -> str:
    cal = "Brasil" if filial == "BR" else f"filial {filial}"
    return {"TODO_DIA": "todo dia do cron, sem olhar calendario",
            "DIA_UTIL": f"so em dia util ({cal}, calendario do Winthor)",
            "ULTIMO_DIA_UTIL": f"so no ULTIMO dia util do mes ({cal}, calendario do Winthor)",
            "DIA_FIXO": "no dia fixado no cron"}[regra]


# ─── Destino ─────────────────────────────────────────────────────────────

async def _destino(origem: dict, entrega_pedida: str, usuario: dict) -> tuple[str, str, str | None, str]:
    """-> (canal, entrega, destino, descricao). `aqui` = onde o pedido foi feito."""
    canal_origem = (origem or {}).get("canal")
    if entrega_pedida == "aqui":
        if canal_origem == "whatsapp":
            if origem.get("privado"):
                entrega_pedida = "whatsapp_privado"
            else:
                return ("whatsapp", "grupo", origem["chat"],
                        f"neste grupo do WhatsApp ({origem.get('nome_grupo') or origem['chat']})")
        elif canal_origem == "web":
            entrega_pedida = "web"
        else:
            raise ValueError("este canal ainda nao recebe agendamentos — use WhatsApp ou o chat web")
    if entrega_pedida == "whatsapp_privado":
        if not usuario.get("whatsapp"):
            raise ValueError("seu usuario nao tem WhatsApp cadastrado na tela de Acessos")
        return ("whatsapp", "privado", None, "no seu privado do WhatsApp")
    if entrega_pedida == "web":
        if not usuario.get("oid"):
            raise ValueError("voce ainda nao entrou no chat web — entre uma vez ou escolha o WhatsApp")
        return ("web", "conversa", None, "na conversa '📅 Agendamentos' do chat web")
    raise ValueError(f"entrega invalida: {entrega_pedida}")


# ─── Cadastro (super admin, com previa e confirmacao) ────────────────────

async def preparar(pool, email: str, turno: str, origem: dict, *, titulo: str, pergunta: str,
                   cron: str | None = None, horario: str | None = None, dias: str | None = None,
                   regra_dia: str = "DIA_UTIL", formato: str = "TEXTO", entrega_pedida: str = "aqui",
                   filial_calendario: str = "BR") -> dict:
    from gateway.app import acl_store
    if not await acl_store.is_super_admin(email):
        return {"status": "FALHA", "erro": "SEM_PERMISSAO",
                "mensagem": "agendar tarefas esta liberado, por enquanto, so para super admin"}
    if (origem or {}).get("canal") == "agendador":
        return {"status": "FALHA", "erro": "SEM_PERMISSAO",
                "mensagem": "um job agendado nao pode criar outro agendamento"}
    regra_dia, formato = (regra_dia or "DIA_UTIL").upper(), (formato or "TEXTO").upper()
    if regra_dia not in REGRAS:
        return {"status": "FALHA", "erro": "REGRA_INVALIDA", "mensagem": f"regra_dia: {', '.join(REGRAS)}"}
    if formato not in FORMATOS:
        return {"status": "FALHA", "erro": "FORMATO_INVALIDO", "mensagem": f"formato: {', '.join(FORMATOS)}"}
    if not (pergunta or "").strip() or not (titulo or "").strip():
        return {"status": "FALHA", "erro": "DADOS_INCOMPLETOS", "mensagem": "informe titulo e pergunta"}
    filial_calendario = (filial_calendario or "BR").upper()
    if filial_calendario != "BR":
        filial_calendario = filial_calendario.zfill(2)
    try:
        expr = cron_de(cron, horario, dias)
        usuario = await pool.fetchrow("SELECT email, nome, whatsapp, oid FROM acl_users "
                                      "WHERE lower(email) = lower($1)", email) or {"email": email}
        canal, ent, destino, onde = await _destino(origem, entrega_pedida, dict(usuario))
    except (cron_simples.CronInvalido, ValueError) as e:
        return {"status": "FALHA", "erro": "DADOS_INVALIDOS", "mensagem": str(e)}
    proxima = cron_simples.proxima(expr, datetime.now(ZoneInfo(TZ)), TZ)
    dados = {"titulo": titulo.strip()[:80], "pergunta": pergunta.strip(), "cron": expr,
             "regra_dia": regra_dia, "formato": formato, "canal": canal, "entrega": ent,
             "destino": destino, "filial_calendario": filial_calendario}
    codigo = confirmacoes.cria("agendar", email, turno, dados)
    previa = (f"📅 PRÉVIA DO AGENDAMENTO — nada foi gravado ainda\n"
              f"Título: {dados['titulo']}\n"
              f"Pergunta que vou responder: {dados['pergunta']}\n"
              f"Quando: {cron_simples.descreve(expr)} — {_descreve_regra(regra_dia, filial_calendario)}\n"
              f"Próxima janela do relógio: {proxima:%d/%m/%Y %H:%M}"
              f"{' (roda se a regra do dia permitir)' if regra_dia in ('DIA_UTIL', 'ULTIMO_DIA_UTIL') else ''}\n"
              f"Entrega: {onde} · formato {formato}\n"
              f"Roda com o SEU acesso (o seu escopo de filiais).\n"
              f"Para gravar, o usuário responde confirmando.\n"
              f"Código de confirmação: {codigo}")
    return {"status": "PREVIA", "previa": previa, "codigo_confirmacao": codigo}


async def confirmar(pool, email: str, turno: str, codigo: str, mensagem: str | None = None) -> dict:
    try:
        d = confirmacoes.consome(codigo, "agendar", email, turno, mensagem)
    except confirmacoes.ConfirmacaoInvalida as e:
        return {"status": "FALHA", "erro": "CONFIRMACAO_INVALIDA", "mensagem": str(e)}
    proxima = cron_simples.proxima(d["cron"], datetime.now(ZoneInfo(TZ)), TZ)
    novo = await pool.fetchval(
        """INSERT INTO ebdia_agendamento
           (titulo, criado_por, canal, entrega, destino, pergunta, cron, regra_dia,
            filial_calendario, formato_saida, proxima_exec)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id""",
        d["titulo"], email.lower(), d["canal"], d["entrega"], d["destino"], d["pergunta"],
        d["cron"], d["regra_dia"], d["filial_calendario"], d["formato"], proxima)
    return {"status": "AGENDADO", "id": novo, "titulo": d["titulo"],
            "proxima_janela": f"{proxima:%d/%m/%Y %H:%M}"}


async def gerir(pool, email: str, acao: str, id_agend: int | None = None) -> dict:
    from gateway.app import acl_store
    if not await acl_store.is_super_admin(email):
        return {"status": "FALHA", "erro": "SEM_PERMISSAO", "mensagem": "so super admin gere agendamentos"}
    acao = (acao or "listar").lower()
    if acao == "listar":
        rows = await pool.fetch(
            """SELECT a.id, a.titulo, a.criado_por, a.cron, a.regra_dia, a.canal, a.entrega,
                      a.destino, a.pergunta, a.filial_calendario, a.formato_saida, a.ativo,
                      a.proxima_exec, a.ultima_exec, u.nome AS dono_nome,
                      l.status AS ultimo_status, l.msg_erro AS ultimo_erro
               FROM ebdia_agendamento a
               LEFT JOIN acl_users u ON lower(u.email) = lower(a.criado_por)
               LEFT JOIN LATERAL (SELECT status, msg_erro FROM ebdia_agendamento_log l
                                  WHERE l.id_agend = a.id ORDER BY l.dt_inicio DESC LIMIT 1) l ON true
               WHERE a.excluido_em IS NULL ORDER BY a.ativo DESC, a.proxima_exec NULLS LAST, a.id""")
        return {"status": "OK", "agendamentos": [
            {**{k: r[k] for k in ("id", "titulo", "criado_por", "dono_nome", "cron", "regra_dia",
                                  "canal", "entrega", "pergunta", "filial_calendario",
                                  "formato_saida", "ativo", "ultimo_status", "ultimo_erro")},
             "entrega_desc": {"grupo": f"grupo {r['destino'] or ''}".strip(),
                              "privado": "privado do WhatsApp",
                              "conversa": "chat web (📅 Agendamentos)"}.get(r["entrega"], r["entrega"]),
             "regra_desc": _descreve_regra(r["regra_dia"], r["filial_calendario"]),
             "quando": cron_simples.descreve(r["cron"]),
             "proxima": f"{r['proxima_exec'].astimezone(ZoneInfo(TZ)):%d/%m %H:%M}" if r["proxima_exec"] else None,
             "ultima": f"{r['ultima_exec'].astimezone(ZoneInfo(TZ)):%d/%m %H:%M}" if r["ultima_exec"] else None}
            for r in rows]}
    if not id_agend:
        return {"status": "FALHA", "erro": "ID_OBRIGATORIO", "mensagem": "informe o id do agendamento"}
    if acao == "historico":
        rows = await pool.fetch(
            "SELECT janela_agendada, status, duracao_seg, msg_erro FROM ebdia_agendamento_log "
            "WHERE id_agend = $1 ORDER BY janela_agendada DESC LIMIT 10", id_agend)
        return {"status": "OK", "historico": [
            {"janela": f"{r['janela_agendada'].astimezone(ZoneInfo(TZ)):%d/%m %H:%M}",
             "status": r["status"], "duracao_seg": float(r["duracao_seg"]) if r["duracao_seg"] else None,
             "erro": r["msg_erro"]} for r in rows]}
    if acao in ("pausar", "reativar"):
        ativo = acao == "reativar"
        cron = await pool.fetchval("SELECT cron FROM ebdia_agendamento WHERE id = $1 "
                                   "AND excluido_em IS NULL", id_agend)
        if cron is None:
            return {"status": "FALHA", "erro": "NAO_ENCONTRADO", "mensagem": f"agendamento {id_agend} nao existe"}
        # reativar recalcula a proxima janela a partir de agora — nao dispara atrasado
        proxima = cron_simples.proxima(cron, datetime.now(ZoneInfo(TZ)), TZ) if ativo else None
        await pool.execute("UPDATE ebdia_agendamento SET ativo = $2, "
                           "proxima_exec = COALESCE($3, proxima_exec) WHERE id = $1",
                           id_agend, ativo, proxima)
        return {"status": "OK", "id": id_agend, "ativo": ativo}
    if acao == "rodar_agora":
        # so antecipa a janela: o worker pega no proximo ciclo, com todas as travas
        n = await pool.execute(
            "UPDATE ebdia_agendamento SET proxima_exec = date_trunc('minute', now()) "
            "WHERE id = $1 AND ativo AND excluido_em IS NULL", id_agend)
        if n.endswith(" 0"):
            return {"status": "FALHA", "erro": "NAO_ENCONTRADO",
                    "mensagem": f"agendamento {id_agend} nao existe ou esta pausado"}
        return {"status": "OK", "id": id_agend, "nota": "roda em ate 30 segundos"}
    if acao == "excluir":
        n = await pool.execute("UPDATE ebdia_agendamento SET ativo = false, excluido_em = now() "
                               "WHERE id = $1 AND excluido_em IS NULL", id_agend)
        if n.endswith(" 0"):
            return {"status": "FALHA", "erro": "NAO_ENCONTRADO", "mensagem": f"agendamento {id_agend} nao existe"}
        return {"status": "OK", "id": id_agend, "excluido": True, "nota": "o historico de execucao fica guardado"}
    return {"status": "FALHA", "erro": "ACAO_INVALIDA",
            "mensagem": "acao: listar, historico, pausar, reativar, rodar_agora, excluir"}


# ─── Worker: reivindicar e executar ──────────────────────────────────────

async def reivindicar(pool, limite: int = 5) -> list[dict]:
    """Pega os jobs vencidos com FOR UPDATE SKIP LOCKED, grava a janela no log
    (a unique descarta janela repetida) e ja avanca a proxima_exec — tudo numa
    transacao curta. A execucao (minutos) acontece FORA dela."""
    agora = datetime.now(ZoneInfo(TZ))
    jobs = []
    async with pool.acquire() as con:
        async with con.transaction():
            rows = await con.fetch(
                """SELECT * FROM ebdia_agendamento
                   WHERE ativo AND excluido_em IS NULL AND proxima_exec <= now()
                   ORDER BY proxima_exec LIMIT $1 FOR UPDATE SKIP LOCKED""", limite)
            for r in rows:
                janela = r["proxima_exec"].replace(second=0, microsecond=0)
                log_id = await con.fetchval(
                    """INSERT INTO ebdia_agendamento_log (id_agend, janela_agendada)
                       VALUES ($1, $2) ON CONFLICT (id_agend, janela_agendada) DO NOTHING
                       RETURNING id""", r["id"], janela)
                prox = cron_simples.proxima(r["cron"], agora, r["tz"] or TZ)
                await con.execute("UPDATE ebdia_agendamento SET ultima_exec = now(), "
                                  "proxima_exec = $2 WHERE id = $1", r["id"], prox)
                if log_id is not None:            # janela nova: e nossa
                    jobs.append({**dict(r), "log_id": log_id, "janela": janela})
    return jobs


async def _fecha_log(pool, log_id: int, status: str, t0: float, erro: str | None = None,
                     artefatos: list[str] | None = None) -> None:
    await pool.execute(
        "UPDATE ebdia_agendamento_log SET status = $2, dt_fim = now(), duracao_seg = $3, "
        "msg_erro = $4, artefatos = $5 WHERE id = $1",
        log_id, status, round(time.time() - t0, 1), (erro or None) and erro[:2000], artefatos or [])


async def _entrega_job(job: dict, usuario: dict, texto: str, artefato_ids: list[str]) -> None:
    """Entrega no destino do job. Grupo: confere se continua autorizado."""
    arquivos = await entrega.arquivos_dos_artefatos(
        artefato_ids, [job["criado_por"], usuario.get("oid")])
    if job["canal"] == "web":
        await entrega.web(job["criado_por"], texto, artefato_ids)
        return
    if job["entrega"] == "grupo":
        from app.adapters.whatsapp import grupos_autorizados
        if job["destino"] not in grupos_autorizados():
            raise entrega.EntregaFalhou("FORA_DA_WHITELIST", "o grupo saiu do WA_GRUPOS")
        chat = job["destino"]
    else:
        if not usuario.get("whatsapp"):
            raise entrega.EntregaFalhou("CHAT_ID_INVALIDO", "o dono nao tem mais WhatsApp cadastrado")
        chat = entrega.jid_privado(usuario["whatsapp"])
    await entrega.whatsapp(chat, texto, arquivos)


async def _avisa_falha(pool, job: dict, usuario: dict | None, motivo: str) -> None:
    """Falha nunca e muda: tenta o destino do job; se nem isso der, a conversa web do dono."""
    texto = f"⚠️ O agendamento *{job['titulo']}* (#{job['id']}) não rodou: {motivo}"
    try:
        await _entrega_job(job, usuario or {}, texto, [])
    except Exception as e:
        log.warning("agenda #%s: aviso no destino falhou (%s) — tentando a conversa web", job["id"], e)
        try:
            await entrega.web(job["criado_por"], texto)
        except Exception as e2:
            log.error("agenda #%s: NENHUM aviso entregue: %s", job["id"], e2)


async def executar(pool, job: dict, *, roda_agente=None, consulta_cal=None,
                   agora: datetime | None = None) -> str:
    """Roda um job ja reivindicado. Devolve o status gravado no log."""
    from gateway.app import acl_store
    t0 = time.time()
    agora = agora or datetime.now(ZoneInfo(TZ))
    janela = job["janela"]
    usuario = await acl_store.get_user(job["criado_por"])
    if not usuario:
        await pool.execute("UPDATE ebdia_agendamento SET ativo = false WHERE id = $1", job["id"])
        await _fecha_log(pool, job["log_id"], "ERRO", t0, "dono sem acesso (revogado) — agendamento pausado")
        return "ERRO"
    usuario = {**usuario, "whatsapp": await pool.fetchval(
        "SELECT whatsapp FROM acl_users WHERE lower(email) = lower($1)", job["criado_por"])}
    if agora - janela > tolerancia_atraso():
        msg = (f"a janela das {janela.astimezone(ZoneInfo(TZ)):%d/%m %H:%M} passou "
               f"(o agendador estava parado) — nao rodei fora de hora")
        await _fecha_log(pool, job["log_id"], "PULADO_ATRASADO", t0, msg)
        await _avisa_falha(pool, job, usuario, msg)
        return "PULADO_ATRASADO"
    try:
        hoje = janela.astimezone(ZoneInfo(job["tz"] or TZ)).date()
        if not await calendario_winthor.passa_regra(job["regra_dia"], hoje,
                                                    job["filial_calendario"], consulta_cal):
            await _fecha_log(pool, job["log_id"], "PULADO_NAO_DIA_UTIL", t0)
            return "PULADO_NAO_DIA_UTIL"
    except calendario_winthor.CalendarioIndisponivel as e:
        msg = f"o calendario do Winthor nao respondeu ({e})"
        await _fecha_log(pool, job["log_id"], "ERRO", t0, msg)
        await _avisa_falha(pool, job, usuario, msg)
        return "ERRO"

    try:
        texto, artefatos = await asyncio.wait_for(
            (roda_agente or _roda_agente)(job, usuario),
            timeout=_int_env("AGENDA_TIMEOUT_S", 600))
    except asyncio.TimeoutError:
        msg = "a analise passou do tempo limite"
        await _fecha_log(pool, job["log_id"], "TIMEOUT", t0, msg)
        await _avisa_falha(pool, job, usuario, msg)
        return "TIMEOUT"
    except Exception as e:
        msg = f"erro na analise ({type(e).__name__})"
        log.exception("agenda #%s: falha no agente", job["id"])
        await _fecha_log(pool, job["log_id"], "ERRO", t0, f"{msg}: {e}")
        await _avisa_falha(pool, job, usuario, msg)
        return "ERRO"
    if not (texto or "").strip():
        await _fecha_log(pool, job["log_id"], "ERRO", t0, "analise voltou vazia")
        await _avisa_falha(pool, job, usuario, "a analise voltou vazia")
        return "ERRO"

    cabecalho = f"📅 *{job['titulo']}* · agendamento #{job['id']}"
    try:
        await _entrega_job(job, usuario, f"{cabecalho}\n\n{texto}", artefatos)
    except entrega.EntregaFalhou as e:
        await _fecha_log(pool, job["log_id"], "FALHA_ENTREGA", t0, f"{e.codigo}: {e.detalhe}", artefatos)
        try:
            await entrega.web(job["criado_por"],
                              f"{cabecalho}\n\n⚠️ Não consegui entregar no destino ({e.codigo}). "
                              f"Segue aqui:\n\n{texto}", artefatos)
        except Exception as e2:
            log.error("agenda #%s: entrega e fallback falharam: %s", job["id"], e2)
        return "FALHA_ENTREGA"
    await _fecha_log(pool, job["log_id"], "OK", t0, artefatos=artefatos)
    return "OK"


async def recupera_interrompidos(pool) -> int:
    """Ao subir: execucoes que ficaram EM_EXECUCAO foram cortadas por um reinicio
    (deploy, vigia de modelo). A unique impede rodar a janela de novo — entao
    registra e AVISA, em vez de o job sumir em silencio."""
    from gateway.app import acl_store
    rows = await pool.fetch(
        """UPDATE ebdia_agendamento_log l SET status = 'ERRO', dt_fim = now(),
                  msg_erro = 'interrompido: o agendador reiniciou durante a execucao'
           FROM ebdia_agendamento a
           WHERE l.id_agend = a.id AND l.status = 'EM_EXECUCAO'
           RETURNING a.*, l.janela_agendada AS janela""")
    for r in rows:
        job = dict(r)
        usuario = await acl_store.get_user(job["criado_por"]) or {}
        usuario = {**usuario, "whatsapp": await pool.fetchval(
            "SELECT whatsapp FROM acl_users WHERE lower(email) = lower($1)", job["criado_por"])}
        await _avisa_falha(pool, job, usuario,
                           "foi interrompido por um reinicio do sistema. Use 'rodar agora' na tela Agendados")
    return len(rows)


async def _roda_agente(job: dict, usuario: dict) -> tuple[str, list[str]]:
    """A MESMA funcao do chat (run_turn_stream), como o dono do job."""
    from app.agent import run_turn_stream
    from gateway.app.models_catalog import DEFAULT_MODEL
    pergunta = job["pergunta"]
    if job["formato_saida"] in _INSTRUCAO_FORMATO:
        pergunta += "\n\n" + _INSTRUCAO_FORMATO[job["formato_saida"]]
    contexto = (f"[AGENDAMENTO #{job['id']} — {job['titulo']}. Execucao automatica: "
                "ninguem vai responder pergunta de volta. Responda direto e completo.]")
    if job["canal"] == "whatsapp" and job["entrega"] == "grupo":
        from gateway.app.routes.whatsapp import MARCA_GRUPO
        contexto = f"{MARCA_GRUPO}\n{contexto}"
    texto, artefatos = "", []
    async for ev in run_turn_stream(
            user_message=f"{contexto}\n{pergunta}", conversation_history=[],
            user_id=usuario.get("oid") if job["canal"] == "web" and usuario.get("oid") else job["criado_por"],
            user_role=usuario.get("role") or "user", user_filiais="*",
            channel="whatsapp" if job["canal"] == "whatsapp" else "web",
            model=DEFAULT_MODEL if DEFAULT_MODEL.startswith("deepseek") else "deepseek-flash",
            user_email=job["criado_por"], origem={"canal": "agendador", "job": job["id"]}):
        t = ev.get("type")
        if t == "token":
            texto += ev.get("text", "")
        elif t in ("tool", "tool_use"):
            texto = ""
        elif t == "artifact" and ev.get("id"):
            artefatos.append(str(ev["id"]))
    from app.adapters.whatsapp_voz import limpar_texto_visual
    return limpar_texto_visual(texto).strip(), artefatos

"""Webhook da Evolution API — o EBD.ia no WhatsApp, em grupo e no privado.

A Evolution chama esta rota a cada mensagem do grupo. A rota decide em
microssegundos se e com ela (grupo autorizado + chamou o @ebd.ia) e devolve
200 na hora; o atendimento roda em segundo plano, porque o agente pode levar
minutos e a Evolution reenviaria o evento se a resposta demorasse.

Mensagem que NAO chama o bot e descartada sem ser guardada nem registrada.

QUEM PODE: o numero precisa estar no campo WhatsApp de um usuario ATIVO na
tela de Acessos. A pergunta roda com o papel e as filiais dessa pessoa.

Variaveis (gateway/.env):
    WA_ENABLED=true
    WA_WEBHOOK_TOKEN=<segredo longo>          mesmo valor no webhook da Evolution
    WA_GRUPOS=1203630...@g.us                 JIDs autorizados, separados por virgula
    WA_PRIVADO=true                           atende no privado (padrao true)
    WA_ACK_APOS_S=15                          aviso "ja te retorno" so se demorar mais que isso
    WA_ACK=true                               false desliga o aviso de vez
    WA_VOZ_COM_TEXTO=true                     resposta em audio vai tambem por escrito
    WA_NUMEROS=lid:123=ciclano@...           SO para LID sem telefone (excecao)
    WA_BOT_IDS=5511888887777                  numero (e LID, se houver) do bot
    EVO_URL=http://127.0.0.1:8081
    EVO_APIKEY=<AUTHENTICATION_API_KEY da Evolution>
    EVO_INSTANCE=ebdia
    WA_DEBUG_MENCAO=false                     true loga mencoes nao reconhecidas
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time

from fastapi import APIRouter, HTTPException, Request

from app.adapters import whatsapp_voz as voz
from app.adapters.whatsapp_ack import aviso_ligado, espera_antes_do_aviso, frase_de_aviso, primeiro_nome

from app.adapters.whatsapp import (
    Mensagem, baixa_midia, envia_arquivo, envia_audio, envia_texto, foi_chamado,
    grupos_autorizados,
    limpa_pergunta, mapa_numeros, md_para_whatsapp, normaliza_whatsapp, parse_evento,
    privado_ligado,
)

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

HIST_TTL_S = 2 * 3600          # conversa no grupo "esfria" em 2 h
TIMEOUT_TURNO_S = 600          # teto de um atendimento
ROLE_GRUPO = "grupo_whatsapp"  # nao-admin: nunca propoe auto-append da KB
AVISO_SEM_PERMISSAO_S = 24 * 3600   # "sem permissao" no maximo 1x/dia por pessoa
# o numero pode ter sido de alguem (ex-colaborador): os contatos antigos
# continuam escrevendo, e sem limite cada "oi" viraria resposta automatica
MARCA_GRUPO = "[GRUPO de WhatsApp — todos os participantes leem a resposta]"

_locks: dict[str, asyncio.Lock] = {}
_hist: dict[tuple[str, str], tuple[float, list]] = {}
_tarefas: set[asyncio.Task] = set()
_ids_cache: tuple[float, set[str]] = (0.0, set())
_avisados: dict[str, float] = {}
_vistos: dict[str, float] = {}     # msg_id -> quando: a Evolution as vezes entrega 2x
VISTO_TTL_S = 600


def _ligado() -> bool:
    return os.getenv("WA_ENABLED", "false").strip().lower() == "true"


def _token_ok(request: Request) -> bool:
    esperado = os.getenv("WA_WEBHOOK_TOKEN", "")
    if len(esperado) < 16:          # sem segredo decente, nada passa
        return False
    recebido = (request.headers.get("x-ebdia-token")
                or request.query_params.get("token") or "")
    return hmac.compare_digest(recebido.encode(), esperado.encode())


def _veio_de_fora(request: Request) -> bool:
    """A Evolution chama direto (host-gateway). Passou pelo nginx = de fora."""
    return bool(request.headers.get("x-forwarded-for")
                or request.headers.get("x-real-ip"))


async def _ids_do_bot() -> set[str]:
    """WA_BOT_IDS + o ownerJid da instancia, consultado a cada 10 min."""
    global _ids_cache
    fixos = {x.strip() for x in os.getenv("WA_BOT_IDS", "").split(",") if x.strip()}
    ts, cache = _ids_cache
    if time.time() - ts < 600:
        return fixos | cache
    descobertos: set[str] = set()
    try:
        import httpx
        url = os.getenv("EVO_URL", "http://127.0.0.1:8081").rstrip("/")
        inst = os.getenv("EVO_INSTANCE", "ebdia")
        async with httpx.AsyncClient(timeout=5) as cli:
            r = await cli.get(f"{url}/instance/fetchInstances",
                              params={"instanceName": inst},
                              headers={"apikey": os.getenv("EVO_APIKEY", "")})
        dados = r.json() if r.status_code == 200 else []
        for it in dados if isinstance(dados, list) else [dados]:
            it = it.get("instance", it) if isinstance(it, dict) else {}
            for k in ("ownerJid", "owner"):
                if it.get(k):
                    descobertos.add(str(it[k]))
    except Exception as e:  # sem isso o gatilho de texto e a resposta ainda valem
        logger.warning("wa: nao consegui ler o ownerJid: %s", type(e).__name__)
    _ids_cache = (time.time(), descobertos)
    return fixos | descobertos


def _historico(grupo: str, email: str) -> list:
    """Por PESSOA no grupo: contexto de quem ve mais nao vaza para quem ve menos."""
    ts, h = _hist.get((grupo, email), (0.0, []))
    return h if time.time() - ts < HIST_TTL_S else []


def _mascara(tel: str | None) -> str:
    return f"...{tel[-4:]}" if tel else "-"


@router.post("/whatsapp/webhook")
async def webhook(request: Request):
    if not _ligado():
        return {"ok": True, "ignorado": "desligado"}
    if _veio_de_fora(request):
        raise HTTPException(status_code=404)
    if not _token_ok(request):
        raise HTTPException(status_code=401)
    try:
        payload = await request.json()
    except Exception:
        return {"ok": True}

    m = parse_evento(payload)
    if m is None or m.de_mim:
        return {"ok": True}
    if m.privado:
        if not privado_ligado():
            return {"ok": True}
    elif m.grupo not in grupos_autorizados():
        return {"ok": True}
    if not foi_chamado(m, await _ids_do_bot()):
        if os.getenv("WA_DEBUG_MENCAO", "").lower() == "true" and m.mencionados:
            logger.info("wa: mencao nao reconhecida mencionados=%s", m.mencionados)
        return {"ok": True}          # descartada, sem registro do conteudo

    if m.msg_id:
        agora = time.time()
        for k in [k for k, v in _vistos.items() if agora - v > VISTO_TTL_S]:
            _vistos.pop(k, None)
        if m.msg_id in _vistos:
            logger.info("wa: evento repetido ignorado")
            return {"ok": True, "repetido": True}
        _vistos[m.msg_id] = agora

    t = asyncio.create_task(_atende(m))
    _tarefas.add(t)
    t.add_done_callback(_tarefas.discard)
    return {"ok": True, "aceito": True}


async def _atende(m: Mensagem) -> None:
    lock = _locks.setdefault(m.grupo, asyncio.Lock())
    async with lock:                          # uma pergunta por vez no grupo
        try:
            await _responde(m)
        except Exception:
            logger.exception("wa: falha no atendimento")
            try:
                await envia_texto(m.grupo, "Tive um erro ao montar a resposta. "
                                  "Tenta de novo em instantes?", citar=m)
            except Exception:
                logger.exception("wa: falha ate no aviso de erro")


async def _quem_perguntou(m: Mensagem, acl_store) -> dict | None:
    """Usuario ATIVO da tela de Acessos dono do numero, ou None.

    1. telefone -> campo WhatsApp da tabela (a regra)
    2. so LID, sem telefone -> WA_NUMEROS "lid:<n>=email" (a excecao)
    """
    if m.telefone:
        u = await acl_store.get_user_by_whatsapp(normaliza_whatsapp(m.telefone))
        if u:
            return u
    if m.lid:
        # so a chave de LID: telefone fora da tabela NAO entra pelo .env
        email = mapa_numeros().get(f"lid:{m.lid}")
        if email:
            return await acl_store.get_user(email)
    return None


async def _responde(m: Mensagem) -> None:
    from gateway.app import acl_store
    from app.agent import run_turn_stream

    usuario = await _quem_perguntou(m, acl_store)
    if not usuario:
        # telefone mascarado; o LID vai inteiro porque e o que o admin mapeia
        logger.info("wa: sem permissao %s tel=%s lid=%s",
                    "privado" if m.privado else "grupo", _mascara(m.telefone), m.lid)
        quem = f"{m.grupo}|{m.remetente_jid}"
        if time.time() - _avisados.get(quem, 0.0) >= AVISO_SEM_PERMISSAO_S:
            _avisados[quem] = time.time()
            await envia_texto(m.grupo, "Você não tem permissão para usar este "
                              "recurso. Fale com a TI.", citar=m)
        return
    email = usuario["email"]

    # ── 1. o que chegou: texto, foto, audio ou planilha ──
    texto_pergunta = limpa_pergunta(m.texto) if not m.privado else m.texto.strip()
    imagens, planilha_ctx, aviso_planilha = None, None, None
    modo_voz = voz.pediu_audio(texto_pergunta)
    ja_avisou = False

    if m.midia:
        dados = await baixa_midia(m)
        if not dados:
            await envia_texto(m.grupo, "Não consegui baixar o arquivo. Manda de novo?", citar=m)
            return
        tipo = m.midia["tipo"]
        if tipo == "audio":
            try:
                texto_pergunta = await asyncio.to_thread(voz.transcrever, dados)
            except voz.VozIndisponivel:
                await envia_texto(m.grupo, "Ainda não consigo ouvir áudio por aqui. "
                                  "Manda por escrito?", citar=m)
                return
            if not texto_pergunta:
                await envia_texto(m.grupo, "Não entendi o áudio. Pode repetir?", citar=m)
                return
            modo_voz = True
            # eco da transcricao: desligado por padrao — virava ruido em todo
            # audio, e a propria resposta ja mostra o que foi entendido
            if os.getenv("WA_VOZ_ECO", "false").strip().lower() == "true":
                ja_avisou = True
                await envia_texto(m.grupo, f"🎙️ Entendi: «{texto_pergunta}»", citar=m)
        elif tipo == "imagem":
            from app.anexos import AnexoInvalido, prepara_imagem
            try:
                imagens = [prepara_imagem(dados, m.midia["mimetype"] or "image/jpeg")]
            except AnexoInvalido as e:
                await envia_texto(m.grupo, str(e), citar=m)
                return
            texto_pergunta = texto_pergunta or "O que é isto? Relacione com o negócio da EBD se fizer sentido."
        elif _e_planilha(m.midia):
            planilha_ctx, aviso_planilha, erro = await _recebe_planilha(m, email, dados)
            if erro:
                await envia_texto(m.grupo, erro, citar=m)
                return
            texto_pergunta = texto_pergunta or "Analise esta planilha."
        else:
            await envia_texto(m.grupo, "Por aqui eu leio foto, áudio e planilha "
                              "(xlsx, xls, csv). Esse tipo de arquivo ainda não.", citar=m)
            return

    if not texto_pergunta:
        await envia_texto(m.grupo, "Oi! Me chama com a pergunta junto — por "
                          "exemplo: @ebd.ia como está o faturamento hoje?", citar=m)
        return
    planilha_ctx = planilha_ctx or _planilha_da_conversa(m.grupo, email)

    logger.info("wa: pergunta %s de %s (%d chars)%s%s",
                "privada" if m.privado else "no grupo", email, len(texto_pergunta),
                f" [{m.midia['tipo']}]" if m.midia else "", " [voz]" if modo_voz else "")
    # o agente precisa saber se todos leem, e se a resposta vai em audio
    mensagem_agente = texto_pergunta if m.privado else f"{MARCA_GRUPO}\n{texto_pergunta}"
    if modo_voz:
        mensagem_agente += f"\n{voz.MARCA_AUDIO}"

    texto, historia, artefatos, t0 = "", None, [], time.perf_counter()

    async def _consome() -> None:
        nonlocal texto, historia
        async for ev in run_turn_stream(
            user_message=mensagem_agente,
            conversation_history=_historico(m.grupo, email),
            user_id=email,
            user_role=ROLE_GRUPO,
            user_filiais="*",          # o MCP restringe pelo e-mail
            channel="whatsapp",
            user_email=email,
            model=_modelo_wa(),
            imagens=imagens,
            planilha_ctx=planilha_ctx,
            aviso_planilha=aviso_planilha,
        ):
            tipo = ev.get("type")
            if tipo == "token":
                texto += ev.get("text", "")
            elif tipo in ("tool", "tool_use"):
                texto = ""              # fica so o que vem depois da ultima ferramenta
            elif tipo == "artifact":
                artefatos.append(ev)
            elif tipo == "done":
                historia = ev.get("history")

    # ── 2. o agente comeca ja; o aviso so sai se ele nao terminar logo ──
    tarefa = asyncio.create_task(_consome())
    try:
        feito, _ = await asyncio.wait({tarefa}, timeout=espera_antes_do_aviso())
        if not feito and not ja_avisou and aviso_ligado():
            frase = frase_de_aviso(texto_pergunta, primeiro_nome(m.nome))
            if frase:
                await envia_texto(m.grupo, frase, citar=m)
        async with asyncio.timeout(TIMEOUT_TURNO_S):
            await tarefa
    except TimeoutError:
        tarefa.cancel()
        logger.warning("wa: turno passou de %ss", TIMEOUT_TURNO_S)
        texto = texto or ("A consulta passou de 10 minutos e parei. Tenta uma "
                          "pergunta mais específica — um mês, uma filial.")

    if historia:
        _hist[(m.grupo, email)] = (time.time(), historia)

    # ── 3. a resposta: audio (se pedido), texto, e os arquivos gerados ──
    falou = False
    if modo_voz:
        try:
            wav = await asyncio.to_thread(voz.sintetizar, voz.extrair_fala(texto))
            falou = await envia_audio(m.grupo, wav, citar=m)
        except voz.VozIndisponivel:
            logger.warning("wa: voz pedida mas o TTS nao esta instalado")
        except Exception as e:
            logger.warning("wa: falha no audio: %s: %s", type(e).__name__, str(e)[:160])
    visual = voz.limpar_texto_visual(texto)
    if not falou or os.getenv("WA_VOZ_COM_TEXTO", "true").lower() == "true":
        resposta = md_para_whatsapp(visual) or "Não consegui montar a resposta dessa vez."
        await envia_texto(m.grupo, resposta, citar=None if falou else m)
    for art in artefatos:
        await _envia_artefato(m.grupo, art)
    logger.info("wa: respondido em %.0fs (%d chars%s%s)", time.perf_counter() - t0,
                len(visual), ", audio" if falou else "",
                f", {len(artefatos)} arquivo(s)" if artefatos else "")


def _modelo_wa() -> str:
    """O MESMO modelo padrao da web (DEFAULT_MODEL, que o troca_modelo.sh
    ja altera). Sem isto o agente caia no CLAUDE_MODEL do config — o Opus,
    pela API da Anthropic — e o WhatsApp rodou um dia inteiro no modelo mais
    caro ate o credito acabar (30/09/2026). WA_MODEL forca outro, se preciso."""
    from gateway.app.models_catalog import DEFAULT_MODEL
    return os.getenv("WA_MODEL", "").strip() or DEFAULT_MODEL


# ─── planilha recebida e arquivos gerados ────────────────────────────────

_EXT_PLANILHA = (".xlsx", ".xls", ".csv", ".xlsm", ".ods")
_conv_planilha: dict[tuple[str, str], tuple[float, str]] = {}


def _e_planilha(midia: dict) -> bool:
    nome = (midia.get("nome") or "").lower()
    mime = midia.get("mimetype") or ""
    return nome.endswith(_EXT_PLANILHA) or "spreadsheet" in mime or \
        "excel" in mime or mime == "text/csv"


def _planilha_da_conversa(chat: str, email: str) -> dict | None:
    """Pergunta seguinte sobre a mesma planilha continua com acesso a ela."""
    ts, conv = _conv_planilha.get((chat, email), (0.0, ""))
    if not conv or time.time() - ts > HIST_TTL_S:
        return None
    from gateway.app import db
    return {"pool": db._pool_or_raise(), "conversation_id": conv, "user_oid": email}


async def _recebe_planilha(m: Mensagem, email: str, dados: bytes):
    """Grava no Postgres como o chat web. -> (planilha_ctx, aviso, erro)."""
    from gateway.app import db
    from app.planilhas import PlanilhaInvalida, le_planilha
    from app.tools.planilha_exec import grava
    nome = m.midia.get("nome") or "planilha.xlsx"
    try:
        pl = await asyncio.to_thread(le_planilha, dados, nome)
    except PlanilhaInvalida as e:
        return None, None, str(e)
    # a planilha precisa de uma conversa (FK); o WhatsApp ganha uma propria
    conv = await db.create_conversation(f"wa:{email}", f"WhatsApp · {nome}"[:42],
                                        "deepseek-flash")
    conv_id = str(conv["id"])
    await grava(db._pool_or_raise(), conv_id, email, nome, pl)
    _conv_planilha[(m.grupo, email)] = (time.time(), conv_id)
    cols = ", ".join(c.nome for c in pl.colunas)
    abas = ""
    if len(pl.abas) > 1:
        lista = " · ".join(f"{a['nome']} ({a['linhas']} linhas)" for a in pl.abas)
        abas = (f" O ARQUIVO TEM {len(pl.abas)} ABAS: {lista}. Estou mostrando "
                f"'{pl.aba}'. DIGA ao usuario quais sao as outras.")
    aviso = (f"[O usuario anexou a planilha '{nome}' com {pl.total} linhas e as "
             f"colunas: {cols}.{abas} Use planilha_resumo e diga o que entendeu.]")
    ctx = {"pool": db._pool_or_raise(), "conversation_id": conv_id, "user_oid": email}
    return ctx, aviso, None


async def _envia_artefato(chat: str, art: dict) -> None:
    """Excel, PDF, PowerPoint ou grafico gerado pelo agente -> arquivo na conversa.

    O evento traz o ID do REGISTRO no banco, que nao e o nome do arquivo em
    disco (ele e salvo com outro uuid, antes do registro). O caminho certo
    vem da tabela artifacts.
    """
    from pathlib import Path
    from gateway.app import db
    row = await db._pool_or_raise().fetchrow(
        "SELECT file_path, filename FROM artifacts WHERE id = $1::uuid", str(art.get("id")))
    arq = Path(row["file_path"]) if row and row["file_path"] else None
    if not arq or not arq.exists():
        logger.warning("wa: artefato %s sem arquivo em disco (%s)", art.get("id"), arq)
        return
    nome = art.get("filename") or row["filename"] or arq.name
    ok = await envia_arquivo(chat, arq.read_bytes(), nome)
    logger.info("wa: arquivo %s %s", nome, "enviado" if ok else "RECUSADO")

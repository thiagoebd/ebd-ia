"""Webhook da Evolution API — o EBD.ia respondendo em grupo de WhatsApp.

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

from app.adapters.whatsapp import (
    Mensagem, envia_texto, foi_chamado, grupos_autorizados,
    limpa_pergunta, mapa_numeros, md_para_whatsapp, normaliza_whatsapp, parse_evento,
)

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

HIST_TTL_S = 2 * 3600          # conversa no grupo "esfria" em 2 h
TIMEOUT_TURNO_S = 600          # teto de um atendimento
ROLE_GRUPO = "grupo_whatsapp"  # nao-admin: nunca propoe auto-append da KB

_locks: dict[str, asyncio.Lock] = {}
_hist: dict[tuple[str, str], tuple[float, list]] = {}
_tarefas: set[asyncio.Task] = set()
_ids_cache: tuple[float, set[str]] = (0.0, set())


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
    if m is None or m.grupo not in grupos_autorizados():
        return {"ok": True}
    if not foi_chamado(m, await _ids_do_bot()):
        if os.getenv("WA_DEBUG_MENCAO", "").lower() == "true" and m.mencionados:
            logger.info("wa: mencao nao reconhecida mencionados=%s", m.mencionados)
        return {"ok": True}          # descartada, sem registro do conteudo

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
        logger.info("wa: sem permissao tel=%s lid=%s", _mascara(m.telefone), m.lid)
        await envia_texto(m.grupo, "Você não tem permissão para usar este "
                          "recurso. Fale com a TI.", citar=m)
        return
    email = usuario["email"]

    pergunta = limpa_pergunta(m.texto)
    if not pergunta:
        await envia_texto(m.grupo, "Oi! Me chama com a pergunta junto — por "
                          "exemplo: @ebd.ia como está o faturamento hoje?", citar=m)
        return

    logger.info("wa: pergunta de %s (%d chars)", email, len(pergunta))
    await envia_texto(m.grupo, "🔎 Consultando…", citar=m)

    texto, historia, t0 = "", None, time.perf_counter()
    try:
        async with asyncio.timeout(TIMEOUT_TURNO_S):
            async for ev in run_turn_stream(
                user_message=pergunta,
                conversation_history=_historico(m.grupo, email),
                user_id=email,
                user_role=ROLE_GRUPO,
                user_filiais="*",          # o MCP restringe pelo e-mail
                channel="whatsapp",
                user_email=email,
            ):
                tipo = ev.get("type")
                if tipo == "token":
                    texto += ev.get("text", "")
                elif tipo in ("tool", "tool_use"):
                    texto = ""              # fica so o que vem depois da ultima ferramenta
                elif tipo == "done":
                    historia = ev.get("history")
    except TimeoutError:
        logger.warning("wa: turno passou de %ss", TIMEOUT_TURNO_S)
        texto = texto or ("A consulta passou de 10 minutos e parei. Tenta uma "
                          "pergunta mais específica — um mês, uma filial.")

    if historia:
        _hist[(m.grupo, email)] = (time.time(), historia)
    resposta = md_para_whatsapp(texto) or "Não consegui montar a resposta dessa vez."
    await envia_texto(m.grupo, resposta, citar=m)
    logger.info("wa: respondido em %.0fs (%d chars)",
                time.perf_counter() - t0, len(resposta))

"""POST /api/chat — chat com streaming SSE, persistencia e seletor de modelo.

Regras de modelo:
- Conversa NOVA: usa o `model` do corpo (validado contra o role); fallback = Haiku.
- Conversa EXISTENTE: usa o modelo gravado na conversa (nao se troca no meio).
"""
import json
import logging
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from gateway.app.auth.entra import verify_token
from gateway.app.models_catalog import is_admin
from gateway.app import acl_store
from fastapi import HTTPException
from gateway.app import db
from gateway.app.models_catalog import resolve_model

from app.agent import run_turn_stream, _conv_id_ctx

import re as _re

def _looks_like_data(text: str) -> bool:
    """Detecta se a resposta apresenta numeros/valores/tabela como se fossem dados reais."""
    if not text:
        return False
    if _re.search(r"R\$\s*[\d.]", text):          # R$ 1.234
        return True
    if _re.search(r"\|[^\n]*\d[^\n]*\|", text):  # linha de tabela com numero
        return True
    if _re.search(r"\b\d{1,3}(?:\.\d{3})+\b", text):  # 1.358 / 9.521.869
        return True
    return False



logger = logging.getLogger("uvicorn.error")
router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    model: str | None = None
    # imagens em base64 (data URL ou base64 puro). O front manda no MESMO
    # corpo JSON — nao precisa de multipart nem rota separada.
    imagens: list[str] | None = None
    # planilha: base64 do xlsx/csv + nome, no MESMO corpo JSON
    planilha_b64: str | None = None
    planilha_nome: str | None = None
    history: list | None = None  # compat (ignorado, janela vem do banco)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _title_from(text: str) -> str:
    t = text.strip().replace("\n", " ")
    return (t[:42] + "…") if len(t) > 42 else (t or "Nova conversa")


def _titulo_da_planilha(pl, nome_arquivo: str) -> str:
    """Titulo a partir do que a planilha CONTEM, nao do nome do arquivo.

    'filiais-ebd-cnpjs.xlsx' vira 'Filiais e CNPJs (21 linhas)' — o usuario
    reconhece a conversa pelo assunto, nao pelo nome que o Excel deu.
    """
    cols = [c.nome.replace("_", " ").title() for c in pl.colunas
            if c.preenchidas > 0 and not c.nome.startswith("COLUNA_")][:3]
    if cols:
        base = ", ".join(cols)
        return (f"{base} ({pl.total} linhas)")[:42]
    return (nome_arquivo or "Planilha")[:42]


async def _titulo_da_imagem(blocos: list) -> str:
    """Batiza a conversa a partir da PROPRIA imagem.

    Mensagem so com foto deixava o titulo vazio — a barra lateral enchia de
    "Nova conversa" e ninguem achava a conversa depois. Aqui o modelo olha a
    imagem e devolve um titulo curto.
    """
    if not blocos:
        return "Nova conversa"
    try:
        import sys as _s
        from pathlib import Path as _P
        _core = str(_P(__file__).resolve().parents[3] / "core")
        if _core not in _s.path:
            _s.path.insert(0, _core)
        from app.agent import _client_for  # type: ignore
        import os as _o
        modelo = _o.getenv("TITULO_MODEL") or _o.getenv("DEEPSEEK_MODEL") \
            or "deepseek-flash"
        cli, m = _client_for(modelo)
        conteudo = list(blocos[:1]) + [{
            "type": "text",
            "text": ("De um titulo de ate 6 palavras para esta imagem, em "
                     "portugues. So o titulo, sem aspas e sem ponto final."),
        }]
        # o cliente e ASSINCRONO (AsyncAnthropic) — `with` sincrono estoura
        # e cai no except, deixando o titulo em "Imagem enviada"
        # max_tokens folgado: o modelo raciocina antes de responder e com
        # teto baixo termina em stop_reason=max_tokens SEM texto — o titulo
        # vinha vazio e caia no fallback, sem erro no log (intermitente).
        async with cli.messages.stream(model=m, max_tokens=4000,
                                       messages=[{"role": "user",
                                                  "content": conteudo}]) as st:
            async for _ in st.text_stream:
                pass
            r = await st.get_final_message()
        t = "".join(getattr(b, "text", "") for b in r.content
                    if getattr(b, "type", "") == "text").strip()
        t = t.strip(" \"'").replace("\n", " ")
        if not t:
            logger.warning("titulo da imagem veio VAZIO: stop=%s out=%s",
                           getattr(r, "stop_reason", "?"),
                           getattr(getattr(r, "usage", None),
                                   "output_tokens", "?"))
            return "Imagem enviada"
        # o modelo as vezes responde "Titulo: X" ou manda frase inteira
        if ":" in t[:12]:
            t = t.split(":", 1)[1].strip()
        return (t[:42] + "…") if len(t) > 42 else t
    except Exception as e:
        logger.warning("titulo da imagem falhou: %s: %s",
                       type(e).__name__, str(e)[:160])
        return "Imagem enviada"


def _e_uuid(valor) -> bool:
    """True se o id e um UUID de verdade.

    O frontend manda `tmp-<timestamp>` para conversa nova (App.tsx). Sem esta
    checagem o asyncpg levanta ValueError e o stream morre em silencio.
    """
    if not valor:
        return False
    try:
        import uuid as _uuid
        _uuid.UUID(str(valor))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


MAX_IMAGENS = 5


def _prepara_imagens(brutas: list[str] | None) -> tuple[list, str | None]:
    """data URL ou base64 -> blocos prontos. (blocos, erro para o usuario)"""
    if not brutas:
        return [], None
    if len(brutas) > MAX_IMAGENS:
        return [], f"Manda no maximo {MAX_IMAGENS} imagens por mensagem."
    import base64 as _b64
    import sys as _sys
    from pathlib import Path as _P
    _core = str(_P(__file__).resolve().parents[3] / "core")
    if _core not in _sys.path:
        _sys.path.insert(0, _core)
    from app.anexos import AnexoInvalido, prepara_imagem

    blocos = []
    for bruto in brutas:
        try:
            mime = "image/jpeg"
            if bruto.startswith("data:"):
                cabeca, _, dados = bruto.partition(",")
                mime = cabeca[5:].split(";")[0] or mime
            else:
                dados = bruto
            blocos.append(prepara_imagem(_b64.b64decode(dados), mime))
        except AnexoInvalido as e:
            return [], str(e)
        except Exception:
            logger.warning("imagem invalida no /api/chat")
            return [], "Nao consegui ler essa imagem. Tenta outro arquivo?"
    return blocos, None


@router.post("/chat")
async def chat(body: ChatRequest, claims: dict = Depends(verify_token)):
    oid = claims.get("oid")
    _email = claims.get("preferred_username") or claims.get("upn") or claims.get("unique_name") or claims.get("email")
    if not await acl_store.is_allowed(_email):
        raise HTTPException(status_code=403, detail="Seu acesso ainda nao foi configurado. Fale com o admin (TI Grupo EBD).")
    user_id = oid or claims.get("sub") or "web-user"
    user_role = "admin"  # passou aqui = autorizado pela ACL
    user_filiais = "*"

    async def event_stream():
        _t0 = time.perf_counter()
        def _lap(tag): logger.info(f'[PERF] {tag}: {(time.perf_counter()-_t0)*1000:.0f}ms')
        conv_id = body.conversation_id
        new_conv = False
        try:
            _imgs, _erro_img = _prepara_imagens(body.imagens)
            if _erro_img:
                yield _sse({"type": "token", "text": f"⚠️ {_erro_img}"})
                yield _sse({"type": "done", "stop_reason": "anexo_invalido"})
                return
            if _imgs:
                logger.info("chat: %d imagem(ns) anexada(s)", len(_imgs))
            _titulo = _title_from(body.message) if body.message.strip() else None

            # planilha: le, valida e guarda. O agente so vera o resumo.
            _erro_pl = None
            # inicializa ANTES do try: se a leitura falhar, a variavel
            # precisa existir — senao o erro real some atras de um NameError
            _pl_pendente = None
            if body.planilha_b64:
                try:
                    import base64 as _b64p
                    import sys as _sp
                    from pathlib import Path as _Pp
                    _c = str(_Pp(__file__).resolve().parents[3] / "core")
                    if _c not in _sp.path:
                        _sp.path.insert(0, _c)
                    from app.planilhas import PlanilhaInvalida, le_planilha
                    bruto = body.planilha_b64
                    if bruto.startswith("data:"):
                        bruto = bruto.partition(",")[2]
                    _pl = le_planilha(_b64p.b64decode(bruto),
                                      body.planilha_nome or "planilha.xlsx")
                    _pl_pendente = _pl
                    logger.info("chat: planilha %s com %d linhas",
                                body.planilha_nome, _pl.total)
                except PlanilhaInvalida as e:
                    _erro_pl = str(e)
                except Exception as e:
                    logger.warning("planilha falhou: %s", type(e).__name__)
                    _erro_pl = "Nao consegui ler essa planilha."
            else:
                _pl_pendente = None

            if _titulo is None:
                if _pl_pendente is not None:
                    _titulo = _titulo_da_planilha(_pl_pendente,
                                                  body.planilha_nome or "")
                else:
                    _titulo = await _titulo_da_imagem(_imgs)

            if _erro_pl:
                yield _sse({"type": "token", "text": f"⚠️ {_erro_pl}"})
                yield _sse({"type": "done", "stop_reason": "anexo_invalido"})
                return

            if conv_id and not _e_uuid(conv_id):
                # frontend manda tmp-<timestamp> em conversa nova: nao e UUID,
                # e passar isso ao Postgres derruba o stream inteiro
                logger.info("conversation_id nao-UUID (%r): tratando como nova",
                            str(conv_id)[:40])
                conv_id = None
            if conv_id:
                conv = await db.get_conversation(conv_id, user_id)
                if not conv:
                    model_used = resolve_model(body.model, user_id)
                    conv = await db.create_conversation(user_id, _titulo, model_used)
                    new_conv = True
            else:
                model_used = resolve_model(body.model, user_id)
                conv = await db.create_conversation(user_id, _titulo, model_used)
                new_conv = True

            conv_id = str(conv["id"])
            _conv_id_ctx.set(conv_id)
            model_used = conv["model"]  # sempre o que esta gravado na conversa

            yield _sse({"type": "conversation", "id": conv_id,
                        "title": conv["title"], "new": new_conv,
                        "model": model_used})

            _aviso_pl = None
            _pl_ctx = None
            if conv_id:
                if _pl_pendente is not None:
                    from app.tools.planilha_exec import grava as _grava_pl
                    await _grava_pl(db._pool_or_raise(), conv_id, user_id,
                                    body.planilha_nome or "planilha.xlsx",
                                    _pl_pendente)
                _pl_ctx = {"pool": db._pool_or_raise(),
                           "conversation_id": conv_id, "user_oid": user_id}
                if _pl_pendente is not None:
                    _cols = ", ".join(c.nome for c in _pl_pendente.colunas)
                    _abas = ""
                    if len(_pl_pendente.abas) > 1:
                        _lista = " · ".join(
                            f"{a['nome']} ({a['linhas']} linhas)"
                            for a in _pl_pendente.abas)
                        _abas = (
                            f" O ARQUIVO TEM {len(_pl_pendente.abas)} ABAS: "
                            f"{_lista}. Estou mostrando a aba "
                            f"'{_pl_pendente.aba}', que e a com mais dados. "
                            f"DIGA ao usuario quais sao as outras abas — ele "
                            f"pode querer analisar outra.")
                    _aviso_pl = (
                        f"[O usuario anexou a planilha '{body.planilha_nome}' "
                        f"com {_pl_pendente.total} linhas e as colunas: {_cols}."
                        f"{_abas} Use planilha_resumo para ver os tipos e "
                        f"exemplos, e diga a ele o que voce entendeu do arquivo "
                        f"antes de perguntar o que fazer.]")

            window = await db.build_model_window(conv_id, user_id)
            _lap('window pronta')
            # guarda as imagens junto: sem isso a proxima pergunta chega ao
            # modelo com a mensagem VAZIA e ele perde o contexto da foto
            _cont_user = {"text": body.message}
            if _imgs:
                _cont_user["imagens"] = body.imagens[:len(_imgs)]
            if _pl_pendente is not None:
                _cont_user["anexo"] = {"nome": body.planilha_nome or "planilha",
                                       "tipo": "planilha"}
            await db.add_message(conv_id, "user", _cont_user)
            _lap('user msg gravada')

            assistant_text = ""
            tools_used = []          # so tools com SUCESSO (controla badge)
            tool_outcomes = []       # [(name, success)] reportado pelo agent
            any_tool_failed = False
            saved = False
            try:
                async for ev in run_turn_stream(
                    user_message=body.message,
                    conversation_history=window,
                    user_id=user_id,
                    user_role=user_role,
                    user_filiais=user_filiais,
                    channel="web",
                    user_email=_email,
                    model=model_used,
                    imagens=_imgs or None,
                    planilha_ctx=_pl_ctx,
                    aviso_planilha=_aviso_pl,
                    origem={"canal": "web", "conversation_id": conv_id},
                ):
                    etype = ev.get("type")
                    if etype == "token":
                        if not assistant_text: _lap('PRIMEIRO TOKEN do agent'); event_stream._ttft_ms = (time.perf_counter()-_t0)*1000.0
                        assistant_text += ev.get("text", "")
                    elif etype == "tool" or etype == "tool_use":
                        if not getattr(event_stream, "_tool_marked", False):
                            _lap("PRIMEIRA TOOL chamada"); event_stream._tool_marked = True
                    elif etype == "tool_done":
                        # Badge SO acende em sucesso real
                        name = ev.get("name")
                        if ev.get("success"):
                            if name and name not in tools_used:
                                tools_used.append(name)
                        else:
                            any_tool_failed = True
                        # nao repassa tool_done cru pro frontend (interno)
                        continue
                    elif etype == "done":
                        tool_outcomes = ev.get("tool_outcomes", [])
                        any_ok = any(ok for (_n, ok) in tool_outcomes)
                        # -- LLM EVENT (obs Fase 2): usage/custo em llm_events.jsonl --
                        try:
                            import json as _j, os as _o, time as _t
                            from datetime import datetime as _dt, timezone as _tz
                            from pathlib import Path as _P
                            _u = ev.get("usage") or {}
                            _pr = lambda k, d: float(_o.getenv(k, d))
                            _in  = int(_u.get("input_tokens", 0) or 0)
                            _out = int(_u.get("output_tokens", 0) or 0)
                            _cr  = int(_u.get("cache_read_input_tokens", 0) or 0)
                            _cw  = int(_u.get("cache_creation_input_tokens", 0) or 0)
                            _mstr = str(model_used).lower()
                            if 'deepseek' in _mstr:
                                if 'pro' in _mstr:
                                    # o Pro e roteado para o V4.1 Flash e cobrado como Flash
                                    _pin, _pout, _prd, _pwr = 0.15, 0.60, 0.003, 0.15
                                else:
                                    # V4.1 Flash, off-peak (comunicado 09/09/2026)
                                    _pin, _pout, _prd, _pwr = 0.15, 0.60, 0.003, 0.15
                            elif 'haiku' in _mstr:
                                _pin, _pout, _prd, _pwr = 1.0, 5.0, 0.10, 2.0
                            elif 'opus' in _mstr:
                                _pin, _pout, _prd, _pwr = 5.0, 25.0, 0.50, 10.0
                            else:
                                _pin, _pout, _prd, _pwr = 3.0, 15.0, 0.30, 6.0
                            _usd = (_in*_pr('LLM_PRICE_IN', _pin) + _out*_pr('LLM_PRICE_OUT', _pout)
                                    + _cr*_pr('LLM_PRICE_CACHE_READ', _prd)
                                    + _cw*_pr('LLM_PRICE_CACHE_WRITE', _pwr)) / 1000000.0
                            _rec = {
                                "ts": _dt.now(_tz.utc).isoformat().replace("+00:00","Z"),
                                "user_email": _email,
                                "user_nome": (_email or "?").split("@")[0],
                                "canal": "web",
                                "model": model_used,
                                "conversation_id": str(conv_id),
                                "input_tokens": _in, "output_tokens": _out,
                                "cache_read_tokens": _cr, "cache_creation_tokens": _cw,
                                "custo_brl": round(_usd * _pr("USD_BRL","5.20"), 6),
                                "ttft_ms": round(getattr(event_stream, "_ttft_ms", 0.0), 1),
                                "total_ms": round((_t.perf_counter()-_t0)*1000.0, 1),
                                "tools_executadas": len(tool_outcomes),
                                # mensagem so com imagem deixava a linha VAZIA
                                # no painel — ninguem sabia o que foi perguntado
                                "pergunta": ((body.message or "").strip()
                                             or (f"[{len(_imgs)} imagem(ns)] "
                                                 + (_titulo or ""))
                                             )[:120],
                                "imagens": len(_imgs),
                            }
                            _lf = _P(__file__).resolve().parents[3] / "logs" / "gateway" / "llm_events.jsonl"
                            with open(_lf, "a", encoding="utf-8") as _f:
                                _f.write(_j.dumps(_rec, ensure_ascii=False) + "\n")
                        except Exception:
                            pass
                        # ── TRAVA ANTI-FABULACAO ──────────────────────────────
                        # Se a resposta apresenta dados (numeros/R$/tabela) mas
                        # NENHUMA tool teve sucesso nesta turn -> os numeros foram
                        # inventados. Bloqueia, substitui o texto, zera o badge.
                        if _looks_like_data(assistant_text) and not any_ok:
                            logger.error(
                                "ANTI-FABULACAO disparou: resposta com dados sem tool OK. "
                                "tool_outcomes=%s preview=%r",
                                tool_outcomes, assistant_text[:200],
                            )
                            assistant_text = ("Nao consegui trazer esses dados do "
                                              "Winthor e nao vou arriscar numeros "
                                              "sem base. Pode reformular a pergunta, "
                                              "de preferencia com filial e periodo?")
                            tools_used = []
                            ev["text"] = assistant_text
                            ev["fabricacao_bloqueada"] = True
                        await db.add_message(conv_id, "assistant",
                                             {"text": assistant_text, "tools": tools_used})
                        saved = True
                        ev.pop("history", None)
                    yield _sse(ev)
            finally:
                if not saved and assistant_text:
                    # mesma trava no caminho de excecao/interrupcao
                    if _looks_like_data(assistant_text) and not tools_used:
                        assistant_text = ("Nao consegui trazer esses dados do "
                                          "Winthor e nao vou arriscar numeros sem "
                                          "base. Pode reformular a pergunta, de "
                                          "preferencia com filial e periodo?")
                        tools_used = []
                    await db.add_message(conv_id, "assistant",
                                         {"text": assistant_text, "tools": tools_used})
        except Exception as e:
            logger.exception("Erro no /api/chat stream")
            # NAO deixar o stream morrer mudo: ate 31/07/2026 uma excecao aqui
            # terminava o stream sem emitir nada e o usuario via bolha vazia
            try:
                yield _sse({"type": "token", "text":
                            "Tive um erro interno ao processar essa pergunta. "
                            "Tente de novo; se persistir, avise a TI."})
                yield _sse({"type": "done", "stop_reason": "erro_interno"})
            except Exception:
                pass
            yield _sse({"type": "error", "detail": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

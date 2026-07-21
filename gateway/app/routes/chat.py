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
    history: list | None = None  # compat (ignorado, janela vem do banco)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _title_from(text: str) -> str:
    t = text.strip().replace("\n", " ")
    return (t[:42] + "…") if len(t) > 42 else (t or "Nova conversa")


@router.post("/chat")
async def chat(body: ChatRequest, claims: dict = Depends(verify_token)):
    oid = claims.get("oid")
    _email = claims.get("preferred_username") or claims.get("upn") or claims.get("unique_name") or claims.get("email")
    if not is_admin(oid, _email):
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
            if conv_id:
                conv = await db.get_conversation(conv_id, user_id)
                if not conv:
                    model_used = resolve_model(body.model, user_id)
                    conv = await db.create_conversation(user_id, _title_from(body.message), model_used)
                    new_conv = True
            else:
                model_used = resolve_model(body.model, user_id)
                conv = await db.create_conversation(user_id, _title_from(body.message), model_used)
                new_conv = True

            conv_id = str(conv["id"])
            _conv_id_ctx.set(conv_id)
            model_used = conv["model"]  # sempre o que esta gravado na conversa

            yield _sse({"type": "conversation", "id": conv_id,
                        "title": conv["title"], "new": new_conv,
                        "model": model_used})

            window = await db.build_model_window(conv_id, user_id)
            _lap('window pronta')
            await db.add_message(conv_id, "user", {"text": body.message})
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
                                    _pin, _pout, _prd, _pwr = 0.435, 0.87, 0.003625, 0.0
                                else:
                                    _pin, _pout, _prd, _pwr = 0.14, 0.28, 0.0028, 0.0
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
                                "custo_brl": round(_usd * _pr("USD_BRL","5.40"), 6),
                                "ttft_ms": round(getattr(event_stream, "_ttft_ms", 0.0), 1),
                                "total_ms": round((_t.perf_counter()-_t0)*1000.0, 1),
                                "tools_executadas": len(tool_outcomes),
                                "pergunta": (body.message or "")[:120],
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
                            assistant_text = ("Nao consegui consultar o Winthor agora — "
                                              "tenta de novo daqui a pouco?")
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
                        assistant_text = ("Nao consegui consultar o Winthor agora — "
                                          "tenta de novo daqui a pouco?")
                        tools_used = []
                    await db.add_message(conv_id, "assistant",
                                         {"text": assistant_text, "tools": tools_used})
        except Exception as e:
            logger.exception("Erro no /api/chat stream")
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

"""Adapter Telegram pra arquitetura unificada.

Mesmo cérebro do CLI (core/agent.py) — adapter apenas:
1. Traduz update Telegram → run_turn() do agent
2. Mantém histórico por chat_id (in-memory por enquanto)
3. Aplica ACL hardcoded (admin via ADMIN_CHAT_IDS)
4. Envia resposta em Markdown nativo do Telegram
5. Suporta comandos /start /reset /historico /aprovar /descartar

Limites Telegram:
- 4096 chars por mensagem (vamos quebrar quando passar)
- Markdown v1 (mais permissivo que MarkdownV2)
"""
import os
import logging
import time
from typing import Any
from app.agent import run_turn
from app.config import settings
from app.tools.knowledge_append import approve_proposal, discard_proposal
from app.storage.chat_history import load_history, save_history, reset_history

# ACL hardcoded (futuro: vir de FILIAL_ACL_CHATBOT no Oracle)
_admin_ids_str = os.environ.get("ADMIN_CHAT_IDS", "")
ADMIN_CHAT_IDS = {int(x.strip()) for x in _admin_ids_str.split(",") if x.strip().isdigit()}

# Histórico em memória, por chat_id (some no restart — futuro: Postgres)
logger = logging.getLogger(__name__)

_history: dict[int, list[dict]] = {}
_session_stats: dict[int, dict] = {}

# Pricing Sonnet 4.6 (US$/MTok)
PRICE_INPUT = 3.00 / 1_000_000
PRICE_OUTPUT = 15.00 / 1_000_000
PRICE_CACHE_WRITE = 3.75 / 1_000_000
PRICE_CACHE_READ = 0.30 / 1_000_000
USD_BRL = 5.20

TELEGRAM_MAX_LEN = 4000  # margem dos 4096


def _calc_cost_usd(u: dict) -> float:
    return (
        u.get("input_tokens", 0) * PRICE_INPUT
        + u.get("output_tokens", 0) * PRICE_OUTPUT
        + u.get("cache_creation_input_tokens", 0) * PRICE_CACHE_WRITE
        + u.get("cache_read_input_tokens", 0) * PRICE_CACHE_READ
    )


def get_user_role(chat_id: int) -> str:
    """ACL hardcoded — futuro: query FILIAL_ACL_CHATBOT."""
    if chat_id in ADMIN_CHAT_IDS:
        return "admin"
    return "vendedor"  # default seguro pra quem não está na lista


def chunk_message(text: str, max_len: int = TELEGRAM_MAX_LEN) -> list[str]:
    """Quebra texto em chunks pra respeitar limite Telegram."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # tenta cortar em quebra de linha
        cut = text.rfind("\n", 0, max_len)
        if cut < max_len // 2:  # quebra muito cedo, força corte
            cut = max_len
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    return chunks


async def handle_message(chat_id: int, user_first_name: str, text: str) -> list[str]:
    """Processa uma mensagem do Telegram e retorna lista de strings pra enviar."""
    role = get_user_role(chat_id)
    text = text.strip()

    # Comandos especiais primeiro
    if text == "/start":
        if role == "admin":
            return [
                f"👋 Olá, *{user_first_name}*\\!\n\n"
                f"Sou o *EBD\\.ia*, agente comercial conectado ao Winthor\\.\n\n"
                f"Você está como `admin` — pode propor auto\\-append na knowledge base\\.\n\n"
                f"*Comandos:*\n"
                f"• `/reset` \\- limpa histórico\n"
                f"• `/saldo` \\- custo da sessão\n"
                f"• `/aprovar PROP\\-XXXX` \\- aprova proposta\n"
                f"• `/descartar PROP\\-XXXX` \\- descarta proposta\n\n"
                f"Manda qualquer pergunta sobre vendas, RCAs, ruptura, estoque\\.\\.\\."
            ]
        else:
            return [
                f"👋 Olá, {user_first_name}.\n\n"
                f"Seu acesso ainda não foi liberado. Fale com o Thiago pra ser adicionado.\n\n"
                f"Seu chat_id é: `{chat_id}`"
            ]

    if text == "/reset":
        reset_history(chat_id)
        _history[chat_id] = []
        _session_stats[chat_id] = {"cost_usd": 0.0, "turns": 0}
        return ["✅ Histórico limpo."]

    if text == "/saldo":
        s = _session_stats.get(chat_id, {})
        cost = s.get("cost_usd", 0.0)
        turns = s.get("turns", 0)
        return [
            f"💰 *Sessão atual:*\n"
            f"Turns: {turns}\n"
            f"Custo: US$ {cost:.4f} (R$ {cost*USD_BRL:.4f})"
        ]

    if text.startswith("/aprovar "):
        if role != "admin":
            return ["❌ Apenas admin pode aprovar propostas."]
        pid = text.split(maxsplit=1)[1].strip()
        r = approve_proposal(pid, user_name=user_first_name)
        emoji = "✅" if r["ok"] else "❌"
        return [f"{emoji} {r['msg']}"]

    if text.startswith("/descartar "):
        if role != "admin":
            return ["❌ Apenas admin pode descartar propostas."]
        pid = text.split(maxsplit=1)[1].strip()
        r = discard_proposal(pid)
        emoji = "⚠️" if r["ok"] else "❌"
        return [f"{emoji} {r['msg']}"]

    # Mensagem normal — chama o agent
    historico = _history.get(chat_id) or load_history(chat_id)
    logger.info(f"🔍 [{chat_id}] hist_len={len(historico)} msgs, mem={chat_id in _history}")
    _llm_t0 = __import__('time').perf_counter()
    result = await run_turn(
        text,
        conversation_history=historico,
        user_id=str(chat_id),
        user_role=role,
        user_filiais="*",  # futuro: vir da ACL
        channel="telegram",
     model=__import__('os').getenv('TELEGRAM_MODEL', 'claude-haiku-4-5'))
    # -- LLM EVENT (obs Fase 2): canal telegram --
    try:
        import json as _j, os as _o, time as _t
        from datetime import datetime as _dt, timezone as _tz
        from pathlib import Path as _P
        _u = (result.get('usage') if isinstance(result, dict) else None) or dict()
        _pr = lambda k, d: float(_o.getenv(k, d))
        _in  = int(_u.get('input_tokens', 0) or 0)
        _out = int(_u.get('output_tokens', 0) or 0)
        _cr  = int(_u.get('cache_read_input_tokens', 0) or 0)
        _cw  = int(_u.get('cache_creation_input_tokens', 0) or 0)
        _mstr = str(((result.get('model') if isinstance(result, dict) else '') or '')).lower()
        if 'haiku' in _mstr:
            _pin, _pout, _prd, _pwr = 1.0, 5.0, 0.10, 2.0
        elif 'opus' in _mstr:
            _pin, _pout, _prd, _pwr = 5.0, 25.0, 0.50, 10.0
        else:
            _pin, _pout, _prd, _pwr = 3.0, 15.0, 0.30, 6.0
        _usd = (_in*_pr('LLM_PRICE_IN', _pin) + _out*_pr('LLM_PRICE_OUT', _pout)
                + _cr*_pr('LLM_PRICE_CACHE_READ', _prd)
                + _cw*_pr('LLM_PRICE_CACHE_WRITE', _pwr)) / 1000000.0
        _rec = dict(
            ts=_dt.now(_tz.utc).isoformat().replace('+00:00','Z'),
            user_email='service@ebd.ia', user_nome='telegram', canal='telegram',
            model=(result.get('model') if isinstance(result, dict) else None) or 'desconhecido',
            conversation_id='telegram',
            input_tokens=_in, output_tokens=_out,
            cache_read_tokens=_cr, cache_creation_tokens=_cw,
            custo_brl=round(_usd * _pr('USD_BRL','5.40'), 6),
            ttft_ms=0.0,
            total_ms=round((_t.perf_counter()-_llm_t0)*1000.0, 1),
            tools_executadas=len((result.get('tool_calls') if isinstance(result, dict) else None) or []),
            pergunta=str(text)[:120],
        )
        _lf = _P(__file__).resolve().parents[3] / 'logs' / 'gateway' / 'llm_events.jsonl'
        with open(_lf, 'a', encoding='utf-8') as _f:
            _f.write(_j.dumps(_rec, ensure_ascii=False) + chr(10))
    except Exception:
        pass
    _history[chat_id] = result["history"]
    try:
        save_history(chat_id, result["history"])
    except Exception as e:
        logger.warning(f"Falha salvando historico chat_id={chat_id}: {e}")

    u = result.get("usage", {})
    cost = _calc_cost_usd(u)
    stats = _session_stats.setdefault(chat_id, {"cost_usd": 0.0, "turns": 0})
    stats["cost_usd"] += cost
    stats["turns"] += 1

    logger.info(
        f"💰 [{chat_id}] turn#{stats['turns']} | "
        f"in={u.get('input_tokens',0)} out={u.get('output_tokens',0)} "
        f"cache_w={u.get('cache_creation_input_tokens',0)} cache_r={u.get('cache_read_input_tokens',0)} | "
        f"R$ {cost*USD_BRL:.4f} | total: R$ {stats['cost_usd']*USD_BRL:.4f}"
    )

    response = result["text"]
    # Footer só visivel pro admin (debug)
    if role == "admin":
        response += (
            f"\n\n_⚙️ {result['iterations']} iter • {len(result['tool_calls'])} tools • "
            f"R$ {cost*USD_BRL:.4f} • total: R$ {stats['cost_usd']*USD_BRL:.4f}_"
        )

    return chunk_message(response)

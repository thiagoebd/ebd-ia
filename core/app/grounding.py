"""Lastro numerico (SHADOW MODE): mede se cada numero da resposta final
existe nos tool_results do turno. NAO bloqueia nada — apenas loga a metrica."""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os as _os
import re

_log = logging.getLogger("uvicorn.error")

_TOKEN = re.compile(r"-?\d[\d.,]*")
_REL_TOL = 0.01


def _parse_br(tok: str, suffix: str = "") -> float | None:
    t = tok.strip().rstrip(".,")
    if not t:
        return None
    try:
        if "," in t:
            v = float(t.replace(".", "").replace(",", "."))
        elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
            v = float(t.replace(".", ""))
        else:
            v = float(t)
    except ValueError:
        return None
    mult = {"k": 1e3, "mil": 1e3, "m": 1e6, "mi": 1e6, "bi": 1e9, "b": 1e9}
    return v * mult.get(suffix.lower(), 1.0)


def _parse_raw(tok: str) -> float | None:
    t = tok.strip().rstrip(".,")
    try:
        return float(t.replace(",", "")) if t else None
    except ValueError:
        return None


def _nums_from_answer(text: str) -> list[float]:
    out = []
    for m in _TOKEN.finditer(text):
        tail = text[m.end():m.end() + 3]
        sfx = ""
        for cand in ("mil", "bi", "mi", "m", "k", "b"):
            if tail.lower().startswith(cand):
                sfx = cand
                break
        v = _parse_br(m.group(0), sfx)
        if v is not None:
            out.append(v)
    return out


def _nums_from_sources(chunks: list[str], cap: int = 4000) -> list[float]:
    out = []
    for c in chunks:
        for m in _TOKEN.finditer(c or ""):
            v = _parse_raw(m.group(0))
            if v is not None:
                out.append(v)
                if len(out) >= cap:
                    return out
    return out


def _close(a: float, b: float) -> bool:
    if a == b:
        return True
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) / scale <= _REL_TOL


def _is_trivial(v: float) -> bool:
    return v == int(v) and (abs(v) <= 31 or 1900 <= v <= 2100)


def _explain(v: float, src: list[float]) -> str | None:
    """direct = veio da query. derived = aritmetica do LLM sobre numeros com
    lastro (soma/subtracao/razao). None = SEM EXPLICACAO -> suspeita real."""
    if any(_close(v, s) for s in src):
        return "direct"
    P = src[:300]
    for a in P:
        for b in P:
            if _close(v, a - b) or _close(v, a + b):
                return "derived"
            if b and (_close(v, a / b * 100.0) or _close(v, a / b)):
                return "derived"
    return None


def check_grounding(answer: str, tool_chunks: list[str]) -> dict:
    ans = _nums_from_answer(answer or "")
    src = _nums_from_sources(tool_chunks or [])
    direct = derived = 0
    unmatched = []
    for v in ans:
        if _is_trivial(v):
            continue
        kind = _explain(v, src)
        if kind == "direct":
            direct += 1
        elif kind == "derived":
            derived += 1
        else:
            unmatched.append(v)
    return {
        "nums_answer": len(ans),
        "nums_source": len(src),
        "direct": direct,
        "derived": derived,
        "unmatched": len(unmatched),
        "samples": unmatched[:6],
    }


def log_grounding(res: dict, **extra) -> None:
    rec = {"ts": _dt.datetime.now().isoformat(timespec="seconds"), **res, **extra}
    try:
        _log.warning("GROUNDING %s", json.dumps(rec, default=str))
    except Exception:
        pass
    try:
        d = _os.getenv("GROUNDING_LOG_DIR", "logs")
        _os.makedirs(d, exist_ok=True)
        with open(_os.path.join(d, "grounding.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass

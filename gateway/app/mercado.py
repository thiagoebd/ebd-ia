"""Painel de mercado da tela inicial: macro (Banco Central) + noticias do setor.

Principios (cicatrizes do projeto):
- A tela NUNCA espera rede: serve o cache pronto e atualiza por tras.
- Se a atualizacao falhar, mantem o ultimo payload BOM e expoe a idade.
- Passando do limite sem atualizar, devolve vazio — melhor bloco ausente do
  que dado velho passando por novo.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

log = logging.getLogger("uvicorn.error")

UA = {"User-Agent": "Mozilla/5.0 (compatible; EBDia/1.0; +interno)"}
TTL_NOTICIAS = int(os.getenv("MERCADO_TTL_NOTICIAS", "1800"))   # 30 min
TTL_MACRO = int(os.getenv("MERCADO_TTL_MACRO", "43200"))        # 12 h
IDADE_MAX = int(os.getenv("MERCADO_IDADE_MAX", "21600"))        # 6 h -> some

# Series do SGS/Banco Central. rotulo, codigo, prefixo, sufixo, mostra_ref
SERIES = [
    ("Dólar", 1, "R$ ", "", True),
    ("Selic", 432, "", "% a.a.", False),
    ("IPCA 12m", 13522, "", "%", True),
    ("IGP-M", 189, "", "%", True),
]

FRENTES = [
    os.getenv("MERCADO_Q_SETOR",
              '"atacado distribuidor" OR "canal indireto" OR "setor atacadista" '
              'OR "distribuidora de alimentos" OR "ranking ABAD"'),
    os.getenv("MERCADO_Q_MERCADO",
              '"varejo alimentar" OR "bens de consumo" OR atacarejo '
              'OR "supermercado" AND tecnologia'),
]
JANELA_DIAS = os.getenv("MERCADO_JANELA_DIAS", "7")
BLOQUEIO = tuple(x.strip().lower() for x in os.getenv(
    "MERCADO_BLOQUEIO", "vietnam,.vn,xinhua,globaltimes,people.cn,instagram.com"
).split(",") if x.strip())

_STOP = {"de","da","do","das","dos","em","no","na","nos","nas","e","o","a","os","as","com",
         "para","por","um","uma","que","se","ao","aos","sua","seu","the","of","and","mais"}
_LOJA = re.compile(r"inaugur|abre .{0,12}loja|nova loja|reinaugur|revitaliz|megaloja|"
                   r"nova unidade|primeira (loja|unidade)|celebra \d+ anos", re.I)

_cache: dict = {"macro": None, "macro_em": 0.0, "noticias": None, "noticias_em": 0.0}
_lock = asyncio.Lock()
_atualizando = False


def _get(url: str, timeout: int = 10) -> bytes:
    ultimo = None
    for _ in range(2):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as e:                       # rede intermitente: 1 retry
            ultimo = e
            time.sleep(0.6)
    raise ultimo


def _toks(t: str) -> set[str]:
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return {p.rstrip("s") for p in re.findall(r"[a-z0-9]{3,}", t) if p not in _STOP}


def buscar_macro() -> list[dict]:
    out = []
    for rotulo, cod, pre, pos, mostra_ref in SERIES:
        try:
            url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}"
                   f"/dados/ultimos/1?formato=json")
            d = json.loads(_get(url, 8))[0]
            out.append({"rotulo": rotulo, "valor": f"{pre}{d['valor']}{pos}",
                        "ref": d["data"] if mostra_ref else None})
        except Exception as e:
            log.warning("mercado_macro_falhou serie=%s erro=%s", cod, str(e)[:100])
    return out


def buscar_noticias(limite: int = 4) -> list[dict]:
    brutos, vistos = [], set()
    for i, expr in enumerate(FRENTES):
        try:
            q = urllib.parse.quote(f"({expr}) when:{JANELA_DIAS}d")
            url = (f"https://news.google.com/rss/search?q={q}"
                   f"&hl=pt-BR&gl=BR&ceid=BR:pt-419")
            xml = _get(url, 12).decode("utf-8", "ignore")
        except Exception as e:
            log.warning("mercado_feed_falhou frente=%s erro=%s", i + 1, str(e)[:100])
            continue
        for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
            g = lambda t: (re.search(rf"<{t}[^>]*>(.*?)</{t}>", it, re.S) or [None, ""])[1]
            link = g("link")
            if not link or link in vistos:
                continue
            if any(x in (g("source") + link).lower() for x in BLOQUEIO):
                continue
            try:
                dt = parsedate_to_datetime(g("pubDate"))
            except Exception:
                continue
            vistos.add(link)
            brutos.append({"dt": dt,
                           "titulo": re.sub(r"\s+-\s+[^-]+$", "", g("title")).strip(),
                           "veiculo": g("source"), "link": link})
    brutos.sort(key=lambda x: x["dt"], reverse=True)

    finais, lojas = [], 0
    for i in brutos:
        k = _toks(i["titulo"])
        if any(len(k & _toks(m["titulo"])) / max(len(k | _toks(m["titulo"])), 1) >= 0.45
               for m in finais):
            continue
        if _LOJA.search(i["titulo"]):
            if lojas >= 1:
                continue
            lojas += 1
        finais.append(i)
        if len(finais) >= limite:
            break

    agora = datetime.now(timezone.utc)
    for i in finais:
        h = int((agora - i["dt"]).total_seconds() // 3600)
        i["quando"] = f"há {h}h" if h < 48 else i["dt"].strftime("%d/%m")
        i.pop("dt")
    return finais


async def _atualizar(force: bool = False) -> None:
    global _atualizando
    if _atualizando:
        return
    _atualizando = True
    try:
        agora = time.time()
        if force or agora - _cache["macro_em"] > TTL_MACRO:
            m = await asyncio.to_thread(buscar_macro)
            if m:
                _cache["macro"], _cache["macro_em"] = m, agora
        if force or agora - _cache["noticias_em"] > TTL_NOTICIAS:
            n = await asyncio.to_thread(buscar_noticias)
            if n:
                _cache["noticias"], _cache["noticias_em"] = n, agora
    except Exception as e:
        log.warning("mercado_atualizar_falhou erro=%s", str(e)[:150])
    finally:
        _atualizando = False


async def payload() -> dict:
    """Devolve o cache imediatamente e agenda atualizacao se estiver velho."""
    agora = time.time()
    vazio = _cache["macro"] is None and _cache["noticias"] is None
    if vazio:
        async with _lock:
            if _cache["macro"] is None and _cache["noticias"] is None:
                await _atualizar(force=True)        # so a primeira vez bloqueia
    elif (agora - _cache["macro_em"] > TTL_MACRO
          or agora - _cache["noticias_em"] > TTL_NOTICIAS):
        asyncio.create_task(_atualizar())           # demais: atualiza por tras

    def fresco(chave, em):
        return _cache[chave] if _cache[chave] and agora - em <= IDADE_MAX else []

    return {
        "macro": fresco("macro", _cache["macro_em"]),
        "noticias": fresco("noticias", _cache["noticias_em"]),
        "atualizado_em": int(max(_cache["macro_em"], _cache["noticias_em"])) or None,
    }

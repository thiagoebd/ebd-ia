"""Resenha no grupo: manchetes recentes de um assunto (time, evento) para o
agente quebrar o gelo SEM inventar fato — o placar ou a posicao so entram se
estiverem na manchete. Mesma fonte do painel de mercado (Google News RSS).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

log = logging.getLogger("uvicorn.error")
UA = {"User-Agent": "Mozilla/5.0 (compatible; EBDia/1.0; +interno)"}
JANELA_DIAS = 4
LIMITE = 4

MANCHETES_TOOL = {
    "name": "manchetes_atuais",
    "description": (
        "Manchetes dos ultimos dias sobre um assunto (time de futebol, evento). "
        "SO para resenha/quebra-gelo no WhatsApp, nunca para analise de negocio. "
        "Use apenas o que as manchetes dizem — placar, posicao ou contratacao que "
        "nao estiver nelas NAO existe."),
    "input_schema": {
        "type": "object",
        "properties": {"assunto": {"type": "string", "description": "ex. 'Flamengo'"}},
        "required": ["assunto"],
    },
}
FERRAMENTAS = [MANCHETES_TOOL]
NOMES = {t["name"] for t in FERRAMENTAS}


def _baixa(url: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10).read()


def parse_rss(xml: str, agora: datetime | None = None, limite: int = LIMITE) -> list[dict]:
    agora = agora or datetime.now(timezone.utc)
    itens, vistos = [], set()
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        g = lambda t: (re.search(rf"<{t}[^>]*>(.*?)</{t}>", it, re.S) or [None, ""])[1]
        titulo = unescape(re.sub(r"\s+-\s+[^-]+$", "", g("title")).strip())
        if not titulo or titulo.lower() in vistos:
            continue
        try:
            dt = parsedate_to_datetime(g("pubDate"))
        except Exception:
            continue
        vistos.add(titulo.lower())
        itens.append((dt, titulo, unescape(g("source"))))
    itens.sort(key=lambda x: x[0], reverse=True)
    saida = []
    for dt, titulo, veiculo in itens[:limite]:
        h = int((agora - dt).total_seconds() // 3600)
        saida.append({"titulo": titulo, "veiculo": veiculo,
                      "quando": f"há {max(h, 0)}h" if h < 48 else dt.strftime("%d/%m")})
    return saida


async def executa(nome: str, entrada: dict) -> str:
    assunto = ((entrada or {}).get("assunto") or "").strip()[:80]
    if not assunto:
        return json.dumps({"manchetes": [], "aviso": "assunto vazio"}, ensure_ascii=False)
    q = urllib.parse.quote(f"{assunto} when:{JANELA_DIAS}d")
    url = f"https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    try:
        xml = (await asyncio.to_thread(_baixa, url)).decode("utf-8", "ignore")
        manchetes = parse_rss(xml)
    except Exception as e:
        log.warning("resenha: manchetes indisponiveis assunto=%s erro=%s", assunto, str(e)[:100])
        manchetes = []
    return json.dumps({"assunto": assunto, "manchetes": manchetes,
                       "aviso": None if manchetes else
                       "sem manchete agora — brinque sem citar fato atual"},
                      ensure_ascii=False)

#!/usr/bin/env python3
"""EBD.ia — Mineracao p/ resgate da familia equipe_campo/visitas (T160-T163).
Extrai do queries.jsonl os SQLs OK da familia (PCVISITAFV / PCUSUARI+FANTASIA /
checkin / RCA por filial), deduplicados, com latencia e frequencia — o insumo
para transcrever os templates. Output colavel no chat.
Uso: python3 mine_visitas.py [--log caminho] [--top 12]"""
import json, sys, os, re
from collections import defaultdict

def arg(f, d): return sys.argv[sys.argv.index(f)+1] if f in sys.argv else d
LOG = os.path.expanduser(arg("--log", "~/projects/ebd-ia/logs/mcp-oracle/queries.jsonl"))
TOP = int(arg("--top", "12"))
PADRAO = re.compile(r"PCVISITAFV|CHECKIN|PCUSUARI|TIPOVEND|CODUSUR.*FANTASIA|FANTASIA.*CODUSUR", re.I)

grupos = defaultdict(lambda: {"n": 0, "ok": 0, "err": 0, "ms": [], "sql": "", "full": ""})
for ln in open(LOG, encoding="utf-8"):
    ln = ln.strip()
    if not ln: continue
    try: r = json.loads(ln)
    except Exception: continue
    sql = r.get("sql_prefix") or ""
    if not PADRAO.search(sql): continue
    norm = re.sub(r"\s+", " ", sql).strip()
    chave = re.sub(r"\d{4}-\d{2}-\d{2}|\d{8}|'\d+'", "?", norm)[:80]
    g = grupos[chave]
    g["n"] += 1
    ev = r.get("event", "")
    if ev == "oracle_query_ok":
        g["ok"] += 1; g["ms"].append(float(r.get("elapsed_ms", 0) or 0))
        if len(norm) > len(g["full"]): g["full"] = norm
    elif "error" in ev or "timeout" in ev:
        g["err"] += 1
    g["sql"] = g["sql"] or norm

rank = sorted(grupos.values(), key=lambda g: (-g["ok"], -g["n"]))
print("=" * 100)
print(f" MINERACAO FAMILIA VISITAS/EQUIPE — {sum(g['n'] for g in rank)} queries em {len(rank)} padroes")
print(" (ok = candidato a template validado; err puro = padrao a NAO repetir)")
print("=" * 100)
for i, g in enumerate(rank[:TOP], 1):
    med = sorted(g["ms"])[len(g["ms"])//2] if g["ms"] else 0
    st = "CANDIDATO" if g["ok"] else "SO-ERRO  "
    print(f"\n[{i:02d}] {st} ok={g['ok']} err={g['err']} mediana={med:.0f}ms")
    print(f"     {(g['full'] or g['sql'])[:380]}")
print("\n" + "=" * 100)
print(" PROXIMO PASSO: cole este output no chat -> transcrevo T160-T163 + cicatrizes de coluna")
print("=" * 100)

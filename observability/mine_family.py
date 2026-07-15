#!/usr/bin/env python3
"""EBD.ia — minera uma familia de queries do queries.jsonl p/ virar template.
Separa CANDIDATO (rodou ok) de SO-ERRO (padrao a NAO repetir) e faz o
VEREDITO DE COLUNA: coluna que so aparece em erro = alucinacao.
Uso: python3 mine_family.py --re "PCPRODUT|CODAUXILIAR|CODEAN" [--cols "EAN,FUNCAO"] [--top 10]"""
import json, os, re, sys
from collections import defaultdict, Counter

def arg(f, d): return sys.argv[sys.argv.index(f)+1] if f in sys.argv else d
LOG  = os.path.expanduser(arg("--log", "~/projects/ebd-ia/logs/mcp-oracle/queries.jsonl"))
PAD  = re.compile(arg("--re", "PCPRODUT"), re.I)
TOP  = int(arg("--top", "10"))
COLS = [c.strip().upper() for c in arg("--cols", "").split(",") if c.strip()]

rows = []
for ln in open(LOG, encoding="utf-8"):
    ln = ln.strip()
    if not ln: continue
    try: r = json.loads(ln)
    except Exception: continue
    if PAD.search(r.get("sql_prefix") or ""): rows.append(r)

grupos = defaultdict(lambda: {"ok": 0, "err": 0, "ms": [], "full": "", "erro": ""})
for r in rows:
    norm = re.sub(r"\s+", " ", r.get("sql_prefix") or "").strip()
    chave = re.sub(r"\d{4}-\d{2}-\d{2}|\d{8}|'\d+'", "?", norm)[:80]
    g = grupos[chave]
    ev = r.get("event", "")
    if ev == "oracle_query_ok":
        g["ok"] += 1; g["ms"].append(float(r.get("elapsed_ms", 0) or 0))
        if len(norm) > len(g["full"]): g["full"] = norm
    elif "error" in ev or "timeout" in ev:
        g["err"] += 1
        g["erro"] = g["erro"] or str(r.get("error", ""))[:70]
        if not g["full"]: g["full"] = norm

print("=" * 100)
print(f" MINERACAO — {len(rows)} queries em {len(grupos)} padroes  (filtro: {PAD.pattern})")
print("=" * 100)
for i, (k, g) in enumerate(sorted(grupos.items(), key=lambda x: (-x[1]["ok"], -x[1]["err"]))[:TOP], 1):
    med = sorted(g["ms"])[len(g["ms"])//2] if g["ms"] else 0
    st = "CANDIDATO" if g["ok"] else "SO-ERRO  "
    print(f"\n[{i:02d}] {st} ok={g['ok']} err={g['err']} mediana={med:.0f}ms {('· ' + g['erro']) if g['erro'] else ''}")
    print(f"     {g['full'][:340]}")

if COLS:
    print("\n" + "=" * 100)
    print(" VEREDITO DE COLUNA  (ok=0 e erro>0  =>  COLUNA NAO EXISTE / alucinacao)")
    print("=" * 100)
    for c in COLS:
        ok = sum(1 for r in rows if c in (r.get("sql_prefix") or "").upper() and r.get("event") == "oracle_query_ok")
        er = sum(1 for r in rows if c in (r.get("sql_prefix") or "").upper() and "error" in r.get("event", ""))
        vd = "NAO EXISTE (alucinacao)" if (ok == 0 and er > 0) else ("EXISTE (validada em prod)" if ok else "sem evidencia")
        print(f"  {c:<16} ok={ok:<4} erro={er:<4} -> {vd}")
print("\n>>> cole este output no chat -> viram templates + cicatrizes")

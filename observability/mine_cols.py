#!/usr/bin/env python3
"""EBD.ia — veredito de coluna com PROVA do Oracle.
Fonte autoritativa de INEXISTENCIA: a msg ORA-00904 ("ALIAS"."COLUNA") + resolucao
alias->tabela pelo FROM/JOIN da propria query. Existencia: coluna qualificada por
alias da tabela-alvo em query OK. Descarta discovery (ALL_TAB_COLUMNS).
Uso: python3 mine_cols.py --tabela PCPRODUT [--log ...]"""
import json, os, re, sys
from collections import Counter, defaultdict

def arg(f, d): return sys.argv[sys.argv.index(f)+1] if f in sys.argv else d
LOG = os.path.expanduser(arg("--log", "~/projects/ebd-ia/logs/mcp-oracle/queries.jsonl"))
TAB = arg("--tabela", "PCPRODUT").upper()
DISC = re.compile(r"ALL_TAB_COLUMNS|USER_TAB_COLUMNS|ALL_VIEWS", re.I)
RE_ALIAS = re.compile(r"(?:FROM|JOIN)\s+(?:EBD\.)?([A-Z0-9_]+)\s+(?:AS\s+)?([A-Z][A-Z0-9_]*)?", re.I)
RE_904Q = re.compile(r'ORA-00904:\s*"([A-Z0-9_]+)"\."([A-Z0-9_]+)"', re.I)
RE_904U = re.compile(r'ORA-00904:\s*"([A-Z0-9_]+)"\s*:', re.I)

def aliases(sql):
    """alias -> tabela (e tabela -> tabela, p/ uso sem alias)"""
    m = {}
    for tab, al in RE_ALIAS.findall(sql or ""):
        tab = tab.upper()
        m[tab] = tab
        if al and al.upper() not in ("ON", "WHERE", "GROUP", "ORDER", "LEFT", "INNER", "JOIN", "SELECT", "AS"):
            m[al.upper()] = tab
    return m

nao_existe = Counter(); existe = Counter()
amostra = {}; unqual = Counter(); tabelas_da_query = Counter()
for ln in open(LOG, encoding="utf-8"):
    ln = ln.strip()
    if not ln: continue
    try: r = json.loads(ln)
    except Exception: continue
    sql = (r.get("sql_prefix") or "")
    if DISC.search(sql): continue
    al = aliases(sql)
    if TAB not in al.values(): continue
    ev = r.get("event", "")
    blob = str(r.get("error", "")) + " " + str(r.get("full_code", ""))
    if "error" in ev:
        achou = False
        for a, c in RE_904Q.findall(blob):
            t = al.get(a.upper())
            if t == TAB:
                nao_existe[c.upper()] += 1; amostra.setdefault(c.upper(), sql[:70]); achou = True
        if not achou:
            for c in RE_904U.findall(blob):
                unqual[c.upper()] += 1
    elif ev == "oracle_query_ok":
        alvo = [a for a, t in al.items() if t == TAB]
        for a in alvo:
            for c in re.findall(rf"\b{re.escape(a)}\.([A-Z][A-Z0-9_]*)", sql, re.I):
                existe[c.upper()] += 1

print("=" * 88)
print(f" VEREDITO DE COLUNA — tabela {TAB}  (fonte: msg ORA-00904 do Oracle + alias->tabela)")
print("=" * 88)
print(f"\n NAO EXISTEM em {TAB} (Oracle disse; alias resolvido):")
if nao_existe:
    for c, n in nao_existe.most_common():
        print(f"   {c:<18} {n}x  ·  {amostra[c][:60]}")
else: print("   (nenhuma)")
print(f"\n EXISTEM em {TAB} (usadas com alias da tabela em query OK):")
print("   " + (", ".join(f"{c}({n})" for c, n in existe.most_common(18)) or "(nenhuma)"))
if unqual:
    print(f"\n ORA-00904 sem qualificacao de alias (pode ser de qualquer tabela da query):")
    print("   " + ", ".join(f"{c}({n})" for c, n in unqual.most_common(8)))

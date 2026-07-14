#!/usr/bin/env python3
"""EBD.ia — Relatorio de Auto-Ajuste (colavel no chat do Claude).
Le queries.jsonl + llm_events.jsonl, compara com o periodo anterior e imprime
um snapshot compacto + acoes sugeridas. Salva copia em observability/reports/.
Uso: python3 obs_selfreport.py [--dias 7]"""
import json, sys, os, re, hashlib
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict

def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default

DIAS = int(arg("--dias", "7"))
BASE = os.path.expanduser(arg("--base", "~/projects/ebd-ia"))
QF = arg("--queries", f"{BASE}/logs/mcp-oracle/queries.jsonl")
LF = arg("--llm", f"{BASE}/logs/gateway/llm_events.jsonl")
AGORA = datetime.now(timezone.utc)
INI, INI_PREV = AGORA - timedelta(days=DIAS), AGORA - timedelta(days=2 * DIAS)

def carrega(path, campo_ts):
    out = []
    if not os.path.exists(path): return out
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln: continue
        try:
            r = json.loads(ln)
            r["_t"] = datetime.fromisoformat(r[campo_ts].replace("Z", "+00:00"))
            out.append(r)
        except Exception: pass
    return out

def norm_sql(s):
    return re.sub(r"\s+", " ", (s or ""))[:95]

def pct(a, b): return 100.0 * a / b if b else 0.0
def delta(cur, prev):
    if prev == 0: return " (novo)" if cur else ""
    d = 100.0 * (cur - prev) / prev
    return f" ({'+' if d >= 0 else ''}{d:.0f}% vs per. anterior)"

Q = carrega(QF, "timestamp"); L = carrega(LF, "ts")
qc = [r for r in Q if r["_t"] >= INI]; qp = [r for r in Q if INI_PREV <= r["_t"] < INI]
lc = [r for r in L if r["_t"] >= INI]; lp = [r for r in L if INI_PREV <= r["_t"] < INI]

def blob(r): return (str(r.get("event","")) + " " + str(r.get("error","")) + " " + str(r.get("sql_prefix","")))
def conta(rows):
    err = [r for r in rows if r.get("event") in ("oracle_query_error", "oracle_query_timeout")]
    cod = Counter()
    for r in err:
        m = re.search(r"(ORA-\d+|DPY-\d+|PLS-\d+)", blob(r))
        cod[m.group(1) if m else "sem-codigo"] += 1
    return err, cod

errc, codc = conta(qc); errp, _ = conta(qp)
tout_c = sum(1 for r in qc if r.get("event") == "oracle_query_timeout")
acl_c  = sum(1 for r in qc if r.get("event") == "acl_denied")
canon_c = sum(1 for r in qc if "VIEW_VENDAS_RESUMO_FATURAMENTO" in (r.get("sql_prefix") or ""))
bruto_c = sum(1 for r in qc if "GD_FATO_VENDAFATURAMENTO" in (r.get("sql_prefix") or ""))
canon_p = sum(1 for r in qp if "VIEW_VENDAS_RESUMO_FATURAMENTO" in (r.get("sql_prefix") or ""))
bruto_p = sum(1 for r in qp if "GD_FATO_VENDAFATURAMENTO" in (r.get("sql_prefix") or ""))
lentas = sorted([r for r in qc if r.get("event") == "oracle_query_ok" and float(r.get("elapsed_ms", 0)) > 20000],
                key=lambda r: -float(r["elapsed_ms"]))
p904 = Counter(norm_sql(r.get("sql_prefix")) for r in errc if "ORA-00904" in blob(r))

def soma(rows, k): return sum(float(r.get(k, 0) or 0) for r in rows)
custo_c, custo_p = soma(lc, "custo_brl"), soma(lp, "custo_brl")
cr, ci = soma(lc, "cache_read_tokens"), soma(lc, "input_tokens")
hit = pct(cr, cr + ci)
tools = sorted(float(r.get("tools_executadas", 0) or 0) for r in lc)
t_med = (sum(tools) / len(tools)) if tools else 0
t_p95 = tools[int(0.95 * (len(tools) - 1))] if tools else 0
por_canal = defaultdict(lambda: [0, 0.0])
for r in lc:
    por_canal[r.get("canal", "?")][0] += 1; por_canal[r.get("canal", "?")][1] += float(r.get("custo_brl", 0) or 0)
por_modelo = Counter(r.get("model", "?") for r in lc)
caros = sorted(lc, key=lambda r: -float(r.get("custo_brl", 0) or 0))[:4]
retrab = [r for r in lc if float(r.get("tools_executadas", 0) or 0) > 5][:4]

W = []
def w(s=""): W.append(s)
H = "=" * 78
w(H); w(f" EBD.ia — RELATORIO DE AUTO-AJUSTE  v1 · gerado {AGORA.strftime('%d/%m/%Y %H:%M UTC')}")
w(f" janela: ultimos {DIAS} dias (comparado com os {DIAS} anteriores)"); w(H)
w(f"[1] SAUDE ORACLE  queries={len(qc)}{delta(len(qc), len(qp))}")
w(f"    erros={len(errc)} ({pct(len(errc), len(qc)):.1f}%){delta(len(errc), len(errp))} · timeouts={tout_c} · acl_negado={acl_c}")
w(f"    codigos: " + (", ".join(f"{c}={n}" for c, n in codc.most_common(6)) or "nenhum"))
w()
w(f"[2] ALUCINACAO DE SCHEMA (ORA-00904) — padroes distintos p/ virar template/cicatriz:")
if p904:
    for s, n in p904.most_common(6): w(f"    {n}x  {s}")
else: w("    nenhum no periodo ✓")
w()
adoc = pct(canon_c, canon_c + bruto_c); adop = pct(canon_p, canon_p + bruto_p)
w(f"[3] ANTI-CANONICO  adocao canonica (proxy) = {adoc:.1f}%  (anterior: {adop:.1f}%)  alvo>=70% p/ Fase B")
w(f"    queries lentas >20s: {len(lentas)} — top padroes:")
vist = set()
for r in lentas:
    s = norm_sql(r.get("sql_prefix"))
    if s[:50] in vist: continue
    vist.add(s[:50]); w(f"    {float(r['elapsed_ms'])/1000:6.1f}s  {s}")
    if len(vist) >= 5: break
if not lentas: w("    nenhuma ✓")
w()
w(f"[4] LLM  turns={len(lc)}{delta(len(lc), len(lp))} · custo=R$ {custo_c:.2f}{delta(custo_c, custo_p)} · medio=R$ {(custo_c/len(lc) if lc else 0):.3f}/turn")
w(f"    cache_hit={hit:.1f}% (alvo>=80) · tools/turn media={t_med:.1f} · 95% dos turns usam <= {t_p95:.0f} tools")
w(f"    canais: " + " · ".join(f"{c}: {v[0]} turns / R$ {v[1]:.2f}" for c, v in sorted(por_canal.items())))
w(f"    modelos: " + " · ".join(f"{m}={n}" for m, n in por_modelo.most_common(5)))
w(f"    turns mais caros:")
for r in caros: w(f"      R$ {float(r.get('custo_brl',0)):.3f} · {r.get('canal')}/{r.get('model')} · cw={int(float(r.get('cache_creation_tokens',0) or 0))} · {str(r.get('pergunta',''))[:60]}")
if retrab:
    w(f"    retrabalho (>5 tools):")
    for r in retrab: w(f"      {int(float(r.get('tools_executadas',0)))} tools · R$ {float(r.get('custo_brl',0)):.3f} · {str(r.get('pergunta',''))[:60]}")
w()
w("[5] ACOES SUGERIDAS (regras do mapa sinal->acao):")
ac = []
if p904: ac.append(f"- {sum(p904.values())} ORA-00904 em {len(p904)} padroes -> criar/consertar templates (secao 2)")
if adoc < 70 and (canon_c + bruto_c) > 5: ac.append(f"- adocao canonica {adoc:.0f}% < 70% -> Fase B segue bloqueada; revisar prompts da secao 3")
if hit < 80 and lc: ac.append(f"- cache hit {hit:.0f}% < 80% -> revisar prompt caching (prefixo/TTL)")
if t_p95 > 5: ac.append(f"- p95 de {t_p95:.0f} tools/turn -> discovery queimando iteracoes; ampliar catalogo get_template")
if tout_c: ac.append(f"- {tout_c} timeouts -> padrao anti-canonico ativo (secao 3)")
if not ac: ac.append("- nenhum gatilho disparado ✓ manter observacao")
for a in ac: w(a)
w(); w(H)
w(" PROXIMO PASSO: cole este relatorio no chat do EBD.ia (Claude) com a frase:")
w("   'analisa o relatorio de observabilidade'  -> patches de ajuste serao gerados")
w(H)

texto = "\n".join(W)
print(texto)
try:
    rep_dir = os.path.join(BASE, "observability", "reports")
    os.makedirs(rep_dir, exist_ok=True)
    fp = os.path.join(rep_dir, f"autoajuste_{AGORA.strftime('%Y%m%d')}.txt")
    open(fp, "w", encoding="utf-8").write(texto + "\n")
    print(f"\n[copia salva em {fp}]")
except Exception as e:
    print(f"\n[aviso: nao salvou copia: {e}]")

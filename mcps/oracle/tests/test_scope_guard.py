"""Testes do scope_guard. Roda offline, sem Oracle e sem Postgres."""
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "app")

from app.scope_guard import ScopeDenied, aplicar_escopo, montar_catalogo

COLUNAS = [
    ("PCPEDC", "CODFILIAL"), ("PCUSUARI", "CODFILIAL"), ("PCFALTA", "CODFILIAL"),
    ("PCMETA", "CODFILIAL"), ("PCPRODFILIAL", "CODFILIAL"),
    ("PCCLIENT", "CODFILIALNF"),
    ("VIEW_VENDAS_RESUMO_FATURAMENTO", "CODFILIAL"),
    ("VIEW_DEVOL_RESUMO_FATURAMENTO", "CODFILIAL"),
    ("GD_FATO_VENDAFATURAMENTO", "CODIGOFILIAL"),
    ("GD_DIM_CLIENTE", "CODIGOFILIAL"),
]
TABELAS = [t for t, _ in COLUNAS] + [
    "PCFILIAL", "PCFORNEC", "PCPRODUT", "PCDEPTO", "GD_DIM_RCA", "PCROTACLI",
]
CAT = montar_catalogo(COLUNAS, TABELAS)
RJ1 = ["10", "13", "17"]

_ok = _fail = 0


def check(nome, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  PASSOU  {nome}")
    else:
        _fail += 1
        print(f"  FALHOU  {nome}  {extra}")


def nega(nome, sql, motivo_esperado, allowed=RJ1):
    try:
        aplicar_escopo(sql, allowed, CAT)
        check(nome, False, "-> nao recusou")
    except ScopeDenied as e:
        check(nome, e.motivo == motivo_esperado, f"-> motivo={e.motivo}")


print("\n== catalogo ==")
check("PCFILIAL usa CODIGO (override)", CAT.coluna("PCFILIAL") == "CODIGO")
check("DW usa CODIGOFILIAL", CAT.coluna("GD_FATO_VENDAFATURAMENTO") == "CODIGOFILIAL")
check("PCFORNEC sem coluna de filial", CAT.coluna("PCFORNEC") is None)
check("PCFORNEC e conhecida", CAT.conhece("PCFORNEC"))
check("tabela inventada nao e conhecida", not CAT.conhece("PCXYZ_INEXISTENTE"))
c2 = montar_catalogo([("T", "CODFILIALNF"), ("T", "CODFILIAL")], ["T"])
check("preferencia CODFILIAL > CODFILIALNF", c2.coluna("T") == "CODFILIAL")

print("\n== escopo total (todos os usuarios de hoje) ==")
sql_br = "SELECT SUM(VLATEND) FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO"
out, info = aplicar_escopo(sql_br, "*", CAT)
check("usuario '*' -> SQL byte-identico", out == sql_br and not info["aplicado"])
out, info = aplicar_escopo(sql_br, None, CAT)
check("allowed None -> SQL byte-identico", out == sql_br)

print("\n== injecao ==")
out, info = aplicar_escopo(sql_br, RJ1, CAT)
check("1 tabela -> 1 predicado", info["predicados"] == 1)
check("predicado tem as 3 filiais", "'10'" in out and "'13'" in out and "'17'" in out)

sql_join = ("SELECT p.NUMPED, c.CLIENTE FROM EBD.PCPEDC p "
            "JOIN EBD.PCCLIENT c ON c.CODCLI = p.CODCLI WHERE p.DATA >= TRUNC(SYSDATE)")
out, info = aplicar_escopo(sql_join, RJ1, CAT)
check("join -> 2 predicados", info["predicados"] == 2)
check("usa alias correto p.", "p.CODFILIAL" in out)
check("usa coluna correta da PCCLIENT", "c.CODFILIALNF" in out)

sql_cte = ("WITH a AS (SELECT CODFILIAL, SUM(VLATEND) v FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO "
           "GROUP BY CODFILIAL), b AS (SELECT CODFILIAL, SUM(VLDEVOLUCAO) d "
           "FROM EBD.VIEW_DEVOL_RESUMO_FATURAMENTO GROUP BY CODFILIAL) "
           "SELECT a.CODFILIAL, a.v - NVL(b.d,0) FROM a LEFT JOIN b ON b.CODFILIAL = a.CODFILIAL")
out, info = aplicar_escopo(sql_cte, RJ1, CAT)
check("CTE -> predicado dentro de cada CTE", info["predicados"] == 2)

sql_sub = ("SELECT c.CODCLI, (SELECT COUNT(*) FROM EBD.PCPEDC p WHERE p.CODCLI = c.CODCLI) "
           "FROM EBD.PCCLIENT c")
out, info = aplicar_escopo(sql_sub, RJ1, CAT)
check("subquery correlacionada tambem filtra", info["predicados"] == 2)

print("\n== dado global ==")
out, info = aplicar_escopo("SELECT COUNT(*) FROM EBD.PCFORNEC WHERE FORNECEDOR LIKE '%KIBON%'", RJ1, CAT)
check("tabela sem filial -> 0 predicados, passa", info["predicados"] == 0)

print("\n== recusas (falha fechada) ==")
nega("tabela desconhecida", "SELECT * FROM EBD.PCXYZ_INEXISTENTE", "tabela_desconhecida")
nega("escopo vazio", sql_br, "escopo_vazio", allowed=[])
nega("filial unica fora do escopo",
     "SELECT SUM(VLATEND) FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO WHERE CODFILIAL = '02'",
     "filial_fora_do_escopo")
nega("lista toda fora do escopo",
     "SELECT SUM(VLATEND) FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO WHERE CODFILIAL IN ('02','05')",
     "filial_fora_do_escopo")
nega("SQL invalido", "ISTO NAO E SQL", "sql_nao_parseavel")

print("\n== nao recusa quando ha intersecao (o agente dizendo 'Brasil') ==")
sql_br_lista = ("SELECT CODFILIAL, SUM(VLATEND) FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO "
                "WHERE CODFILIAL IN ('01','02','10','13') GROUP BY CODFILIAL")
try:
    out, info = aplicar_escopo(sql_br_lista, RJ1, CAT)
    check("lista ampla -> estreita em vez de recusar", info["predicados"] == 1)
except ScopeDenied as e:
    check("lista ampla -> estreita em vez de recusar", False, f"recusou: {e.motivo}")

print("\n== filial dentro do escopo passa ==")
try:
    out, info = aplicar_escopo(
        "SELECT SUM(VLATEND) FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO WHERE CODFILIAL = '10'",
        RJ1, CAT)
    check("pedir filial propria funciona", info["predicados"] == 1)
except ScopeDenied as e:
    check("pedir filial propria funciona", False, f"recusou: {e.motivo}")

print(f"\n{'='*50}\nPASSOU: {_ok}   FALHOU: {_fail}\n{'='*50}")
sys.exit(1 if _fail else 0)

"""Sanidade do KB — roda sem Oracle.

Pega o que estraga em silencio: cerca ``` desbalanceada (o get_template para de
enxergar o SQL), template duplicado por `cat >>` rodado duas vezes, SQL que nao
parseia, e cicatriz com numero repetido.

O que EXIGE banco (tempo de execucao, dado real) fica no test_tlog2.py, que
roda dentro do container.
"""
import re
from pathlib import Path

import pytest
import sqlglot

DOCS = Path(__file__).resolve().parents[1] / "docs"
KB = (DOCS / "query_templates.md").read_text(encoding="utf-8")
SC = (DOCS / "sql-corrections.md").read_text(encoding="utf-8")
KN = (DOCS / "knowledge.md").read_text(encoding="utf-8")

BINDS = {":codFilial": "'18'", ":dias": "30", ":listaFiliais": "'18','05'",
         ":codProd": "1", ":codRca": "1", ":codCli": "1"}


def _blocos_sql(texto):
    return re.findall(r"```sql\n(.*?)```", texto, re.S)


def test_cercas_balanceadas():
    assert KB.count("```") % 2 == 0, "cerca ``` aberta — get_template fica cego"


def test_templates_sem_duplicata():
    ids = re.findall(r"^## (T-[A-Z]+\d\d) ", KB, re.M)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert not dup, f"template duplicado (append rodou 2x?): {dup}"


def test_cicatrizes_sem_duplicata():
    nums = re.findall(r"^## #(\d+) ", SC, re.M)
    dup = sorted({n for n in nums if nums.count(n) > 1})
    assert not dup, f"cicatriz com numero repetido: {dup}"


def test_secoes_do_knowledge_unicas():
    secs = re.findall(r"^## (\d+)\. ", KN, re.M)
    dup = sorted({s for s in secs if secs.count(s) > 1})
    assert not dup, f"secao duplicada no knowledge.md: {dup}"


def test_todo_template_tem_sql():
    for tid in set(re.findall(r"^## (T-[A-Z]+\d\d) ", KB, re.M)) - SEM_SQL:
        corpo = re.search(rf"^## {tid} .*?\n(.*?)(?=^## |\Z)", KB, re.M | re.S)
        assert corpo and "```sql" in corpo.group(1), f"{tid} sem bloco sql"


def _template_sql():
    """O SQL canonico de cada template = PRIMEIRO bloco sql sob o titulo.

    Blocos seguintes sao ilustracao (errado x certo, WHERE isolado, trecho
    comentado) e nao precisam compilar sozinhos.
    """
    fora = []
    for tid in re.findall(r"^## (T-[A-Z]+\d\d) ", KB, re.M):
        corpo = re.search(rf"^## {tid} .*?\n(.*?)(?=^## |\Z)", KB, re.M | re.S).group(1)
        blocos = _blocos_sql(corpo)
        if blocos:
            fora.append((tid, blocos[0]))
    return fora


@pytest.mark.parametrize("tid,sql", _template_sql())
def test_sql_do_template_parseia(tid, sql):
    q = sql
    for k, v in BINDS.items():
        q = q.replace(k, v)
    try:
        sqlglot.parse_one(q, read="oracle")
    except Exception as e:
        pytest.fail(f"{tid} nao parseia em Oracle: {str(e)[:160]}")


# Templates que sao PADRAO DE CONTEUDO, nao consulta: definem o que a resposta
# deve trazer e deixam o modelo montar a query. Nao tem bloco SQL de proposito.
SEM_SQL = {"T-PAINEL01"}


def test_todos_os_templates_cobertos():
    """Se um template ficar sem SQL, o parametrize acima o ignora em silencio."""
    titulos = set(re.findall(r"^## (T-[A-Z]+\d\d) ", KB, re.M)) - SEM_SQL
    cobertos = {t for t, _ in _template_sql()}
    assert titulos == cobertos, f"template sem SQL: {sorted(titulos - cobertos)}"


def test_tlog_filtra_filial_e_data():
    """PCMOVENDPEND tem 97 mi de linhas; sem CODFILIAL+DATA estoura o timeout
    de 85s do gateway (cicatriz #62)."""
    faltando = []
    for tid in re.findall(r"^## (T-LOG\d\d) ", KB, re.M):
        corpo = re.search(rf"^## {tid} .*?\n(.*?)(?=^## |\Z)", KB, re.M | re.S).group(1)
        sqls = _blocos_sql(corpo)
        if not sqls:
            continue
        s = sqls[0].upper()
        if "PCMOVENDPEND" in s and "CODFILIAL" not in s:
            faltando.append(tid)
    assert not faltando, f"varre PCMOVENDPEND sem filtrar filial: {faltando}"


def test_nao_usa_views_gd():
    """GD_* e legado GoodData: serve de de-para, nunca de fonte."""
    ruins = []
    for tid in re.findall(r"^## (T-[A-Z]+\d\d) ", KB, re.M):
        corpo = re.search(rf"^## {tid} .*?\n(.*?)(?=^## |\Z)", KB, re.M | re.S).group(1)
        for s in _blocos_sql(corpo):
            if re.search(r"\bFROM\s+(EBD\.)?GD_", s, re.I):
                ruins.append(tid)
    assert not ruins, f"template consultando view GD_*: {ruins}"


def test_nao_usa_tabela_fotografia():
    """Tabelas terminadas em 6 digitos de data sao copias congeladas de 2018
    (cicatriz #58)."""
    ruins = [s[:80] for s in _blocos_sql(KB)
             if re.search(r"\bPC[A-Z]+\d{6}\b", s)]
    assert not ruins, f"template usando tabela-fotografia: {ruins}"

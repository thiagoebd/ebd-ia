"""scope_guard.py — enforcement de escopo de filial por reescrita de SQL.

Etapa 1: modulo ISOLADO. Nada no server.py importa isto ainda.

Principio: o agente escreve o SQL que quiser (template ou livre) e este modulo
injeta o filtro de filial em cada tabela escopavel, no escopo sintatico correto,
de forma deterministica — sem consultar o LLM.

Falha FECHADA: qualquer duvida vira recusa, nunca liberacao.
"""
from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp

log = logging.getLogger(__name__)

PREFERENCIA = ("CODFILIAL", "CODIGOFILIAL", "CODFILIALNF", "FILIAL")

# "FILIAL" so vale como escopo quando e CODIGO (VARCHAR2(2)); em algumas
# tabelas ela e NOME ("EBD MATRIZ", VARCHAR2(25/40)) e nao serve de filtro.
MAX_LEN_CODIGO = 3

# Tabelas cuja coluna de filial NAO segue o padrao. PCFILIAL e a lista de
# filiais e sua chave e CODIGO — sem isto, um gerente regional lista as 24.
OVERRIDES: dict[str, str] = {
    "PCFILIAL": "CODIGO",
}

IGNORAR = {"DUAL"}


class ScopeDenied(Exception):
    """Recusa por escopo. `motivo` e estavel p/ log; `detalhe` e p/ humano."""

    def __init__(self, motivo: str, detalhe: str = ""):
        self.motivo = motivo
        self.detalhe = detalhe
        super().__init__(f"{motivo}: {detalhe}" if detalhe else motivo)


class Catalogo:
    """Sabe DUAS coisas: quais tabelas tem coluna de filial, e quais existem.

    A segunda e o que fecha a falha: tabela desconhecida vira recusa em vez de
    passar sem filtro.
    """

    def __init__(self, com_filial: dict[str, str], conhecidas: set[str],
                 ambiguas: set[str] | None = None):
        self.com_filial = {k.upper(): v.upper() for k, v in com_filial.items()}
        self.conhecidas = {t.upper() for t in conhecidas} | set(self.com_filial)
        self.ambiguas = {t.upper() for t in (ambiguas or ())} - set(self.com_filial)

    def coluna(self, tabela: str) -> str | None:
        return self.com_filial.get(tabela.upper())

    def conhece(self, tabela: str) -> bool:
        return tabela.upper() in self.conhecidas

    def ambigua(self, tabela: str) -> bool:
        return tabela.upper() in self.ambiguas

    def resumo(self) -> dict:
        return {"tabelas": len(self.conhecidas), "com_filial": len(self.com_filial),
                "ambiguas": len(self.ambiguas)}


def montar_catalogo(linhas_colunas, linhas_tabelas, linhas_ambiguas=()) -> Catalogo:
    """linhas_colunas: [(TABELA, COLUNA)]; linhas_tabelas: [(TABELA,)] ou [TABELA]."""
    por_tabela: dict[str, str] = {}
    for linha in linhas_colunas:
        t, c = str(linha[0]).upper(), str(linha[1]).upper()
        if c not in PREFERENCIA:
            continue
        atual = por_tabela.get(t)
        if atual is None or PREFERENCIA.index(c) < PREFERENCIA.index(atual):
            por_tabela[t] = c
    por_tabela.update(OVERRIDES)
    conhecidas = set()
    for linha in linhas_tabelas:
        nome = linha[0] if isinstance(linha, (tuple, list)) else linha
        conhecidas.add(str(nome).upper())
    ambiguas = set()
    for linha in linhas_ambiguas:
        nome = linha[0] if isinstance(linha, (tuple, list)) else linha
        ambiguas.add(str(nome).upper())
    return Catalogo(por_tabela, conhecidas, ambiguas)


def carregar_do_oracle(pool, owner: str = "EBD") -> Catalogo:
    """Duas queries no startup (~5s). Custo zero por requisicao depois.

    Medido no ambiente real: GROUP BY sobre ALL_TAB_COLS = 54,6s e NOT EXISTS
    correlacionado = 74s. Prefixo indexavel + decisao em Python = 3,3s.
    """
    conn = pool.acquire()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, DATA_LENGTH "
                "FROM ALL_TAB_COLS WHERE OWNER = :o AND ("
                "  COLUMN_NAME LIKE 'CODFILIAL%' OR COLUMN_NAME LIKE 'FILIAL%' "
                "  OR COLUMN_NAME = 'CODIGOFILIAL')",
                o=owner,
            )
            brutas = cur.fetchall()
            cur.execute(
                "SELECT TABLE_NAME FROM ALL_TABLES WHERE OWNER = :o "
                "UNION ALL SELECT VIEW_NAME FROM ALL_VIEWS WHERE OWNER = :o",
                o=owner,
            )
            tabelas = cur.fetchall()
    finally:
        pool.release(conn)

    colunas = []
    tocadas = set()
    for tab, col, dtype, dlen in brutas:
        tab, col = str(tab).upper(), str(col).upper()
        tocadas.add(tab)
        if col in ("CODFILIAL", "CODIGOFILIAL", "CODFILIALNF"):
            colunas.append((tab, col))
        elif col == "FILIAL" and str(dtype).startswith("VARCHAR") and (dlen or 99) <= MAX_LEN_CODIGO:
            # FILIAL so vale como escopo quando e codigo curto; em algumas
            # tabelas ela e nome ("EBD MATRIZ") e nao serve de filtro.
            colunas.append((tab, col))

    cat = montar_catalogo(colunas, tabelas, tocadas)
    log.info("scope_guard catalogo carregado: %s", cat.resumo())
    return cat


def _tabelas_diretas(select: exp.Select) -> list[exp.Table]:
    """So as tabelas do FROM/JOIN DESTE select. Subqueries sao tratadas no
    proprio select delas (find_all(exp.Select) passa por todas)."""
    out: list[exp.Table] = []
    frm = select.args.get("from_") or select.args.get("from")
    if frm is not None and isinstance(frm.this, exp.Table):
        out.append(frm.this)
    for j in select.args.get("joins") or []:
        if isinstance(j.this, exp.Table):
            out.append(j.this)
    return out


def _pedido_incompativel(tree, permitidas: list[str], colunas: set[str]) -> list[str]:
    """Recusa APENAS quando o pedido explicito e totalmente fora do escopo.

    Distincao que importa: `CODFILIAL IN ('01'..'16')` e o agente dizendo
    "Brasil inteiro" — tem intersecao com o escopo, entao o AND injetado
    estreita sozinho e nao ha nada a recusar. Ja `CODFILIAL = '02'` para um
    gerente de RJ1 nao tem intersecao nenhuma: ai sim recusa, senao ele
    receberia zero linhas e concluiria que a filial nao vendeu nada.

    Bind variable (:codFilial) nao e literal — nao dispara aqui; nesse caso o
    predicado injetado faz a intersecao, o que e seguro.
    """
    permitido = set(permitidas)
    incompativel: set[str] = set()
    for node in list(tree.find_all(exp.EQ)) + list(tree.find_all(exp.In)):
        alvo = node.this
        if not isinstance(alvo, exp.Column) or alvo.name.upper() not in colunas:
            continue
        if isinstance(node, exp.EQ):
            lits = [node.expression]
        else:
            lits = list(node.expressions or [])
        pedidas = {
            str(l.this).strip().zfill(2)
            for l in lits
            if isinstance(l, exp.Literal) and l.is_string
        }
        if pedidas and not (pedidas & permitido):
            incompativel |= pedidas
    return sorted(incompativel)


def escopo_total(allowed) -> bool:
    if allowed is None or allowed == "*":
        return True
    if isinstance(allowed, (list, tuple, set)) and "*" in allowed:
        return True
    return False


def aplicar_escopo(sql: str, allowed, catalogo: Catalogo, dialeto: str = "oracle"):
    """Retorna (sql_final, info). Levanta ScopeDenied em qualquer duvida.

    allowed == "*" (ou None) -> devolve o SQL INTOCADO, custo ~0.
    """
    if escopo_total(allowed):
        return sql, {"aplicado": False, "motivo": "escopo_total"}

    permitidas = sorted({str(f).strip().zfill(2) for f in (allowed or [])})
    if not permitidas:
        raise ScopeDenied("escopo_vazio")

    try:
        tree = sqlglot.parse_one(sql, read=dialeto)
    except Exception as e:
        raise ScopeDenied("sql_nao_parseavel", str(e)[:120])

    ctes = {c.alias_or_name.upper() for c in tree.find_all(exp.CTE)}

    colunas_filial = set(catalogo.com_filial.values()) | set(PREFERENCIA)
    incompativel = _pedido_incompativel(tree, permitidas, colunas_filial)
    if incompativel:
        raise ScopeDenied("filial_fora_do_escopo", ", ".join(incompativel))

    reais: list[tuple[exp.Table, str]] = []
    for t in tree.find_all(exp.Table):
        nome = t.name.upper()
        if nome in ctes or nome in IGNORAR:
            continue
        reais.append((t, nome))

    for t, nome in reais:
        if not catalogo.conhece(nome):
            raise ScopeDenied("tabela_desconhecida", nome)


    precisam = {id(t) for t, nome in reais if catalogo.coluna(nome)}

    alvo = [exp.Literal.string(f) for f in permitidas]
    marcadas: set[int] = set()
    for select in tree.find_all(exp.Select):
        for t in _tabelas_diretas(select):
            nome = t.name.upper()
            if nome in ctes or nome in IGNORAR:
                continue
            col = catalogo.coluna(nome)
            if not col:
                continue
            select.where(exp.column(col, t.alias_or_name).isin(*alvo), copy=False)
            marcadas.add(id(t))

    ambiguas_tocadas = sorted({nome for _t, nome in reais if catalogo.ambigua(nome)})

    faltando = precisam - marcadas
    if faltando:
        nomes = sorted({nome for t, nome in reais if id(t) in faltando})
        raise ScopeDenied("tabela_sem_filtro", ", ".join(nomes))

    final = tree.sql(dialect=dialeto)

    try:
        sqlglot.parse_one(final, read=dialeto)
    except Exception as e:
        raise ScopeDenied("sql_regenerado_invalido", str(e)[:120])

    return final, {
        "aplicado": True,
        "predicados": len(marcadas),
        "filiais": permitidas,
        # Tabelas com coluna de filial NAO reconhecida (ex: CODFILIALRETIRA).
        # AVISO, nao recusa: o modo sombra vai dizer se alguma importa de fato.
        "ambiguas": ambiguas_tocadas,
    }

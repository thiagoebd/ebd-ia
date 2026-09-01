"""Pre-voo de colunas: recusa SQL com coluna inexistente ANTES do Oracle.

Motivo (medido em 27/07/2026): 74% dos erros do agente sao ORA-00904. Devolver
a lista de colunas certas junto com o erro nao resolveu — o log mostra o agente
recebendo os nomes corretos e mesmo assim so REMOVENDO a coluna citada e
tentando de novo, uma por vez, ate estourar o orcamento de 3 tentativas.

Aqui a validacao acontece antes: nao gasta ida ao banco, e a recusa lista TODAS
as colunas invalidas de uma vez em vez de uma por rodada.

PRINCIPIO: falso negativo e barato (o Oracle pega depois), falso positivo e
caro (recusa query boa). Na duvida, NAO valida.
"""
from __future__ import annotations

import difflib
import re
from typing import Iterable

try:
    import sqlglot
    from sqlglot import exp
    _SQLGLOT = True
except Exception:  # pragma: no cover
    _SQLGLOT = False

# pseudo-colunas e fontes que nunca estao no ALL_TAB_COLUMNS
_IGNORAR_TABELA = {"DUAL"}
_PSEUDO_COLUNAS = {"ROWNUM", "ROWID", "LEVEL", "SYSDATE", "SYSTIMESTAMP",
                   "USER", "NEXTVAL", "CURRVAL", "COUNT", "NULL"}


def tabelas_fisicas(sql: str) -> list[str]:
    """Tabelas reais citadas no SQL (exclui CTE e DUAL)."""
    if not _SQLGLOT:
        return []
    try:
        arv = sqlglot.parse_one(sql, read="oracle")
    except Exception:
        return []
    ctes = {c.alias_or_name.upper() for c in arv.find_all(exp.CTE)}
    nomes: list[str] = []
    for t in arv.find_all(exp.Table):
        n = (t.name or "").upper()
        if not n or n in ctes or n in _IGNORAR_TABELA or n in nomes:
            continue
        nomes.append(n)
    return nomes


def _mapa_alias(arv, ctes: set[str]) -> dict[str, str]:
    """alias -> TABELA FISICA. Alias de CTE/subquery fica de fora.

    AMBIGUIDADE: o mesmo apelido pode designar tabelas diferentes em escopos
    diferentes (duas CTEs usando `v`). Como este resolvedor e plano, apelido
    ambiguo e DESCARTADO — validar contra a tabela errada recusa query boa,
    que e o pior erro possivel aqui.
    """
    mapa: dict[str, str] = {}
    ambiguos: set[str] = set()
    for t in arv.find_all(exp.Table):
        nome = (t.name or "").upper()
        if not nome or nome in ctes or nome in _IGNORAR_TABELA:
            continue
        for chave in filter(None, (nome, (t.alias or "").upper())):
            anterior = mapa.get(chave)
            if anterior and anterior != nome:
                ambiguos.add(chave)
            mapa[chave] = nome
    for a in ambiguos:
        mapa.pop(a, None)
    return mapa


def _nomes_definidos(arv) -> set[str]:
    """Apelidos criados pela propria query (SELECT ... AS X, CTE, subquery).

    Sem isto, `SELECT SUM(A) AS TOTAL ... ORDER BY TOTAL` seria recusado.
    """
    definidos: set[str] = set()
    for a in arv.find_all(exp.Alias):
        if a.alias:
            definidos.add(a.alias.upper())
    for c in arv.find_all(exp.CTE):
        definidos.add(c.alias_or_name.upper())
        for coluna in (c.args.get("alias").columns if c.args.get("alias") else []):
            definidos.add(str(coluna).upper())
    for s in arv.find_all(exp.Subquery):
        if s.alias:
            definidos.add(s.alias.upper())
    return definidos


def _em_contexto_apelido(col) -> bool:
    """True se a coluna esta em ORDER BY / GROUP BY / HAVING.

    So nesses contextos o Oracle aceita apelido do SELECT. No SELECT e no
    WHERE, o nome e sempre coluna de tabela — foi por confundir isso que
    `ROUND(VLTOTCOM,2) AS VLTOTCOM` escapou da validacao.
    """
    no = col.parent
    while no is not None:
        if isinstance(no, (exp.Order, exp.Group, exp.Having)):
            return True
        if isinstance(no, exp.Select):
            return False
        no = no.parent
    return False


def colunas_invalidas(sql: str, dicionario: dict[str, Iterable[str]]
                      ) -> list[tuple[str, str]]:
    """Retorna [(TABELA, COLUNA)] das colunas que NAO existem.

    `dicionario` = {TABELA: colunas}. Tabela ausente do dicionario e ignorada
    (nao da para afirmar nada sobre ela).

    UNION: cada ramo e validado SEPARADAMENTE. Um `SELECT a FROM T1 UNION
    SELECT a FROM T2` tem 2 tabelas no total, o que impedia validar coluna
    sem qualificacao — mas cada ramo tem uma tabela so.
    """
    if not _SQLGLOT or not dicionario:
        return []
    try:
        arv = sqlglot.parse_one(sql, read="oracle")
    except Exception:
        return []

    # quebra o UNION em ramos e valida um por um
    if isinstance(arv, exp.Union):
        ruins_union: list[tuple[str, str]] = []
        vistos_u: set[tuple[str, str]] = set()
        for ramo in arv.flatten() if hasattr(arv, "flatten") else []:
            for t, c in colunas_invalidas(ramo.sql(dialect="oracle"),
                                          dicionario):
                if (t, c) not in vistos_u:
                    vistos_u.add((t, c))
                    ruins_union.append((t, c))
        return ruins_union

    dic = {t.upper(): {c.upper() for c in cols} for t, cols in dicionario.items()}
    ctes = {c.alias_or_name.upper() for c in arv.find_all(exp.CTE)}
    alias = _mapa_alias(arv, ctes)
    definidos = _nomes_definidos(arv)

    fisicas = [t for t in set(alias.values()) if t in dic]
    # so vale validar coluna sem qualificacao quando ha UMA tabela fisica e
    # nenhuma fonte derivada — senao nao da pra saber de quem e a coluna
    tem_derivada = bool(ctes) or any(True for _ in arv.find_all(exp.Subquery))
    unica = fisicas[0] if (len(fisicas) == 1 and not tem_derivada) else None

    ruins: list[tuple[str, str]] = []
    vistos: set[tuple[str, str]] = set()
    # por tabela: quantas colunas referenciadas EXISTEM. Se nenhuma existir,
    # o suspeito e o dicionario (incompleto/desatualizado), nao o SQL —
    # nesse caso e mais seguro deixar o Oracle decidir.
    validas_por_tab: dict[str, int] = {}

    for col in arv.find_all(exp.Column):
        nome = (col.name or "").upper()
        if not nome or nome in _PSEUDO_COLUNAS:
            continue
        qualificador = (col.table or "").upper()

        # FURO DO ALIAS HOMONIMO: `ROUND(n.VLATEND,2) AS VLATEND` registrava
        # VLATEND em `definidos` e a coluna passava batido — que e exatamente
        # como o agente escreve.
        #
        # Regra do Oracle: apelido do SELECT so pode ser referenciado em
        # ORDER BY / GROUP BY / HAVING. Dentro do proprio SELECT ou no WHERE,
        # o nome e SEMPRE coluna de tabela. Logo `definidos` so vale nesses
        # tres contextos — e nunca para coluna qualificada.
        if nome in definidos and not qualificador and _em_contexto_apelido(col):
            continue

        if qualificador:
            if qualificador in ctes:
                continue
            tabela = alias.get(qualificador)
            if not tabela or tabela not in dic:
                continue
        elif unica:
            tabela = unica
        else:
            continue

        if nome in dic[tabela]:
            validas_por_tab[tabela] = validas_por_tab.get(tabela, 0) + 1
        elif (tabela, nome) not in vistos:
            vistos.add((tabela, nome))
            ruins.append((tabela, nome))

    # trava anti-dicionario-furado
    return [(t, c) for t, c in ruins if validas_por_tab.get(t, 0) > 0]


def mensagem_recusa(ruins: list[tuple[str, str]],
                    dicionario: dict[str, Iterable[str]]) -> str:
    """Mensagem acionavel: o que esta errado e qual e o nome certo."""
    linhas = ["SQL RECUSADO ANTES DE EXECUTAR: coluna inexistente."]
    por_tab: dict[str, list[str]] = {}
    for tab, col in ruins:
        por_tab.setdefault(tab, []).append(col)

    for tab, cols in por_tab.items():
        reais = sorted({c.upper() for c in dicionario.get(tab, [])})
        linhas.append(f"\n{tab} NAO tem: {', '.join(sorted(cols))}")
        for c in sorted(cols):
            perto = difflib.get_close_matches(c, reais, n=4, cutoff=0.5)
            comeca = [r for r in reais if len(c) >= 3 and r.startswith(c[:4])
                      and r not in perto]
            contem = [r for r in reais if len(c) >= 4 and c in r
                      and r not in perto and r not in comeca]
            sug = (perto + comeca + contem)[:6]
            linhas.append(f"  {c} -> " + (", ".join(sug) if sug
                                          else "nenhuma parecida"))

    linhas.append(
        "\nCorrija TODAS de uma vez e reenvie. NAO remova uma coluna por vez: "
        "as outras da lista tambem estao erradas. Se a coluna que voce precisa "
        "nao existir nesta tabela, ela pode estar em OUTRA — consulte "
        "ALL_TAB_COLUMNS. NAO diga ao usuario que o banco falhou: o Winthor "
        "esta no ar e a consulta nem chegou nele.")
    return "\n".join(linhas)


# ============================================================
# Zero linhas em consulta de CADASTRO.
#
# Caso real (28/07/2026): o agente buscou o fornecedor "HAVAIANAS" na
# PCFORNEC, voltou ZERO linhas, o log marcou oracle_query_ok — e ele passou
# 7 minutos e 18 consultas analisando vendas, positivacao, mix e ruptura de um
# conjunto VAZIO. Havaianas e MARCA (PCMARCA 1272); o fornecedor e ALPARGATAS.
#
# 'ok' significa "nao deu erro", nao "achou". Numa consulta de cadastro, zero
# linha quase sempre quer dizer que o termo esta na tabela errada — e seguir
# adiante produz conclusao falsa com procedencia legitima, que e pior que erro.
#
# So vale para tabela de CADASTRO: em tabela de movimento, zero linha e uma
# resposta legitima ("nao houve venda no periodo").
# ============================================================

_CADASTRO = {
    "PCFORNEC", "PCMARCA", "PCSUBMARCA", "PCCLIENT", "PCPRODUT", "PCUSUARI",
    "PCEMPR", "PCFILIAL", "PCPRACA", "PCROTAEXP", "PCROTACLI", "PCDEPTO",
    "PCSECAO", "PCTABDEV", "PCTIPOOS", "PCVEICUL", "PCSUPERV", "PCPLPAG",
    "PCCOB", "PCATIVI", "PCLINHAPROD", "PCCATEGORIA", "PCPRODFILIAL",
}

# procurar nome por texto e o padrao de uma consulta de resolucao
_RE_BUSCA_TEXTO = re.compile(r"\b(LIKE|UPPER|LOWER|INSTR)\b", re.I)


def aviso_zero_linhas(sql: str, n_linhas: int) -> str:
    """Alerta quando uma consulta de RESOLUCAO volta vazia. '' se nao se aplica."""
    if n_linhas != 0 or not sql:
        return ""
    tabelas = [t for t in tabelas_fisicas(sql)]
    if not tabelas:
        return ""
    # todas as tabelas precisam ser de cadastro: se houver tabela de movimento
    # junto, zero linha pode ser resposta legitima
    if not all(t in _CADASTRO for t in tabelas):
        return ""
    if not _RE_BUSCA_TEXTO.search(sql):
        return ""

    return (
        "\n\n[ATENCAO] Esta consulta de CADASTRO voltou ZERO LINHAS. Isso quase "
        "sempre significa que o termo buscado esta em OUTRA tabela, nao que ele "
        "nao exista. NAO prossiga com a analise assumindo que encontrou — o "
        "resultado seria zero em tudo, com aparencia de dado real.\n"
        "Antes de continuar, procure o termo em: PCFORNEC.FORNECEDOR, "
        "PCFORNEC.FANTASIA, PCMARCA.MARCA e PCPRODUT.DESCRICAO. Marca e "
        "fornecedor sao coisas diferentes (ex.: HAVAIANAS e marca da "
        "ALPARGATAS). Se ainda assim nao achar, PERGUNTE ao usuario em vez de "
        "seguir com conjunto vazio."
    )


def sintaxe_arriscada(sql: str) -> list[str]:
    """Erros de ESTRUTURA que o dicionario de colunas nao pega.

    Diferente de `colunas_invalidas`: aqui a coluna existe, o problema e onde
    ela foi usada. Casos vistos em producao entre 03/08 e 01/09/2026.
    """
    if not _SQLGLOT:
        return []
    try:
        arv = sqlglot.parse_one(sql, read="oracle")
    except Exception:
        return []

    avisos: list[str] = []

    # ORDER BY por APELIDO em UNION — o Oracle exige POSICAO (ORDER BY 1).
    # Visto 2x seguidas: 'ORDER BY ONDE' e depois 'ORDER BY TIPO'.
    if isinstance(arv, exp.Union):
        ordem = arv.args.get("order")
        if ordem is not None:
            ramos = list(arv.flatten()) if hasattr(arv, "flatten") else []
            primeiro = ramos[0] if ramos else None
            saida = set()
            if isinstance(primeiro, exp.Select):
                for e in primeiro.expressions:
                    if isinstance(e, exp.Alias) and e.alias:
                        saida.add(e.alias.upper())
            for o in ordem.find_all(exp.Column):
                nome = (o.name or "").upper()
                if nome in saida:
                    avisos.append(
                        f"ORDER BY '{nome}' em UNION: o Oracle nao aceita "
                        f"apelido do SELECT aqui (ORA-00904). Use a POSICAO "
                        f"da coluna — ex.: ORDER BY 1."
                    )
    return avisos

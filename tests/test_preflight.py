"""Pre-voo de colunas.

Os quatro primeiros testes sao os erros REAIS do log de 27/07/2026. Os demais
existem para garantir que o validador nao recusa query boa — falso positivo
aqui e muito pior que falso negativo, porque bloqueia trabalho legitimo.
"""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "mcps" / "oracle" / "app"))

import preflight as pf  # noqa: E402

DIC = {
    "PCCARREG": ["NUMCAR", "DTSAIDA", "DTSAIDAVEICULO", "DTRETORNO", "DTFECHA",
                 "DT_CANCEL", "CODMOTORISTA", "CODVEICULO", "TOTPESO",
                 "TOTVOLUME", "NUMNOTAS", "CODFUNCCONF", "CODROTAPRINC",
                 "CODFILIALSAIDA", "VLTOTAL", "DESTINO"],
    "PCPEDC": ["NUMPED", "CODFILIAL", "DATA", "NUMCAR", "CODCLI", "ORIGEMPED",
               "CODEMITENTE", "DTCANCEL", "TOTPESO", "DTENTREGA", "POSICAO"],
    "PCNFSAID": ["NUMNOTA", "NUMTRANSVENDA", "NUMCAR", "NUMPED", "DTSAIDA",
                 "VLTOTAL", "CODFILIAL", "CODCLI"],
    "PCCLIENT": ["CODCLI", "CLIENTE", "TELCOM", "TELENT", "MUNICIPIO", "UF"],
    "PCMOVENDPEND": ["CODFILIAL", "DATA", "NUMOS", "TIPOOS", "CODFUNCOS",
                     "QT", "CODPROD", "DTESTORNO", "CODENDERECO"],
}


def _nomes(sql):
    return {c for _, c in pf.colunas_invalidas(sql, DIC)}


# ---------------------------------------------------------------
# Erros REAIS do log — todos precisam ser pegos
# ---------------------------------------------------------------

def test_log_1_pcnfsaid_numtransvf():
    sql = ("SELECT NUMNOTA, NUMTRANSVENDA, NUMTRANSVF, NUMCAR, NUMPED, "
           "DTSAIDA, VLTOTAL, CODFILIAL FROM EBD.PCNFSAID "
           "WHERE NUMNOTA = 3561011 AND CODFILIAL = '02'")
    assert _nomes(sql) == {"NUMTRANSVF"}


def test_log_2_pccarreg_codfuncsep():
    """CODFUNCSEP existe na PCCORTEI e na PCMOVEND — o agente misturou tabela."""
    sql = ("SELECT NUMCAR, DTSAIDA, DTSAIDAVEICULO, CODFUNCSEP, CODFUNCCONF, "
           "DT_CANCEL, DTFECHA FROM EBD.PCCARREG WHERE NUMCAR = 5192956")
    assert _nomes(sql) == {"CODFUNCSEP"}


def test_log_3_qualificado_com_subquery():
    """O caso que consumiu suas 3 tentativas: 4 colunas invalidas de uma vez,
    e o agente removeu uma por rodada."""
    sql = """
    SELECT cr.NUMCAR, cr.DTSAIDA, cr.DTSAIDAVEICULO, cr.CODFUNCMOTORISTA,
           cr.PLACA, cr.TOTNOTAS, cr.TOTPESO, cr.SITUACAO
    FROM EBD.PCCARREG cr
    WHERE cr.NUMCAR IN (SELECT DISTINCT p.NUMCAR FROM EBD.PCPEDC p
                        WHERE p.CODFILIAL = '13' AND p.DTCANCEL IS NULL)
      AND cr.DT_CANCEL IS NULL
    """
    assert _nomes(sql) == {"CODFUNCMOTORISTA", "PLACA", "TOTNOTAS", "SITUACAO"}


def test_log_4_com_cte():
    sql = """
    WITH clientes_loja AS (
        SELECT DISTINCT p.CODCLI FROM EBD.PCPEDC p
        WHERE p.ORIGEMPED = 'W' AND p.CODEMITENTE = 7777
    )
    SELECT c.CODCLI, c.CLIENTE, c.FONE
    FROM EBD.PCCLIENT c JOIN clientes_loja cl ON cl.CODCLI = c.CODCLI
    """
    assert _nomes(sql) == {"FONE"}


# ---------------------------------------------------------------
# Falso positivo: nada disto pode ser recusado
# ---------------------------------------------------------------

def test_sql_valido_passa():
    sql = ("SELECT NUMCAR, DTSAIDA, TOTPESO FROM EBD.PCCARREG "
           "WHERE DT_CANCEL IS NULL")
    assert pf.colunas_invalidas(sql, DIC) == []


def test_apelido_do_select_nao_e_coluna():
    """SELECT SUM(X) AS TOTAL ... ORDER BY TOTAL"""
    sql = ("SELECT CODFILIALSAIDA, SUM(TOTPESO) AS PESO_TOTAL "
           "FROM EBD.PCCARREG GROUP BY CODFILIALSAIDA ORDER BY PESO_TOTAL DESC")
    assert pf.colunas_invalidas(sql, DIC) == []


def test_coluna_de_cte_nao_e_coluna_de_tabela():
    sql = """
    WITH resumo AS (SELECT NUMCAR AS CARGA, TOTPESO AS PESO FROM EBD.PCCARREG)
    SELECT r.CARGA, r.PESO FROM resumo r WHERE r.PESO > 100
    """
    assert pf.colunas_invalidas(sql, DIC) == []


def test_sem_qualificacao_com_duas_tabelas_nao_valida():
    """Ambiguo: nao da pra saber de quem e a coluna. Deixa o Oracle decidir."""
    sql = ("SELECT NUMCAR, XPTO FROM EBD.PCCARREG c, EBD.PCPEDC p "
           "WHERE c.NUMCAR = p.NUMCAR")
    assert pf.colunas_invalidas(sql, DIC) == []


def test_tabela_fora_do_dicionario_nao_e_recusada():
    sql = "SELECT QUALQUER_COISA FROM EBD.PCTABELA_NOVA"
    assert pf.colunas_invalidas(sql, DIC) == []


def test_pseudo_colunas_passam():
    sql = ("SELECT NUMCAR FROM EBD.PCCARREG WHERE ROWNUM <= 10 "
           "AND DTSAIDA <= SYSDATE")
    assert pf.colunas_invalidas(sql, DIC) == []


def test_funcoes_e_binds_passam():
    sql = ("SELECT TO_CHAR(DTSAIDA,'DD/MM') AS DIA, COUNT(*) AS N "
           "FROM EBD.PCCARREG WHERE DTSAIDA >= TRUNC(SYSDATE) - :dias "
           "GROUP BY TO_CHAR(DTSAIDA,'DD/MM')")
    assert pf.colunas_invalidas(sql, DIC) == []


def test_dual_passa():
    assert pf.colunas_invalidas("SELECT 1 FROM DUAL", DIC) == []


def test_sql_quebrado_nao_recusa():
    """Se nao parseia, o Guard e o Oracle cuidam. Nao e papel do pre-voo."""
    assert pf.colunas_invalidas("SELECT FROM WHERE (((", DIC) == []


def test_dicionario_vazio_nao_recusa():
    assert pf.colunas_invalidas("SELECT XPTO FROM EBD.PCCARREG", {}) == []


def test_join_qualificado_valido():
    sql = """
    SELECT p.CODFILIAL, c.NUMCAR, c.TOTPESO
    FROM EBD.PCPEDC p JOIN EBD.PCCARREG c ON c.NUMCAR = p.NUMCAR
    WHERE p.DATA >= TRUNC(SYSDATE) - 30
    """
    assert pf.colunas_invalidas(sql, DIC) == []


def test_template_real_tlog04_passa():
    """Template do KB nao pode ser recusado pelo proprio validador."""
    sql = """
    SELECT m.CODFUNCOS AS SEPARADOR, COUNT(*) AS LINHAS,
           COUNT(DISTINCT m.NUMOS) AS OS,
           COUNT(DISTINCT TRUNC(m.DATA)) AS DIAS
    FROM EBD.PCMOVENDPEND m
    WHERE m.CODFILIAL = '18' AND m.DATA >= TRUNC(SYSDATE) - 30
      AND m.DTESTORNO IS NULL AND m.TIPOOS IN (13,14,16,17,20)
    GROUP BY m.CODFUNCOS
    """
    assert pf.colunas_invalidas(sql, DIC) == []


# ---------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------

def test_tabelas_fisicas_exclui_cte():
    sql = ("WITH t AS (SELECT NUMCAR FROM EBD.PCCARREG) "
           "SELECT * FROM t JOIN EBD.PCPEDC p ON 1=1")
    assert set(pf.tabelas_fisicas(sql)) == {"PCCARREG", "PCPEDC"}


def test_mensagem_lista_tudo_e_sugere():
    sql = ("SELECT cr.NUMCAR, cr.PLACA, cr.TOTNOTAS FROM EBD.PCCARREG cr")
    ruins = pf.colunas_invalidas(sql, DIC)
    msg = pf.mensagem_recusa(ruins, DIC)
    assert "PLACA" in msg and "TOTNOTAS" in msg
    assert "NUMNOTAS" in msg           # sugestao certa pra TOTNOTAS
    assert "uma coluna por vez" in msg  # o comportamento observado no log
    assert "banco falhou" in msg


def test_mensagem_nao_fala_em_indisponibilidade():
    ruins = pf.colunas_invalidas("SELECT cr.NUMCAR, cr.PLACA FROM EBD.PCCARREG cr", DIC)
    msg = pf.mensagem_recusa(ruins, DIC).lower()
    assert "indispon" not in msg
    assert "esta no ar" in msg


# ---------------------------------------------------------------
# Integracao com o server (cache + recusa) e com o bridge
# ---------------------------------------------------------------

def test_cache_consulta_o_banco_uma_vez_so(srv, monkeypatch):
    """Sem cache seria uma ida a ALL_TAB_COLUMNS por pergunta."""
    from conftest import FakePool
    pool = FakePool()
    monkeypatch.setattr(srv, "get_pool", lambda: pool)
    srv._DIC_CACHE.clear()

    d1 = srv._dicionario_colunas(["PCCARREG"])
    d2 = srv._dicionario_colunas(["PCCARREG"])
    d3 = srv._dicionario_colunas(["PCCARREG"])

    assert "CODFILIALSAIDA" in d1["PCCARREG"]
    assert d1 == d2 == d3
    assert pool.acquires == 1, f"foi ao banco {pool.acquires}x (deveria ser 1)"


def test_cache_nao_esconde_tabela_nova(srv, monkeypatch):
    from conftest import FakePool
    pool = FakePool()
    monkeypatch.setattr(srv, "get_pool", lambda: pool)
    srv._DIC_CACHE.clear()
    srv._dicionario_colunas(["PCCARREG"])
    d = srv._dicionario_colunas(["PCCARREG", "PCROTAEXP"])
    assert "PCROTAEXP" in d and pool.acquires == 2


def test_tabela_inexistente_nao_entra_no_dicionario(srv, monkeypatch):
    """Tabela desconhecida tem que SUMIR do dicionario: se entrasse vazia, o
    pre-voo recusaria toda coluna dela."""
    from conftest import FakePool
    pool = FakePool()
    monkeypatch.setattr(srv, "get_pool", lambda: pool)
    srv._DIC_CACHE.clear()
    d = srv._dicionario_colunas(["PCNAOEXISTE"])
    assert d == {}


def test_banco_fora_desliga_o_prevoo(srv_sem_banco):
    """Se o dicionario nao vem, o pre-voo nao pode bloquear nada."""
    srv_sem_banco._DIC_CACHE.clear()
    assert srv_sem_banco._dicionario_colunas(["PCCARREG"]) == {}


def test_integracao_recusa_o_sql_do_log(srv, monkeypatch):
    from conftest import FakePool
    monkeypatch.setattr(srv, "get_pool", lambda: FakePool())
    srv._DIC_CACHE.clear()
    sql = ("SELECT cr.NUMCAR, cr.PLACA, cr.TOTNOTAS, cr.SITUACAO "
           "FROM EBD.PCCARREG cr WHERE cr.DT_CANCEL IS NULL")
    dic = srv._dicionario_colunas(srv.tabelas_fisicas(sql))
    ruins = srv.colunas_invalidas(sql, dic)
    assert {c for _, c in ruins} == {"PLACA", "TOTNOTAS", "SITUACAO"}


def test_bridge_repassa_a_mensagem_do_prevoo():
    from conftest import BRIDGE
    msg = "SQL RECUSADO ANTES DE EXECUTAR: coluna inexistente.\nPCCARREG NAO tem: PLACA"
    out = BRIDGE._instrucao_por_erro("SQL_PREFLIGHT", msg)
    assert "PCCARREG NAO tem: PLACA" in out
    assert "NUNCA invente" in out
    assert "nem chegou no Oracle" in out
    assert "FALHOU" not in out


def test_bridge_prevoo_mantem_marcador_antifabulacao():
    from conftest import BRIDGE
    saida = BRIDGE.format_result_for_claude(
        {"status": "error",
         "error": {"code": "SQL_PREFLIGHT", "message": "coluna inexistente"}})
    assert saida.startswith("__ORACLE_ERROR__")


# ---------------------------------------------------------------
# O pre-voo nao pode recusar os proprios templates do KB
# ---------------------------------------------------------------

def _templates_do_kb():
    import re
    kb = (RAIZ / "docs" / "query_templates.md").read_text(encoding="utf-8")
    fora = []
    for tid in re.findall(r"^## (T-[A-Z]+\d\d) ", kb, re.M):
        corpo = re.search(rf"^## {tid} .*?\n(.*?)(?=^## |\Z)", kb, re.M | re.S).group(1)
        b = re.findall(r"```sql\n(.*?)```", corpo, re.S)
        if b:
            sql = b[0]
            for k, v in {":codFilial": "'18'", ":dias": "30",
                         ":listaFiliais": "'18','05'"}.items():
                sql = sql.replace(k, v)
            fora.append((tid, sql))
    return fora


def _dic_permissivo(sql):
    """Dicionario onde TODA coluna citada existe em TODA tabela citada.

    Se mesmo assim o pre-voo acusar, o bug e do resolvedor (atribuiu coluna a
    tabela que nem esta no dicionario, ou confundiu CTE com tabela fisica).
    """
    import re
    # nomes curtos contam: a PCMOVENDPEND tem a coluna QT, de 2 letras
    cols = {c.upper() for c in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql)}
    return {t: cols for t in pf.tabelas_fisicas(sql)}


@pytest.mark.parametrize("tid,sql", _templates_do_kb())
def test_template_do_kb_nao_e_recusado(tid, sql):
    ruins = pf.colunas_invalidas(sql, _dic_permissivo(sql))
    assert ruins == [], f"{tid} recusado indevidamente: {ruins}"


@pytest.mark.parametrize("tid,sql", _templates_do_kb())
def test_template_do_kb_tem_tabela_reconhecida(tid, sql):
    assert pf.tabelas_fisicas(sql), f"{tid}: nenhuma tabela fisica reconhecida"


def test_contraprova_template_com_dicionario_furado():
    """Sem isto, os dois testes acima passariam com um validador que nunca
    acusa nada. Aqui uma coluna REAL do template e removida do dicionario:
    o pre-voo tem que acusar."""
    alvo = dict(_templates_do_kb())["T-LOG04"]
    dic = _dic_permissivo(alvo)
    for t in dic:
        dic[t] = dic[t] - {"CODFUNCOS"}
    ruins = pf.colunas_invalidas(alvo, dic)
    assert any(c == "CODFUNCOS" for _, c in ruins), \
        "validador nao acusou coluna ausente do dicionario"


def test_dicionario_furado_nao_recusa_a_query_toda():
    """Se NENHUMA coluna referenciada existe no dicionario, o suspeito e o
    dicionario, nao o SQL. Melhor deixar o Oracle decidir do que bloquear
    trabalho legitimo com base em metadado incompleto."""
    dic_furado = {"PCCARREG": {"COLUNA_QUALQUER"}}
    sql = ("SELECT cr.NUMCAR, cr.DTSAIDA, cr.TOTPESO FROM EBD.PCCARREG cr")
    assert pf.colunas_invalidas(sql, dic_furado) == []


def test_trava_nao_engole_erro_real():
    """Com o dicionario bom, a trava nao pode esconder coluna errada: basta
    UMA coluna valida na tabela para a validacao valer."""
    dic = {"PCCARREG": {"NUMCAR", "DTSAIDA"}}
    sql = "SELECT cr.NUMCAR, cr.PLACA FROM EBD.PCCARREG cr"
    assert [c for _, c in pf.colunas_invalidas(sql, dic)] == ["PLACA"]


# ---------------------------------------------------------------
# Falso positivo real observado em producao (17:07 de 27/07/2026)
# ---------------------------------------------------------------

DIC_VIEWS = {
    "VIEW_DEVOL_RESUMO_FATURAVULSA": {"NUMTRANSVENDA", "CODCLI", "CODPROD",
                                      "VLDEVOLUCAO", "QT", "CODFILIAL"},
    "VIEW_DEVOL_RESUMO_FATURAMENTO": {"NUMTRANSVENDA", "CODCLI", "CODPROD",
                                      "CONDVENDA", "VLVENDA", "QT", "CODFILIAL"},
}


def test_mesmo_alias_em_ctes_diferentes_nao_recusa():
    """CONDVENDA existe na FATURAMENTO e nao na FATURAVULSA. Com o resolvedor
    plano, o alias `v` da segunda CTE sobrescrevia o da primeira e a coluna
    era validada contra a view errada."""
    sql = """
    WITH avulsa AS (
        SELECT v.NUMTRANSVENDA, v.VLDEVOLUCAO
        FROM EBD.VIEW_DEVOL_RESUMO_FATURAVULSA v
    ),
    faturamento AS (
        SELECT v.NUMTRANSVENDA, v.CONDVENDA, v.VLVENDA
        FROM EBD.VIEW_DEVOL_RESUMO_FATURAMENTO v
    )
    SELECT a.VLDEVOLUCAO, f.CONDVENDA FROM avulsa a, faturamento f
    """
    assert pf.colunas_invalidas(sql, DIC_VIEWS) == []


def test_alias_ambiguo_desliga_validacao_daquele_alias():
    sql = ("SELECT v.XPTO FROM EBD.VIEW_DEVOL_RESUMO_FATURAVULSA v "
           "UNION ALL SELECT v.YPTO FROM EBD.VIEW_DEVOL_RESUMO_FATURAMENTO v")
    assert pf.colunas_invalidas(sql, DIC_VIEWS) == []


def test_alias_nao_ambiguo_continua_validando():
    """A trava nao pode desligar a validacao quando nao ha ambiguidade."""
    sql = """
    WITH avulsa AS (
        SELECT a.NUMTRANSVENDA, a.CONDVENDA
        FROM EBD.VIEW_DEVOL_RESUMO_FATURAVULSA a
    )
    SELECT * FROM avulsa
    """
    assert [c for _, c in pf.colunas_invalidas(sql, DIC_VIEWS)] == ["CONDVENDA"]


def test_recusa_correta_de_17h09_continua_valendo():
    """PUNIT e DTVENDA nao existem mesmo — essa recusa estava certa."""
    dic = {"VIEW_DEVOL_RESUMO_FATURAMENTO":
           DIC_VIEWS["VIEW_DEVOL_RESUMO_FATURAMENTO"] | {"NUMNOTA", "DESCRICAO"}}
    sql = ("SELECT d.NUMTRANSVENDA, d.NUMNOTA, d.CODCLI, d.CODPROD, d.QT, "
           "d.PUNIT, d.DTVENDA FROM EBD.VIEW_DEVOL_RESUMO_FATURAMENTO d")
    assert {c for _, c in pf.colunas_invalidas(sql, dic)} == {"PUNIT", "DTVENDA"}

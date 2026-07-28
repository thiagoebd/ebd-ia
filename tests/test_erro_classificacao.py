"""Classificacao do erro do Oracle.

Antes, TODO erro mandava o agente responder "o banco falhou, tente depois" —
inclusive um ORA-00904 de nome de coluna errado. O agente desistia na primeira
tentativa e o _MAX_SQL_FAILS=3 nunca era usado. Erro de SQL e RECUPERAVEL.
"""
import pytest

from conftest import BRIDGE

_instrucao_por_erro = BRIDGE._instrucao_por_erro
format_result_for_claude = BRIDGE.format_result_for_claude


def _sql(msg):
    return _instrucao_por_erro("ORACLE_ERROR", msg)


# ---- erro de SQL: manda CORRIGIR, nao desistir ----

@pytest.mark.parametrize("msg", [
    'ORA-00904: "CODFILIAL": invalid identifier',
    "ORA-00942: table or view does not exist",
    "ORA-30076: invalid extract field for extract source",
    "ORA-01722: invalid number",
    "ORA-00979: not a GROUP BY expression",
])
def test_sql_manda_corrigir(msg):
    out = _sql(msg)
    assert "CORRIJA" in out.upper()
    assert "NAO DESISTA" in out.upper() or "NOVAMENTE" in out.upper()


@pytest.mark.parametrize("msg", [
    'ORA-00904: "X": invalid identifier',
    "ORA-30076: invalid extract field",
    "ORA-03113: end-of-file on communication channel",
    "Consulta excedeu o tempo limite",
])
def test_sempre_proibe_inventar(msg):
    assert "NUNCA INVENTE" in _sql(msg).upper()


def test_sql_nao_diz_que_banco_caiu():
    """A regressao que o Thiago reportou: erro de digitacao virava
    'o Winthor esta fora do ar'."""
    out = _sql('ORA-00904: "CODFILIAL": invalid identifier').lower()
    assert "esta no ar" in out
    assert "tenta de novo daqui a pouco" not in out


def test_dica_especifica_00904():
    out = _sql('ORA-00904: "CODFILIAL": invalid identifier')
    assert "ALL_TAB_COLUMNS" in out


def test_dica_especifica_30076():
    out = _sql("ORA-30076: invalid extract field for extract source")
    assert "TO_CHAR" in out and "HH24" in out


# ---- timeout: manda reescrever mais leve ----

def test_timeout_pede_query_mais_leve():
    out = _instrucao_por_erro("TIMEOUT", "Query passou de 85s — interrompida.")
    assert "REESCREVA" in out.upper()
    assert "CODFILIAL" in out.upper()


# ---- infra: ai sim, desiste ----

@pytest.mark.parametrize("msg", [
    "ORA-03113: end-of-file on communication channel",
    "DPY-6005: cannot connect to database",
    "TNS-12541: no listener",
])
def test_infra_manda_esperar(msg):
    out = _sql(msg).lower()
    assert "indispon" in out


def test_infra_e_sql_sao_diferentes():
    infra = _sql("ORA-03113: end-of-file on communication channel")
    sql = _sql('ORA-00904: "X": invalid identifier')
    assert infra != sql


# ---- escopo de acesso nao e falha de banco ----

def test_escopo_nao_vira_falha_de_banco():
    out = _instrucao_por_erro("ORACLE_ERROR",
                              "Consulta fora do ESCOPO do usuario").lower()
    assert "escopo" in out
    assert "indispon" not in out


# ---- o marcador anti-fabulacao nao pode quebrar ----

def test_marcador_preservado():
    """__ORACLE_ERROR__ e o que o agent e o gateway detectam pra bloquear
    fabulacao. Se sumir, a trava inteira para de funcionar."""
    saida = format_result_for_claude(
        {"status": "error",
         "error": {"code": "ORACLE_ERROR",
                   "message": 'ORA-00904: "X": invalid identifier'}})
    assert saida.startswith("__ORACLE_ERROR__")


def test_sucesso_nao_tem_marcador():
    saida = format_result_for_claude(
        {"status": "ok", "result": {"rows": [{"A": 1}]}, "elapsed_ms": 10})
    assert "__ORACLE_ERROR__" not in saida


# ---- aviso de zero linhas chega ao agente ----

def test_zero_linhas_com_aviso_chega_ao_agente():
    """O MCP anexa o aviso; o bridge nao pode engolir."""
    saida = format_result_for_claude({
        "status": "ok",
        "result": {"columns": ["CODFORNEC"], "rows": [],
                   "aviso": "\n\n[ATENCAO] Esta consulta de CADASTRO voltou ZERO LINHAS."},
        "elapsed_ms": 30})
    assert "0 linhas" in saida
    assert "ZERO LINHAS" in saida


def test_zero_linhas_sem_aviso_continua_curto():
    saida = format_result_for_claude(
        {"status": "ok", "result": {"columns": [], "rows": []}, "elapsed_ms": 12})
    assert saida.startswith("OK (0 linhas")
    assert "ATENCAO" not in saida

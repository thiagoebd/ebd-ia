"""ORA-00904 -> sugestao de colunas reais.

74% dos erros do agente sao coluna inexistente (323 de 436 medidos em
27/07/2026). Estes testes cobrem o mecanismo que devolve o nome certo.
"""
import datetime

import pytest

from conftest import RECENTE, VELHA


# ------------------------------------------------------------------
# _marca_coluna — rotulo de conteudo a partir da estatistica
# ------------------------------------------------------------------

def test_vazia(srv):
    # CODFILIALSAIDA: existe, 0 valores distintos, 100% nulo
    assert srv._marca_coluna(0, 1143784, 1153949, RECENTE) == " [VAZIA]"


def test_quase_vazia(srv):
    # 9 preenchidas em 1,15 mi
    assert srv._marca_coluna(4, 1153940, 1153949, RECENTE) == " [QUASE VAZIA]"


def test_valor_unico(srv):
    # KMINICIAL: preenchida, mas sempre zero. O disfarce mais traicoeiro:
    # COUNT(col) diz que tem dado.
    assert srv._marca_coluna(1, 751557, 1153949, RECENTE) == " [VALOR UNICO]"


def test_coluna_cheia_nao_marca(srv):
    assert srv._marca_coluna(2626, 1, 1153949, RECENTE) == ""


def test_estatistica_velha_nao_condena(srv):
    """Guarda de validade: melhor nao avisar do que condenar coluna boa."""
    assert srv._marca_coluna(0, 999, 1000, VELHA) == ""


def test_sem_analise_nao_marca(srv):
    assert srv._marca_coluna(0, 999, 1000, None) == ""


def test_marca_nunca_levanta(srv):
    """Regressao do bug real: datetime nao importado no server.py fazia isto
    virar NameError, engolido por um except que devolvia string vazia."""
    for args in [(None, None, None, RECENTE), ("x", "y", "z", RECENTE),
                 (0, 10, 0, RECENTE), (0, 10, None, RECENTE)]:
        assert isinstance(srv._marca_coluna(*args), str)


# ------------------------------------------------------------------
# _tabelas_do_sql
# ------------------------------------------------------------------

@pytest.mark.parametrize("sql,esperado", [
    ("SELECT * FROM EBD.PCCARREG", ["PCCARREG"]),
    ("select a from pccarreg c", ["PCCARREG"]),
    ("SELECT 1 FROM EBD.PCPEDC p JOIN EBD.PCCARREG c ON c.NUMCAR = p.NUMCAR",
     ["PCPEDC", "PCCARREG"]),
    ("SELECT 1 FROM EBD.PCMOVENDPEND m LEFT JOIN EBD.PCEMPR e "
     "ON e.MATRICULA = m.CODFUNCOS", ["PCMOVENDPEND", "PCEMPR"]),
])
def test_tabelas_extraidas(srv, sql, esperado):
    achadas = srv._tabelas_do_sql(sql)
    for t in esperado:
        assert t in achadas, f"{t} nao saiu de: {sql}"


def test_tabelas_sql_quebrado_nao_levanta(srv):
    assert isinstance(srv._tabelas_do_sql("SELECT FROM WHERE ((("), list)


def test_tabelas_sql_vazio(srv):
    assert srv._tabelas_do_sql("") == []


# ------------------------------------------------------------------
# _sugestao_colunas
# ------------------------------------------------------------------

def test_sugere_nome_parecido(srv):
    out = srv._sugestao_colunas(
        "SELECT CODFILIAL FROM EBD.PCCARREG",
        'ORA-00904: "CODFILIAL": invalid identifier')
    assert "CODFILIALSAIDA" in out
    assert "COLUNA INEXISTENTE" in out


def test_sugestao_marca_coluna_vazia(srv):
    """Sugerir CODFILIALSAIDA sem avisar que esta vazia troca um erro
    visivel (ORA-00904) por um invisivel (zero linhas com cara de resposta)."""
    out = srv._sugestao_colunas(
        "SELECT CODFILIAL FROM EBD.PCCARREG",
        'ORA-00904: "CODFILIAL": invalid identifier')
    assert "CODFILIALSAIDA [VAZIA]" in out
    assert "ZERO LINHAS" in out


def test_nome_curto_encontra_prefixo(srv):
    """Regressao do bug real: difflib da 0.50 para KM x KMROTA (corte 0.55) e
    o filtro de substring exigia 4 caracteres. 'nenhuma parecida com KM' saia
    logo acima de uma amostra que continha KMROTA."""
    out = srv._sugestao_colunas("SELECT KM FROM EBD.PCROTAEXP",
                                'ORA-00904: "KM": invalid identifier')
    assert "KMROTA" in out
    assert "nenhuma parecida" not in out


def test_alias_qualificado(srv):
    out = srv._sugestao_colunas(
        "SELECT c.CODFILIAL FROM EBD.PCCARREG c",
        'ORA-00904: "C"."CODFILIAL": invalid identifier')
    assert "CODFILIALSAIDA" in out


def test_tabela_inexistente(srv):
    out = srv._sugestao_colunas("SELECT X FROM EBD.PCNAOEXISTE",
                                'ORA-00904: "X": invalid identifier')
    assert "nao foram encontradas" in out or "nao encontrada" in out


def test_sem_tabela_devolve_vazio(srv):
    assert srv._sugestao_colunas("SELECT 1 FROM DUAL",
                                 'ORA-00904: "X": invalid identifier') in ("", None) \
        or "DUAL" in srv._sugestao_colunas("SELECT 1 FROM DUAL",
                                           'ORA-00904: "X": invalid identifier')


def test_banco_fora_nao_derruba(srv_sem_banco):
    """Se o pool estourar, a sugestao some — mas o erro original continua
    chegando ao agente. Nunca pode virar excecao."""
    out = srv_sem_banco._sugestao_colunas(
        "SELECT CODFILIAL FROM EBD.PCCARREG",
        'ORA-00904: "CODFILIAL": invalid identifier')
    assert out == ""


def test_conexao_devolvida_ao_pool(srv, monkeypatch):
    from conftest import FakePool
    pool = FakePool()
    monkeypatch.setattr(srv, "get_pool", lambda: pool)
    srv._sugestao_colunas("SELECT CODFILIAL FROM EBD.PCCARREG",
                          'ORA-00904: "CODFILIAL": invalid identifier')
    assert pool.liberou == 1, "conexao vazando do pool"


def test_saida_tem_teto(srv):
    out = srv._sugestao_colunas(
        "SELECT X FROM EBD.PCCARREG a JOIN EBD.PCPEDC b ON 1=1 "
        "JOIN EBD.PCROTAEXP c ON 1=1 JOIN EBD.PCMOVENDPEND d ON 1=1",
        'ORA-00904: "X": invalid identifier')
    assert len(out) <= 1800

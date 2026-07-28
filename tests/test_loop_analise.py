"""Parada do loop em analise longa.

Bug real observado em 28/07/2026: uma analise de 12 passos, com varias
consultas bem-sucedidas, terminou com "nao consegui montar uma consulta
valida". O orcamento de falhas era CUMULATIVO no turno inteiro — 3 erros
espalhados entre 12 consultas abortavam tudo e descartavam o que ja tinha
sido apurado.
"""
import sys
from pathlib import Path

import pytest

from conftest import RAIZ

sys.path.insert(0, str(RAIZ / "core" / "app"))
import loop_policy  # noqa: E402

decidir = loop_policy.decidir_parada


def oq(*resultados):
    """Atalho: True = consulta ok, False = falhou."""
    return [("oracle_query", r) for r in resultados]


# ---------------------------------------------------------------
# O bug: falhas espalhadas numa analise longa
# ---------------------------------------------------------------

def test_analise_longa_com_falhas_espalhadas_nao_aborta():
    """9 consultas boas e 3 falhas alternadas: o caso do print."""
    outcomes = oq(True, True, False, True, True, False, True, True,
                  False, True, True, True)
    assert decidir(outcomes) == "seguir"


def test_sucesso_zera_a_contagem():
    outcomes = oq(False, False, True)
    assert decidir(outcomes) == "seguir"


def test_duas_falhas_seguidas_ainda_segue():
    assert decidir(oq(True, False, False)) == "seguir"


# ---------------------------------------------------------------
# Sem nada aproveitavel: ai sim aborta
# ---------------------------------------------------------------

def test_tres_falhas_sem_nenhum_sucesso_aborta():
    assert decidir(oq(False, False, False)) == "abortar"


def test_duas_falhas_sem_sucesso_ainda_segue():
    assert decidir(oq(False, False)) == "seguir"


def test_sem_consulta_nenhuma_segue():
    assert decidir([]) == "seguir"
    assert decidir([("create_excel", True)]) == "seguir"


# ---------------------------------------------------------------
# Com dado na mao: conclui em vez de descartar
# ---------------------------------------------------------------

def test_com_sucesso_e_muitas_falhas_pede_conclusao():
    """6 falhas seguidas, mas ha 3 consultas boas: nao pode jogar fora."""
    outcomes = oq(True, True, True, False, False, False, False, False, False)
    assert decidir(outcomes) == "concluir"


def test_orcamento_maior_quando_ha_progresso():
    """Com sucesso, o limite sobe de 3 para 6 falhas seguidas."""
    com_dado = oq(True, False, False, False, False, False)
    assert decidir(com_dado) == "seguir"
    sem_dado = oq(False, False, False)
    assert decidir(sem_dado) == "abortar"


def test_nao_pede_conclusao_duas_vezes():
    outcomes = oq(True, False, False, False, False, False, False)
    assert decidir(outcomes, ja_pediu_conclusao=False) == "concluir"
    assert decidir(outcomes, ja_pediu_conclusao=True) == "parar"


def test_parar_nunca_vira_mensagem_de_falha():
    """'parar' encerra sem dizer que nao conseguiu — havia dado."""
    outcomes = oq(True, True, False, False, False, False, False, False)
    assert decidir(outcomes, ja_pediu_conclusao=True) == "parar"


# ---------------------------------------------------------------
# Limite configuravel e outras tools nao interferem
# ---------------------------------------------------------------

def test_outras_tools_nao_contam():
    outcomes = [("create_excel", False), ("create_route_map", False),
                ("oracle_query", True)]
    assert decidir(outcomes) == "seguir"


def test_limite_configuravel():
    assert decidir(oq(False, False), max_fails=2) == "abortar"
    assert decidir(oq(False), max_fails=2) == "seguir"


def test_aviso_de_conclusao_proibe_inventar():
    """A instrucao de fechar com o que tem nao pode virar convite a fabular."""
    assert "NUNCA invente" in loop_policy.AVISO_CONCLUA
    assert "NAO conseguiu apurar" in loop_policy.AVISO_CONCLUA
    assert "PARE de consultar" in loop_policy.AVISO_CONCLUA

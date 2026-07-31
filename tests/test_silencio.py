"""Nenhuma resposta pode chegar vazia ao usuario.

Mapeado em 31/07/2026: tokens so sao emitidos em dois pontos do agent.py.
Tres saidas podiam entregar bolha vazia — sem texto, sem erro, sem selo.

A propriedade que MAIS importa aqui: estas mensagens so aparecem quando nada
mais foi emitido. Elas NUNCA podem contaminar uma resposta que funcionou.
"""
import re
import sys
from pathlib import Path

import pytest

from conftest import RAIZ

sys.path.insert(0, str(RAIZ / "core" / "app"))
import loop_policy as lp  # noqa: E402


MOTIVOS = (lp.MOTIVO_SEM_TEXTO, lp.MOTIVO_PARCIAL, lp.MOTIVO_MAX_ITERACOES)


# ---------------------------------------------------------------
# toda saida silenciosa produz mensagem
# ---------------------------------------------------------------

@pytest.mark.parametrize("motivo", MOTIVOS)
@pytest.mark.parametrize("outcomes", [
    [],
    [("oracle_query", True)],
    [("oracle_query", False)],
    [("oracle_query", True), ("create_excel", True)],
])
def test_sempre_ha_mensagem(motivo, outcomes):
    m = lp.mensagem_silencio(motivo, outcomes)
    assert m and len(m) > 40, (motivo, outcomes)


def test_motivo_desconhecido_nao_inventa_texto():
    """Na duvida, silencio de codigo — nunca uma mensagem errada."""
    assert lp.mensagem_silencio("xpto") == ""
    assert lp.mensagem_silencio("") == ""
    assert lp.mensagem_silencio(None) == ""


# ---------------------------------------------------------------
# a mensagem reflete se HOUVE dado apurado
# ---------------------------------------------------------------

def test_com_dado_diz_que_consultou():
    m = lp.mensagem_silencio(lp.MOTIVO_SEM_TEXTO, [("oracle_query", True)])
    assert "consultei os dados" in m.lower()


def test_sem_dado_nao_diz_que_consultou():
    m = lp.mensagem_silencio(lp.MOTIVO_SEM_TEXTO, [("oracle_query", False)])
    assert "consultei os dados" not in m.lower()


def test_consulta_falha_nao_conta_como_dado():
    assert lp.teve_dado_apurado([("oracle_query", False)]) is False
    assert lp.teve_dado_apurado([("create_excel", True)]) is False
    assert lp.teve_dado_apurado([]) is False
    assert lp.teve_dado_apurado(None) is False


def test_uma_consulta_ok_entre_falhas_conta():
    assert lp.teve_dado_apurado(
        [("oracle_query", False), ("oracle_query", True)]) is True


# ---------------------------------------------------------------
# nenhuma mensagem pode inventar dado nem culpar o banco
# ---------------------------------------------------------------

@pytest.mark.parametrize("motivo", MOTIVOS)
@pytest.mark.parametrize("dado", [True, False])
def test_nunca_cita_numero(motivo, dado):
    m = lp.mensagem_silencio(motivo, [("oracle_query", dado)])
    assert not re.search(r"\d{2,}", m), f"mensagem com numero: {m}"


@pytest.mark.parametrize("motivo", MOTIVOS)
def test_nunca_culpa_o_banco(motivo):
    """Nao e falha do Winthor: dizer que e confunde o usuario e a TI."""
    m = lp.mensagem_silencio(motivo, [("oracle_query", True)]).lower()
    for proibido in ("banco caiu", "banco fora", "indisponibilidade",
                     "erro do oracle", "winthor fora"):
        assert proibido not in m


@pytest.mark.parametrize("motivo", MOTIVOS)
def test_e_acionavel(motivo):
    """Tem que dizer ao usuario o que fazer, nao so que deu errado."""
    m = lp.mensagem_silencio(motivo, [("oracle_query", True)]).lower()
    assert any(p in m for p in ("reformular", "repetir", "quebrar", "tente"))


# ---------------------------------------------------------------
# o contrato com o agent.py: os 3 pontos de saida existem mesmo
# ---------------------------------------------------------------

def _fonte_agent() -> str:
    return (RAIZ / "core" / "app" / "agent.py").read_text(encoding="utf-8")


def test_tokens_so_saem_em_dois_pontos():
    """Se alguem passar a emitir token em outro lugar, a analise que sustenta
    este modulo muda e o teste avisa."""
    fonte = _fonte_agent()
    n = len(re.findall(r'yield \{"type": "token"', fonte))
    assert n <= 4, (f"{n} pontos emitem token — remapeie as saidas "
                    f"silenciosas antes de confiar neste modulo")


def test_texto_e_acumulado_nao_transmitido_ao_vivo():
    """text_acc += delta.text sem yield: e por isso que C e D sao sempre mudas."""
    fonte = _fonte_agent()
    assert "text_acc += delta.text" in fonte

"""Politica de acesso por perfil — ortogonal ao escopo de filial."""
import sys
from pathlib import Path

import pytest

from conftest import RAIZ

sys.path.insert(0, str(RAIZ / "mcps" / "oracle" / "app"))
import policies as pol  # noqa: E402


# ---------------------------------------------------------------
# normaliza_role — o bug que existia: fallback era ADMIN
# ---------------------------------------------------------------

@pytest.mark.parametrize("entrada", [None, "", "  ", "xpto", "ADMINISTRADOR",
                                     "root", 0, [], "diretoria", "adm", "Diretor Comercial"])
def test_role_invalido_nunca_vira_admin(entrada):
    assert pol.normaliza_role(entrada) != "admin"
    assert pol.normaliza_role(entrada) == pol.ROLE_PADRAO


@pytest.mark.parametrize("r", ["admin", "diretor", "gerente", "supervisor", "analista"])
def test_roles_validos_passam(r):
    assert pol.normaliza_role(r) == r
    assert pol.normaliza_role(r.upper()) == r
    assert pol.normaliza_role(f"  {r} ") == r


def test_role_padrao_e_o_menor_privilegio():
    assert pol.NIVEL_ROLE[pol.ROLE_PADRAO] == min(pol.NIVEL_ROLE.values())


# ---------------------------------------------------------------
# comissao: admin e diretor veem; o resto nao
# ---------------------------------------------------------------

@pytest.mark.parametrize("r", ["admin", "diretor"])
def test_comissao_liberada(r):
    assert pol.recursos_violados(["PCGMMETACOMB"], r) == []
    assert pol.recursos_violados(["PCCOMISSAOUSUR"], r) == []


@pytest.mark.parametrize("r", ["gerente", "supervisor", "analista"])
def test_comissao_bloqueada(r):
    v = pol.recursos_violados(["PCGMMETACOMB"], r)
    assert len(v) == 1 and v[0]["recurso"] == "comissao"


def test_role_desconhecido_bloqueia_comissao():
    """Antes o fallback era admin — este teste e o que impede a volta."""
    assert pol.recursos_violados(["PCGMMETACOMB"], None) != []
    assert pol.recursos_violados(["PCGMMETACOMB"], "diretoria") != []


def test_prefixo_pega_toda_a_familia_pcgm():
    for t in ("PCGMMETA", "PCGMMETACOMB", "PCGMPARAMMETA", "PCGMPREMIONIVEL",
              "PCGMINDICADOR", "PCGMFAIXAPADRAOITEM"):
        assert pol.recursos_violados([t], "gerente") != [], t


def test_tabela_fora_da_politica_passa_para_todos():
    for r in pol.ROLES_VALIDOS:
        assert pol.recursos_violados(["PCPEDC", "PCEST", "PCMETA"], r) == []


def test_pcmeta_nao_esta_restrita():
    """Meta e objetivo comercial; o que e sensivel e o valor pago."""
    assert pol.recursos_violados(["PCMETA"], "gerente") == []


def test_uma_tabela_restrita_no_meio_ja_bloqueia():
    v = pol.recursos_violados(["PCPEDC", "PCEST", "PCGMMETACOMB"], "supervisor")
    assert v and v[0]["tabelas_atingidas"] == ["PCGMMETACOMB"]


def test_sem_tabela_nao_bloqueia():
    assert pol.recursos_violados([], "analista") == []
    assert pol.recursos_violados(None, "analista") == []


# ---------------------------------------------------------------
# extensibilidade: politica nova sem tocar em codigo
# ---------------------------------------------------------------

def test_politica_customizada_e_respeitada():
    nova = [{"recurso": "folha", "descricao": "RH",
             "tabelas": ["PCEMPR", "PCLANC%"],
             "roles_permitidos": ["admin"]}]
    assert pol.recursos_violados(["PCEMPR"], "diretor", nova) != []
    assert pol.recursos_violados(["PCEMPR"], "admin", nova) == []
    assert pol.recursos_violados(["PCLANCBLOQ"], "gerente", nova) != []
    assert pol.recursos_violados(["PCGMMETACOMB"], "gerente", nova) == []


def test_politica_incompleta_e_ignorada_sem_quebrar():
    ruins = [{"recurso": "x"}, {"recurso": "y", "tabelas": []},
             {"recurso": "z", "roles_permitidos": ["admin"]}]
    assert pol.recursos_violados(["PCGMMETACOMB"], "analista", ruins) == []


# ---------------------------------------------------------------
# mensagem
# ---------------------------------------------------------------

def test_mensagem_diz_que_nao_e_erro_de_banco():
    m = pol.mensagem_recusa(pol.recursos_violados(["PCGMMETACOMB"], "gerente"),
                            "gerente")
    assert "ACESSO RESTRITO POR PERFIL" in m
    assert "NAO e falha do banco" in m
    assert "NUNCA invente" in m
    assert "admin" in m and "diretor" in m


def test_mensagem_vazia_quando_liberado():
    assert pol.mensagem_recusa([], "admin") == ""


# ---------------------------------------------------------------
# carregamento com fallback — sem Postgres NAO pode liberar
# ---------------------------------------------------------------

def test_sem_postgres_cai_no_default_restritivo(monkeypatch):
    monkeypatch.setattr(pol, "_CACHE", {"ts": 0.0, "politicas": None})
    monkeypatch.setenv("POSTGRES_HOST", "host-que-nao-existe.invalido")
    carregadas = pol.carrega_politicas(force=True)
    assert carregadas, "lista vazia liberaria TUDO"
    assert pol.recursos_violados(["PCGMMETACOMB"], "gerente", carregadas) != []


def test_cache_evita_ida_ao_banco(monkeypatch):
    monkeypatch.setattr(pol, "_CACHE",
                        {"ts": 9e18, "politicas": [{"recurso": "x",
                                                    "tabelas": ["PCX"],
                                                    "roles_permitidos": ["admin"]}]})
    assert pol.carrega_politicas()[0]["recurso"] == "x"

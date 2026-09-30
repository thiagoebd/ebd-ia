"""Catalogo de templates — o que o get_template devolve ao agente.

O catalogo estava parado em 20/07/2026 com 56 de 108 templates: faltavam
exatamente as familias criadas depois (T-LOG, T-GM, T-CMP, T-PRC). Sem ele
completo nao da para tirar os SQL do prompt — o agente pediria e receberia
"nao encontrado".
"""
import json
import sys

from conftest import RAIZ

sys.path.insert(0, str(RAIZ / "core"))
import app.tools.template_catalog as tc  # noqa: E402

CAT = json.loads((RAIZ / "core" / "app" / "data" / "templates.json")
                 .read_text(encoding="utf-8"))
POR_CODE = {t["code"]: t for t in CAT["templates"]}


def test_catalogo_cobre_as_familias_novas():
    """T-LOG, T-GM, T-CMP e T-PRC nasceram depois do catalogo antigo."""
    for pref in ("T-LOG", "T-GM", "T-CMP", "T-PRC"):
        assert any(c.startswith(pref) for c in POR_CODE), f"falta {pref}"


def test_catalogo_tem_mais_que_o_antigo():
    assert CAT["count"] >= 85, f"so {CAT['count']} templates"


def test_toda_entrada_tem_os_campos_que_o_get_template_usa():
    for t in CAT["templates"]:
        for campo in ("code", "title", "familia", "binds", "sql", "validated"):
            assert campo in t, f"{t.get('code')} sem {campo}"


def test_get_template_entrega_sql_executavel():
    out = tc.tool_get_template(code="T250")
    assert "SELECT" in out.upper()
    assert "T250" in out


def test_get_template_avisa_quando_e_remissao():
    """'Identica ao T101 com X' nao e SQL — devolver isso faz o agente
    executar um comentario."""
    incompletos = [t for t in CAT["templates"] if t.get("incompleto")
                   and t.get("remissao")]
    if not incompletos:
        return
    out = tc.tool_get_template(code=incompletos[0]["code"])
    assert "nao tem SQL proprio" in out
    assert incompletos[0]["remissao"] in out


def test_get_template_avisa_quando_e_placeholder():
    """'-- ... (ver bloco acima) ...' tambem nao e query."""
    sos = [t for t in CAT["templates"] if t.get("incompleto")
           and not t.get("remissao")]
    if not sos:
        return
    out = tc.tool_get_template(code=sos[0]["code"])
    assert "nao tem SQL executavel" in out


def test_get_template_de_codigo_inexistente_lista_opcoes():
    out = tc.tool_get_template(code="NAOEXISTE")
    assert "nao existe" in out.lower()
    assert "T-" in out or "T1" in out


def test_list_templates_agrupa_por_familia():
    out = tc.tool_list_templates(familia=None)
    assert "familias:" in out
    for fam in ("logistica", "metas", "faturamento"):
        assert fam in out


def test_list_templates_filtra():
    out = tc.tool_list_templates(familia="logistica")
    assert "T-LOG" in out


def test_binds_extraidos_do_sql():
    """O agente precisa saber o que preencher."""
    com = [t for t in CAT["templates"] if t["binds"]]
    assert len(com) >= 40
    t = com[0]
    for b in t["binds"]:
        assert f":{b}" in t["sql"]


def test_nenhum_sql_cita_view_banida():
    """Cicatriz #38: as GD_* estao desativadas."""
    ruins = [t["code"] for t in CAT["templates"] if "GD_FATO" in t["sql"]
             or "GD_DIM" in t["sql"]]
    assert not ruins, f"templates com view banida: {ruins}"

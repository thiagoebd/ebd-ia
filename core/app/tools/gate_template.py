"""Gate de template — força o uso do catálogo sem custo de latência."""
import re

BANIDAS = {
    "GD_FATO_ROTACLIENTE": "Para rota use PCROTACLI (templates T270/T271/T272). GD_FATO_ROTACLIENTE dá resultado pobre/zero.",
    "PCMOVROTACLI": "Para rota use PCROTACLI (T270). PCMOVROTACLI tem 34M linhas e dá timeout.",
}
TABELAS_NEGOCIO = {
    "PCFALTA", "PCROTACLI", "PCMETA", "PCPEDC", "PCFORNEC", "PCCLIENT",
    "GD_DIM_RCA", "VIEW_VENDAS_RESUMO_FATURAMENTO", "GD_FATO_VENDAFATURAMENTO",
}

def _tabelas(sql: str) -> set:
    up = (sql or "").upper()
    return {t for t in set(BANIDAS) | TABELAS_NEGOCIO if re.search(rf"\b(EBD\.)?{t}\b", up)}

def checar_gate(sql: str, consultou_catalogo: bool):
    tabs = _tabelas(sql)
    for tab in tabs:
        if tab in BANIDAS:
            return ("bloquear", f"__GATE_TEMPLATE__ Tabela {tab} não deve ser usada. {BANIDAS[tab]}")
    if (tabs & TABELAS_NEGOCIO) and not consultou_catalogo:
        negocio = ", ".join(sorted(tabs & TABELAS_NEGOCIO))
        return ("dica",
                f"\n\n[dica do sistema: há templates SQL validados para {negocio}. "
                f"Se for repetir esse tipo de consulta, chame list_templates/get_template — "
                f"o template tem as colunas certas e evita ORA-00904. Esta resposta seguiu normalmente.]")
    return ("ok", "")
    return ("ok", "")

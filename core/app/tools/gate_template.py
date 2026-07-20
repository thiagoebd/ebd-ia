"""Gate de template — força o uso do catálogo (v4 híbrido: 3 níveis)."""
import re

# NÍVEL 1: banidas — bloqueiam SEMPRE
BANIDAS = {
    "GD_FATO_ROTACLIENTE": "Para rota use PCROTACLI (templates T270/T271/T272). GD_FATO_ROTACLIENTE dá resultado pobre/zero.",
    "PCMOVROTACLI": "Para rota use PCROTACLI (T270). PCMOVROTACLI tem 34M linhas e dá timeout.",
}

# NÍVEL 2: core — famílias que TÊM template. Bloqueiam se não consultou o catálogo.
TABELAS_CORE = {
    "PCFALTA", "PCROTACLI", "PCMETA", "PCPEDC", "PCFORNEC", "PCCLIENT",
    "GD_DIM_RCA", "VIEW_VENDAS_RESUMO_FATURAMENTO", "GD_FATO_VENDAFATURAMENTO",
}

# NÍVEL 3: auxiliares — dão contexto mas raramente têm template. Só dica.
TABELAS_AUXILIARES = {
    "PCUSUARI", "PCPRODUT", "PCSUPERV", "PCLOGALTCLI", "PCPRODFILIAL",
}

def _tabelas(sql: str, universo: set) -> set:
    up = (sql or "").upper()
    return {t for t in universo if re.search(rf"\b(EBD\.)?{t}\b", up)}

def checar_gate(sql: str, consultou_catalogo: bool):
    for tab in _tabelas(sql, set(BANIDAS)):
        return ("bloquear", f"__GATE_TEMPLATE__ Tabela {tab} não deve ser usada. {BANIDAS[tab]}")

    core = _tabelas(sql, TABELAS_CORE)
    if core and not consultou_catalogo:
        nomes = ", ".join(sorted(core))
        return ("bloquear",
                f"__GATE_TEMPLATE__ A consulta usa {nomes}, que tem template SQL validado. "
                f"Chame list_templates e depois get_template para pegar as colunas corretas "
                f"(evita ORA-00904). Depois refaça a consulta com o SQL do template.")

    aux = _tabelas(sql, TABELAS_AUXILIARES)
    if aux and not consultou_catalogo:
        nomes = ", ".join(sorted(aux))
        return ("dica",
                f"\n\n[dica do sistema: se for repetir consultas envolvendo {nomes}, "
                f"vale checar list_templates — pode haver template validado. "
                f"Esta resposta seguiu normalmente.]")

    return ("ok", "")

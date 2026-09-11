"""Resolver NOME para código no Winthor — com o usuário no circuito.

O PROBLEMA

"thiago parreira" existe no banco como "THIAGO MARTINS PARREIRA". Casar os
dois é o certo. Mas "PARREIRA COMERCIO LTDA" também contém "PARREIRA" e é
outra empresa. Não existe regra que acerte sempre.

A SAÍDA

O banco traz CANDIDATOS, e o resultado se divide em três baldes:

    resolvido  — um único candidato plausível, casa direto
    ambiguo    — vários candidatos, o USUÁRIO decide
    nao_achado — nenhum candidato

O agente NUNCA escolhe sozinho entre candidatos ambíguos. Entregar um
número que parece completo e não é, é pior que dizer "não achei estes 12" —
é o mesmo princípio do freio anti-fabulação.

AS CINCO ENTIDADES

95% dos casos caem em: cliente, fornecedor, produto, filial e vendedor.
Cada uma tem tabela, colunas de busca e regras próprias — a de fornecedor,
por exemplo, SEMPRE resolve pela raiz (cicatriz #74).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.planilhas import normaliza_texto, tokens

# Cada entidade: onde procurar, o que devolver, e a regra que a diferencia.
ENTIDADES: dict[str, dict] = {
    "cliente": {
        "tabela": "EBD.PCCLIENT",
        "codigo": "CODCLI",
        "nome": "CLIENTE",
        "busca": ["CLIENTE", "FANTASIA"],
        "doc": "CGCENT",
        "extra": "CODCLI, SUBSTR(CLIENTE,1,60) AS NOME, CGCENT AS DOC",
    },
    "fornecedor": {
        "tabela": "EBD.PCFORNEC",
        "codigo": "CODFORNEC",
        "nome": "FORNECEDOR",
        "busca": ["FORNECEDOR", "FANTASIA"],
        "doc": "CGC",
        # cicatriz #74: fornecedor SEMPRE pela raiz
        "extra": ("NVL(CODFORNECPRINC, CODFORNEC) AS CODFORNEC, "
                  "SUBSTR(FORNECEDOR,1,60) AS NOME, CGC AS DOC"),
        "regra": "resolvido pela RAIZ: NVL(CODFORNECPRINC, CODFORNEC)",
    },
    "produto": {
        "tabela": "EBD.PCPRODUT",
        "codigo": "CODPROD",
        "nome": "DESCRICAO",
        "busca": ["DESCRICAO", "DESCRICAO1"],
        "doc": "CODAUXILIAR",
        "extra": ("CODPROD, SUBSTR(DESCRICAO,1,60) AS NOME, "
                  "CODAUXILIAR AS DOC"),
        "filtro": "DTEXCLUSAO IS NULL",
    },
    "filial": {
        "tabela": "EBD.PCFILIAL",
        "codigo": "CODIGO",
        "nome": "FANTASIA",
        "busca": ["FANTASIA", "RAZAOSOCIAL"],
        "doc": "CGC",
        "extra": "CODIGO AS CODFILIAL, SUBSTR(FANTASIA,1,40) AS NOME",
    },
    "vendedor": {
        "tabela": "EBD.PCUSUARI",
        "codigo": "CODUSUR",
        "nome": "NOME",
        "busca": ["NOME"],
        "extra": "CODUSUR, SUBSTR(NOME,1,50) AS NOME, CODFILIAL",
        # cicatriz #90: só RCA de campo
        "filtro": ("(DTTERMINO IS NULL OR DTTERMINO >= TRUNC(SYSDATE)) "
                   "AND CODUSUR NOT IN (SELECT COD_CADRCA FROM EBD.PCSUPERV "
                   "WHERE COD_CADRCA IS NOT NULL)"),
        "regra": "só RCA de campo ativo (cicatriz #90)",
    },
}


@dataclass
class Resolucao:
    resolvido: dict[str, dict] = field(default_factory=dict)   # nome -> registro
    ambiguo: dict[str, list] = field(default_factory=dict)     # nome -> candidatos
    nao_achado: list[str] = field(default_factory=list)

    def resumo(self) -> dict:
        return {
            "resolvidos": len(self.resolvido),
            "ambiguos": len(self.ambiguo),
            "nao_achados": len(self.nao_achado),
            # o agente precisa VER os ambíguos para perguntar ao usuário
            "para_decidir": [
                {"buscado": nome,
                 "candidatos": [
                     {"codigo": c.get(list(c.keys())[0]),
                      "nome": c.get("NOME", "")} for c in cands[:5]
                 ]}
                for nome, cands in list(self.ambiguo.items())[:10]
            ],
            "nao_achados_exemplos": self.nao_achado[:10],
        }


def sql_por_nome(entidade: str, nomes: list[str], max_cand: int = 6) -> str:
    """SQL que traz candidatos para uma lista de nomes.

    Estratégia: cada nome vira um conjunto de tokens, e o SQL exige que
    TODOS estejam presentes. "thiago parreira" casa com "THIAGO MARTINS
    PARREIRA" porque ambos os tokens aparecem; não casa com "PARREIRA
    COMERCIO" porque falta THIAGO.
    """
    e = ENTIDADES.get(entidade)
    if not e:
        raise ValueError(f"entidade desconhecida: {entidade}")

    blocos = []
    for nome in nomes[:200]:          # o SQL tem limite prático
        toks = tokens(nome)
        if not toks:
            continue
        condicoes = []
        for campo in e["busca"]:
            partes = [
                f"UPPER(TRANSLATE({campo}, "
                f"'ÁÀÃÂÉÊÍÓÔÕÚÜÇáàãâéêíóôõúüç', "
                f"'AAAAEEIOOOUUCaaaaeeiooouuc')) LIKE '%{t}%'"
                for t in toks
            ]
            condicoes.append("(" + " AND ".join(partes) + ")")
        filtro = e.get("filtro")
        onde = "(" + " OR ".join(condicoes) + ")"
        if filtro:
            onde += f" AND ({filtro})"
        blocos.append(
            f"SELECT '{nome.replace(chr(39), chr(39) * 2)}' AS BUSCADO, "
            f"{e['extra']} FROM {e['tabela']} WHERE {onde} "
            f"AND ROWNUM <= {max_cand}"
        )

    if not blocos:
        return ""
    return "\nUNION ALL\n".join(blocos)


def classifica(nomes: list[str], linhas_oracle: list[dict]) -> Resolucao:
    """Separa em resolvido / ambíguo / não achado.

    Um candidato -> resolve. Vários -> o usuário decide. Nenhum -> não achado.

    A exceção: se um candidato bate EXATAMENTE com o nome buscado e os
    outros não, ele vence — "AGUAS PRATA" contra ["AGUAS PRATA", "AGUAS
    PRATA DISTRIBUIDORA"] resolve no primeiro.
    """
    por_nome: dict[str, list] = {}
    for l in linhas_oracle:
        buscado = str(l.get("BUSCADO", ""))
        por_nome.setdefault(buscado, []).append(
            {k: v for k, v in l.items() if k != "BUSCADO"})

    r = Resolucao()
    for nome in nomes:
        cands = por_nome.get(nome, [])
        if not cands:
            r.nao_achado.append(nome)
        elif len(cands) == 1:
            r.resolvido[nome] = cands[0]
        else:
            alvo = normaliza_texto(nome)
            exatos = [c for c in cands
                      if normaliza_texto(c.get("NOME", "")) == alvo]
            if len(exatos) == 1:
                r.resolvido[nome] = exatos[0]
            else:
                r.ambiguo[nome] = cands
    return r


def texto_para_o_usuario(entidade: str, r: Resolucao) -> str:
    """Como o agente deve apresentar o resultado. Sem esconder o que falhou."""
    e = ENTIDADES.get(entidade, {})
    linhas = [
        f"{len(r.resolvido)} de "
        f"{len(r.resolvido) + len(r.ambiguo) + len(r.nao_achado)} "
        f"{entidade}(s) resolvidos."
    ]
    if e.get("regra"):
        linhas.append(f"Regra aplicada: {e['regra']}.")
    if r.ambiguo:
        linhas.append(f"\n{len(r.ambiguo)} com mais de um candidato — "
                      f"preciso que você escolha:")
        for nome, cands in list(r.ambiguo.items())[:10]:
            opcoes = " · ".join(
                f"{list(c.values())[0]} {c.get('NOME', '')[:34]}"
                for c in cands[:4])
            linhas.append(f"  \"{nome}\" -> {opcoes}")
        if len(r.ambiguo) > 10:
            linhas.append(f"  ... e mais {len(r.ambiguo) - 10}")
    if r.nao_achado:
        linhas.append(f"\n{len(r.nao_achado)} sem nenhum candidato: "
                      + ", ".join(f'"{n}"' for n in r.nao_achado[:8]))
        if len(r.nao_achado) > 8:
            linhas.append(f"  ... e mais {len(r.nao_achado) - 8}")
    return "\n".join(linhas)

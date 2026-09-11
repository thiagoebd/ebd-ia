"""Ferramentas de planilha para o agente.

TRÊS FERRAMENTAS, TRÊS MOMENTOS

  planilha_resumo    o que tem aqui? (colunas, tipos, contagem, exemplos)
  planilha_resolver  esses NOMES, quais são no Winthor? (com crítica)
  planilha_cruzar    junta a planilha com uma consulta ao Winthor

O QUE O AGENTE NUNCA VÊ

As linhas. Nem 50, nem 50.000 — elas ficam no Postgres e o cruzamento
acontece em Python. O agente vê resumos: quantos casaram, quantos não,
e alguns exemplos. Isso mantém o custo constante e a resposta honesta.

O agente também NÃO decide sozinho entre candidatos ambíguos de nome —
ele traz a lista e pergunta. Entregar planilha com 480 de 500 casados,
sem dizer, é o mesmo erro de inventar número.
"""
from __future__ import annotations

PLANILHA_RESUMO_TOOL = {
    "name": "planilha_resumo",
    "description": (
        "Mostra o que a planilha anexada contém: nome das colunas, tipo de "
        "cada uma, quantas linhas e alguns exemplos de valores. "
        "USE SEMPRE ANTES de qualquer outra coisa com planilha — sem isso "
        "você não sabe quais colunas existem e vai chutar nome de coluna. "
        "Não traz as linhas: elas ficam no banco."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "planilha_id": {
                "type": "string",
                "description": "Id da planilha. Omita para usar a última anexada.",
            },
        },
    },
}

PLANILHA_RESOLVER_TOOL = {
    "name": "planilha_resolver",
    "description": (
        "Descobre o CÓDIGO no Winthor a partir de uma coluna de NOMES.\n\n"
        "Use quando a planilha tem 'CLIENTE', 'FORNECEDOR', 'PRODUTO', "
        "'FILIAL' ou 'VENDEDOR' por extenso, em vez do código.\n\n"
        "A busca é por TOKENS: 'thiago parreira' casa com 'THIAGO MARTINS "
        "PARREIRA'. O resultado vem em tres grupos:\n"
        "  resolvidos — um candidato só, já casou\n"
        "  ambiguos   — VÁRIOS candidatos: MOSTRE ao usuário e PERGUNTE "
        "qual é, não escolha sozinho\n"
        "  nao_achados — nenhum candidato\n\n"
        "SEMPRE diga ao usuário quantos ficaram em cada grupo. Entregar "
        "resultado parcial como se fosse completo é erro grave."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "coluna": {
                "type": "string",
                "description": "Nome da coluna da planilha que tem os nomes.",
            },
            "entidade": {
                "type": "string",
                "enum": ["cliente", "fornecedor", "produto", "filial", "vendedor"],
                "description": (
                    "O que esses nomes são. fornecedor resolve sempre pela "
                    "RAIZ; vendedor traz só RCA de campo ativo."
                ),
            },
            "planilha_id": {"type": "string"},
        },
        "required": ["coluna", "entidade"],
    },
}

PLANILHA_CRUZAR_TOOL = {
    "name": "planilha_cruzar",
    "description": (
        "Junta a planilha com dados do Winthor e devolve o resultado.\n\n"
        "Como funciona: você escreve uma consulta SQL normal ao Winthor, "
        "usando o marcador :chaves onde entram os valores da planilha. "
        "A ferramenta pega os valores da coluna indicada, normaliza "
        "(zero à esquerda, notação científica, pontuação de CNPJ), quebra "
        "em blocos de 1000 (limite do Oracle), executa e junta tudo.\n\n"
        "Exemplo — planilha com CODPROD, quer estoque e fornecedor:\n"
        "  coluna_planilha: 'CODIGO'\n"
        "  coluna_winthor: 'CODPROD'\n"
        "  sql: SELECT e.CODPROD, e.QTESTGER, f.FORNECEDOR\n"
        "       FROM EBD.PCEST e\n"
        "       JOIN EBD.PCPRODUT p ON p.CODPROD = e.CODPROD\n"
        "       JOIN EBD.PCFORNEC f ON f.CODFORNEC = p.CODFORNEC\n"
        "       WHERE e.CODPROD IN (:chaves) AND e.CODFILIAL = '18'\n\n"
        "Devolve QUANTOS casaram e quantos não, com exemplos dos que "
        "ficaram de fora. DIGA ISSO ao usuário — nunca apresente o "
        "resultado como se tivesse casado tudo.\n\n"
        "O resultado vira uma planilha nova, que você pode exportar com "
        "create_excel."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "coluna_planilha": {
                "type": "string",
                "description": "Coluna da planilha com a chave (ex.: CODIGO).",
            },
            "sql": {
                "type": "string",
                "description": "SQL ao Winthor com :chaves no IN (...).",
            },
            "coluna_winthor": {
                "type": "string",
                "description": "Coluna do resultado que casa com a da planilha.",
            },
            "tipo_chave": {
                "type": "string",
                "enum": ["codigo", "texto"],
                "default": "codigo",
                "description": (
                    "codigo: normaliza zero à esquerda, notação científica e "
                    "pontuação. texto: maiúsculas sem acento."
                ),
            },
            "planilha_id": {"type": "string"},
        },
        "required": ["coluna_planilha", "sql", "coluna_winthor"],
    },
}

FERRAMENTAS = [PLANILHA_RESUMO_TOOL, PLANILHA_RESOLVER_TOOL, PLANILHA_CRUZAR_TOOL]

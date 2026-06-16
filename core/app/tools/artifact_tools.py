"""Schema das tools de artefato que o Claude vê.

Por enquanto: create_excel. PDF e PPTX virão nas próximas etapas.
"""

CREATE_EXCEL_TOOL = {
    "name": "create_excel",
    "description": (
        "OBRIGATÓRIO chamar esta tool quando o usuário pedir Excel/planilha/xlsx/baixar. "
        "Não chamar = bug grave. Gera planilha .xlsx com cabeçalho EBD, tabela nativa "
        "com filtros, formatação condicional opcional, salva em /var/ebd-ia/artifacts/ "
        "e retorna ID do artefato pro frontend mostrar card de download. "
        "NUNCA gere espontaneamente (só quando pedido). REUTILIZE rows que oracle_query "
        "acabou de retornar nesta mesma rodada — NÃO rode oracle_query duas vezes. "
        "Se oracle_query falhar, ajuste o SQL e tente de novo — não desista da planilha."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Título da planilha — vira nome do arquivo e cabeçalho. Ex: 'Top 10 Filiais — Faturamento Líquido MTD'",
            },
            "subtitle": {
                "type": "string",
                "description": "Subtítulo curto. Ex: 'Visão BR · MTD jun/2026'",
            },
            "sheets": {
                "type": "array",
                "description": "Lista de abas. Geralmente uma só.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Nome da aba, max 31 chars"},
                        "columns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {"type": "string", "description": "Chave do dado em rows"},
                                    "label": {"type": "string", "description": "Cabeçalho mostrado no Excel"},
                                    "type": {
                                        "type": "string",
                                        "enum": ["text", "money", "int", "percent", "date"],
                                    },
                                },
                                "required": ["key", "label", "type"],
                            },
                        },
                        "rows": {
                            "type": "array",
                            "description": "Linhas de dado. Cada objeto tem as chaves de columns.",
                            "items": {"type": "object"},
                        },
                        "highlights": {
                            "type": "array",
                            "description": "Formatação condicional opcional.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "column": {"type": "string"},
                                    "rule": {"type": "string", "enum": ["below", "above"]},
                                    "value": {"type": "number"},
                                    "color": {"type": "string", "enum": ["red", "green", "amber"]},
                                },
                                "required": ["column", "rule", "value", "color"],
                            },
                        },
                    },
                    "required": ["name", "columns", "rows"],
                },
            },
            "metadata": {
                "type": "object",
                "description": "Metadados pra aba 'Metadados' (linguagem de negócio, sem schema técnico).",
                "properties": {
                    "source_label": {"type": "string", "description": "Ex: 'Faturamento Líquido EBD · visão BR'"},
                    "period": {"type": "string", "description": "Ex: 'MTD jun/2026'"},
                    "scope": {"type": "string", "description": "Ex: '21 filiais consolidadas'"},
                },
            },
        },
        "required": ["title", "sheets"],
    },
}

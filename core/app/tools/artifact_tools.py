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
        " DADOS GRANDES (>50 linhas): voce so ve um PREVIEW de 50 linhas — use "
        "use_last_result=true para a planilha conter TODAS as linhas da ultima "
        "consulta (o sistema injeta os dados; NAO re-digite linhas no parametro rows)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "use_last_result": {
                "type": "boolean",
                "description": ("true = o sistema injeta TODAS as linhas da ultima "
                                "oracle_query desta conversa na (unica) aba. "
                                "OBRIGATORIO quando o resultado tem >50 linhas. "
                                "Envie a aba com name+columns e SEM rows."),
            },
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


CREATE_PDF_TOOL = {
    "name": "create_pdf",
    "description": (
        "OBRIGATÓRIO chamar esta tool quando o usuário pedir PDF/relatório/imprimir/exportar PDF. "
        "Não chamar = bug grave. Gera relatório .pdf clean com cabeçalho EBD (logo top-right + título), "
        "rodapé com data e disclaimer, salva em /var/ebd-ia/artifacts/ e retorna ID do artefato pro "
        "frontend mostrar card de download. O CONTEÚDO do PDF é Markdown (mesmo formato da resposta "
        "no chat — você passa as seções, tabela e análise como markdown_body). "
        "NUNCA gere espontaneamente (só quando pedido). REUTILIZE rows que oracle_query acabou de "
        "retornar nesta mesma rodada — NÃO rode oracle_query duas vezes. "
        "Se oracle_query falhar, ajuste o SQL e tente de novo — não desista do PDF."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Título do relatório — vira nome do arquivo e cabeçalho. Ex: 'Ruptura por Filial — 16/06/2026'",
            },
            "subtitle": {
                "type": "string",
                "description": "Subtítulo curto. Ex: 'Visão BR · hoje 16/06/2026'",
            },
            "markdown_body": {
                "type": "string",
                "description": (
                    "Conteúdo do relatório em Markdown. Use ## para seções (ex: Resumo executivo, "
                    "Detalhamento, Próximos passos). Use tabela markdown (| col | col |) pros dados. "
                    "Use **negrito** pra destaque. NÃO repita o título (já está no cabeçalho). "
                    "NÃO inclua data/rodapé (já estão no template)."
                ),
            },
            "metadata": {
                "type": "object",
                "description": "Metadados pra linha de contexto abaixo do subtítulo (linguagem de negócio, sem schema técnico).",
                "properties": {
                    "source_label": {"type": "string", "description": "Ex: 'Ruptura de Pedidos · visão BR'"},
                    "period": {"type": "string", "description": "Ex: 'hoje 16/06/2026'"},
                    "scope": {"type": "string", "description": "Ex: '8 filiais com ocorrência'"},
                },
            },
        },
        "required": ["title", "markdown_body"],
    },
}


# ───────────────────────── PowerPoint / Apresentações ─────────────────────────

CREATE_PPTX_TOOL = {
    "name": "create_pptx",
    "description": (
        "Gera deck PowerPoint (.pptx) com identidade visual EBD. "
        "USE quando o usuário pedir apresentação/slides/ppt/powerpoint/deck/'manda em ppt'. "
        "NÃO use create_pdf nem create_excel nesses casos.\n\n"
        "SCHEMA DE CADA SLIDE (campo 'kind' obrigatório):\n\n"
        "1) cover (1º slide, obrigatório):\n"
        "   {'kind':'cover', 'title':'...', 'subtitle':'...', 'eyebrow_label':'...' (opcional)}\n\n"
        "2) intro (2º slide, obrigatório):\n"
        "   {'kind':'intro', 'title':'O que vamos ver', 'lead':'descrição curta', "
        "'bullets':['descrição da seção 1', 'descrição da seção 2', ...]}\n\n"
        "3) stat_callout (1-3 números gigantes em destaque):\n"
        "   {'kind':'stat_callout', 'title':'...', 'subtitle':'...' (opcional), "
        "'stats':[{'label':'FATURAMENTO MTD', 'value':'R$ 15,1M', 'description':'detalhe'}, ...]}\n"
        "   Use pra abrir com impacto (totais, %, share).\n\n"
        "4) kpi_grid (3-4 KPIs em cards):\n"
        "   {'kind':'kpi_grid', 'title':'...', 'subtitle':'...' (opcional), "
        "'kpis':[{'label':'...', 'value':'...', 'description':'...', 'highlighted':true (opcional)}, ...]}\n\n"
        "5) table (tabela ordenada):\n"
        "   {'kind':'table', 'title':'...', 'subtitle':'...' (opcional), "
        "'columns':[{'key':'filial','label':'Filial','type':'text','width':2.5}, "
        "{'key':'liq','label':'Líquido','type':'money','width':1.2}, "
        "{'key':'pct','label':'% Meta','type':'percent','width':0.9}], "
        "'rows':[{'filial':'EBD SP','liq':1888711,'pct':8.52}, ...]}\n"
        "   IMPORTANTE: 'columns' SEMPRE lista de DICTS (NÃO strings). "
        "Types disponíveis: text, money, int, percent.\n\n"
        "6) bullets (leituras/observações finais):\n"
        "   {'kind':'bullets', 'title':'...', 'subtitle':'...' (opcional), "
        "'items':[{'label':'Destaque', 'text':'observação detalhada'}, ...]}\n"
        "   IMPORTANTE: campo é 'items' (NÃO 'bullets', NÃO 'points', NÃO 'texts').\n\n"
        "REGRAS:\n"
        "- SEMPRE: cover + intro + 1-N slides de dados\n"
        "- NUNCA: gerar quote_dark/closing com frases de efeito inventadas\n"
        "- SE A TOOL RETORNAR ERRO: NÃO tentar refazer mais de 1 vez — reporte ao usuário em uma frase e ofereça PDF/Excel como alternativa\n"
        "- REUSAR dados de queries Oracle já executadas na rodada — NÃO rerodar"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title":         {"type": "string", "description": "Título da capa"},
            "subtitle":      {"type": "string", "description": "Subtítulo vermelho da capa"},
            "footer_author": {"type": "string", "description": "Autor/área (rodapé)"},
            "slides": {
                "type": "array",
                "description": "Lista de slides; cada um com 'kind' obrigatório e demais campos conforme schema acima",
                "items": {"type": "object"}
            }
        },
        "required": ["title", "subtitle", "slides"]
    }
}


CREATE_CHART_TOOL = {
    "name": "create_chart",
    "description": (
        "Gera grafico interativo renderizado NA CONVERSA (nao e download). "
        "Chamar quando o usuario pedir grafico/visualizacao/evolucao/tendencia, "
        "OU quando serie temporal ou comparacao visual comunicar melhor que tabela. "
        "REGRAS (nao violar): 'line' SO para serie temporal; 'bar' SO para comparacao "
        "de magnitude entre categorias; ranking onde o usuario precisa do VALOR EXATO "
        "continua TABELA (nao chame esta tool); pizza NAO existe; maximo 2 series. "
        "footer e OBRIGATORIO: a regra do dado em linguagem de negocio "
        "(bruto/liquido, periodo, agrupamento), como no rodape das respostas. "
        "REUTILIZE rows que oracle_query acabou de retornar nesta rodada — "
        "NAO rode oracle_query de novo so para o grafico."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "chart_type": {"type": "string", "enum": ["line", "bar"],
                           "description": "line = serie temporal; bar = comparacao entre categorias"},
            "title": {"type": "string", "description": "Ex: 'Faturamento Liquido — ultimos 7 dias'"},
            "x_key": {"type": "string", "description": "Chave do eixo X em data. Ex: 'dia'"},
            "series": {"type": "array", "maxItems": 2,
                       "items": {"type": "object", "properties": {
                           "key": {"type": "string"}, "label": {"type": "string"}},
                           "required": ["key", "label"]},
                       "description": "1 a 2 series numericas"},
            "data": {"type": "array", "maxItems": 60,
                     "items": {"type": "object"},
                     "description": "Pontos. Cada item tem x_key + as keys das series (numericos)"},
            "y_format": {"type": "string", "enum": ["money", "int", "percent"]},
            "footer": {"type": "string",
                       "description": "OBRIGATORIO. Rodape de fonte em linguagem de negocio"},
        },
        "required": ["chart_type", "title", "x_key", "series", "data", "footer"],
    },
}


CREATE_ROUTE_MAP_TOOL = {
    "name": "create_route_map",
    "description": (
        "Plota no MAPA (renderizado na conversa) o roteiro de um vendedor/RCA — "
        "os clientes da rota como marcadores, na ordem de visita. "
        "Chamar quando o usuario pedir 'roteiro', 'rota do vendedor no mapa', "
        "'onde estao os clientes do RCA', 'mapa da rota'. "
        "Fonte da coordenada: PCCLIENT.LATITUDE/LONGITUDE (join por CODCLI na PCROTACLI). "
        "REUTILIZE as rows que oracle_query acabou de retornar — NAO rode a query de novo. "
        "Passe TODOS os pontos que tem coordenada; o backend deduplica por codcli e "
        "descarta lat/lng invalidos. Idealmente filtre por UM dia (DIASEMANA) para o "
        "roteiro-dia; a rota inteira do RCA e a carteira toda, nao um roteiro. "
        "footer OBRIGATORIO: fonte + escopo (ex: 'Rota ativa do RCA X, quarta-feira — "
        "coordenada de cadastro PCCLIENT')."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string",
                      "description": "Ex: 'Roteiro RCA 3366 (Antonio Fernando) — quarta'"},
            "rca": {"type": "string",
                    "description": "Identificacao do RCA. Ex: '3366 — Antonio Fernando (fil 08)'"},
            "points": {
                "type": "array", "maxItems": 200,
                "items": {
                    "type": "object",
                    "properties": {
                        "seq": {"type": "integer", "description": "SEQUENCIA da rota"},
                        "codcli": {"type": "integer"},
                        "cliente": {"type": "string"},
                        "lat": {"type": "string", "description": "LATITUDE (string do Oracle)"},
                        "lng": {"type": "string", "description": "LONGITUDE (string do Oracle)"},
                        "municipio": {"type": "string"},
                        "status": {"type": "string",
                            "enum": ["vendeu", "visitou_nao_vendeu", "nao_visitou", "fora_rota"],
                            "description": "Status do cliente no dia (colore o pin). vendeu=verde, "
                                           "visitou_nao_vendeu=vermelho, nao_visitou=amarelo, fora_rota=azul"},
                    },
                    "required": ["codcli", "cliente", "lat", "lng"],
                },
                "description": "Clientes da rota COM coordenada. Backend deduplica por codcli.",
            },
            "footer": {"type": "string",
                       "description": "OBRIGATORIO. Fonte + escopo do roteiro em linguagem de negocio."},
        },
        "required": ["title", "rca", "points", "footer"],
    },
}

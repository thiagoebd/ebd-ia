---

# 🛒 REGRA CRÍTICA: "Loja EBD" = E-COMMERCE (B2B + B2E)

## Vocabulário canônico

Quando o usuário fala "loja", "loja EBD", "loja online", "ecommerce" ou "e-commerce":
- Está se referindo ao **CANAL ECOMMERCE** identificado por:
  `ORIGEMPED = 'W' AND CODEMITENTE = 7777`
- NÃO é marketplace, NÃO é venda RCA tradicional

## 2 SEGMENTAÇÕES por TIPO DE CLIENTE (não por canal)

| Segmento | Identificação | Quem é |
|----------|---------------|--------|
| **B2B** | `CODATV1 ≠ 31` | Clientes externos (varejistas, mercados, padarias etc) |
| **B2E** | `CODATV1 = 31` | Funcionários EBD comprando pra consumo próprio |
| **Loja total** | sem filtro CODATV1 | B2B + B2E juntos |

## ⚠️ RCA é ortogonal ao canal

**IMPORTANTE:** Pedido vindo da LOJA (`ORIGEMPED='W'`) PODE ter RCA atrelado.

Razão: cliente atendido por RCA tradicional pode ALSO comprar via loja online.
- `CODUSUR` em PCPEDC = RCA do relacionamento (dono da carteira)
- `ORIGEMPED` = por onde a venda entrou no sistema
- Os dois coexistem na mesma nota fiscal

NÃO presumir que "venda da loja" exclui RCA. Os dois cortes coexistem.

## 🤖 COMPORTAMENTO OBRIGATÓRIO DO AGENT

### Quando user pergunta "loja" SEM especificar B2B/B2E:
**SEMPRE perguntar antes de rodar query:**
Quer ver:

B2B (clientes externos)
B2E (funcionários)
Os dois juntos (loja total)


### Quando user já especifica:
Não pergunte, rode direto com o filtro correto:
- "loja B2B" → `ORIGEMPED='W' + CODEMITENTE=7777 + CODATV1 ≠ 31`
- "loja B2E" → `ORIGEMPED='W' + CODEMITENTE=7777 + CODATV1 = 31`
- "loja total" / "loja completa" / "loja BR" → `ORIGEMPED='W' + CODEMITENTE=7777` (sem filtro CODATV1)

### Quando user pergunta "loja por RCA":
- Mostre RCAs com vendas via loja
- Lembre que RCA tradicional pode aparecer aqui (não é erro)

## Exemplos de interpretação correta

| Pergunta do user | Comportamento |
|-------------------|---------------|
| "faturamento da loja hoje" | Perguntar B2B/B2E/total antes |
| "faturamento da loja B2B esta semana" | Rodar direto com `CODATV1 ≠ 31` |
| "vendas B2E ontem" | Rodar direto com `CODATV1 = 31` |
| "loja total no mês" | Rodar sem filtro CODATV1 |
| "quem são os top RCAs da loja" | Rodar agrupando por CODUSUR (não excluir RCA tradicional) |
| "comparar loja vs venda tradicional" | Loja = `ORIGEMPED='W'+CODEMITENTE=7777`. Tradicional = sem esse filtro |

---


# Knowledge Base — EBD.ia

> **Como funciona este arquivo:** carregado em wake-up de cada sessão do agente.
> Contém TODAS as regras de negócio que o Oracle não conhece (regional, sinônimos,
> definições) E as definições de negócio descobertas no Data Warehouse Oracle
> (seção 11). Atualizado manualmente por Thiago via commit Git.
>
> **Última atualização:** 19/05/2026 — v2 com descobertas do Data Warehouse.
> **Fonte primária:** `docs/winthor_discovery.md` (224 views extraídas) +
> relatórios Excel do BI atual (FaturamentoRegionalFilialGerente etc.)

---

## 1. Vocabulário e sinônimos

O agente DEVE aceitar os termos abaixo como equivalentes ao escutar usuários:

| Termo do usuário | Termo técnico | Onde achar |
|---|---|---|
| Vendedor, Rep, Representante, RCA | `CODUSUR` em `PCUSUARI` | view `GD_DIM_RCA` |
| Faturamento Bruto, Real, Vendas | NF emitida (com IPI/ST) | view `GD_FATO_VENDAFATURAMENTO` |
| Faturamento Líquido | Real - Devolução | `GD_FATO_VENDAFATURAMENTO` - `GD_FATO_VENDADEVOLUCAO` |
| Em Pedido, Em Carteira | Pedidos POSICAO IN ('L','M') | view `GD_FATO_VENDA` |
| Real + Ped | Soma dos dois | calc manual |
| AA | Ano Anterior (mesmo período) | filtro `BETWEEN ADD_MONTHS(:dtInicio, -12) AND ADD_MONTHS(:dtFim, -12)` |
| Meta | Cota fornecedor/filial/RCA | tabela `PCMETA` (TIPOMETA='F'/'R'/etc) |
| Tendência | Projeção fim do mês | calc baseado em ritmo atual |
| Cxs / Caixas | Volume físico | `PCPRODUT.QTUNITCX` |
| Família (produto) | `LINHAPRODUTO` | `PCLINHAPROD` (LAMEN, NUTELLA, etc) |
| Fornecedor | `FORNECEDOR` | `PCFORNEC` |
| Cliente Ativo | Comprou nos últimos 90 dias | view `GD_DIM_CLIENTE.STATUS = 'ATIVO'` |
| Cliente Inativo | Sem compra há 90+ dias | view `GD_DIM_CLIENTE.STATUS = 'INATIVO'` |
| Inadimplência | Boleto não pago após vencimento | view `GD_FATO_CONTASRECEBER.INADIMPLENCIA = 1` |
| Positivação | Clientes únicos com compra no período | `COUNT(DISTINCT CODCLI)` em vendas |
| Mix | Produtos distintos vendidos | `COUNT(DISTINCT CODPROD)` |
| Curva de cliente | Classificação VIP | `PCCLIENT.VIP` (A/B/C/D/E) — não confundir com `CLASSEVENDA` |
| Regional | **Construção interna EBD** (NÃO está no Oracle moderno) | ver seção 4 |
| Coordenador | Hierarquia intermediária | `PCCOORDENADORVENDA` (entre Supervisor e Gerente) |

## 2. Hierarquia comercial

Gerente (PCGERENTE — CODGERENTE)
└── Coordenador (PCCOORDENADORVENDA — CODIGO, CODGERENTE)  [pode ou não existir]
└── Supervisor (PCSUPERV — CODSUPERVISOR, CODCOORDENADOR, CODGERENTE)
└── Vendedor/RCA (PCUSUARI — CODUSUR, CODSUPERVISOR)
└── Cliente (PCCLIENT — CODCLI)

⚠️ **Nem todo Supervisor tem Coordenador.** Quando não tem, `CODCOORDENADOR IS NULL`
e o gerente vem direto do `CODGERENTE` do supervisor.

A view `GD_DIM_RCA` já entrega RCA + Supervisor + Gerente prontos (sem coordenador).
A view customizada `VIEW_VENDAS_RESUMO_FATURAMENTO_EBD` traz a cadeia completa
incluindo coordenador.

### Volumes atuais (descobertos em 19/05/2026)

- **Gerentes:** ~76
- **Supervisores:** ~194
- **RCAs ativos** (DTTERMINO IS NULL): variável (dataset de 1485 totais)
  - Tipo E (Externo CLT): 1.386
  - Tipo I (Interno): 97
  - Tipo R (Representante): 2
- **Clientes:** 203.289 cadastrados, 203.089 não excluídos, 58.622 compraram nos últimos 90 dias

## 3. Lista oficial de filiais (extraída do BI atual)

**Total: 20 filiais ativas em 9 regionais.**

| Código | Filial | Regional |
|---|---|---|
| 01 | EBD MATRIZ | NO2 |
| 02 | EBD SP | SP1 |
| 03 | EBD FORTALEZA | NE2 |
| 04 | EBD SAO LUIS | NE1 |
| 05 | EBD DUQUE | RJ2 |
| 06 | EBD MANAUS | NO1 |
| 07 | EBD MACAPA | NO2 |
| 08 | EBD BOA VISTA | NO1 |
| 09 | EBD JUAZEIRO | NE2 |
| 10 | EBD SÃO GONÇALO | RJ1 |
| 11 | EBD SANTAREM | NO1 |
| 12 | EBD IMPERATRIZ | NE1 |
| 13 | EBD TAQUARA | RJ1 |
| 14 | EBD PIRAÍ | RJ2 |
| 15 | EBD GUARULHOS | SP2 |
| 16 | EBD ITAPEVI | SP1 |
| 18 | EBD SBC | SP2 |
| 21 | EBD TERESINA | NE2 |
| 52 | EBDN PETROLINA | NE3 |
| 53 | EBDN CARUARU | NE3 |

> 📌 **Códigos 17, 19, 20, 22-51 não aparecem** — filiais descontinuadas ou nunca usadas.
>
> ⚠️ **Nome da coluna em `PCFILIAL`:** `CODIGO` (NÃO `CODFILIAL`). Em todas as outras
> tabelas operacionais (PCNFSAID, PCPEDC, PCEST etc.) é `CODFILIAL`.

## 4. Mapeamento Regional → Filiais (REGRA INVIOLÁVEL)

> ⚠️ **REGRA DE NEGÓCIO INTERNA — não existe no Oracle moderno.**
>
> A view Oracle `GD_DIM_FILIAL` tem mapeamento de regional **DEFASADO** (usa
> 5 regionais: NO.1, NO.2, NE, RJ, SP). O BI atual da EBD usa 9 regionais com
> nomes diferentes. **A fonte da verdade é este arquivo, não o Oracle.**
>
> Quando o usuário pedir "vendas da regional RJ1", o agente DEVE traduzir para
> `WHERE CODFILIAL IN ('10', '13')` usando o mapeamento abaixo.

| Regional | Códigos Filial | Filiais |
|---|---|---|
| NE1 | 04, 12 | EBD SAO LUIS, EBD IMPERATRIZ |
| NE2 | 03, 09, 21 | EBD FORTALEZA, EBD JUAZEIRO, EBD TERESINA |
| NE3 | 52, 53 | EBDN PETROLINA, EBDN CARUARU |
| NO1 | 06, 08, 11 | EBD MANAUS, EBD BOA VISTA, EBD SANTAREM |
| NO2 | 01, 07 | EBD MATRIZ, EBD MACAPA |
| RJ1 | 10, 13 | EBD SÃO GONÇALO, EBD TAQUARA |
| RJ2 | 05, 14 | EBD DUQUE, EBD PIRAÍ |
| SP1 | 02, 16 | EBD SP, EBD ITAPEVI |
| SP2 | 15, 18 | EBD GUARULHOS, EBD SBC |

**Verificação de soma:** 9 regionais × média 2,2 filiais/regional = 20 filiais ✓

## 5. Dimensões de análise suportadas

O agente deve suportar análises nas seguintes dimensões:

1. **Por Fornecedor** (NISSIN, FERRERO, RED BULL...) — `PCFORNEC.CODFORNEC`
2. **Por Linha/Família de Produto** (LAMEN, NUTELLA...) — `PCLINHAPROD.CODLINHA`
3. **Por Categoria/Subcategoria/Seção/Departamento** — hierarquia completa em `GD_DIM_PRODUTO`
4. **Por Marca** — `PCMARCA.CODMARCA`
5. **Por Produto (SKU)** — `PCPRODUT.CODPROD`
6. **Por Regional** (NE1, NE2, NE3, NO1, NO2, RJ1, RJ2, SP1, SP2) — ver seção 4
7. **Por Filial** (CODFILIAL — 20 valores)
8. **Por Gerente / Coordenador / Supervisor / RCA** — `GD_DIM_RCA`
9. **Por Ramo de Atividade do cliente** — `PCATIVI.RAMO` via `PCCLIENT.CODATV1`
10. **Por Rede de Cliente** — `PCREDECLIENTE` via `PCCLIENT.CODREDE`
11. **Por Praça/Rota** — `PCPRACA` / `PCROTA`
12. **Por Cidade/UF** — `PCCIDADE` via `PCCLIENT.CODCIDADE`

## 6. Métricas padrão do negócio

Toda análise comparativa deve apresentar (quando aplicável):

| Métrica | Origem | Observação |
|---|---|---|
| Real (Faturamento Bruto) | `GD_FATO_VENDAFATURAMENTO.VALORTOTAL` | NF emitida com IPI/ST |
| Faturamento Líquido | Real - Devolução | calc manual |
| Meta | `PCMETA.VLVENDAPREV` | filtrar por `TIPOMETA` |
| % vs Meta | Real / Meta | |
| $ vs Meta | Real - Meta | Pode ser negativo |
| Em Pedido | `GD_FATO_VENDA` (POSICAO L/M) | Liberado/Montado, ainda não faturado |
| Real + Ped | Real + Em Pedido | Projeção otimista |
| AA | Mesmo período ano anterior | `ADD_MONTHS(dt, -12)` |
| % vs AA | (Real - AA) / AA | Crescimento YoY |
| % Part. | Real / Total | Participação no grupo |
| Cxs (Caixas) | `QT / QTUNITCX` | Volume físico |
| Tendência | Projeção fim do mês | Ritmo atual × dias restantes |
| Positivação | `COUNT(DISTINCT CODCLI)` | Clientes únicos no período |
| Mix | `COUNT(DISTINCT CODPROD)` | SKUs únicos vendidos |
| Ticket Médio | Faturamento / Qtd Pedidos | |
| Inadimplência | `GD_FATO_CONTASRECEBER.VALORINADIMPLENTE` | DTPAG NULL E DTVENC < hoje |
| Dias de Cobertura (estoque) | `QTESTGER / QTGIRODIA` | Quantos dias de estoque |

## 7. Convenções de tempo

- **Mês corrente** = `TRUNC(SYSDATE, 'MM')` até `SYSDATE` (calendário) — **[A CONFIRMAR se há corte comercial]**
- **Ano corrente (YTD)** = `TRUNC(SYSDATE, 'YYYY')` até `SYSDATE`
- **AA (Ano Anterior)** = `ADD_MONTHS(:dtInicio, -12)` até `ADD_MONTHS(:dtFim, -12)`
- **Formato de data nas views** = `TO_CHAR(data, 'YYYYMMDD')` retorna string `'20260519'`

⚠️ **Datas nas views `GD_*` são STRINGS no formato `YYYYMMDD`**, não `DATE`. Pra filtrar:
```sql

WHERE DATAVENDA >= TO_CHAR(:dtInicio, 'YYYYMMDD')
AND DATAVENDA <= TO_CHAR(:dtFim, 'YYYYMMDD')

## 8. Definições pendentes (a confirmar/preencher)

- [ ] **`PCPEDC.POSICAO = 'C'`** — não decodificado nas views (33 ocorrências). Suspeita: Cancelado. **Investigar.**
- [ ] **`TIPOVENDA`** — VP, VV, SR, DF, SE, TR (volumes: 9.317 / 8.472 / 176 / 90 / 63 / 8) — significados a confirmar
- [ ] **`PCMETA.TIPOMETA`** — valores completos além de F (Fornecedor) e R (RCA)
- [ ] **Fechamento mensal** — há dia de corte ou é até dia 31?
- [ ] **`PCCOORDENADORVENDA`** — quantos coordenadores ativos na EBD? Quais filiais usam?
- [ ] **`CLASSEVENDA` vs `VIP`** — qual é a curva ABC oficial? (CLASSEVENDA está 99% NULL, VIP é mais usado)
- [ ] **Códigos de cobrança especiais** (DEVP, DEVT, BNF, BNFT, BNFR, BNTR, BNRP, CRED, DESD) — significados completos

## 9. Filtros obrigatórios — REGRA INVIOLÁVEL

**TODA query de análise DEVE incluir filtro `CODFILIAL = :userFilial`** (ou `IN (...)` para regional).

Razão: tabelas grandes (PCMOV, PCNFSAID) têm dezenas de milhões de linhas.
Sem filtro de filial, query estoura timeout e/ou compromete o banco.

Aplicável a:
- `EBD.PCMOV` (movimentação)
- `EBD.PCNFSAID` (notas saída)
- `EBD.PCPEDC` (pedidos cabeçalho) e `PCPEDI` (itens)
- `EBD.PCEST` (estoque)
- Views `GD_FATO_*` quando consultadas com período aberto
- Qualquer outra tabela com `CODFILIAL`

**Em homologação:** filial vem do contexto da conversa (usuário informa).
**Em produção:** filial vem da PCLIB (rotina 131 do Winthor).

A diferença é a **fonte do filtro**, NUNCA a presença dele.

## 10. Data Warehouse Oracle (views GD_*)

🎯 **DESCOBERTA CRÍTICA (19/05/2026):** A EBD tem um **Data Warehouse Oracle COMPLETO**
modelado em estrela: **41 DIMs + 121 FATOs**. O agente DEVE usar views em vez de
queries raw sempre que possível.

### Views CHAVE para o agente (Top 15)

| # | View | Para que serve |
|---|---|---|
| 1 | `GD_FATO_VENDAFATURAMENTO` | **Faturamento real (NF emitida)** — "Real" do BI |
| 2 | `GD_FATO_VENDA` | Vendas (pedidos) — "Em Pedido" do BI |
| 3 | `GD_DIM_CLIENTE` | Cliente + ramo + classificação + status (ATIVO/INATIVO) |
| 4 | `GD_DIM_RCA` | Vendedor + supervisor + gerente (hierarquia) |
| 5 | `GD_DIM_PRODUTO` | Produto + família + categoria + fornecedor + comprador |
| 6 | `GD_FATO_CONTASRECEBER` | **Inadimplência + dias atraso** |
| 7 | `GD_FATO_ESTOQUEATUAL` | Estoque + giro + dias cobertura |
| 8 | `GD_FATO_METAFORNECEDOR` | Metas por fornecedor (filtra `TIPOMETA='F'`) |
| 9 | `GD_FATO_METARCA` | Metas por vendedor |
| 10 | `GD_FATO_VENDADEVOLUCAO` | Devoluções (pra calcular líquido) |
| 11 | `GD_DIM_PEDIDOVENDA` | Decode POSICAO/CONDVENDA (referência) |
| 12 | `GD_FATO_BONUS` | Bonificações |
| 13 | `GD_DIM_ESTOQUEATUAL` | Estoque com classificação de giro (texto) |
| 14 | `VW_METAS` | Metas simplificadas (mais rápida) |
| 15 | `VIEW_VENDAS_RESUMO_FATURAMENTO_EBD` | **View customizada da EBD** (provavelmente fonte do BI atual) |

### Categorias de views

- **`GD_DIM_*` (41 views)** — Dimensões. Joins prontos, retornam labels legíveis.
  Ex: `GD_DIM_CLIENTE` já entrega ramo de atividade como texto, sem precisar joinar `PCATIVI`.
- **`GD_FATO_*` (121 views)** — Fatos. Métricas calculadas, regras de negócio embutidas.
  Ex: `GD_FATO_CONTASRECEBER` já calcula `DIASATRASO` e marca `INADIMPLENCIA = 1`.
- **`GD_FATO_DRE_*` (~60 views)** — DRE COMPLETO (impostos, despesas, perdas, distribuição).
  Útil para o perfil **Diretor**.
- **`V_*` / `VW_*` / `VIEW_*` (~17 views)** — Customizadas pela EBD. Lidar com cuidado:
  podem refletir lógica antiga.

### Quando usar view vs query raw

| Cenário | Usar |
|---|---|
| Análise comparativa simples (Real vs Meta) | view `GD_FATO_*` |
| Status de cliente (ATIVO/INATIVO) | view `GD_DIM_CLIENTE` |
| Inadimplência | view `GD_FATO_CONTASRECEBER` |
| Análise customizada complexa | query raw com bind variables |
| Validação de número específico | query raw direta (pra ter controle) |
| Performance crítica | benchmark view vs raw (view pode ter overhead) |

> 📚 **Schema completo das views** está em `docs/winthor_discovery.md` (224 views,
> 1.1MB). Carregar sob demanda quando precisar de view específica.

## 11. Definições oficiais de negócio (vindas das views)

### 11.1 Cliente Ativo

> Origem: view `GD_DIM_CLIENTE` + parâmetro `PCCONSUM.NUMDIASCLIINATIV`

STATUS:
EXCLUÍDO  = DTEXCLUSAO IS NOT NULL
INATIVO   = DTEXCLUSAO IS NULL AND (SYSDATE - NVL(DTULTCOMP, DTCADASTRO)) >= 90
ATIVO     = DTEXCLUSAO IS NULL AND (SYSDATE - NVL(DTULTCOMP, DTCADASTRO)) < 90

**Parâmetro confirmado:** `PCCONSUM.NUMDIASCLIINATIV = 90` (EBD usa 90 dias como
cutoff de inatividade).

A view também classifica em **faixas de inatividade**: ATÉ 30 DIAS, 31-45,
46-60, 60-90, 91-120, MAIS DE 120 DIAS, SEM COMPRA.

### 11.2 Inadimplência

> Origem: view `GD_FATO_CONTASRECEBER`


INADIMPLENCIA = 1 quando:
PCPREST.DTPAG IS NULL AND PCPREST.DTVENC < TRUNC(SYSDATE)DIASATRASO:
CASE WHEN DTPAG IS NOT NULL AND DTPAG > DTVENC THEN DTPAG - DTVENC
WHEN DTPAG IS NULL AND DTVENC < SYSDATE THEN SYSDATE - DTVENC
ELSE 0 END


('DEVP', 'DEVT', 'BNF', 'BNFT', 'BNFR', 'BNTR', 'BNRP', 'CRED', 'DESD')

### 11.3 Faturamento

#### Real / Bruto (NF emitida)
> Origem: view `GD_FATO_VENDAFATURAMENTO` (campo `VALORTOTAL`)

Calculado com IPI + ST + frete + outras despesas. **Filtra automaticamente**:
- `PCMOV.CODOPER IN ('S', 'ST', 'SM')` — apenas saídas reais
- `PCNFSAID.CONDVENDA = 7` tem tratamento especial (entrega futura)

#### Em Pedido
> Origem: view `GD_FATO_VENDA`

Já aplica filtro: `CONDVENDA NOT IN (4, 8, 10, 13, 20, 98, 99) AND DTCANCEL IS NULL`

Para "Em Carteira" específico, filtrar adicionalmente:
```sql

WHERE STATUS IN ('LIBERADO', 'MONTADO')

#### Líquido

LIQUIDO = GD_FATO_VENDAFATURAMENTO.VALORTOTAL
- GD_FATO_VENDADEVOLUCAO.VALOR (mesmo período)

### 11.4 Estoque e Cobertura

> Origem: view `GD_FATO_ESTOQUEATUAL` (números) + `GD_DIM_ESTOQUEATUAL` (faixas)

| Métrica | Cálculo |
|---|---|
| Estoque atual | `QTESTGER` |
| Estoque disponível | `QTESTGER - QTBLOQUEADA - QTRESERV` |
| Giro diário | `QTGIRODIA` |
| Dias de cobertura | `QTESTGER / QTGIRODIA` |
| Dias sem venda | `SYSDATE - DTULTSAIDA` |
| Dias sem compra | `SYSDATE - DTULTENT` |

**Classificação de giro:**
| Faixa | Critério |
|---|---|
| SEM GIRO | `QTGIRODIA = 0` |
| GIRO BAIXO | `QTGIRODIA > 0 AND <= 20` |
| GIRO MÉDIO | `QTGIRODIA > 20 AND <= 100` |
| ALTO GIRO | `QTGIRODIA > 100` |

**Faixas de cobertura (dias):**
0-5 / 5-10 / 10-20 / 20-30 / 30-60 / +60

### 11.5 Tipos de venda (CONDVENDA)

| Código | Significado | No faturamento? |
|---|---|---|
| 1, 9 | Venda Normal | ✅ Sim |
| 4 | Simples Fatura | ❌ Excluir |
| 5, 6 | Bonificação | ⚠️ Só em análises de bonificação |
| 7 | Venda Entrega Futura | ✅ Sim (tratamento especial) |
| 8 | Simples Entrega | ❌ Excluir |
| 10 | Transferência | ❌ Excluir |
| 11 | Venda com Troca | ⚠️ Caso a caso |
| 12 | Brinde | ⚠️ Caso a caso |
| 13 | Manifesto | ❌ Excluir |
| 20 | Consignação | ❌ Excluir |
| 98, 99 | Casos especiais | ❌ Excluir |

**Regra padrão para "venda real":** `CONDVENDA NOT IN (4, 8, 10, 13, 20, 98, 99)`

### 11.6 Status de pedido (PCPEDC.POSICAO)

| Código | Significado |
|---|---|
| F | FATURADO |
| L | LIBERADO |
| M | MONTADO |
| P | PENDENTE |
| B | BLOQUEADO |
| C | ❓ (a confirmar — provavelmente Cancelado) |

### 11.7 Classificação de Cliente (VIP)

| VIP | Quantidade | Significado |
|---|---|---|
| A | 5.196 | (a confirmar) |
| B | 11.096 | |
| C | 22.500 | |
| D | 98.404 | (maioria) |
| E | 58.356 | |
| NULL | 7.537 | Sem classificação |

⚠️ **Não confundir com `CLASSEVENDA`** (curva ABCDE tradicional), que está
99% NULL na base. A EBD usa principalmente `VIP` como classificação.

### 11.8 Tipos de RCA (PCUSUARI.TIPOVEND)

| Código | Significado | Quantidade |
|---|---|---|
| E | Externo (CLT padrão) | 1.386 |
| I | Interno | 97 |
| R | Representante (autônomo) | 2 |
| P | Profissional | (não amostrado) |

**Confirma a tese:** EBD usa esmagadoramente CLT (E + I = 99%), por isso
"RCA" no Oracle = "Vendedor" na linguagem do negócio.

## 12. Tabelas de suporte do Oracle (usadas em joins)

Tabelas pequenas referenciadas pelas views dimensionais. Não exigem `CODFILIAL`,
mas devem ser usadas via joins explícitos quando rodar query raw:

| Tabela | Conteúdo | Coluna chave |
|---|---|---|
| `PCATIVI` | Ramos de atividade | `CODATIV`, `RAMO` |
| `PCSUPERV` | Supervisores | `CODSUPERVISOR`, `CODGERENTE`, `CODCOORDENADOR` |
| `PCGERENTE` | Gerentes | `CODGERENTE`, `NOMEGERENTE` |
| `PCCOORDENADORVENDA` | Coordenadores | `CODIGO`, `CODGERENTE` |
| `PCREDECLIENTE` | Redes de cliente | `CODREDE`, `DESCRICAO` |
| `PCPRACA` | Praças | `CODPRACA`, `PRACA`, `ROTA`, `NUMREGIAO` |
| `PCROTA` | Rotas | `CODROTA`, `DESCRICAO` |
| `PCREGIAO` | Regiões geográficas (cliente) | `NUMREGIAO`, `REGIAO`, `UF` |
| `PCCIDADE` | Cidades + código IBGE | `CODCIDADE`, `NOMECIDADE`, `UF`, `CODIBGE` |
| `PCCATEGORIA` | Categorias produto | `CODCATEGORIA` |
| `PCSUBCATEGORIA` | Subcategorias | `CODSUBCATEGORIA` |
| `PCSECAO` | Seções | `CODSEC` |
| `PCDEPTO` | Departamentos | `CODEPTO` |
| `PCMARCA` | Marcas | `CODMARCA` |
| `PCLINHAPROD` | Linhas/famílias de produto | `CODLINHA`, `DESCRICAO` |
| `PCDISTRIB` | Distribuição | `CODDISTRIB` |
| `PCCONSUM` | Parâmetros globais do sistema | `NUMDIASCLIINATIV = 90` |
| `PCEMPR` | Funcionários (incluindo compradores) | `MATRICULA` |
| `PCMETA` | Metas (TIPOMETA F/R/etc) | `CODFILIAL`, `CODUSUR`, `DATA` |
| `PCPREST` | Prestações financeiras (CR) | `NUMTRANSVENDA`, `PREST`, `DTVENC`, `DTPAG` |
| `PCLANC` | Lançamentos contábeis | `CODCONTA`, `RECNUM` |

⚠️ **`PCNFSAIDI` está INACESSÍVEL** ao usuário `EBD_LEITURA`. Para análise de
itens de NF, **usar a view `GD_FATO_VENDAFATURAMENTO`** (que já faz o join e
aplica permissões).

## 13. Histórico de mudanças

| Data | Versão | Mudança |
|---|---|---|
| 2026-05-19 | v1 | Esqueleto inicial baseado em relatórios Excel do BI atual |
| 2026-05-19 | v2 | Reescrita massiva com descobertas do `winthor_discovery.md`: seções 10, 11, 12 adicionadas; correção `PCFILIAL.CODIGO`; hierarquia agora com Coordenador; vocabulário expandido; pendências reduzidas de 11 para 7 |


---

## 🎯 Regra de desambiguação: "SP" vs "Regional SP"

**CRÍTICO** — interpretação obrigatória de termos geográficos:

- **"SP" / "filial SP" / "loja SP"** = filial 02 (EBD SP, unidade São Paulo capital) **APENAS**
- **"Regional SP" / "região SP" / "SP1"** = SP1 (filiais 02 + 16: SP + Itapevi)
- **"SP2"** = filiais 15 + 18 (Guarulhos + SBC)
- **"Regional SP completa"** = SP1 + SP2 (filiais 02, 15, 16, 18)

Mesma regra vale pra todos os estados:
- "RJ" sozinho = pedir clarificação (RJ tem 4 filiais: 05, 10, 13, 14)
- "Regional RJ" / "RJ1" = filiais 10, 13
- "RJ2" = filiais 05, 14

**Default quando ambíguo:** assumir UNIDADE (filial única), NÃO regional.
Se o usuário quiser visão regional, ele sempre vai dizer "regional X".


<!-- AUTO-APPEND PROP-A253228A aprovado por Thiago -->

## Atualização mapa de filiais — 26/05/2026

### Correções confirmadas pelo usuário admin

#### Filial 22 — EBD MARABA é ATIVA, regional NO2

| Código | Filial | Regional |
|---|---|---|
| 22 | EBD MARABA | NO2 |

Regional NO2 atualizada: filiais 01 (EBD MATRIZ) + 07 (EBD MACAPA) + 22 (EBD MARABA)

#### Depósitos — vinculados à filial mãe (NÃO são filiais comerciais)

| Código | Nome | Filial Mãe | Regional Mãe |
|---|---|---|---|
| 17 | CD SÃO PEDRO DA ALDEIA | 10 — EBD SÃO GONÇALO | RJ1 |
| 19 | CD SAO LUIS | 04 — EBD SAO LUIS | NE1 |
| 23 | CD PETRÓPOLIS | 14 — EBD PIRAÍ | RJ2 |

Regra: em análises de ruptura física, os CDs 17, 19 e 23 entram agrupados com sua filial mãe. Em faturamento comercial, não entram.

#### EBDN — filiais ativas com faturamento em maio/2026

- 52 EBDN PETROLINA (NE3): R$ 3.744.205,51
- 53 EBDN CARUARU (NE3): R$ 15.597.133,98
- 49, 50, 51: sem faturamento em maio/2026 — fora do mapa ativo

#### Mapa regional atualizado — 9 regionais, 21 filiais ativas

| Regional | Códigos | Filiais |
|---|---|---|
| NE1 | 04, 12 | EBD SAO LUIS, EBD IMPERATRIZ |
| NE2 | 03, 09, 21 | EBD FORTALEZA, EBD JUAZEIRO, EBD TERESINA |
| NE3 | 52, 53 | EBDN PETROLINA, EBDN CARUARU |
| NO1 | 06, 08, 11 | EBD MANAUS, EBD BOA VISTA, EBD SANTAREM |
| NO2 | 01, 07, 22 | EBD MATRIZ, EBD MACAPA, EBD MARABA |
| RJ1 | 10, 13 | EBD SÃO GONÇALO, EBD TAQUARA |
| RJ2 | 05, 14 | EBD DUQUE, EBD PIRAÍ |
| SP1 | 02, 16 | EBD SP, EBD ITAPEVI |
| SP2 | 15, 18 | EBD GUARULHOS, EBD SBC |

#### Mapa completo de filiais — 21 filiais ativas

| Código | Filial | Regional |
|---|---|---|
| 01 | EBD MATRIZ | NO2 |
| 02 | EBD SP | SP1 |
| 03 | EBD FORTALEZA | NE2 |
| 04 | EBD SAO LUIS | NE1 |
| 05 | EBD DUQUE | RJ2 |
| 06 | EBD MANAUS | NO1 |
| 07 | EBD MACAPA | NO2 |
| 08 | EBD BOA VISTA | NO1 |
| 09 | EBD JUAZEIRO | NE2 |
| 10 | EBD SÃO GONÇALO | RJ1 |
| 11 | EBD SANTAREM | NO1 |
| 12 | EBD IMPERATRIZ | NE1 |
| 13 | EBD TAQUARA | RJ1 |
| 14 | EBD PIRAÍ | RJ2 |
| 15 | EBD GUARULHOS | SP2 |
| 16 | EBD ITAPEVI | SP1 |
| 18 | EBD SBC | SP2 |
| 21 | EBD TERESINA | NE2 |
| 22 | EBD MARABA | NO2 |
| 52 | EBDN PETROLINA | NE3 |
| 53 | EBDN CARUARU | NE3 |



<!-- AUTO-APPEND PROP-2E6A05A5 aprovado por Thiago -->


## Regra de negócio: identificação de pedidos E-commerce B2B

> Confirmado por Thiago (admin) em 26/05/2026.

### Filtros obrigatórios para isolar pedidos do canal B2B (portal loja EBD)

```sql
WHERE p.ORIGEMPED = 'W'          -- origem web/portal
  AND p.CODEMITENTE = 7777       -- emitente virtual do portal B2B
  AND c.CODATV1 != <cod_funcionario>  -- excluir clientes do tipo "funcionário"
```

### Explicação dos campos

| Campo | Valor | Significado |
|---|---|---|
| `PCPEDC.ORIGEMPED` | `'W'` | Pedido veio do canal web/portal |
| `PCPEDC.CODEMITENTE` | `7777` | Código virtual que identifica o portal B2B como emitente — presente em TODOS os pedidos B2B, independente do CODUSUR |
| `PCCLIENT.CODATV1` | ≠ ramo "funcionário" | Cliente deve ser um estabelecimento comercial real, não um funcionário EBD |

### Dois perfis de CODUSUR no canal W

1. **Vendedor exclusivo B2B** — CODUSUR com nome `'ECOMMERCE B2B LOJAEBD XX'` (ex: 2611 Manaus, 2608 Caruaru, etc). Pedido digitado/gerado pela equipe do portal.
2. **RCA de campo** — CODUSUR normal de vendedor externo. Cliente comprou sozinho pelo portal, mas o pedido caiu na carteira do RCA responsável. Identificado pelo `CODEMITENTE = 7777`.

**O filtro correto para "tudo que veio do portal B2B" é `CODEMITENTE = 7777`**, não filtrar por CODUSUR com nome B2B (isso pega só o perfil 1).

### Exclusão de clientes funcionário

Clientes do ramo de atividade "funcionário" (interno EBD) NÃO devem entrar em métricas de e-commerce B2B. Filtrar via:
```sql
JOIN EBD.PCATIVI ati ON ati.CODATIV = c.CODATV1
WHERE UPPER(ati.RAMO) NOT LIKE '%FUNCIONARIO%'
  AND UPPER(ati.RAMO) NOT LIKE '%FUNCIONÁRIO%'
```
Ou via GD_DIM_CLIENTE:
```sql
WHERE UPPER(dc.RAMOATIVIDADE) NOT LIKE '%FUNCIONARIO%'
  AND UPPER(dc.RAMOATIVIDADE) NOT LIKE '%FUNCIONÁRIO%'
```

### Template base para análise B2B

```sql
SELECT p.NUMPED, p.DATA, p.CODFILIAL, p.CODCLI, c.CLIENTE,
       p.CODUSUR, p.POSICAO, p.CONDVENDA,
       p.VLTOTAL, p.VLATEND, p.NUMPEDRCA, p.OBS1
FROM EBD.PCPEDC p
JOIN EBD.PCCLIENT c ON c.CODCLI = p.CODCLI
JOIN EBD.PCATIVI ati ON ati.CODATIV = c.CODATV1
WHERE p.ORIGEMPED = 'W'
  AND p.CODEMITENTE = 7777
  AND UPPER(ati.RAMO) NOT LIKE '%FUNCIONARIO%'
  AND UPPER(ati.RAMO) NOT LIKE '%FUNCIONÁRIO%'
  AND p.CODFILIAL = :userFilial
ORDER BY p.DATA DESC
```



<!-- AUTO-APPEND PROP-E2EBADEA aprovado por Thiago -->


## Regra de negócio: identificação de pedidos E-commerce B2E (Business to Employee)

> Confirmado por Thiago (admin) em 26/05/2026.
> B2E = canal de venda para funcionários EBD via portal loja.

### Filtros obrigatórios para isolar pedidos B2E

```sql
WHERE p.ORIGEMPED = 'W'    -- origem web/portal
  AND p.CODEMITENTE = 7777 -- emitente virtual do portal
  AND c.CODATV1 = 31       -- ramo FUNCIONARIOS (único código confirmado)
```

### Código de ramo confirmado

| CODATIV | RAMO | Fonte |
|---|---|---|
| 31 | FUNCIONARIOS | EBD.PCATIVI — único código de funcionário no cadastro |

> ⚠️ Não existem outros códigos de ramo para funcionário. CODATIV=31 é o único.
> Confirmado via `SELECT CODATIV, RAMO FROM EBD.PCATIVI WHERE UPPER(RAMO) LIKE '%FUNC%'`.

### Diferença B2B vs B2E (mesmo canal W)

| Canal | ORIGEMPED | CODEMITENTE | CODATV1 | Público |
|---|---|---|---|---|
| B2B | W | 7777 | ≠ 31 (excluir funcionário) | Clientes comerciais |
| B2E | W | 7777 | = 31 | Funcionários EBD |

Ambos usam o mesmo portal e o mesmo `CODEMITENTE=7777`. O que diferencia é **exclusivamente o ramo de atividade do cliente**.

### Template base para análise B2E

```sql
SELECT
  pf.CODIGO AS CODFILIAL,
  SUBSTR(NVL(pf.FANTASIA, '?'), 1, 25) AS FILIAL,
  COUNT(DISTINCT p.NUMPED) AS PEDIDOS,
  COUNT(DISTINCT p.CODCLI) AS FUNCIONARIOS,
  SUM(CASE WHEN p.POSICAO = 'F' THEN p.VLATEND ELSE 0 END) AS FATURADO_NF,
  SUM(CASE WHEN p.POSICAO IN ('L','M') THEN p.VLATEND ELSE 0 END) AS EM_CARTEIRA,
  SUM(CASE WHEN p.POSICAO = 'B' THEN p.VLATEND ELSE 0 END) AS BLOQUEADO
FROM EBD.PCPEDC p
JOIN EBD.PCCLIENT c ON c.CODCLI = p.CODCLI
JOIN EBD.PCFILIAL pf ON pf.CODIGO = p.CODFILIAL
WHERE p.ORIGEMPED = 'W'
  AND p.CODEMITENTE = 7777
  AND c.CODATV1 = 31
  AND p.DATA >= TRUNC(SYSDATE, 'MM')
  AND p.DTCANCEL IS NULL
GROUP BY pf.CODIGO, pf.FANTASIA
ORDER BY FATURADO_NF DESC
```

### Números de referência — maio/2026 (até 26/05)

| Métrica | Valor |
|---|---|
| NF emitida BR | R$ 79.030 |
| Em carteira | R$ 4.131 |
| Bloqueado | R$ 1.264 |
| Pedidos | 632 |
| Funcionários únicos | ~434 |
| Filiais ativas no canal | 13 de 21 |

Top filiais: SP (R$ 17.628) › Fortaleza (R$ 11.786) › SBC (R$ 10.747)

### Vocabulário aceito pelo agente

Termos que devem acionar esse filtro:
- "B2E", "B2E canal", "venda funcionário", "venda para funcionários",
  "portal funcionário", "benefício funcionário", "ecommerce funcionário"



<!-- AUTO-APPEND PROP-78E75851 aprovado por Thiago -->

## Regra padrão: "faturamento" = Líquido

> Confirmado por Thiago (admin) em 28/05/2026.

Quando qualquer usuário perguntar "faturamento" (sem adjetivo), o agente DEVE
retornar o **Faturamento Líquido**, não o Bruto.

### Definição oficial

```
Faturamento Líquido = Faturamento Bruto
                    - Devoluções (vinculadas + avulsas)
                    - Cancelamentos
                    - Bonificações (CONDVENDA 5/6)
```

### Regra de resposta

| O usuário diz | O agente entrega |
|---|---|
| "faturamento" | Líquido (padrão) |
| "faturamento bruto" | Bruto (explícito) |
| "faturamento líquido" | Líquido (explícito) |
| "vendas" | Líquido (mesmo padrão) |

### Implementação SQL

Usar a combinação:
- `VIEW_VENDAS_RESUMO_FATURAMENTO` com `CONDVENDA = 1` → Bruto base
- Subtrair `VIEW_DEVOL_RESUMO_FATURAMENTO` (`CONDVENDA = 1`) → devoluções vinculadas
- Subtrair `VIEW_DEVOL_RESUMO_FATURAVULSA` (sem filtro CONDVENDA) → devoluções avulsas

Bonificações e cancelamentos já são excluídos pelo filtro `CONDVENDA = 1` na view principal.

> ⚠️ A view `GD_FATO_VENDAFATURAMENTO` retorna o **Bruto** (inclui bonificações
> dependendo do período). Para Líquido oficial, usar `VIEW_VENDAS_RESUMO_FATURAMENTO`
> com as deduções de devolução conforme fórmula acima (cicatriz 2026-05-20).

### Comunicação ao usuário

Sempre que exibir faturamento, deixar claro no rodapé:
> *Fonte: Faturamento Líquido (bruto - devoluções - bonificações)*


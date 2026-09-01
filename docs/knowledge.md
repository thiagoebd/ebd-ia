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
| 11 | EBD SANTAREM | NO2 |
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
| NO1 | 06, 08 | EBD MANAUS, EBD BOA VISTA |
| NO2 | 01, 07, 11, 22 | EBD MATRIZ, EBD MACAPA, EBD SANTAREM, EBD MARABA |
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

## 10. Views GD_* — DESATIVADAS (legado GoodData)

As views `GD_FATO_*` e `GD_DIM_*` sao resquicio do **GoodData**, ferramenta de BI
que a EBD **nao usa mais**. Sao views (nao tabelas): cada consulta reexecuta os
joins de baixo, e agregacao por RCA ou fornecedor no mes **estoura o timeout**.

**NAO USE NENHUMA VIEW `GD_*`.** De-para obrigatorio:

| Em vez de | Use |
|---|---|
| `GD_FATO_VENDAFATURAMENTO` | `VIEW_VENDAS_RESUMO_FATURAMENTO` |
| `GD_DIM_RCA` | ja vem na view (`CODUSUR`, `CODSUPERVISOR`); nome via `PCUSUARI.NOME`, `PCSUPERV.NOME`, `PCGERENTE.NOMEGERENTE` |
| `GD_DIM_CLIENTE` | ja vem na view (`CODCLI`, `CLIENTE`, `CODATIV`, `UF`); ramo via `PCATIVI.RAMO` |
| `GD_DIM_PRODUTO` | ja vem na view (`CODPROD`, `DESCRICAO`, `FORNECPRINC`, `CODEPTO`) |
| `GD_FATO_ROTACLIENTE` | `PCROTACLI` |
| `GD_FATO_CONTASRECEBER` | `PCPREST` (aberto = `DTPAG IS NULL`; vencido = `DTVENC < TRUNC(SYSDATE)`) |
| `GD_FATO_ESTOQUEATUAL` | `PCEST` (livre = `QTESTGER - QTRESERV - QTBLOQUEADA`) |

### A view de faturamento ja e desnormalizada

`VIEW_VENDAS_RESUMO_FATURAMENTO` traz, na mesma linha: `CODUSUR`,
`CODSUPERVISOR`, `CODGERENTELOCAL`, `CODCLI`, `CLIENTE`, `CODATIV`, `UF`,
`CODPROD`, `DESCRICAO`, `CODFORNEC`, `FORNECPRINC`, `CODEPTO`, `CODSEC`,
`CODCATEGORIA`, `ROTA`, `CODPRACA`, `VIP`, `NUMPED`, `NUMTRANSVENDA`, `QT` e
`VLATEND`. **Nao precisa de join para agrupar por nenhuma dessas dimensoes.**

Colunas-chave: data = `DTSAIDA` (**DATE**, sem TO_CHAR), valor = `VLATEND`,
filtro obrigatorio `CONDVENDA = 1`.

### Custo medido (23/07/2026)

| Consulta | Tempo |
|---|---|
| Ranking por RCA, BR, mes (com joins GD_*) | estourava 85s |
| Ranking por RCA, BR, mes (so a view) | **9,1s** |
| Ranking por RCA, **uma filial**, mes | **0,7s** |
| Ranking por RCA, BR, ultimos 7 dias | **3,3s** |

O custo depende do **volume de linhas varridas**, nao da coluna do `GROUP BY`.
Agrupar por fornecedor, departamento ou categoria custa o mesmo.

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

Regional NO2 atualizada: filiais 01 (EBD MATRIZ) + 07 (EBD MACAPA) + 11 (EBD SANTAREM) + 22 (EBD MARABA)

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
| NO1 | 06, 08 | EBD MANAUS, EBD BOA VISTA |
| NO2 | 01, 07, 11, 22 | EBD MATRIZ, EBD MACAPA, EBD SANTAREM, EBD MARABA |
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
| 11 | EBD SANTAREM | NO2 |
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

### Canal de entrada do pedido — `ORIGEMPED` completo

Ate 24/07 a KB so documentava o `'W'`, e o agente inventava explicacao para os
outros — chegou a dar duas versoes diferentes do `'F'` na mesma conversa.
Medido na filial 13 em 60 dias:

| Valor | Canal | Volume medido (fil 13, 60d) |
|---|---|---|
| `'F'` | Forca de vendas — o canal PRINCIPAL, RCA em campo | 23.623 pedidos, 85 RCAs |
| `'T'` | Televendas | 489 pedidos, 36 RCAs |
| `'W'` | Portal / e-commerce (ver secao 9) | 181 pedidos, 23 clientes |

**`'F'` e venda normal, nao excecao.** Nao trate pedido com `ORIGEMPED='F'` como
digitacao manual, contorno ou anomalia — e por onde a filial vende.

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



<!-- AUTO-APPEND PROP-73CC450B aprovado por Thiago -->

## Regra de consistência: coluna de meta e gap acrescenta ao mesmo quadro — NUNCA substitui

> Aprovado por Thiago (admin) em 21/07/2026.
> Caso: usuário pediu top 10 filiais (retornei faturamento líquido). Depois pediu "coloca uma coluna adicional com meta e gap" — errei ao substituir os valores de líquido por Real+Ped sem avisar.

### Regra inviolável

Quando o usuário pedir para **acrescentar** colunas (meta, gap, % etc.) a um dado já exibido:

1. **MANTENHA a métrica original** do quadro anterior — líquido continua líquido, bruto continua bruto
2. **ADICIONE** as novas colunas como extras no mesmo quadro — NUNCA troque a métrica base
3. Se o novo dado pedido exigir uma métrica diferente (ex: Real+Ped), **crie um novo quadro separado** com label claro, não substitua o anterior

### Exemplo concreto do erro

| ❌ Errado (o que aconteceu) | ✅ Correto |
|---|---|
| Quadro 1: Líquido = R$ 19,7M | Quadro 1: Líquido = R$ 19,7M |
| Quadro 2 (com meta): Líquido = R$ 21,9M (na verdade Real+Ped) | Quadro 2 (com meta): Líquido = R$ 19,7M + Meta + Gap + % |
| Usuário vê valor diferente e perde confiança | Tudo consistente |

### Check-list antes de responder

- [ ] A nova coluna é da **mesma métrica** do quadro original? → adiciona no mesmo
- [ ] É de métrica **diferente**? → quadro separado ou nova coluna com label claro (ex: "Em Pedido", "Real+Ped")
- [ ] O **rodapé de fonte** descreve exatamente o que está sendo exibido?
- [ ] Os números **batem** entre os quadros quando comparáveis?

### Aplicação

Toda vez que usuário pedir complemento de dados sobre algo que já foi mostrado.


## 14. Contexto do negócio — canal indireto e setor mercearil

Este bloco serve para **entender a pergunta e nomear as coisas corretamente**.
NÃO serve para explicar por que um número variou: causa só quando o dado mostra
a causa. Nunca atribua variação a "cenário macro", "retração do consumo" ou
similar sem número que sustente.

### O que a EBD é

Distribuidora do **canal indireto** no setor mercearil: compra da indústria
(fabricantes de alimento, bebida, higiene pessoal e limpeza) e vende para o
varejo — mercearia, mercadinho, supermercado, atacarejo, conveniência.
**Não vende ao consumidor final.**

### O posicionamento estratégico da EBD

A EBD é a **extensão da indústria no ponto de venda**: ela **implementa no campo
a estratégia que a indústria desenha**. O fabricante define o quê, para quem, a
que preço e com qual ativação; a EBD faz isso acontecer em cada PDV. Não é
revenda de volume — é execução de estratégia.

Os meios pelos quais essa execução acontece:

- **Capilaridade** — leva a estratégia ao ponto de venda onde a indústria não chega.
- **Força de vendas** — RCA e vendedor CLT executam em campo o que foi desenhado.
- **Fracionamento** — viabiliza o sortimento no pequeno varejo, que compra caixa e não pallet.
- **Crédito** — financia o varejista para que a estratégia se sustente na ponta.

Por isso métricas de **execução** — positivação, mix, ruptura, cobertura de rota
— importam tanto quanto faturamento: elas medem se a estratégia da indústria
chegou de fato ao PDV.

### Termos do setor ainda não cobertos no vocabulário

| Termo | Significado | Como tratar na EBD |
|---|---|---|
| Canal indireto | Indústria → distribuidor → varejo | é o negócio da EBD |
| Sell-in | Venda da EBD para o varejista | é o nosso faturamento |
| Sell-out | Venda do varejista ao consumidor final | a EBD **não enxerga** esse dado |
| Drop size | Valor médio do pedido | usar **Ticket Médio** (métrica já definida) |
| Curva A | Itens de maior peso no faturamento | ver `VIP` (a curva usada aqui) |

⚠️ **"Cobertura" na EBD é de ESTOQUE** (`QTESTGER / QTGIRODIA`), não cobertura
de carteira ou de visita. Se o usuário falar em cobertura de clientes, pergunte
o que ele quer antes de responder — não assuma.

### Como o setor lê os números

- **Faturamento subindo com positivação caindo é concentração**: poucos clientes
  grandes segurando o número. Vale olhar os dois juntos em análise de carteira.
- **Ruptura em item de curva A pesa muito mais** que em item de cauda longa.
- **Meta se acompanha por Real + Pedido**, porque pedido liberado ainda vira nota.
- **O formato da loja define o sortimento**: atacarejo concentra em curva A,
  mercearia carrega mix pequeno, supermercado carrega mix largo. Comparar mix
  entre formatos diferentes sem dizer isso induz a erro.


## 15. Régua do setor — Ranking ABAD/NielsenIQ 2026 (ano base 2025)

**REGRA DE USO:** todo número aqui é do SETOR, base **2025**. Cite sempre fonte e
ano ("Ranking ABAD/NielsenIQ 2026, base 2025"). Nunca apresente como dado da EBD,
nunca como número do ano corrente, e ao comparar diga que as bases são diferentes.
Estes números servem para **contextualizar** um número da EBD — não para
substituí-lo nem para explicar por que ele variou.

### Tamanho do canal

O canal indireto respondeu por **R$ 616,6 bilhões**, **55,9%** de um mercado de
consumo de alto giro estimado em R$ 1,1 trilhão, atendendo **1,18 milhão de
pontos de venda**. Crescimento sobre 2024: **+17,27% nominal**, cerca de **11%
real** (IPCA 4,26%). Estudo com 768 empresas.

⚠️ A capa da revista traz 56,9%; a matéria de análise e a tabela de dados trazem
**55,9%**. Usar 55,9%.

⚠️ O Atacadão sozinho responde por ~30% do apurado. Sempre que possível use o
recorte **sem Atacadão** para comparar com a EBD — a média com ele é distorcida.

### Onde a EBD se situa

| Modelo de operação | Part. faturamento (sem Atacadão) |
|---|---|
| **Distribuidor com entrega — modelo da EBD** | **44,5%** |
| Atacado generalista com entrega | 35,0% |
| Atacado generalista de autosserviço (atacarejo) | 15,4% |
| Atacado de balcão | 3,9% |
| Agente de serviços | 1,2% |

A maioria das empresas opera em **dois ou mais modelos** ao mesmo tempo.

### Como o setor vende (% dos pedidos)

| Modelo | E-comm | RCA | Loja física | Televendas | CLT |
|---|---|---|---|---|---|
| **Distribuidor com entrega (EBD)** | **6** | **37** | **5** | **5** | **46** |
| Atacado generalista com entrega | 14 | 41 | 15 | 10 | 19 |
| Média do setor | 8 | 27 | 38 | 5 | 22 |

No modelo da EBD a venda é dominada por equipe própria (CLT, 46%) e RCA (37%).
E-commerce e televendas são complementares — se o e-commerce da EBD estiver muito
acima ou abaixo de 6%, é uma diferença que vale comentar.

### O que o setor vende (% do faturamento, sem Atacadão)

| Alimentos | Higiene e beleza | Outros | Mat. construção | Bazar | Bebidas | Limpeza | Eletro |
|---|---|---|---|---|---|---|---|
| 46,0 | 15,2 | 9,1 | 7,9 | 7,1 | 6,2 | 6,1 | 2,3 |

### Estrutura comparável

| Indicador do setor | 2024 | 2025 | Var. |
|---|---|---|---|
| Vendedores CLT | 27.422 | 28.203 | +2,8% |
| Representantes (RCA) | 37.343 | 37.286 | -0,2% |
| Frota própria | — | 22.452 | — |
| Frota terceirizada | — | 28.031 | +16,3% |

Duas leituras estruturais: a **frota terceirizada já superou a própria** no setor,
e a força de vendas migra devagar de RCA para CLT.


## 16. Compras — modelo de dados e armadilhas

### Cadastro de produto por filial — a regra que mais erra

**Catalogo comercial da filial = `PCPRODFILIAL.REVENDA = 'S'`.** O `ATIVO = 'S'`
inclui insumo, amostra e material administrativo e NAO serve para analise
comercial (em Teresina eram 18.598 itens a mais).

**`ENVIARFORCAVENDAS = 'S'`** e o que coloca o produto na VITRINE do app do RCA.
Com `'N'` o item **some da vitrine, mas continua vendavel** — quem sabe o codigo
digita o pedido e ele fatura normalmente.

NUNCA diga que "ninguem consegue vender": o efeito e **friccao de venda**, nao
bloqueio. Comprovado 24/07 na filial 13 (Taquara): os produtos 16064 e 16071
estao com `'N'` desde 23 e 25/06 e mesmo assim receberam 11 pedidos em 06 e
07/07, de nove RCAs diferentes, todos faturados, pelo canal normal
`ORIGEMPED = 'F'`.

Medido 24/07 nas 21 filiais: 85 itens e R$ 2,69 mi com estoque fora da vitrine.
Ao analisar capital parado, cheque este campo antes de sugerir queima ou
devolucao — item fora da vitrine gira menos, mas nao esta impedido (ver
T-CMP06).

**`FORALINHA = 'S'` = "nao vamos mais comprar"**, mas o item continua
`REVENDA = 'S'` e continua vendendo. Rotule como **saindo de linha**, nunca como
fora de linha.

### Natureza do departamento — comercial x apoio

Nem todo produto cadastrado e mercadoria de revenda. **Nao filtre: classifique.**

`CASE WHEN p.CODEPTO IN (150, 160, 170, 171, 900) THEN 'APOIO' ELSE 'COMERCIAL' END`

| Codigo | Departamento | Por que e apoio |
|---|---|---|
| 150 | Material para Armazenagem | pallet e embalagem logistica |
| 160 | Merchandising | material de PDV |
| 170 | Comodato | ativo cedido ao cliente (freezer), nao e venda |
| 171 | Brindes-Fornecedores | premiacao de campanha — faturou ZERO em 6 meses |
| 900 | Servicos | nao e mercadoria |

**Regra de apresentacao:** o total soma **apenas o COMERCIAL**; o apoio aparece a
parte, com a observacao de que nao esta no total. Assim a informacao nao se perde
nem contamina decisao de compra.

Lista de EXCLUSAO curta de proposito: departamento novo de mercadoria (calcados,
por exemplo) entra como comercial automaticamente. So apoio novo exige
manutencao — e esse erro e visivel, porque infla o numero, enquanto o contrario
sumiria calado.

⚠️ **A FatoEstoque NAO faz essa separacao** (so exclui TIPOMERC 'IM' e 'CI'):
ela valoriza patrimonio, e pallet e brinde sao ativos reais. Dois recortes
legitimos — **FatoEstoque para valor de estoque, natureza comercial para analise
de venda e sortimento.** Diga qual esta usando.

### Tabelas

| Tabela | O que e | Volume |
|---|---|---|
| `PCPEDIDO` | cabecalho do pedido de compra | 78.663 |
| `PCITEM` | itens do pedido | 1,4 mi |
| `PCNFENT` | entrada de mercadoria | 1,45 mi |
| `PCSUGESTAOCOMPRAC` / `I` | sugestao de compra | 5.706 / 176.167 |
| `PCDEVFORNEC` | devolucao a fornecedor | 33.600 |
| `PCPRODFILIAL` | parametros do produto POR FILIAL | 854.458 |

Ligacao pedido -> entrada: `PCPEDIDO.NUMPED` -> `PCMOV.NUMPED` ->
`PCMOV.NUMTRANSENT` -> `PCNFENT.NUMTRANSENT`.

### Rotinas do Winthor

220 digita o pedido (sugestao pela 207), 215 libera (se o parametro 1886 da 132
estiver ligado), 1301 da entrada na nota, 1309 analisa pre-entrada, 1106 faz o
bonus de conferencia, 1302 e devolucao a fornecedor. O comprador e vinculado ao
produto POR FILIAL na rotina 238 (campo Cod. Comprador na `PCPRODFILIAL`).

### Armadilhas medidas

- Status do pedido NAO vem de coluna: DTLIBERA, DTENTRADAESTOQUE, DTCHEGADA e
  DTVENC estao em 0%. Use DTEMISSAO, DTPREVENT, DTFATUR (100%).
- 6 notas com DTENT no futuro (2031 a 5112). `DTENT <= SYSDATE` sempre.
- 18,4% dos itens do PCITEM tem QTPEDIDA = 0 e distorcem atendimento.
- `PCFORNEC.PRAZOENTREGA` so em 7,8% dos fornecedores — a formula do estoque
  ideal (`QTGIRODIA x (TEMREPOS + PRAZOENTREGA)`) usa zero em 92% dos casos.
  Prefira o lead time medido.

### Lead time real por filial (mediana, 6 meses)

| Filial | Lead time | Desvio da promessa |
|---|---|---|
| 08 Boa Vista | 34 d | -1,3 |
| 06 Manaus | 31 d | +0,2 |
| 53 Caruaru | 21 d | **+19,7** |
| 07 Macapa | 21 d | +13,1 |
| 52 Petrolina | 20 d | +15,0 |
| 09 Juazeiro | 14 d | +16,5 |
| 18 SBC | 11 d | +4,9 |
| 13 Taquara | 9 d | +3,9 |

O problema nao e distancia, e promessa errada: o Norte demora mais mas o
fornecedor promete certo; o Nordeste promete prazo que nao cumpre.

## 17. Logistica, expedicao e WMS — modelo de dados e armadilhas

Levantado e MEDIDO em 27-28/07/2026 contra o Oracle real. Todo numero desta
secao tem consulta por tras. O que nao foi medido esta marcado como tal.

### 17.1 Tres dominios distintos — nao misturar

| Dominio | Pergunta | Rotinas | Tabela-nucleo |
|---|---|---|---|
| Expedicao | Como a venda vira carga na rua? | 901-967 | `PCCARREG` |
| WMS | Onde a mercadoria esta no CD e quem moveu? | 17xx / 37xx | `PCMOVENDPEND` |
| Roteirizacao de entrega | Em que ordem o caminhao entrega? | 911, 913, 915 | `PCPEDC.NUMSEQENTREGA` |

Existe um quarto uso da sigla "O.S." que NAO e logistica de distribuicao:
`PCORDEMSERVICO` + `PCOSVEICULO*` sao **manutencao de frota** (placa, modelo,
KM, combustivel). Misturar com a O.S. de armazem produz resposta absurda com
cara de certa.

FRONTEIRA CRITICA: rota de VISITA (`PCROTACLI`, roteiro do RCA, usada pelo
`create_route_map`) e coisa diferente de rota de ENTREGA (sequencia do
caminhao). Mesma palavra, dois mundos.

### 17.2 O que EXISTE e esta preenchido

- `PCMOVENDPEND` — coracao do WMS, 97,3 mi de linhas, viva. Separador
  (`CODFUNCOS`), conferente, endereco, O.S., tipo, quantidade, e os carimbos
  `DTINICIOOS` / `DTFIMOS` / `DTFIMSEPARACAO` / `DTINICIOCONFERENCIA` /
  `DTFIMCONFERENCIA` / `DTESTORNO`.
- `PCENDERECO` / `PCESTENDERECO` — as 21 filiais + os 3 depositos (17, 19, 23)
  usam WMS. Endereco bloqueado = endereco DESATIVADO: em SBC os 16.238
  bloqueados tem ZERO estoque; os 14.213 livres carregam 4,09 mi de unidades.
- `PCCORTEI` — corte na separacao, com `PVENDA` (valor) e `MOTIVO`.
- `PCWMSCORTE` — o mesmo corte, com RESPONSAVEL (`CODFUNCCORTE` 100%
  preenchido, `CODFUNCOS` 71-100%), endereco, O.S. e `CODMOTIVO` numerico.
  Os totais batem com a `PCCORTEI` quase linha a linha.
- `PCINVENTENDERECO` + `PCLOGINVENTARIOWMS` — inventario rotativo VIVO: 4.186
  inventarios e 625 mil enderecos contados em 12 meses.
- `PCROTAEXP` — 227 rotas de entrega; `PCCARREG.CODROTAPRINC` casa em 99,87%.
- `PCVOLUMEOS` — 39,1 mi de linhas, rastreabilidade volume a volume (quem
  montou palete, se embarcou, se foi cortado). AINDA NAO EXPLORADA.

### 17.3 O CEMITERIO — colunas e tabelas que parecem uteis e estao VAZIAS

Esta lista existe para o agente NAO escrever query bonita em cima de campo
vazio e devolver zero com cara de resposta.

| Objeto | Situacao medida |
|---|---|
| `PCCARREG.CODFILIALSAIDA` | 0 de 1.153.949 cargas |
| `PCCARREG.DTRETORNO` | 3 registros — a rotina 907 nao e usada, mas a baixa e o DTFECHA (ver 17.9) |
| `PCCARREG.DATAMAPA` / `DATAHORAMAPA` | 5,5% |
| `PCCARREG.KMINICIAL` / `KMFINAL` | valor sempre ZERO desde 2019 |
| `PCROTAEXP.KMROTA` / `DIASENTREGA` / `PRAZOPREVENT` / `QTENTREGA` | 0 rotas preenchidas |
| `PCPEDC.DTEMISSAOMAPA` / `NUMTRANSWMS` / `CODTRANSP` | 0 |
| `PCPEDC.DTAGENDAENTREGA` | 35 registros |
| `PCPEDC.DTENTREGA` | 100% preenchido mas DERIVADO — em SBC 98,6% igual ao `DTFAT`, pior caso 0 dias. NAO usar como entrega realizada |
| `PCMOVENDPEND.CODFUNCEMBALADOR` | 0 |
| `PCMOVEND` (CODFUNCSEP, EMPILHADEIRA, TRANSPALETEIRA, DTINICIOSEP, DTINIABAST, NUMPALETE) | todos 0 |
| `PCCORTEI` (CODFUNCSEP, CODFUNCCONF, QTORIG, QTFALTA) | todos 0 — atribuicao so pela `PCWMSCORTE` |
| `PCENTREGA`, `PCWMSOS`, `PCTRANSPORTE`, `PCROTASZONAENTREGA`, `PCWMSERRO`, `PCLOGCONFERENCIAWMS` | vazias |
| `PCCARREGI` | 29.580 linhas contra 1,15 mi de cargas (2,5%) |
| `PCROTA` | 0 linhas — a rota de entrega e a `PCROTAEXP` |

CONSEQUENCIA DIRETA: **nao existe OTIF por cliente, nem km rodado, nem
produtividade de equipamento.** Nao e falta de query, e falta de dado.

O ciclo da carga EXISTE, porem: montagem, saida do veiculo e BAIXA DO ROMANEIO
estao registrados (secao 17.9). O que nao existe e o evento por ENTREGA — nao
da pra dizer se o cliente X recebeu no prazo, mas da pra dizer quanto tempo a
carga ficou na rua e quantas estao em aberto.

REGRA DE METODO: medir preenchimento na JANELA RECENTE, nunca na tabela
inteira. `DTSAIDAVEICULO` parece morta (16,9% no historico total) e esta viva
(70,6% nos ultimos 3 meses).

### 17.4 Onde o KM realmente esta

A integracao com a MaximaTech/MyFrota e de MAO UNICA: `PCMYFROTA_FILA` tem
560.094 registros de saida, e `PCMYFROTA_VIAGEM`, `PCMYFROTA_HISTORICO`,
`PCMYFROTA_LOG`, `PCRASTREABILIDADE` e `PCITENSMYFROTA` estao todas com ZERO
(contagem real, nao estatistica). `PCARC_CLIENTES_ROTEIRIZADOS` tem so duas
colunas: `DTEXPORTACAO` e `CODCLI` — e log de exportacao.

Se perguntarem km, rastreamento ou roteiro otimizado: responder que esse dado
vive fora do Winthor, na plataforma da MaximaTech. NUNCA inventar numero de km.

### 17.5 Ruptura de expedicao — o furo que a diretoria nao ve

Sao DUAS rupturas diferentes:
- `PCFALTA` = ruptura COMERCIAL, no momento do pedido (o agente ja conhece).
- `PCCORTEI` / `PCWMSCORTE` = ruptura FISICA no CD, na separacao. Pedido
  aceito, carga montada, e na hora de separar nao tinha.

Medido em 90 dias: **R$ 5,01 milhoes cortados**, concentrados em RJ2 — CD
Petropolis (23) R$ 1,66 mi e Pirai (14) R$ 829 mil, metade da empresa.

Motivos (todos sao `PCTABDEV` com `TIPO = 'CO'`):

| Cod | Motivo | Valor 90d | Peso |
|---|---|---|---|
| 62 | FALTA DE PRODUTO | R$ 3,02 mi | 60% |
| 65 | MERCADORIA VENCIDA | R$ 1,62 mi | 32% |
| 64 | MERCADORIA AVARIADA | R$ 269 mil | 5% |
| 118 | OCORRENCIAS EXPEDICAO WMS | R$ 36,6 mil | |
| 116 | EMBALAGEM ERRADA | R$ 1,1 mil | |

R$ 1,62 mi de mercadoria VENCIDA cortada na separacao nao e erro de separador:
e gestao de validade. O produto entrou, foi enderecado, venceu no endereco e so
foi descoberto quando alguem foi busca-lo. A `PCESTENDERECO` tem `DTVAL`.

### 17.6 Produtividade de armazem — o que se sustenta

O tempo decorrido da O.S. NAO e tempo trabalhado (O.S. fica aberta; em Teresina
a mediana da diferenca deu 1.110 minutos). O `HORA` da `PCMOVENDPEND` tambem
nao serve: e carimbo da O.S., nao do movimento.

O unico denominador honesto e **LINHAS POR DIA TRABALHADO**. Medido em SBC:
apanha varia de 192 a 517 linhas/dia entre separadores.

SEGMENTACAO OBRIGATORIA: separar APANHA de PALETIZADO pelo indice
unidades/linha. Apanha fica entre 35 e 96; paletizado entre 649 e 1.982. Corte
em 200 cai num vazio grande. Rankear junto compara trabalhos diferentes.

Acuracia usa a taxa de ESTORNO (`DTESTORNO IS NOT NULL`). Medido em SBC, so
movimentos de separacao: 0,04% a 0,59% por pessoa. ATENCAO: o estorno GERAL da
filial (1,295%) e muito maior que o da separacao (0,28%) — o retrabalho esta na
movimentacao interna, nao na apanha. Pirai 4,01% e Petropolis 3,11% no geral
tem problema de MOVIMENTACAO, nao de separador.

Gargalo medivel: fila entre `DTFIMSEPARACAO` e `DTINICIOCONFERENCIA` — Sao Luis
107,5 min, SBC 81,7, Petropolis 74,7, Pirai 59,8, Duque 49,5. A DURACAO da
conferencia nao existe (inicio e fim gravados no mesmo instante).

Operacao e NOTURNA e ATRAVESSA A MEIA-NOITE. Medido na filial 18 em 14 dias
pela hora de `DTINICIOOS` (a `DATA` da PCMOVENDPEND e truncada, e a coluna
`HORA` e ruido — bate com o relogio real em 5% das linhas): turno das **21h as
07h**, pico A MEIA-NOITE com 18% dos inicios de O.S., e **57% do trabalho
depois da meia-noite** contra 38% entre 18h e 23h.

Consequencia pratica: pergunta de turno NAO pode agrupar por dia calendario —
usar `TRUNC(DTINICIOOS - 12/24)` (cicatrizes #67 e #68).

### 17.7 Enums

`PCENDERECO.TIPOENDER`: `AE` aereo (pulmao), `AP` picking.
`PCENDERECO.SITUACAO`: `L` livre, `O` ocupado.
`PCENDERECO.BLOQUEIO`: `S` bloqueado (= desativado, sem estoque), `N` ativo.
Existe `Z` em Taquara (60 enderecos), fora da documentacao.
`PCENDERECO.STATUS`: `N` normal, `F` falta, `C` crossdocking, `A` avaria,
`E` excesso, `S` stage.
`PCMOVENDPEND.CODOPER`: `E`/`S` entrada/saida, `EV`/`SV` avaria, `EA`/`SA` ajuste.
`PCMOVENDPEND.POSICAO`: `C` concluido, `P` pendente, `A` aguardando.
`PCINVENTENDERECO.TIPO`: `R` rotativo, `G` geral.
`PCVEICUL.SITUACAO`: `V` e `L` = frota ATIVA (1.717 veiculos rodaram em 6
meses); `I` = inativo (842 cadastrados, 1 carga). `B` e `O` residuais.
`PCVEICUL.TIPOVEICULO`: `L`/`M`/`P` = leve/medio/pesado (peso medio de carga
382 / 671 / 772 kg, e a `PCROTAEXP` tem as tres faixas de comissao). `E` sem
traducao confirmada.

Tipos de O.S. vem da `PCTIPOOS` DA EBD (42 codigos, 12 marcados "Fora de uso"),
que e CUSTOMIZADA — o tipo 16 aqui e "Separacao por carregamento" e o 12 e
"Separacao especifica Red - Cafe". NAO usar a tabela generica da TOTVS.
Separacao = 13, 14, 16, 17, 20. Movimentacao interna = 50 a 61.
Armazenagem = 51, 52, 60, 97, 98. Inventario = 70.

### 17.8 Perfil operacional por filial (30 dias)

Entregas por carga: Imperatriz 39,3, Caruaru 31,1, Sao Luis 26,1, Petrolina
25,5 no topo; Guarulhos 5,7, Marabá 8,0 e Itapevi 8,5 na base. Peso por carga
de 480 kg (Fortaleza) a 2.510 kg (Marabá).

ATENCAO: `TOTVOLUME` NAO e comparavel entre filiais (157,16 em Duque contra
1,14 em Itapevi com pesos parecidos). Unidade nao padronizada no cadastro. Peso
serve para comparar; volume so dentro da mesma filial.

Cancelamento de carga subiu de 35,4% (2022) para 49,9% (2026) — metade das
cargas montadas e desfeita, e quase nenhuma tinha nota. E uso da 901 como
rascunho, nao cancelamento fiscal.

### 17.9 Ciclo da carga — montagem, saida e baixa do romaneio

MEDIDO em 27/07/2026, 90 dias, 31.927 cargas nao canceladas:

| Marco | Coluna | Preenchimento | Quando |
|---|---|---|---|
| Carga montada | `DTSAIDA` | 100% | dia 0 |
| Veiculo sai | `DTSAIDAVEICULO` | 70,6% | +0,3 dia |
| **Baixa do romaneio** | **`DTFECHA`** | **93,8%** | **+3 dias (mediana)** |
| Acerto de caixa | `DTCAIXA` | 90,7% | +3 dias |

Quem deu baixa: `CODFUNCFECHA` (93,8%). Hora da baixa: `HORAFECHA` e
`MINUTOFECHA` (93,0%) — o `DTFECHA` e TRUNCADO, so tem a data.

Isto e a rotina 410 (acerto de carga e caixa). NAO confundir com `DTRETORNO`,
que e o registro da rotina 907 e tem 3 linhas em toda a tabela.

NAO existe tabela separada de romaneio ou acerto: `PCACERTOMANIF`,
`PCPREACERTO`, `PCCONTROLEDEENTREGA`, `PCENTREGA` e `PCZONASENTREGA` estao
todas VAZIAS. E tudo na `PCCARREG`.

Dispersao por filial (mediana de dias entre saida e baixa, 90 dias):

| Dias | Filiais |
|---|---|
| 18 / 15 / 13 | 09 Juazeiro / 21 Teresina / 08 Boa Vista |
| 10 a 11 | 22 Maraba, 03 Fortaleza, 04 Sao Luis, 12 Imperatriz |
| 5 a 6 | 01 Matriz, 11 Santarem, 52 Petrolina, 53 Caruaru |
| 2 a 4 | 14 Pirai, 10 Sao Goncalo, 15 Guarulhos, 05 Duque, 02 SP, 18 SBC, 07 Macapa, 13 Taquara, 06 Manaus, 16 Itapevi |

A mediana da empresa (3 dias) NAO representa ninguem: o Norte e o Nordeste
levam de 4 a 9 vezes mais que o Sudeste. Qualquer alerta de carga em aberto
tem que usar o normal DA FILIAL, nunca um numero fixo (ver T-LOG15).

Pior caso observado: 82 dias em Duque, 75 em Fortaleza, 73 em Taquara — em
pracas cuja mediana e 2. Carga sem baixa e mercadoria e dinheiro sem prestacao
de contas.

⚠️ ARMADILHA DE CONTAGEM: contar carga em aberto DEPOIS do join com PCPEDC
multiplica pelo numero de pedidos. Agregar por NUMCAR primeiro — o T-LOG14 e o
T-LOG15 ja fazem isso.

### 17.10 Meta de fechamento de carga e classificacao da rota

REGRA DE NEGOCIO (informada pelo Thiago, 27/07/2026): capital e regiao
metropolitana tem meta de **2 a 3 dias** para fechamento de carga. Rota de
interior leva dias legitimamente e nao entra na mesma regua.

A `PCROTAEXP.DESCRICAO` classifica sozinha — o cadastro e nomeado por praca:

  METROPOLITANA:  descricao com 'CAPITAL' ou 'METROPOLIT'
                  ex.: CE - CAPITAL, CE - METROPOLITANA, PI - CAPITAL
  INTERIOR:       'INTERIOR', 'SERTAO', 'LITORAL', 'VALE', 'SERRA',
                  'BAIXADA', 'FLUVIAL', 'MARAJO'
                  ex.: CE - SERTAO DE SOBRAL, STM-FLUVIAL, PA-MARAJO

Prefixo da rota = praca/estado: CE, PI, MA, PA, RR, AM, STM (Santarem),
IMP (Imperatriz), CAU (Caruaru), PNZ (Petrolina), DC (Duque de Caxias).
Sufixo `(AS)` = autosservico. `AGENDAMENTO` = entrega agendada, lenta por
natureza.

### ADERENCIA MEDIDA (90 dias, 29.872 cargas com baixa)

| Faixa | Cargas | % |
|---|---|---|
| ate 1 dia | 8.635 | 28,9% |
| 2 a 3 dias (meta) | 7.387 | 24,7% |
| 4 a 7 dias | 7.902 | 26,5% |
| 8 a 15 dias | 3.818 | 12,8% |
| 16 a 30 dias | 1.677 | 5,6% |
| mais de 30 dias | 453 | 1,5% |

**53,6% fecham dentro da meta; 46,4% passam de 3 dias.**

### O CASO FORTALEZA (filial 03)

Nas outras filiais a mediana alta se explica pela mistura de rotas: Duque vai
de 1 a 10 dias entre rotas, Santarem de 0 a 21, Matriz de 3 a 17,5.

Em Fortaleza NAO: a rota MAIS RAPIDA da filial leva 6 dias. `CE - CAPITAL`
(1.288 cargas) fecha em 6 e `CE - METROPOLITANA` (622) em 7, contra meta de 2
a 3. Por municipio confirma: Fortaleza 7, Caucaia 8, Maracanau 6, Eusebio 6.
Nao e geografia, e processo de acerto. Teresina (`PI - CAPITAL`) tambem: 6.

Sudeste dentro da meta: Taquara 1 a 2, SBC 1 a 3, Itapevi 1 a 2,5, Sao Goncalo
1 a 3, SP 2 a 5.

### CARGAS EM ABERTO (medido 27/07/2026, janela de 180 dias)

1.907 cargas sem baixa, R$ 55,0 milhoes em `PCCARREG.VLTOTAL`. O risco nao esta
no volume, esta na incoerencia com a praca:

| Filial | Em aberto | Mediana aberta | Mais antiga | Valor |
|---|---|---|---|---|
| 03 Fortaleza | 392 | 5 d | 67 d | R$ 8,88 mi |
| 01 Matriz | 284 | 4 d | 59 d | R$ 9,21 mi |
| 04 Sao Luis | 206 | 3 d | 20 d | R$ 5,42 mi |
| 14 Pirai | 148 | 3 d | 31 d | R$ 3,61 mi |
| **05 Duque** | **142** | **12 d** | 59 d | R$ 4,22 mi |
| **13 Taquara** | **107** | 7 d | **82 d** | R$ 2,85 mi |

Duque e Taquara fecham carga em 2 dias normalmente. Carga aberta com mediana de
12 dias em Duque, e uma de 82 dias em Taquara, nao e rota demorada — e carga
esquecida. Por isso o alerta e RELATIVO a praca (T-LOG15), e nao um numero fixo.

## 18. Gestao de Metas (rotina 3388/GM), premio e comissao

Levantado e MEDIDO em 28/07/2026, com a regra de negocio confirmada pelo Thiago
e a formula validada ao centavo contra um premio fechado real.

### 18.1 O ciclo mensal e quem faz o que

INICIO DO MES
  1. G&G da filial cadastra a parametrizacao de Meta e Premio (mes x filial) e
     libera para o comercial.
  2. O time comercial sobe a meta por INDUSTRIA x RCA (planilha Excel).
     Prazo: ate o QUINTO DIA UTIL.

FIM DO MES
  3. Apos o fechamento do mes, a comissao e apurada.
  4. Comercial apura meta/premio, confere com a ROTINA 111 e FECHA A META.
  5. G&G FECHA O PREMIO e integra para o RM pela ROTINA 9817 (Integracao GM-RM).

A 3388 so existe no WTA (WinThor Anywhere). Acesso liberado pela rotina 530,
que valida a rotina 131. Menus: 1 Cadastro (G&G Corporativo), 2 Configuracoes
(TI Corporativo, mudanca exige chamado), 3 Construcao (G&G Filial + Analista
Comercial), 4 Apuracao (Comercial fecha meta, G&G fecha premio), 5 Extrato
(Extrato so com premio fechado; Conferencia; Relatorio Apoio com comissao
detalhada por produto e RCA).

⚠️ **NAO EXISTE APURACAO DE PREMIO NO MES CORRENTE.** A comissao so e apurada
depois do fechamento do mes. Julho/2026 medido em 28/07: 1.888 metas e apenas
13 fechadas — sao fechamentos prematuros, nao o resultado do mes. Perguntas
sobre premio/comissao devem usar o ULTIMO MES FECHADO. Junho/2026: 1.516 metas,
1.401 metas fechadas, 1.125 premios fechados.

### 18.2 As tabelas (mapa confirmado pelo Thiago)

| Tabela | O que e |
|---|---|
| `PCGMPARAMMETA` | cabecalho da meta (a "parametrizacao 867") |
| `PCGMMETA` | a meta do colaborador; `CODENTIDADEMETA` = **CODUSUR** |
| `PCGMMETACOMB` | **a fato**: faturado, realizado, faixa, comissao, `DTFECHAMENTO` (meta fechada) e `DTPREMIACAO` (premio fechado), a nivel de RCA x INDUSTRIA |
| `PCGMMETACOMBCOMPLE` | o faturado quebrado por percentual de comissao (`PERCOMMOV` x `VLFATPORPERCOM`) |
| `PCGMINDICADOR` | 22 indicadores, com `REGRACALCPREVISTO` e `REGRACALCREALIZADO`. **16 = VALOR FATURADO LIQUIDO, 5 = NUMERO DE CLIENTES POSITIVADOS** |
| `PCGMFAIXAPADRAO` / `ITEM` | faixas **POR REGIONAL**: `PERCINICIAL`, `PERCFINAL`, `PESO` |
| `PCGMPARAMCOMB` + `PCGMPREMIOCOMB` | peso de cada indicador na parametrizacao |
| `PCGMMETAAPROV` | situacao da meta por RCA (`L` liberada, `A` aprovada), com quem e quando |
| `PCGMTIPOMETA` | **3 = META POR INDUSTRIA (fornecedor principal), 4 = META GERAL** |
| `PCGMPARAMETRO` | parametros globais |
| `PCCOMISSAOUSUR` | comissao cadastrada por RCA x PRODUTO (7,0 mi de linhas, 2.846 RCAs) |

`PCGMFILIALEMPREGADO` e `PCGMMETAOBSERV` estao VAZIAS.

### 18.3 A FORMULA (validada ao centavo)

```
comissao_bruta   = SOMA(VLFATPORPERCOM x PERCOMMOV / 100)   [PCGMMETACOMBCOMPLE]
PESO_X_NIVEL     = peso_do_indicador x (peso_da_faixa / 100)
VLCOMISSAO       = comissao_bruta x PESO_X_NIVEL / 100
```

Validado na meta 118452 (RCA 3639, Teresina, perfil NE2, abril/2026):

| Industria | Faturado | Bruta | % Ating. | Faixa | Peso x Nivel | Comissao |
|---|---|---|---|---|---|---|
| Alpargatas | 125.575,29 | 5.361,44 | 114,16% | 105+ → 105 | 80 x 1,05 = 84 | **4.503,61** |
| Torrone | 75,76 | 2,65 | 7,07% | 0-84,99 → 75 | 80 x 0,75 = 60 | **1,59** |
| Nova Foods | 214,75 | 7,11 | 23,12% | 0-84,99 → 75 | 80 x 0,75 = 60 | **4,26** |

Total do vendedor: R$ 4.509,46. Diferenca do calculado para o gravado: R$ 0,00.

A comissao varia POR PRODUTO dentro da mesma industria: a Alpargatas tem venda
a 3%, 4% e 5%. Nao existe "percentual da industria" — existe mix de aliquotas,
e e para isso que a PCGMMETACOMBCOMPLE existe.

### 18.4 As politicas de faixa sao DIFERENTES por regional — DE PROPOSITO

Isso NAO e erro de cadastro. As diferencas de modelo de comissao entre filiais
sao particularidades da regiao, do mercado e do modelo de industria que a EBD
representa naquele local.

| Perfil | Faturamento (ind. 16) | Positivacao (ind. 5) |
|---|---|---|
| SP, N02, NE1, NE2, NO1 | 75 → 80 → 85 → 90 → 100 → 105 | **0** → 30 → 50 → 70 → 100 → 105 |
| RJ | **faixa unica: 100** | 0 → 33,33 → 53,33 → 73,33 → 100 → 106,67 |
| N01 | **faixa unica: 100** | — |

Assimetria relevante: faturamento tem PISO 75 mesmo com 7% de atingimento;
positivacao ZERA abaixo de 85%.

**NUNCA comparar % de comissao entre filiais** e NUNCA apresentar a variacao de
faixa como anomalia. So compare dentro da mesma parametrizacao, ou a filial
contra a propria historia.

### 18.5 Parametros globais que mudam a base de calculo

`ABATER_VALOR_ST_COMISSAO = S` mas `ABATER_VALOR_ST_META = N`: o ICMS-ST e
abatido no calculo da COMISSAO e nao no da META. As duas bases sao diferentes
por desenho — e isso explica divergencia entre o atingimento que o vendedor ve
e o valor que ele recebe.

Outros: `UTILIZA_SOMENTE_FORNECEDOR_REVENDA = S`,
`BLOQUEAR_APURACAO_META_COM_VENDA_MAS_SEM_META = N` (vende sem meta cadastrada
e apura assim mesmo), `PERC_ATINGIDO_REALIZADO_POSITIVO_SEM_VALOR_PREVISTO = 100`.

### 18.6 Reconciliacao com o faturamento

O GM consome a view de faturamento. Medido na meta 118452: GM 125.865,80 contra
`VIEW_VENDAS_RESUMO_FATURAMENTO` 126.189,58 — diferenca de R$ 323,78 (0,26%),
compativel com o abatimento de ST e o filtro de fornecedor revenda.

Para "Real vs Meta" a ponte esta validada, desde que se filtre corretamente
(ver cicatriz #78).

## 19. Custo, precificacao (rotina 201) e sugestao de compra

Levantado e MEDIDO em 28/07/2026, com as formulas da TOTVS conferidas contra o
banco da EBD.

### 19.1 A taxonomia de custo — sao nove, nao um

| Coluna | O que e | Onde |
|---|---|---|
| `CUSTOULTENT` | o que a ultima NF trouxe | PCEST |
| `CUSTOREAL` | custo real MEDIO | PCEST |
| `CUSTOFIN` | custo com o financeiro embutido | PCEST |
| `CUSTOREP` | **custo de reposicao** = custo real medio + ICMS | PCPRODFILIAL (mais completo), PCEST, PCPRODUT |
| `CUSTOULTENTFIN` | ultima entrada financeiro | PCEST |
| `CUSTOPROXIMACOMPRA` | custo da proxima compra | PCPRODUT — **ZERADA** |
| `CUSTOFORNEC` | custo do fornecedor (rotina 240) | PCPRODUT — **ZERADA** |
| `PRECOFABRICA` | custo de reposicao futuro (rotina 240) | PCPRODUT — **ZERADA** |
| `CUSTOPRECIFIC` | o custo que FORMOU o preco | PCTABPR |

⚠️ `CUSTOREP` existe em TRES tabelas com o mesmo nome. Em SBC: PCPRODFILIAL
10.733, PCEST 7.681, PCPRODUT 2.886. **Usar a PCPRODFILIAL.**

A rotina 240 (politica comercial de compras) NAO e usada: custo fornecedor,
preco fabrica, custo da proxima compra e ponto de reposicao estao todos em
zero. `MARGEMMIN` da PCPRODUT tambem: nao ha piso de precificacao cadastrado.

### 19.2 De qual custo sai o preco (parametro 1907)

MEDIDO: o `CUSTOPRECIFIC` bate com o **CUSTO FINANCEIRO em 77,9%** dos casos
(5.367 de 6.893 em SBC), custo real 74,2%, ultima entrada 42,7%, reposicao 20%.

**A EBD precifica sobre o CUSTO FINANCEIRO.** O artigo da TOTVS confirma que o
valor da ultima entrada NAO entra na sugestao de preco.

### 19.3 A formula do preco sugerido (rotina 201)

```
Indice = (100 - (%impostos CMV + %CPMF + %frete KG + %frete terceiros/especial
                 + %comissao + %margem ideal)) / 100
Preco  = custo / Indice   (+ Comissao Freteiro, somada DEPOIS)
Margem Zero = mesmo indice SEM a margem  ->  indice_mz = indice + margem/100
```

E MARKUP sobre o preco de venda, nao margem sobre custo. O `%frete KG` nao e
fixo: `(Vl.FreteKg x Peso Bruto) / Custo Real x 100` — produto pesado e barato
carrega frete proporcionalmente muito maior.

⚠️ **A coluna `PCTABPR.INDICEPRECO` NAO e esse indice**: vale 1,0 em 100% das
1,9 milhao de linhas. Coluna morta (cicatriz #85). O indice real e calculado na
hora e nao fica gravado.

O indice IMPLICITO (`CUSTOPRECIFIC / PVENDA`) tem distribuicao real, de 0,37 a
0,88 em SBC. E a margem fica estavel em 20-23%: o que varia sao os ENCARGOS, de
21% a 63%. Isso e ST, IPI e frete — margem e politica, imposto e circunstancia.

### 19.4 A tabela de preco e por REGIAO, nao por filial

`PCTABPR` tem chave `CODPROD + NUMREGIAO`. O de-para e
**`PCFILIAL.NUMREGIAOPADRAO`** — a coluna `PCFILIAL.NUMREGIAO` esta NULA em
todas as filiais (cicatriz #84).

| Filial | Regiao | Filial | Regiao | Filial | Regiao |
|---|---|---|---|---|---|
| 01 Matriz | 31 | 02 SP | 1 | 03 Fortaleza | 39 |
| 04 Sao Luis | 33 | 05 Duque | 3 | 06 Manaus | 19 |
| 07 Macapa | 32 | 08 Boa Vista | 20 | 09 Juazeiro | 40 |
| 10 Sao Goncalo | 5 | 11 Santarem | 21 | 12 Imperatriz | 34 |
| 13 Taquara | 2 | 14 Pirai | 4 | 15 Guarulhos | 18 |
| 16 Itapevi | 36 | 18 SBC | 81 | 21 Teresina | 97 |
| 22 Maraba | 98 | 52 Petrolina | 42 | 53 Caruaru | 43 |

⚠️ Ha MUITO MAIS regiao de preco do que filial: um produto de giro tem preco em
53 regioes, e so 12 delas pertencem a alguma filial. **41 regioes sao orfas** —
e e nelas que estao os precos abaixo do custo de reposicao. Antes de tratar
preco baixo como problema comercial, verificar se a regiao tem filial.

### 19.5 A sugestao de compra (rotina 220)

```
Sugestao = GIRO_DIA x (PRAZO_ENTREGA + TEMPO_REPOSICAO)
         - ((ESTOQUE - RESERVADO - AVARIADO) + QT_PEDIDA)
```

Negativo = nao precisa comprar. Giro errado gera sugestao errada; recalculo nas
rotinas 552 (diaria) e 507 (eventual, opcao Giro Mercadoria).

⚠️ **`TEMREPOS` = 30 dias em 98,9% dos produtos.** E valor DEFAULT, nao gestao:
item de giro alto e item que gira uma vez por mes tem a mesma cobertura alvo. E
ele domina o calculo — o prazo de entrega medio e de ~10 dias.

O `PRAZOENTREGA` do fornecedor esta preenchido em 39% dos SKUs de revenda de
SBC, variando de 2,3% em Teresina a 93,6% em Sao Luis. O impacto na sugestao,
porem, e de apenas 3,2% — o tempo de reposicao pesa muito mais.

Cobertura real (`Est.Dia` = disponivel / giro dia): mediana de 24,7 dias em Sao
Luis a 289,3 em Maraba, contra o mesmo parametro de 30 para todos.

### 19.6 Preco abaixo do custo de reposicao — medido

R$ 415 mil/mes de perda ESTIMADA (giro diario x 30 x diferenca), concentrada no
Sudeste. Oito filiais com ZERO ocorrencia.

| Filial | SKUs abaixo | % | Perda/mes |
|---|---|---|---|
| 10 Sao Goncalo | 15 | 0,9% | R$ 79.155 |
| 05 Duque | 14 | 0,7% | R$ 78.064 |
| 18 SBC | 46 | 2,0% | R$ 58.820 |
| 16 Itapevi | 46 | 4,5% | R$ 52.961 |
| 02 SP | 47 | 3,5% | R$ 50.138 |

Em SBC a lista e quase toda BARILLA: massa com ovos a R$ 4,29 com reposicao de
R$ 5,19 (-21,1%), com 621 unidades/dia de giro no espaguete.

⚠️ E PROJECAO, nao realizado: multiplica giro por 30 dias e pela diferenca. Se a
proxima compra vier mais barata, a perda nao se materializa. Serve para
priorizar revisao de preco, NAO para lancar no resultado.


## Filial 70 — ARMAZEM GERAL SL KIBON (nao e filial comercial)

MEDIDO no banco em 03/08/2026. **Correcao:** a informacao inicial de que a
filial 70 teria "faturamento zero em 2026" estava ERRADA — ela tem notas.

| | |
|---|---|
| Fantasia | ARMAZEM GERAL SL KIBON |
| **Razao social** | **SOL NASCENTE LTDA** (diferente das demais, que sao EMPRESA BRASILEIRA DE DISTRIBUICAO) |
| Local | Sao Luis/MA, `NUMREGIAOPADRAO` = 33 (mesma da filial 04) |
| Notas em julho/2026 | **200** (R$ 1.042.568,04) |
| Especie | 113 `TP` (transferencia) + 87 `NF` |
| CONDVENDA | **10 em todas** — nenhuma com 1 |
| Clientes | SOL NASCENTE LTDA (a propria) e EMPRESA BRASILEIRA DE DISTRIBUICAO |

As duas pontas sao do grupo: e movimentacao entre CNPJs, nao venda a terceiro.
Por isso a 70 nao entra em ranking de filial, meta nem regional — o mapa
oficial tem 21 filiais comerciais e ela nao esta entre elas.

### CONDVENDA = 10 separa movimentacao de venda

Este e o achado que importa alem da filial 70. Medido em julho/2026:

| Filial | Nome | Notas | Valor | CONDVENDA | Clientes |
|---|---|---|---|---|---|
| 17 | EBD SAO PEDRO ALDEIA | 687 | R$ 7,83 mi | **10** | 1 |
| 23 | EBD PETROPOLIS | 392 | R$ 3,85 mi | **10** | 1 |
| 70 | ARMAZEM GERAL SL KIBON | 200 | R$ 1,04 mi | **10** | 2 |

Com `CONDVENDA = 1` as tres devolvem ZERO. Sem o filtro, entram R$ 12,7 mi de
movimentacao interna no faturamento.

⚠️ PENDENTE: o significado completo de cada `CONDVENDA` nao esta mapeado.
Sabemos que **1 = venda** (regra ja documentada) e que **10 = movimentacao
intragrupo**. Os demais codigos precisam ser levantados.


## Mapa REGIONAL x FILIAL — a fonte e o BANCO, nao este documento

⚠️ **NUNCA escrever o mapa a mao.** Ele sai de:

```sql
SELECT rf.FANTASIAREGIONAL AS REGIONAL, rf.CODFILIAL
FROM EBD.EBD_REGIONAISFILIAIS rf
WHERE rf.PARTICIPAGERENCIAL = 'S'
```

`PARTICIPAGERENCIAL = 'S'` e o filtro que separa as **9 regionais
operacionais** dos agrupamentos maiores (NORTE, NORDESTE, SAO PAULO, RIO DE
JANEIRO, ORIGEM RJ), que tem `= 'N'` e NAO devem entrar no painel.

⚠️ `EBD_REGIONAISFILIAIS.CODREGIONAL` **nao** e o mesmo codigo da
`PCREGIONAL.CODREGIONAL` — juntar as duas por esse campo produz lixo
(NE1 = Fortaleza, RJ1 = Sao Luis). A sigla ja vem em `FANTASIAREGIONAL`:
nao precisa de join.

### O mapa (medido 01/09/2026, para conferencia — a fonte continua sendo o banco)

| Regional | Filiais |
|---|---|
| **N1** | 06 Manaus · 08 Boa Vista |
| **N2** | 01 Matriz · 07 Macapa · 11 Santarem · 22 Maraba |
| **NE1** | 04 Sao Luis · 12 Imperatriz |
| **NE2** | 03 Fortaleza · 09 Juazeiro · 21 Teresina |
| **NE3** | 52 Petrolina · 53 Caruaru |
| **RJ1** | 10 Sao Goncalo · 13 Taquara |
| **RJ2** | 05 Duque · 14 Pirai |
| **SP1** | 02 SP · 16 Itapevi |
| **SP2** | 15 Guarulhos · 18 SBC |

O Norte usa **`N1` e `N2`** — nao `NO1`/`NO2`.

Confere com o GM: os perfis da `PCGMPERFIL` (NE1, NE2, N1...) batem com este
mapa. Duas fontes independentes, mesmo resultado.

### O que ja saiu errado por causa disso

Ate 01/09/2026 o `T-PAINEL01` tinha um mapa escrito a mao, com NE1/NE2/NE3
trocadas e o Norte como NO1/NO2. **O total do painel batia** (soma as 21
filiais de qualquer jeito), entao o erro so aparecia na quebra por regional —
e passou despercebido em varios paineis entregues a diretoria.

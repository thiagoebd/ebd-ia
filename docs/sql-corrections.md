# SQL Corrections — Gotchas e cicatrizes do Oracle Winthor

> **Como funciona este arquivo:** APPEND-ONLY. Toda vez que uma query Oracle
> falha por questão de schema/sintaxe Oracle, ou descobrimos algo não-óbvio do
> Winthor, adicionamos uma entrada aqui. O agente lê este arquivo ANTES de
> escrever qualquer SQL, garantindo que o mesmo erro nunca acontece duas vezes.
>
> **Convenção:** uma entrada por descoberta. Datada. Sem deletar entradas
> antigas (são cicatrizes — provam o que aprendemos).
>
> **Início:** 19/05/2026

---

## Entradas — Regras positivas (faça assim)

### 2026-05-19 — Filtro CODFILIAL é obrigatório (REGRA INVIOLÁVEL)

Tabelas grandes do Winthor (PCMOV, PCNFSAID, PCPEDC, PCEST) têm dezenas de
milhões de linhas. TODA query nessas tabelas DEVE incluir
WHERE CODFILIAL = :userFilial (ou IN (...) para regional).

Sem o filtro:
- Query estoura timeout (30s)
- Pode comprometer performance geral do ODA
- Resultado retornado seria inutilizável (totaliza 20 filiais misturadas)

Aplicável a: PCMOV, PCNFSAID, PCNFSAIDI, PCPEDC, PCPEDI, PCEST, qualquer
tabela com coluna CODFILIAL.

Não aplicável a dimensões pequenas como PCFILIAL, PCFORNEC, PCPRODUT, PCEMPR.

### 2026-05-19 — EBD.PCLIB tem 25.882.874 linhas

A tabela EBD.PCLIB (permissionamento da rotina 131) tem ~25,9 milhões de
linhas. SELECT COUNT(*) leva 4.1s na primeira vez (cold) e ~1s nas vezes
seguintes (cache).

Implicação:
- Em produção (quando consultarmos PCLIB), SEMPRE filtrar por usuário antes
- Cache do resultado em Redis (TTL 15min) é OBRIGATÓRIO
- Nunca fazer SELECT * FROM PCLIB sem WHERE

### 2026-05-19 — V$VERSION retorna múltiplas linhas

SELECT BANNER FROM V$VERSION retorna ~5 linhas. Para o banner principal:

    SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1

Ou:

    SELECT BANNER FROM V$VERSION WHERE BANNER LIKE 'Oracle Database%'

### 2026-05-19 — Convenção de bind variable: :userFilial

Pra evitar SQL injection, o agente NUNCA concatena CODFILIAL na string SQL.
Sempre usa bind variable com nome padronizado :userFilial.

Errado:

    sql = f"SELECT ... WHERE CODFILIAL = '{user_filial}'"

Certo:

    sql = "SELECT ... WHERE CODFILIAL = :userFilial"
    cursor.execute(sql, userFilial=user_filial)

### 2026-05-19 — Oracle 19c usa FETCH FIRST, não LIMIT

Diferente de Postgres/MySQL, Oracle não tem LIMIT. Sintaxe SQL:2008:

    SELECT * FROM tabela WHERE ... FETCH FIRST 10 ROWS ONLY

Para paginação:

    SELECT * FROM tabela WHERE ... OFFSET 0 ROWS FETCH FIRST 10 ROWS ONLY

Por convenção do projeto: queries sem FETCH FIRST recebem cap automático
de 10.000 linhas via SQL Guard.

### 2026-05-19 — PCFILIAL usa CODIGO, NÃO CODFILIAL

A tabela PCFILIAL é a ÚNICA tabela operacional onde o campo da filial chama
CODIGO, não CODFILIAL. Em todas as outras (PCNFSAID, PCPEDC, PCEST, PCMOV,
etc), continua sendo CODFILIAL.

Errado:

    SELECT * FROM EBD.PCFILIAL WHERE CODFILIAL = '01'
    -- ORA-00904: "CODFILIAL": invalid identifier

Certo:

    SELECT * FROM EBD.PCFILIAL WHERE CODIGO = '01'

Razão: PCFILIAL é a tabela "raiz" da hierarquia. As outras tabelas
referenciam PCFILIAL.CODIGO via coluna CODFILIAL.

### 2026-05-19 — PCNFSAIDI INACESSÍVEL ao EBD_LEITURA

O usuário EBD_LEITURA NÃO TEM acesso à tabela PCNFSAIDI (itens das notas
fiscais de saída). Análises por produto/SKU em NF devem usar views.

Errado (vai falhar):

    SELECT CODPROD, SUM(QT * PUNIT)
    FROM EBD.PCNFSAID s
    JOIN EBD.PCNFSAIDI i ON s.NUMNOTA = i.NUMNOTA
    WHERE ...

Certo (usar view dimensional pronta):

    SELECT CODIGOPRODUTO, SUM(QUANTIDADE * VALORUNITARIO)
    FROM EBD.GD_FATO_VENDAFATURAMENTO
    WHERE CODIGOFILIAL = :userFilial
      AND DATAFATURAMENTO BETWEEN TO_CHAR(:dtInicio, 'YYYYMMDD')
                              AND TO_CHAR(:dtFim, 'YYYYMMDD')
    GROUP BY CODIGOPRODUTO

Pendência: solicitar GRANT SELECT em PCNFSAIDI pro DBA, caso precisemos em
produção. Por ora, SEMPRE usar views GD_FATO_VENDA*.

### 2026-05-19 — PCCLIENT.RAMOATV NÃO existe — usar CODATV1 + JOIN PCATIVI

A coluna RAMOATV assumida na primeira versão dos templates NÃO existe em
PCCLIENT. O campo correto é CODATV1 (código numérico do ramo), e o nome do
ramo vem da tabela PCATIVI.

Errado:

    SELECT RAMOATV, COUNT(*) FROM EBD.PCCLIENT GROUP BY RAMOATV
    -- ORA-00904: "RAMOATV": invalid identifier

Certo (com JOIN):

    SELECT ATI.CODATIV, ATI.RAMO, COUNT(*) AS QTD
    FROM EBD.PCCLIENT C
    LEFT JOIN EBD.PCATIVI ATI ON ATI.CODATIV = C.CODATV1
    WHERE C.DTEXCLUSAO IS NULL
    GROUP BY ATI.CODATIV, ATI.RAMO
    ORDER BY QTD DESC

Mais simples (com view dimensional):

    SELECT RAMOATIVIDADE, COUNT(*) AS QTD
    FROM EBD.GD_DIM_CLIENTE
    GROUP BY RAMOATIVIDADE

A view GD_DIM_CLIENTE já entrega RAMOATIVIDADE como string pronta.

### 2026-05-19 — GD_DIM_FILIAL tem mapeamento Regional DEFASADO

A view GD_DIM_FILIAL no Oracle tem um campo CLASSIFICACAO (regional)
hardcoded, mas está DESATUALIZADO vs o BI atual.

View Oracle (DEFASADA):
- Mapeia apenas 16 das 20 filiais ativas (falta 18, 21, 52, 53)
- Usa 5 regionais: NO.1, NO.2, NE, RJ, SP
- Algumas filiais estão no regional errado (ex: 04 EBD SAO LUIS aparece como NO.2)

BI atual (CORRETO):
- Cobre as 20 filiais
- Usa 9 regionais: NE1, NE2, NE3, NO1, NO2, RJ1, RJ2, SP1, SP2

Regra: NUNCA usar GD_DIM_FILIAL.CLASSIFICACAO pra agrupar por regional.
SEMPRE usar o mapeamento da seção 4 do knowledge.md (regional → lista de
CODFILIAL).

A view ainda é útil para CODIGO, FANTASIA, CIDADE, UF, EMAIL. Mas o campo
regional dela é veneno.

### 2026-05-19 — Datas nas views GD_* são STRINGS YYYYMMDD

As views dimensionais do DW Oracle (GD_FATO_*, GD_DIM_*) retornam datas
como STRINGS no formato YYYYMMDD, não como DATE. Convenção do modelo
dimensional.

Errado:

    WHERE DATAFATURAMENTO BETWEEN :dtInicio AND :dtFim
    WHERE DATAVENDA >= TRUNC(SYSDATE, 'MM')

Certo:

    WHERE DATAFATURAMENTO BETWEEN TO_CHAR(:dtInicio, 'YYYYMMDD')
                              AND TO_CHAR(:dtFim, 'YYYYMMDD')
    WHERE DATAVENDA >= TO_CHAR(TRUNC(SYSDATE, 'MM'), 'YYYYMMDD')

Por quê: comparar string com string usando BETWEEN funciona em Oracle
quando o formato é YYYYMMDD (ordenação lexicográfica = cronológica).

Atenção: queries diretas em PCNFSAID.DTSAIDA, PCPEDC.DATA, PCPREST.DTVENC
continuam sendo DATE. Só as views GD_* convertem pra string.

### 2026-05-19 — Tabela de Metas é PCMETA (NÃO PCMETAFV)

Confirmado via view VW_METAS: a tabela de metas no Winthor EBD é PCMETA,
não PCMETAFV como assumido em rascunho anterior.

Estrutura:
- PCMETA.CODFILIAL — filial da meta
- PCMETA.CODUSUR — vendedor (NULL para metas de filial inteira)
- PCMETA.CODIGO — código da entidade alvo (fornecedor, produto, etc — depende de TIPOMETA)
- PCMETA.TIPOMETA — tipo: 'F' (fornecedor), 'R' (RCA), e outros a confirmar
- PCMETA.DATA — período (mês de referência)
- PCMETA.VLVENDAPREV — valor previsto (meta em R$)
- PCMETA.QTVENDAPREV — quantidade prevista
- PCMETA.QTPESOPREV — peso previsto
- PCMETA.MIXPREV — mix de produtos previsto
- PCMETA.CLIPOSPREV — positivação prevista

Views auxiliares:
- VW_METAS — view simplificada (todos os tipos de meta)
- GD_FATO_METAFORNECEDOR — metas filtradas por TIPOMETA = 'F'
- GD_FATO_METARCA — metas filtradas por TIPOMETA = 'R'
- Outras GD_FATO_META* para categoria, departamento, marca, etc.

Exemplo:

    -- Meta de fornecedor no mês corrente, filial 05
    SELECT CODIGOENTIDADEMETA AS CODFORNEC, VALOR AS META
    FROM EBD.GD_FATO_METAFORNECEDOR
    WHERE CODIGOFILIAL = :userFilial
      AND DATA BETWEEN TO_CHAR(TRUNC(SYSDATE, 'MM'), 'YYYYMMDD')
                   AND TO_CHAR(LAST_DAY(SYSDATE), 'YYYYMMDD')

---

## Anti-padrões — NÃO faça

### 2026-05-19 — Anti-padrão: SELECT * em tabelas grandes

Nunca usar SELECT * em PCMOV, PCNFSAID etc. Listar colunas explicitamente.
Reduz tráfego de rede, evita surpresas quando schema muda, e melhora plano
de execução.

### 2026-05-19 — Anti-padrão: concatenar strings em WHERE

Sempre usar bind variables. Concatenação é vetor de SQL injection e
quebra cache de plano de execução do Oracle.

### 2026-05-19 — Anti-padrão: JOIN sem CODFILIAL nos dois lados

Quando juntar tabelas com CODFILIAL, AMBAS devem ser filtradas pela mesma
filial.

Errado (joina filiais cruzadas):

    SELECT ... FROM PCNFSAID s
    JOIN PCNFSAIDI i ON s.NUMNOTA = i.NUMNOTA
    WHERE s.CODFILIAL = :userFilial

Certo:

    SELECT ... FROM PCNFSAID s
    JOIN PCNFSAIDI i ON s.NUMNOTA = i.NUMNOTA AND s.CODFILIAL = i.CODFILIAL
    WHERE s.CODFILIAL = :userFilial

### 2026-05-19 — Anti-padrão: função em coluna indexada

Quando filtrar por data, evitar TRUNC/TO_CHAR na coluna do banco
(quebra uso de índice).

Errado:

    WHERE TRUNC(DTSAIDA) = TRUNC(SYSDATE)

Certo (usa índice):

    WHERE DTSAIDA >= TRUNC(SYSDATE) AND DTSAIDA < TRUNC(SYSDATE) + 1

---

## Formato para novas entradas

Para futuras entradas, seguir o padrão:

    ### YYYY-MM-DD — Título curto descrevendo a descoberta

    Contexto: o que estava acontecendo / qual query estava sendo escrita
    Erro/observação: o que deu errado ou foi descoberto (com código ORA-XXXXX)
    Solução: como fazer corretamente
    Exemplo: snippet de SQL antes/depois quando aplicável

### 2026-05-20 — Alias de 1 letra "V" causa ORA-06553 PLS-306

Quando o alias de uma tabela/view é a letra V, o Oracle 19c interpreta
expressões como v.COLUNA como chamada à função PL/SQL V('COLUNA') (V é
função do APEX). Resultado: ORA-06553: PLS-306: wrong number or types of
arguments in call to 'V'.

Errado:
    SELECT v.VALORTOTAL FROM EBD.GD_FATO_VENDAFATURAMENTO v
    -- ORA-06553

Certo (alias de 2-3 letras descritivo):
    SELECT vf.VALORTOTAL FROM EBD.GD_FATO_VENDAFATURAMENTO vf

Padrão adotado no projeto:
- vf = venda_faturamento
- dr = dim_rca
- dc = dim_cliente
- dp = dim_produto
- mf = meta_fornecedor
- cr = contas_receber
- ea = estoque_atual

REGRA: NUNCA usar alias de 1 letra em SQL Oracle. Mínimo 2 letras,
preferencialmente descritivas.

### 2026-05-20 — Views GD_* RENOMEIAM colunas das tabelas raw

A view GD_FATO_VENDAFATURAMENTO faz PCMOV.NUMTRANSVENDA AS NUMEROTRANSVENDA.
Quem consulta a TABELA PCMOV usa NUMTRANSVENDA. Quem consulta a VIEW
GD_FATO_VENDAFATURAMENTO usa NUMEROTRANSVENDA (com "ERO").

Outros aliases descobertos:
- PCMOV.NUMTRANSVENDA  -> GD_*.NUMEROTRANSVENDA
- PCMOV.CODUSUR        -> GD_*.CODIGORCA
- PCMOV.CODCLI         -> GD_*.CODIGOCLIENTE
- PCMOV.CODPROD        -> GD_*.CODIGOPRODUTO
- PCMOV.CODFILIAL      -> GD_*.CODIGOFILIAL
- PCNFSAID.DTSAIDA     -> GD_*.DATAFATURAMENTO (e convertido pra YYYYMMDD)
- PCMOV.QT             -> GD_*.QUANTIDADE
- PCNFSAID.NUMNOTA     -> GD_*.NUMERONOTAFISCAL (provável)
- PCMOV.PUNIT          -> GD_*.VALORUNITARIO
- PCMOV.CUSTOFIN       -> GD_*.VALORUNITARIOCUSTO

REGRA: Antes de escrever SQL contra uma view GD_*, SEMPRE consultar
docs/winthor_discovery.md ou rodar SELECT * FETCH FIRST 1 ROW ONLY
pra confirmar os aliases REAIS. Não assumir nome da coluna baseado na
tabela raw.

### 2026-05-20 — GD_FATO_VENDAFATURAMENTO em cold cache: 50s+

Primeira execução da view com filtros (CODIGOFILIAL + DATAFATURAMENTO BETWEEN)
levou 54.3s. A view faz JOIN entre PCMOV + PCNFSAID + PCPRODUT + PCMOVCOMPLE
e tem fórmulas complexas (DECODE, ROUND aninhados) pra calcular VALORTOTAL.

Latência medida:
- Cold cache (1ª query do dia): 50-60s
- Warm cache: a confirmar em execução subsequente

Implicações:
1. Cache de Redis (TTL 15min) é OBRIGATÓRIO para qualquer agente em produção
2. Pré-aquecimento ("warmup") da view em queries comuns no startup
3. Considerar criar materialized view dedicada se latência warm > 10s

### 2026-05-20 — GD_FATO_VENDAFATURAMENTO ✅ VALIDADA contra ERP

Em 20/05/2026, executada query agregada (Faturamento por Supervisor) sobre
a view GD_FATO_VENDAFATURAMENTO, filtrando:
- CODIGOFILIAL = '06' (Manaus)
- DATAFATURAMENTO BETWEEN '20260501' AND '20260520'
- CODIGOSUPERVISOR = 252 (Eduardo Leandro)

Resultado da view: R$ 1.088.147,86 (730 notas, 91.632 unidades, 403 clientes
únicos, 7 RCAs ativos).

Resultado do ERP Winthor (mesma janela, mesmo recorte): R$ 1.088.147,86.

DIFERENÇA: ZERO. Bateu nos centavos.

CONCLUSÃO: GD_FATO_VENDAFATURAMENTO é fonte de verdade confiável pra
"Faturamento Bruto" no contexto do BI EBD. Pode ser usada em queries do
agente sem necessidade de adicionar exclusões manuais de CONDVENDA, devoluções,
cancelamentos (a view já faz internamente).

Promovido a base oficial pros templates T100, T101, T102, T103, T107.


### 2026-05-20 — GD_FATO_VENDAFATURAMENTO é LENTA (cold 54s, warm 13s)

Medições reais (filial 06, 20 dias, agregação por supervisor):
- Cold cache (1ª execução): 54.353ms
- Warm cache (2ª execução): 13.404ms

A view faz JOIN entre PCMOV + PCNFSAID + PCPRODUT + PCMOVCOMPLE com fórmulas
DECODE/ROUND aninhadas pra calcular VALORTOTAL corretamente (considerando
CONDVENDA, bonificações, frete, IPI, ST, etc).

Implicações OBRIGATÓRIAS pra agente em produção:
1. Cache Redis TTL 15min em TODA query agregada — sem isso, UX inviável
2. Pré-aquecimento (warmup) das queries comuns no startup do agente
3. Avaliar materialized view dedicada se warm > 10s mesmo com filtros mais
   restritivos (ex: 1 RCA específico, 1 dia)
4. Considerar limitar período máximo a 31 dias por query (mais que isso,
   sugerir parcelamento)

### 2026-05-20 — Nem toda view GD_FATO_* tem coluna VALORTOTAL

Views como GD_FATO_BONUS, GD_FATO_VENDADEVOLUCAOAVULSA e GD_FATO_VENDACANCELADA
NÃO têm VALORTOTAL pré-agregado. Têm apenas QUANTIDADE + VALORUNITARIO.

Pra calcular total: `SUM(QUANTIDADE * VALORUNITARIO)`.
Sempre conferir colunas reais antes de assumir.

### 2026-05-20 — GD_FATO_VENDAFATURAMENTO ✅ VALIDADA contra ERP (centavo)

Query agregada filial 06, supervisor 252 (Eduardo Leandro), 01-20/05/2026:
MCP: R$ 1.088.147,86 / ERP Winthor: R$ 1.088.147,86 / DIFERENÇA: ZERO.

Query agregada filial 06 inteira mesmo período:
View: R$ 11.444.947,76 / ERP "Venda Faturada": R$ 11.444.947,76 / DIFERENÇA: ZERO.

GD_FATO_VENDAFATURAMENTO.VALORTOTAL = "Venda Faturada (Bruto)" do ERP EBD.

A view exclui internamente: CONDVENDA 5/6/11/12 (bonificações), CODOPER fora
de S/ST/SM, TIPOVENDA SR e DF, CODFISCAL = 0. NÃO replicar manualmente.

Latência: cold 54s, warm 13s. Cache Redis obrigatório em produção.

### 2026-05-20 — ✅ FÓRMULA OFICIAL "VENDA LÍQUIDA EBD" descoberta e validada

Entregue pelo time BI EBD em 20/05. Replicada via MCP, bateu CENTAVO A CENTAVO
contra ERP do BI. Filial 06, 01-19/05/2026:
  MCP: Bruto R$ 10.412.159,31 | Dev R$ 999.443,01 | LIQUIDO R$ 9.412.716,30
  BI:  Bruto R$ 10.412.159,31 | Dev R$ 999.443,01 | LIQUIDO R$ 9.412.716,30
Latência: 1.4s.

A VIEW OFICIAL DA EBD é `VIEW_VENDAS_RESUMO_FATURAMENTO` (sem sufixo _EBD).
Existem 3 versões no DW:
  VIEW_VENDAS_RESUMO_FATURAMENTO      ← OFICIAL (esta)
  VIEW_VENDAS_RESUMO_FATURAMENTO_EBD  ← variante (não bate)
  VIEW_VENDAS_RESUMO_FATURAMENTO_EBD1 ← variante (não bate)

O segredo: filtro `CONDVENDA = 1` (Venda à vista/prazo normal). Sem esse
filtro, inclui bonificações/vendas casadas que o BI exclui.

Devolução vem de DUAS views via UNION ALL:
  VIEW_DEVOL_RESUMO_FATURAMENTO  (vinculada à venda) — usa CONDVENDA = 1
  VIEW_DEVOL_RESUMO_FATURAVULSA  (sem vínculo) — SEM filtro de CONDVENDA

Coluna agregada em ambas: VLDEVOLUCAO. Período por DTENT (data entrada).

Datas são DATE (não strings YYYYMMDD) nessas views — usar:
  WHERE DTSAIDA BETWEEN TO_DATE(:dt,'YYYY-MM-DD') AND TO_DATE(:dt,'YYYY-MM-DD')

### 2026-05-20 — REGRA INVIOLÁVEL: "mês corrente" = ATÉ AGORA, não até ontem

Quando diretor pergunta "como está o mês?", ele quer o número DESTE SEGUNDO.

Errado (corta no início de hoje):
    WHERE DTSAIDA >= TRUNC(SYSDATE,'MM') AND DTSAIDA < TRUNC(SYSDATE)

Certo:
    WHERE DTSAIDA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE

Exceção: comparativo com mês anterior fechado:
    WHERE DTSAIDA >= ADD_MONTHS(TRUNC(SYSDATE,'MM'),-1)
      AND DTSAIDA <  TRUNC(SYSDATE,'MM')

### 2026-05-20 — ORA-00937: scalar subquery + função agregada incompatíveis

Oracle 19c não permite misturar `SUM(col)` com `(SELECT x FROM y)` no mesmo
SELECT sem GROUP BY. Workaround: separar em CTEs e CROSS JOIN.

Errado:
    SELECT SUM(col), (SELECT meta FROM m) FROM t   -- ORA-00937

Certo:
    WITH agg AS (SELECT SUM(col) AS x FROM t),
         meta AS (SELECT meta_value FROM m)
    SELECT a.x, m.meta_value FROM agg a CROSS JOIN meta m

### 2026-05-20 — PCFILIAL na EBD usa SÓ CODIGO + FANTASIA

Padrão consolidado da EBD: NÃO usar UF, CIDADE, MUNICIPIO em queries executivas
contra PCFILIAL. Identificação de filial = `CODIGO + FANTASIA`. Quem precisar
geografia usa GD_DIM_FILIAL (raro).

Atenção: PCFILIAL tem coluna BLOB/RAW que quebra `SELECT *` no MCP serializer
(TypeError __str__ returned non-string type bytes). SEMPRE listar colunas
explicitamente em PCFILIAL.

REGRA: ao consultar PCFILIAL pra exibir filial:
    SUBSTR(NVL(pf.FANTASIA, '?'), 1, 30) AS FILIAL

A FAZER: corrigir `_safe_value` no server.py pra tratar bytes
(decode utf-8 errors='replace' OU hex OU None).

### 2026-05-20 — ✅ FÓRMULA UNIVERSAL "Real Líquido por Fornecedor"

Validada em 20/05 contra BI EBD: Pandurata bateu CENTAVO A CENTAVO.
Filial 06+todas, 01-19/05/2026, Pandurata: MCP R$ 6.853.508,52 vs BI
R$ 6.853.508,52. Diferença ZERO.

REGRA 1: CODIGO na PCMETA representa CODFORNECPRINC (NÃO CODFORNEC qualquer).
  Empresas grandes têm N CODFORNEC no Winthor (por CNPJ, filial industrial).
  A meta cadastrada UNICAMENTE pelo CODFORNECPRINC. Exemplo:
  Pandurata tem 13 CODFORNEC (43, 62, 68, 369, 395, 518, 1975, 1980, 4137,
  10472, 10730, 14324, 16006), todos com CODFORNECPRINC=62.
  Meta existe APENAS em CODIGO=62.

REGRA 2: PCMETA tem MUITAS linhas por mês/CODIGO/CODFILIAL (sub-metas).
  Pandurata: 317 linhas no mês corrente, todas CODIGO=62 CODFILIAL=05.
  SEMPRE usar SUM(VLVENDAPREV).

REGRA 3: Fórmula correta de Real Líquido por fornecedor:

    WITH fornec_principal AS (
        SELECT CODFORNEC, NVL(CODFORNECPRINC, CODFORNEC) AS COD_RAIZ
        FROM EBD.PCFORNEC
    ),
    real AS (
        SELECT SUM(v.VLATEND) AS REAL_FATURADO
        FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
        JOIN EBD.PCPRODUT p ON p.CODPROD = v.CODPROD
        JOIN fornec_principal fp ON fp.CODFORNEC = p.CODFORNEC
        WHERE v.DTSAIDA BETWEEN :dtInicio AND :dtFim
          AND v.CONDVENDA = 1
          AND fp.COD_RAIZ = :codFornecPrincipal
    ),
    dev_vinc AS (
        SELECT SUM(d.VLDEVOLUCAO) AS DEV
        FROM EBD.VIEW_DEVOL_RESUMO_FATURAMENTO d
        JOIN EBD.PCPRODUT p ON p.CODPROD = d.CODPROD
        JOIN fornec_principal fp ON fp.CODFORNEC = p.CODFORNEC
        WHERE d.DTENT BETWEEN :dtInicio AND :dtFim
          AND d.CONDVENDA = 1
          AND fp.COD_RAIZ = :codFornecPrincipal
    ),
    dev_avul AS (
        SELECT SUM(d.VLDEVOLUCAO) AS DEV
        FROM EBD.VIEW_DEVOL_RESUMO_FATURAVULSA d
        JOIN EBD.PCPRODUT p ON p.CODPROD = d.CODPROD
        JOIN fornec_principal fp ON fp.CODFORNEC = p.CODFORNEC
        WHERE d.DTENT BETWEEN :dtInicio AND :dtFim
          AND fp.COD_RAIZ = :codFornecPrincipal
    )
    SELECT (SELECT REAL_FATURADO FROM real)
           - NVL((SELECT DEV FROM dev_vinc), 0)
           - NVL((SELECT DEV FROM dev_avul), 0) AS REAL_LIQUIDO
    FROM DUAL

TIPOMETA confirmados:
  F  = CODFORNECPRINC (fornecedor)    ← validado
  M  = CODMARCA (marca)
  SV = CODSUPERVISOR (supervisor)
  GC = CODGERENTE (gerente comercial)
  FL = CODFILIAL (filial)
  R  = CODUSUR (RCA) — a validar

Colunas-chave PCMETA:
  VLVENDAPREV       Meta R$ vendas
  CLIPOSPREV        Meta de positivacao (clientes unicos)
  MIXPREV           Meta de mix de produtos
  PEDIDOSPREV       Meta qtd pedidos
  MARGEMPREV        Meta de margem
  PERINADIMPPREV    Meta % inadimplencia (limite maximo)

### 2026-05-20 — Descoberta arquitetural: BI separa "Real" de "Pedidos"

Print BI EBD em 20/05 (fornecedores até 19/05):
  AJINOMOTO  Meta 27.469.591  Real 8.733.104  Ped 1.627.826  R+Ped 10.360.930
  PANDURATA  Meta 15.587.187  Real 6.853.508  Ped 1.041.750  R+Ped  7.895.259
  HEINZ      Meta 16.272.491  Real 5.862.411  Ped   675.925  R+Ped  6.538.337

BI EBD separa estritamente:
  "Real"       = NF EMITIDA E FATURADA (VIEW_VENDAS_RESUMO_FATURAMENTO)
  "Pedidos"    = liberados a faturar mas ainda nao faturados (PCPEDC)
  "Real + Ped" = soma — visao completa do "que vai entrar na meta"

Consequencia: todo template de comparativo Real-vs-Meta DEVE ter coluna
Pedidos ao lado. Top diretor/gerente quer ver Real+Ped pra projecao.
Top operacional (financeiro, comercial) quer ver Pedidos travados pra agir.

PENDENCIA: sondar PCPEDC.POSICAO pra mapear estados (liberado, preso
financeiro, preso comercial, em digitacao).


---

## #38 — SEMPRE buscar GD_FATO/GD_DIM antes de derivar de PC* (20/05/2026)

**Sintoma:** Tentei derivar carteira BR de PCCLIENT chutando filtros (bloqueio, datas, RCA1/2/3). Errado por 6 horas.

**Causa:** Não verifiquei se Winthor já expõe a métrica via view DW.

**Solução:** ANTES de qualquer query derivativa em tabela PC*, executar:

```sql
SELECT view_name FROM all_views
WHERE owner='EBD' AND view_name LIKE 'GD_FATO_%';

SELECT table_name FROM all_tables
WHERE owner='EBD' AND table_name LIKE 'GD_DIM_%';
```

**Padrão Winthor DW:** GD_DIM_* = dimensões, GD_FATO_* = fatos. Métricas usadas no BI estão lá prontas.

**Caso concreto:** carteira BR (77.315 do BI) vem de `GD_FATO_ROTACLIENTE` direto — 1 linha de SQL, não 6h de chute de filtros.


---

## #39 — Excluir RCAs ÓRFÃOS/VAGOS de métricas de produtividade

RCAs com nome iniciando em 'ORFAO' ou 'RCA VAGO' são códigos fictícios
de filial usados como "depósito" de clientes parados/desistidos. Eles
nunca visitam. **Filtro obrigatório em qualquer métrica de rota:**

```sql
AND UPPER(NVL(dr.RCA,'')) NOT LIKE 'ORFAO%'
AND UPPER(NVL(dr.RCA,'')) NOT LIKE 'RCA VAGO%'
```

## #40 — DIASEMANA tem inconsistências TERCA/TERÇA e SABADO/SÁBADO

Cadastro misturado. Sempre usar:
```sql
WHERE UPPER(DIASEMANA) IN (NOME, REPLACE(NOME,'C','Ç'))
```

## #41 — Cobertura de rota entre RCAs

Aproveitamento por RCA NÃO pode usar CODUSUR = CODIGORCA do par
da rota. Quando RCA falta, colega cobre. Métrica correta:
"clientes DA rota do RCA X atendidos hoje (por qualquer um)".


---

## #42 — Ruptura BR = PCFALTA sem filtro filial (BI inclui CDs)

A view BI de ruptura nao filtra CODFILIAL — soma CDs no total geral.
Filiais "fantasmas" 17 (R$ 705K mes) e 23 (R$ 346K mes) sao CDs reais
com ruptura fisica. Devem entrar.

## #43 — Remapeamento CD → filial mae em ruptura/operacao

CDs 17 (São Pedro da Aldeia) e 23 (Petrópolis) servem fisicamente
as filiais 10 (São Gonçalo) e 14 (Piraí) respectivamente. Em VENDAS
o sistema integra automaticamente. Em RUPTURA precisa forcar via CASE.

## #44 — PCFALTA tem CODUSUR + CODCLI direto

PCFALTA contem 10 colunas, incluindo CODUSUR (vendedor) e CODCLI
(cliente) DIRETO. Nao precisa fazer JOIN com PCPEDC para descobrir
quem vendeu / pra quem. JOIN só com GD_DIM_RCA pra puxar
supervisor/gerente.


---

## #48 — PCVISITAFV eh o "GPS-truth" das visitas

PCVISITAFV = app de forca de vendas em producao. 8M+ linhas historico.
140-180k visitas/mes em 2026. Latitude/Longitude preenchidos.
74,5% adocao (922 de 1.238 RCAs).

USAR PARA: cobertura REAL, motivo de nao-venda, vendas fora de rota.
NAO usar PCVISITA (sistema antigo, mesmas linhas mas sem GPS limpo).

## #49 — Catalogo PCMOTNAOCOMPRA tem 14 motivos (hardcode no agente)

PCMOTIVONAOATEND e PCMOTVISITA estao VAZIAS.
O catalogo correto eh PCMOTNAOCOMPRA (14 linhas).
Mas existem codigos em PCVISITAFV (16,17,18,19,21,90) que nao estao
no catalogo - hardcode "LEGADO" pra esses.

## #50 — Janela de periodo parametrizada (semana/mes/ano)

```sql
WINDOWS = {
    'semana': "v.DATA >= TRUNC(SYSDATE,'IW')",
    'mes':    "v.DATA >= TRUNC(SYSDATE,'MM')",
    'ano':    "v.DATA >= TRUNC(SYSDATE,'YYYY')",
}
```

## #51 — Cadastro duplicado de RCAs

Alexandre Sebastiao tem 2 codigos diferentes (3119 e 3726) com mesmo nome.
Cod 3119 com 0 dentro/84 fora (100%) parece fantasma ativo. Investigar.


---

## #52 — Como subir o MCP Oracle (entry-point correto)

```bash
cd ~/projects/ebd-ia/mcps/oracle
python3 -m app.server &
```

Estrutura: mcps/oracle/app/server.py (instalado com pip install -e .)
Pacote chamado "app" (nao "src" nem "ebd_ia_mcp_oracle").
Roda em 0.0.0.0:8989 com pool 2-10 conexoes Oracle.
Log estruturado em logs/mcp-oracle/queries.jsonl.

NUNCA usar `python3 -m src.mcp_oracle.server` (modulo nao existe).


---

## #53 - PCUSUARI eh o vinculo canonico RCA->Filial

Regra negocio: 1 RCA = 1 filial, 1 Supervisor = 1 filial.
Tabela PCUSUARI tem CODFILIAL direto. GD_DIM_RCA NAO tem filial.

Para derivar filiais por Supervisor/Gerente:
  JOIN PCUSUARI u ON u.CODUSUR = dr.CODIGORCA
  GROUP BY dr.CODIGOSUPERVISOR (ou GERENTE)
  DISTINCT u.CODFILIAL

## #54 - Mix Disponivel: regra final validada

Filtros corretos do "mix disponivel":
  pf.REVENDA = 'S'
  AND pf.ATIVO = 'S'
  AND pf.PROIBIDAVENDA = 'N'    <- nome com 'IDA', nao PROIBVENDA
  AND pf.FORALINHA = 'N'
  AND EXISTS (PCEST com QTESTGER > 0)

NAO ADICIONAR filtro de DTULTENT (gera efetividade > 100%).
PCPRODUT nao tem coluna DTULTENT - so PCEST tem.



<!-- AUTO-APPEND PROP-6687F4E3 aprovado por thiago -->


### 2026-05-21 — GD_DIM_CLIENTE: aliases reais confirmados

Tentativas com `SITUACAO` e `FANTASIA` quebraram com ORA-00904.
Executado `SELECT *` pra confirmar schema real.

**Colunas confirmadas (nomes exatos):**

| Campo assumido (errado) | Campo real (correto) |
|---|---|
| `SITUACAO` | `STATUS` |
| `FANTASIA` | `NOMEFANTASIA` |
| — | `NOMEFANTASIACLIENTEPRINCIPAL` |
| — | `CLIENTEPRINCIPAL` |
| — | `DIASINATIVOS` (texto, ex: "DE 31 A 45 DIAS") |

**Schema completo confirmado:**
```
CODIGOCLIENTE, CLIENTE, CPJCNPJ, TIPOCLIENTE, CODIGOIBGE,
BAIRRO, CEP, ENDERECO, NOMEFANTASIA, CLASSE, CLASSIFICACAO,
EMAILCLIENTE, CODIGORAMOATIVIDADE, RAMOATIVIDADE, GRUPO,
PRACA, CODIGOROTA, ROTA, CODIGOREDE, REDE, REGIAO, UFREGIAO,
CIDADE, UF, NOMEFANTASIACLIENTEPRINCIPAL, CLIENTEPRINCIPAL,
STATUS, DIASINATIVOS, DTCADASTRO, DTULTCOMP, LATITUDE, LONGITUDE
```

**Exemplo de uso correto:**
```sql
SELECT dc.CODIGOCLIENTE, dc.CLIENTE, dc.NOMEFANTASIA,
       dc.CIDADE, dc.UF, dc.RAMOATIVIDADE,
       dc.STATUS, dc.DIASINATIVOS
FROM EBD.GD_DIM_CLIENTE dc
WHERE dc.CODIGOCLIENTE = :codCli
```

**Observações:**
- `STATUS` = 'ATIVO' | 'INATIVO' | 'EXCLUÍDO' (conforme knowledge.md seção 11.1)
- `DIASINATIVOS` é string descritiva: 'ATÉ 30 DIAS', 'DE 31 A 45 DIAS', etc.
- `CODIGOCLIENTE` = número (INTEGER), não string
- `TIPOCLIENTE` = 'F' (Físico) | 'J' (Jurídico)
- `LATITUDE`/`LONGITUDE` podem ser NULL (nem todos os clientes têm geolocalização)



<!-- AUTO-APPEND PROP-505AB8E9 aprovado por thiago -->


### 2026-05-21 — TRUNC() em DATAFATURAMENTO causa ORA-01722 — usar SUBSTR pra agrupar por mês

Tentativa de usar `TRUNC(vf.DATAFATURAMENTO, 'MM')` quebrou com
`ORA-01722: invalid number` porque `DATAFATURAMENTO` é **string VARCHAR2**
no formato `YYYYMMDD`, não um tipo DATE.

**Errado:**
```sql
SELECT TRUNC(vf.DATAFATURAMENTO, 'MM') AS MES  -- ORA-01722
FROM EBD.GD_FATO_VENDAFATURAMENTO vf
```

**Certo — agrupar por mês (YYYYMM):**
```sql
SELECT SUBSTR(vf.DATAFATURAMENTO, 1, 6) AS MES_ANO  -- ex: '202605'
FROM EBD.GD_FATO_VENDAFATURAMENTO vf
GROUP BY SUBSTR(vf.DATAFATURAMENTO, 1, 6)
ORDER BY MES_ANO DESC
```

**Certo — agrupar por ano (YYYY):**
```sql
SELECT SUBSTR(vf.DATAFATURAMENTO, 1, 4) AS ANO  -- ex: '2026'
FROM EBD.GD_FATO_VENDAFATURAMENTO vf
GROUP BY SUBSTR(vf.DATAFATURAMENTO, 1, 4)
```

**Certo — converter pra DATE quando precisar de aritmética:**
```sql
TO_DATE(vf.DATAFATURAMENTO, 'YYYYMMDD') AS DT_DATE
```

**Regra geral:** qualquer função que espera DATE (TRUNC, ADD_MONTHS, etc.)
**não pode** ser aplicada diretamente nas colunas das views GD_*. Sempre
converter com `TO_DATE(col, 'YYYYMMDD')` antes, ou usar `SUBSTR` pra
agrupamentos simples por mês/ano.

Isso reforça a cicatriz de 19/05/2026 "Datas nas views GD_* são STRINGS YYYYMMDD".



<!-- AUTO-APPEND PROP-AD8844AA aprovado por Thiago -->


## Cicatriz: Projeção de Fechamento Mensal EBD — Fórmula Validada

> Descoberta e validada em 28/05/2026 com base em dados reais jan-mai/2026.
> Erro anterior: uso de ritmo médio diário ignorava o padrão de fechamento em lote.

---

### ⚠️ O problema (por que os 3 cenários anteriores erraram)

O modelo de projeção usava **ritmo médio diário × dias restantes**.
Esse modelo FALHA porque ignora que o faturamento EBD é **fortemente não-linear**:
os últimos 1-2 dias do mês concentram 19-31% do total mensal em lote.

---

### 📊 Padrão histórico confirmado (bruto EBD sem excluir loja)

| Mês | Total Mês | Penúltimo dia (R$) | Último dia (R$) | % último dia |
|---|---|---|---|---|
| Jan/2026 | ~R$280M | Sex 30/01: R$30,0M | Sáb 31/01: R$61,5M | ~22% |
| Fev/2026 | R$329,8M | Sex 27/02: R$36,7M | Sáb 28/02: R$62,4M | ~19% |
| Mar/2026 | R$360,4M | Seg 30/03: R$10,1M | Ter 31/03: R$86,4M | ~24% |
| Abr/2026 | R$289,1M | Qua 29/04: R$24,0M | Qui 30/04: R$88,9M | ~31% |
| Mai/2026 | ~R$332,9M | Sex 29/05: R$38,5M | Sáb 30/05: R$62,6M | ~19% |

**Faixa do último dia útil do mês: R$60M–R$89M** (independente do dia da semana).

**Faixa do penúltimo dia útil:** R$10M–R$38,5M (mais variável).

**Aceleração começa na quinta-feira da última semana** — não só no último dia.

---

### 🔵 Exceção crítica: Loja EBD (ORIGEMPED='W' + CODEMITENTE=7777)

A loja EBD (B2B + B2E) tem **comportamento LINEAR** — NÃO segue o padrão de fechamento em lote.

| Mês | Total Loja | Média diária útil |
|---|---|---|
| Jan/2026 | R$799K | ~R$37K/dia útil |
| Fev/2026 | R$1,02M | ~R$48K/dia útil |
| Mar/2026 | R$1,21M | ~R$57K/dia útil |
| Abr/2026 | R$1,13M | ~R$54K/dia útil |
| Mai/2026 | R$1,16M | ~R$54K/dia útil |

Nos últimos 7 dias da loja, **nenhum dia foge da faixa normal** — confirma linearidade.

**REGRA:**
> Quando o usuário perguntar "previsão de fechamento" ou "projeção do mês":
> - O faturamento da loja NÃO usa a fórmula de lote — usa **ritmo médio linear**.
> - O faturamento da loja **pode permanecer incluído no total geral** (não precisa ser excluído da visão macro).
> - Separar apenas quando o usuário pedir análise específica da loja.

---

### 🎯 Fórmula de projeção EBD (corrigida)

```
PREVISÃO_FECHAMENTO = ACUMULADO_ATÉ_HOJE
                    + PROJEÇÃO_DIAS_RESTANTES_NORMAIS
                    + BÔNUS_FECHAMENTO_LOTE
```

#### Componentes:

**1. Acumulado até hoje**
```sql
SELECT SUM(v.VLATEND)
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
WHERE v.DTSAIDA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
  AND v.CONDVENDA = 1
```

**2. Projeção dias restantes normais** (excluindo os 2 últimos dias do mês)
```
ritmo_medio = acumulado / dias_uteis_passados
projecao_normal = ritmo_medio × dias_uteis_restantes_excluindo_ultimos_2
```
> "Dias úteis" = dias com faturamento > R$1M (exclui dom e feriados automaticamente)

**3. Bônus de fechamento em lote** (constante histórica):
- Penúltimo dia útil do mês: usar **mediana histórica = R$24M** (faixa R$10M–R$38M)
- Último dia útil do mês: usar **mediana histórica = R$75M** (faixa R$60M–R$89M)

> Se já passaram esses dias, usar o valor real já incluído no acumulado.

#### Cenários recomendados:

| Cenário | Último dia | Penúltimo | Uso |
|---|---|---|---|
| Conservador | R$62M | R$15M | Piso |
| Base | R$75M | R$24M | Referência |
| Otimista | R$89M | R$38M | Teto |

---

### 📐 Cálculo de dias úteis

```sql
-- Dias com faturamento real > R$1M no mês corrente (proxy de "dia útil")
SELECT COUNT(*) AS DIAS_UTEIS_PASSADOS,
       SUM(BRUTO) AS ACUMULADO
FROM (
  SELECT TRUNC(v.DTSAIDA) AS DT, SUM(v.VLATEND) AS BRUTO
  FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
  WHERE v.DTSAIDA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
    AND v.CONDVENDA = 1
  GROUP BY TRUNC(v.DTSAIDA)
  HAVING SUM(v.VLATEND) > 1000000
)
```

---

### ⚠️ Anti-padrões a evitar

- ❌ **Nunca usar média simples × 31** para projetar meses com fechamento em lote
- ❌ **Nunca projetar a loja com o mesmo modelo** do faturamento tradicional
- ❌ **Nunca assumir que sábado é fraco** — sábado de fechamento é o maior dia do mês
- ❌ **Não usar o ritmo da 3ª semana** para projetar a última — a última semana acelera ~40-60% vs semanas anteriores

---

### 📅 Comportamento da última semana (padrão)

| Dia | Comportamento típico |
|---|---|
| Segunda | Baixo (R$4M–R$8M) |
| Terça | Médio (R$13M–R$14M) |
| Quarta | Médio-alto (R$17M–R$24M) |
| Quinta | Alto (R$21M–R$27M) |
| Penúltimo dia útil | Muito alto (R$10M–R$38M) |
| Último dia útil | Explosivo (R$60M–R$89M) |




<!-- AUTO-APPEND PROP-2D5EAF8D aprovado por Thiago -->


## Filtro correto para excluir supervisores da base de RCAs

> Confirmado por Thiago (admin) em 06/07/2026.

### Problema
Ao contar RCAs de campo, supervisores eram incluídos no denominador porque
estão cadastrados em `PCUSUARI` como qualquer outro usuário. Isso inflava
o total de RCAs ativos e distorcia métricas de checkin, cobertura e efetividade.

### Query correta — excluir supervisores de PCUSUARI

```sql
SELECT * FROM EBD.PCUSUARI
WHERE CODUSUR NOT IN (
    SELECT CODUSUR FROM EBD.PCUSUARI
    WHERE PCUSUARI.CODUSUR IN (
        SELECT COD_CADRCA FROM EBD.PCSUPERV
    )
)
```

### Explicação

| Tabela | Campo | Papel |
|---|---|---|
| `PCUSUARI` | `CODUSUR` | Todos os usuários (RCAs + supervisores + outros) |
| `PCSUPERV` | `COD_CADRCA` | Código do usuário que É supervisor (vínculo supervisor→PCUSUARI) |

O campo `PCSUPERV.COD_CADRCA` aponta para o `CODUSUR` do supervisor em `PCUSUARI`.
Excluindo esses CODUSURs, ficamos apenas com RCAs de campo puros.

### Anti-padrão evitado

❌ Filtrar por `TIPOVEND` ('E','I','R') não é suficiente — supervisores também
têm esses tipos e continuam aparecendo no resultado.

❌ Filtrar por `CODSUPERVISOR IS NULL` em `PCUSUARI` não funciona — campo
se refere ao supervisor DO RCA, não se o usuário é um supervisor.

### Aplicação obrigatória

Usar este filtro em **toda métrica que conta "RCAs de campo"**:
- Checkin / cobertura de rota
- Efetividade de mix
- Positivação por RCA
- Qualquer denominador que represente "força de vendas ativa"

### Impacto medido (06/07/2026)

| | Sem filtro | Com filtro correto |
|---|---:|---:|
| Total RCAs BR | 1.465 | 1.362 |
| Supervisores removidos | — | ~103 |



<!-- AUTO-APPEND PROP-B306AB16 aprovado por Thiago -->


## Cicatriz: Filtro canônico de RCA ativo em PCUSUARI (corrigido 06/07/2026)

### Problema
Queries de força de vendas (checkin, cobertura, efetividade, positivação) estavam contando:
1. **Supervisores** como RCAs de campo — identificados via `PCSUPERV.COD_CADRCA`
2. **RCAs desligados** — com `DTTERMINO` preenchido e no passado

Impacto: base inflada de 1.362 → real de **1.205 RCAs ativos** (-157 desligados, -103 supervisores removidos em etapa anterior).

### Investigação de campos de atividade em PCUSUARI

| Campo | Comportamento | Serve como filtro? |
|---|---|---|
| `DTEXCLUSAO` | 100% NULL para RCAs | ❌ Não |
| `DTTERMINO` | NULL = ativo, data passada = desligado | ✅ Sim |

### Filtro canônico FINAL de RCA ativo

```sql
WHERE CODUSUR NOT IN (
    SELECT COD_CADRCA FROM EBD.PCSUPERV WHERE COD_CADRCA IS NOT NULL
)
AND (DTTERMINO IS NULL OR DTTERMINO >= TRUNC(SYSDATE))
```

### Por que `NOT IN` precisa do `WHERE COD_CADRCA IS NOT NULL`

Oracle: `NOT IN` com qualquer NULL no subselect retorna **zero linhas** (comportamento silencioso).
Sempre filtrar NULLs no subselect de `NOT IN`.

### Distribuição confirmada (06/07/2026)

| Grupo | Qtd |
|---|---:|
| `DTTERMINO IS NULL` (ativos sem prazo) | 1.203 |
| `DTTERMINO >= SYSDATE` (contrato vigente) | — |
| `DTTERMINO < SYSDATE` (desligados) | 2.095 |
| `DTEXCLUSAO` preenchido | 0 |

### Números de referência validados (06/07/2026)

| Métrica | Valor |
|---|---:|
| RCAs ativos BR (filtro correto) | 1.205 |
| Com checkin hoje (9h segunda) | 483 (40,1%) |
| Sem checkin | 722 (59,9%) |

### Aplicação obrigatória

Em **todas** as queries de força de vendas que usam `PCUSUARI` como base de RCAs:
- Checkin / cobertura de rota
- Positivação por RCA
- Efetividade de mix
- Aproveitamento de rota
- Ranking de vendedores

### Anti-padrões a evitar

```sql
-- ❌ ERRADO: DTEXCLUSAO é sempre NULL, não filtra nada
WHERE DTEXCLUSAO IS NULL

-- ❌ ERRADO: NOT IN com NULL no subselect retorna zero linhas silenciosamente
WHERE CODUSUR NOT IN (SELECT COD_CADRCA FROM EBD.PCSUPERV)

-- ❌ ERRADO: filtra desligados mas não exclui supervisores
WHERE DTTERMINO IS NULL

-- ✅ CORRETO: exclui supervisores (sem NULL no subselect) + exclui desligados
WHERE CODUSUR NOT IN (
    SELECT COD_CADRCA FROM EBD.PCSUPERV WHERE COD_CADRCA IS NOT NULL
)
AND (DTTERMINO IS NULL OR DTTERMINO >= TRUNC(SYSDATE))
```



<!-- AUTO-APPEND PROP-2A1C061D aprovado por Thiago -->

## Cicatriz: Contagem de vendedores deve excluir supervisores e cadastros de sistema

> Confirmado por usuário admin em 14/07/2026.
> Erro detectado: resumo retornou 12 "vendedores sem pedido" em Itapevi, detalhe retornou apenas 6 — divergência causada por inclusão de cadastros não-vendedores no resumo.

### Problema
Ao contar ou listar vendedores (com/sem pedido, em campo, em rota etc.), cadastros de sistema e supervisores eram incluídos no numerador/denominador, gerando números inconsistentes entre resumo e detalhe.

### Filtro canônico OBRIGATÓRIO para "vendedores de campo"

```sql
-- Exclui supervisores (via PCSUPERV.COD_CADRCA)
AND u.CODUSUR NOT IN (
    SELECT COD_CADRCA FROM EBD.PCSUPERV WHERE COD_CADRCA IS NOT NULL
)
-- Exclui desligados
AND (u.DTTERMINO IS NULL OR u.DTTERMINO >= TRUNC(SYSDATE))
-- Exclui cadastros operacionais/sistema (e-commerce, GM-RM, fantasmas)
AND UPPER(NVL(u.NOME, '')) NOT LIKE '%ECOMMERCE%'
AND UPPER(NVL(u.NOME, '')) NOT LIKE '%GM-RM%'
AND UPPER(NVL(u.NOME, '')) NOT LIKE 'ORFAO%'
AND UPPER(NVL(u.NOME, '')) NOT LIKE 'RCA VAGO%'
AND UPPER(NVL(u.NOME, '')) NOT LIKE '%B2B%'
AND UPPER(NVL(u.NOME, '')) NOT LIKE '%GERENTE%'
```

### Regra de consistência obrigatória

> O **mesmo filtro** aplicado no resumo ("X vendedores sem pedido") DEVE ser aplicado no detalhe ("quais são esses X vendedores"). Resumo e detalhe **sempre** devem bater.

### Anti-padrões a evitar

- ❌ Usar `COUNT(DISTINCT CODUSUR)` sem filtrar supervisores e cadastros de sistema
- ❌ Aplicar filtro rigoroso só no detalhe e filtro frouxo no resumo
- ❌ Contar cadastros com nome `ECOMMERCE B2B LOJAEBD XX`, `GM-RM`, `ORFAO*`, `RCA VAGO*` como vendedores de campo

### Aplicação obrigatória

Em **todas** as perguntas do tipo:
- "Quantos vendedores saíram em campo hoje?"
- "Quantos vendedores sem pedido?"
- "Lista os vendedores que não visitaram clientes"
- "Ranking de vendedores por visitas/pedidos/faturamento"
- Qualquer contagem ou listagem de força de vendas



<!-- AUTO-APPEND PROP-F1EF0E45 aprovado por Thiago -->


## Cicatriz: Produtividade em Rota — pedidos NA rota vs FORA da rota (15/07/2026)

### Problema detectado
Ao exibir produtividade de RCAs em rota (15/07/2026, EBD MATRIZ filial 01), o valor
total mostrado para ANTONIO KELVEN SOARES DA SILVA (1343) foi **R$ 1.208,30** — número
incorreto. O valor real dos pedidos do dia era **R$ 14.152,77**.

**Causa raiz:** o cruzamento considerou apenas pedidos cujos clientes estavam na rota
planejada do dia (`GD_FATO_ROTACLIENTE + DIASEMANA`), ignorando pedidos digitados para
clientes **fora da rota planejada**. O valor residual (R$ 1.208,30) era apenas a fatia
de pedidos "dentro da rota", não o total real de produção do vendedor.

### Regra de negócio corrigida

> Em qualquer análise de produtividade de campo (rota, roteiro, visita, venda na rua),
> o valor total de pedidos do RCA no dia é a **soma de TODOS os pedidos digitados**,
> independente de o cliente estar ou não na rota planejada daquele dia.
> A rota serve como **denominador de cobertura**, não como filtro de pedidos.

### Colunas obrigatórias em relatórios de rota

Todo relatório de produtividade em rota DEVE exibir as colunas abaixo separadas:

| Coluna | Definição |
|---|---|
| `CLIENTES_ROTA` | Clientes planejados para o dia (GD_FATO_ROTACLIENTE + DIASEMANA) |
| `POSITIVADOS_ROTA` | Clientes da rota que tiveram pedido hoje |
| `PEDIDOS_ROTA` | Pedidos cujo cliente está na rota do dia |
| `VALOR_ROTA` | Valor dos pedidos dentro da rota |
| `PEDIDOS_FORA_ROTA` | Pedidos cujo cliente NÃO está na rota do dia |
| `VALOR_FORA_ROTA` | Valor dos pedidos fora da rota |
| `TOTAL_PEDIDOS` | `PEDIDOS_ROTA + PEDIDOS_FORA_ROTA` |
| `VALOR_TOTAL` | `VALOR_ROTA + VALOR_FORA_ROTA` ← **este é o número correto de produção** |
| `PCT_POSITIVACAO` | `POSITIVADOS_ROTA / CLIENTES_ROTA` |

### Aplicação obrigatória

Sempre que a pergunta envolver qualquer um desses termos:
- "produtividade em rota", "produtividade de campo"
- "pedidos em roteiro", "vendas na rua"
- "RCAs em campo hoje", "resultado do dia do vendedor"
- "cobertura de rota", "aproveitamento de rota"

### SQL base (lógica correta)

```sql
WITH rota_dia AS (
    -- clientes planejados para o dia da semana atual
    SELECT r.CODIGORCA, r.CODIGOCLIENTE
    FROM EBD.GD_FATO_ROTACLIENTE r
    JOIN EBD.GD_DIM_RCA dr ON dr.CODIGORCA = r.CODIGORCA
    JOIN dia_ref d ON UPPER(r.DIASEMANA) IN (d.NOME, REPLACE(d.NOME,'C','Ç'))
    JOIN EBD.PCUSUARI u ON u.CODUSUR = r.CODIGORCA
    WHERE u.CODFILIAL = :codFilial
      AND UPPER(NVL(dr.RCA,'')) NOT LIKE 'ORFAO%'
      AND UPPER(NVL(dr.RCA,'')) NOT LIKE 'RCA VAGO%'
),
pedidos_dia AS (
    SELECT p.CODUSUR,
           p.CODCLI,
           p.NUMPED,
           p.VLATEND,
           CASE WHEN r.CODIGOCLIENTE IS NOT NULL THEN 1 ELSE 0 END AS NA_ROTA
    FROM EBD.PCPEDC p
    LEFT JOIN rota_dia r ON r.CODIGORCA = p.CODUSUR AND r.CODIGOCLIENTE = p.CODCLI
    WHERE p.CODFILIAL = :codFilial
      AND TRUNC(p.DATA) = TRUNC(SYSDATE)
      AND p.POSICAO != 'C'
      AND p.DTCANCEL IS NULL
      AND p.CONDVENDA NOT IN (4,5,6,8,10,11,12,13,20,98,99)
)
SELECT
    pd.CODUSUR,
    SUBSTR(NVL(u.NOME,'?'),1,40)               AS VENDEDOR,
    COUNT(DISTINCT rd.CODIGOCLIENTE)            AS CLIENTES_ROTA,
    COUNT(DISTINCT CASE WHEN pd.NA_ROTA=1 THEN pd.CODCLI END) AS POSITIVADOS_ROTA,
    SUM(CASE WHEN pd.NA_ROTA=1 THEN 1 ELSE 0 END) AS PEDIDOS_ROTA,
    SUM(CASE WHEN pd.NA_ROTA=1 THEN pd.VLATEND ELSE 0 END) AS VALOR_ROTA,
    SUM(CASE WHEN pd.NA_ROTA=0 THEN 1 ELSE 0 END) AS PEDIDOS_FORA_ROTA,
    SUM(CASE WHEN pd.NA_ROTA=0 THEN pd.VLATEND ELSE 0 END) AS VALOR_FORA_ROTA,
    COUNT(pd.NUMPED)                            AS TOTAL_PEDIDOS,
    SUM(pd.VLATEND)                             AS VALOR_TOTAL,
    ROUND(COUNT(DISTINCT CASE WHEN pd.NA_ROTA=1 THEN pd.CODCLI END)
          / NULLIF(COUNT(DISTINCT rd.CODIGOCLIENTE),0)*100,1) AS PCT_POSITIVACAO
FROM pedidos_dia pd
JOIN EBD.PCUSUARI u ON u.CODUSUR = pd.CODUSUR
LEFT JOIN rota_dia rd ON rd.CODIGORCA = pd.CODUSUR
GROUP BY pd.CODUSUR, u.NOME
ORDER BY VALOR_TOTAL DESC
```

### Anti-padrão a evitar

❌ **NUNCA** usar apenas `SUM(VLATEND) WHERE CODCLI IN (clientes da rota)` como valor total
do RCA — isso corta pedidos fora da rota e gera número errado (caso ANTONIO KELVEN: R$ 1.208
em vez de R$ 14.152).

❌ **NUNCA** apresentar `VALOR_ROTA` como se fosse a produção total do vendedor.



<!-- AUTO-APPEND PROP-5F84A956 aprovado por Thiago -->

### 2026-07-23 — RCAs desligados ainda aparecem na rota (PCROTACLI) com clientes órfãos — filtrar SEMPRE por DTTERMINO

**Contexto:** análise de performance de atendimento em EBD SBC (18) no mês de julho/2026. Ao listar vendedores com rota ativa (PCROTACLI + DTFINAL futuro), encontramos 7 vendedores com rota (368 clientes) mas ZERO vendas no mês — todos eram ex-funcionários desligados há meses/anos.

**Erro anterior:** queries de rota/produtividade (T182, T270, T271) não filtravam `u.DTTERMINO` no JOIN com PCROTACLI, inflando o número de "vendedores da filial" e gerando métricas distorcidas de cobertura/aproveitamento.

**Correção OBRIGATÓRIA em TODAS as queries de rota (PCROTACLI):**

```sql
JOIN EBD.PCUSUARI u ON u.CODUSUR = r.CODUSUR
WHERE (u.DTTERMINO IS NULL OR u.DTTERMINO >= TRUNC(SYSDATE))
  -- mais filtros de exclusão padrão (supervisor, ORFAO, VAGO, ECOMMERCE etc.)
```

**Impacto medido (EBD SBC, 23/07/2026):**
- Sem filtro DTTERMINO: 34+ "vendedores" listados
- Com filtro correto: 27 vendedores de campo ativos
- Clientes órfãos removidos: 368 (em 7 ex-funcionários)
- Caso mais crítico: CLOVIS MAURILIO BROCARDO — desligado out/2025, ainda com 129 clientes na rota

**Regra de negócio:** PCROTACLI NÃO é automaticamente limpa quando o RCA é desligado. O cadastro de rota só é atualizado manualmente pelo supervisor/gerente. Portanto, filtro de `DTTERMINO` no JOIN com PCUSUARI é obrigatório — não confiar que PCROTACLI só contenha RCAs ativos.

**Anti-padrão a evitar:**
```sql
-- ❌ ERRADO: confia que PCROTACLI só tem vendedores ativos
JOIN EBD.PCUSUARI u ON u.CODUSUR = r.CODUSUR
WHERE u.CODFILIAL = :codFilial

-- ✅ CORRETO: filtra desligados explicitamente
JOIN EBD.PCUSUARI u ON u.CODUSUR = r.CODUSUR
WHERE u.CODFILIAL = :codFilial
  AND (u.DTTERMINO IS NULL OR u.DTTERMINO >= TRUNC(SYSDATE))
```

**Aplicação:** revisar template T182 (Produtividade em Rota) e templates T270-T272 (Rota de Visitas) para incluir este filtro.


## #55 - PCCARREG NAO tem CODFILIAL nem coluna DATA

Erro cometido em 27/07/2026: assumi `CODFILIAL` e `DATA` na PCCARREG. Nao
existem. `CODFILIALSAIDA` EXISTE mas esta preenchida em 0 de 1.153.949 cargas.

  Data da carga  -> DTSAIDA (99,99% preenchida)
  Filial         -> so via JOIN: PCPEDC.NUMCAR = PCCARREG.NUMCAR
                    (ou PCNFSAID.NUMCAR), pegando PCPEDC.CODFILIAL

Outras datas da PCCARREG: DTFECHA, DTFAT, DTSAIDAVEICULO, DTRETORNO,
DATAMAPA, DATAHORAMAPA, DTINICIOCHECKOUT, DTFIMCHECKOUT.

## #56 - PCCARREG.DT_CANCEL tem UNDERSCORE e cancela metade das cargas

E `DT_CANCEL`, nao `DTCANCEL`. E nao e detalhe: 49,9% das cargas de 2026 estao
canceladas (era 35,4% em 2022). Filtro obrigatorio em TODO template de carga:

  AND DT_CANCEL IS NULL

Quase nenhuma cancelada tem nota (38 em 68 mil) — e montagem desfeita na 901,
nao cancelamento fiscal.

## #57 - KM e prazo de rota NAO EXISTEM (nao insistir)

PCCARREG.KMINICIAL / KMFINAL: preenchidas em ~34% das linhas mas com valor
ZERO em 100% dos casos, em todos os anos desde 2019.
PCROTAEXP: 227 rotas, e KMROTA, DIASENTREGA, PRAZOPREVENT e QTENTREGA com
ZERO rotas preenchidas.

Nao ha como calcular km rodado, desvio de roteiro nem prazo prometido. Esse
dado vive na MaximaTech/MyFrota, e a integracao e de mao unica
(PCMYFROTA_FILA com 560 mil registros de saida, tabelas de retorno zeradas).

## #58 - Tabelas-fotografia de 2018 (BANIR)

Existem copias congeladas com nome quase identico ao das tabelas vivas:
PCMOVENDPEND300818 (8.470 linhas, ultima 30/08/2018), PCMOVENDPEND150818,
PCMOVENDPEND040918, PCENDERECO040918/150818/300818, PCESTENDERECO*,
PCINVENTENDERECO*, PCWMS040918/300818, PCPRODUTPICKING*, PCCARREG120419.

A viva e PCMOVENDPEND (97,3 mi, ultima de hoje). Qualquer nome de tabela
terminado em 6 digitos de data e fotografia — NUNCA consultar.

## #59 - CODFUNCCONF e CODFUNCCOFERENTE sao a MESMA coisa

A PCMOVENDPEND tem as duas colunas (a segunda com o erro de digitacao do
proprio ERP) e elas sao IDENTICAS linha a linha em todas as filiais medidas.
Usar qualquer uma. Ja CODFUNCEMBALADOR esta ZERADA.

A PCCARREG usa CODFUNCCONF; a PCCORTEI tambem. So a PCMOVENDPEND tem a grafia
dupla.

## #60 - PCMOVENDPEND.HORA e carimbo da O.S., nao do movimento

Tentativa de medir produtividade por "hora ativa" produziu 370 linhas/hora e
1,2 hora ativa por dia — impossivel. O HORA e estampado por O.S.; milhares de
linhas herdam a mesma hora (36 mil linhas numa unica hora em SBC).

MEDIDO em 28/07/2026: a coluna HORA nao e nem a hora do movimento nem a do
fim da O.S. — bate com DTINICIOOS em 5,3% das linhas e com DTFIMOS em 0,1%.
Nao usar para nada. Hora real sai de DTINICIOOS / DTFIMOS (ver #68).

Produtividade individual so por LINHAS POR DIA TRABALHADO:
  COUNT(*) / COUNT(DISTINCT TRUNC(DATA))

E o tempo decorrido da O.S. (DTFIMOS - DTINICIOOS) tambem nao serve: a O.S.
fica aberta (mediana de 1.110 minutos em Teresina).

## #61 - Motivo de corte: PCTABDEV com TIPO = 'CO'

Os codigos de corte (62, 64, 65, 116, 118) sao da PCTABDEV, e sao exatamente
o subconjunto TIPO = 'CO'. PCMOTIVONAOATEND esta VAZIA e PCMOTIVOAVARIA so tem
9 codigos (1 a 9) — nao servem.

ARMADILHA DE TIPO: PCCORTEI.MOTIVO e VARCHAR2 e mistura codigo numerico com
texto livre digitado. PCTABDEV.CODDEVOL e NUMBER. Fazer o join pelo lado texto
para nao tomar ORA-01722:

  LEFT JOIN EBD.PCTABDEV d ON TO_CHAR(d.CODDEVOL) = TRIM(c.MOTIVO)

PCWMSCORTE.CODMOTIVO ja e NUMBER e junta direto.

## #62 - PCMOVENDPEND exige CODFILIAL + DATA

97,3 milhoes de linhas. Agrupar por TIPOOS sem filtrar filial levou 204s
(acima do timeout de 85s). Os indices uteis sao (CODFILIAL, POSICAO, DATA) e
(DATA, CODFILIAL). SEMPRE filtrar os dois.

## #63 - "O.S." e ambiguo no Winthor

PCMOVENDPEND.NUMOS = ordem de servico de ARMAZEM.
PCORDEMSERVICO + PCOSVEICULO/PCOSVEICULOMARCA/PCOSVEICULOMODELO = MANUTENCAO
DE FROTA (placa, modelo, KM, combustivel), view VW_OSVEICULO.

Sao coisas diferentes. Tambem existem duas tabelas de tipo: PCTIPOOS (armazem)
e PCTIPOORDEMSERVICO (frota).

## #64 - PCCORTEI tem o valor, PCWMSCORTE tem o responsavel

Sao o MESMO evento em duas tabelas (totais batem quase linha a linha:
Petropolis 8.033 x 8.040, Pirai 5.184 x 5.196, SBC 366 x 367).

  PCCORTEI    -> PVENDA (valor do corte), MOTIVO (texto), CODCLI, CODUSUR
  PCWMSCORTE  -> CODFUNCCORTE (100%), CODFUNCOS (71-100%), CODENDERECO,
                 NUMOS, TIPOOS, CODMOTIVO (numerico)

Na PCCORTEI as colunas CODFUNCSEP, CODFUNCCONF, QTORIG e QTFALTA estao
PRATICAMENTE zeradas: 17 linhas preenchidas em ~31.600 cortes de 90 dias
(0,05%). Nao servem para atribuicao — usar SO a PCWMSCORTE.

## #65 - Preenchimento se mede na janela recente

DTSAIDAVEICULO parece morta olhando a tabela inteira (16,9%) e esta viva nos
ultimos 3 meses (70,6%). Historico antigo dilui e faz campo vivo parecer morto.
Ao avaliar se uma coluna serve, filtrar os ultimos 90 dias.


## #66 - EXTRACT(HOUR FROM coluna DATE) da ORA-30076

Oracle so extrai HOUR/MINUTE/SECOND de TIMESTAMP ou INTERVAL. De uma coluna
DATE (que e o tipo de praticamente toda data do Winthor) so sai YEAR, MONTH e
DAY. Isso quebrou uma pergunta real de turno noturno em 27/07/2026.

  ERRADO:  EXTRACT(HOUR FROM m.DATA)
  ERRADO:  EXTRACT(HOUR FROM c.DTSAIDA)

  CERTO:   TO_NUMBER(TO_CHAR(m.DTINICIOOS, 'HH24'))    -- hora como numero
  CERTO:   TO_CHAR(m.DTINICIOOS, 'HH24')               -- hora como texto '23'
  CERTO:   TO_CHAR(m.DTINICIOOS, 'DD/MM HH24:MI')      -- data e hora
  CERTO:   EXTRACT(HOUR FROM CAST(m.DTINICIOOS AS TIMESTAMP))

ATENCAO ao escolher a coluna: TO_CHAR sobre coluna TRUNCADA nao da erro, so
devolve '00' em tudo. PCMOVENDPEND.DATA e truncada — ver #68.

EXTRACT(YEAR FROM ...) e EXTRACT(MONTH FROM ...) funcionam em DATE — o erro so
aparece com campo de tempo.

CUIDADO ADICIONAL na PCMOVENDPEND: existe a coluna HORA, mas ela e carimbo da
O.S., nao do movimento (cicatriz #60). Para saber a hora REAL de um movimento,
usar TO_CHAR sobre DTINICIOOS ou DTFIMOS, nunca a coluna HORA.

## #67 - Turno que vira o dia: nao usar TRUNC(DATA) sozinho

A operacao de armazem da EBD e NOTURNA e ATRAVESSA A MEIA-NOITE. Medido na
filial 18, 14 dias, pela hora de DTINICIOOS: turno das 21h as 07h, PICO A
MEIA-NOITE (18% dos inicios de O.S.), 57% do trabalho DEPOIS da meia-noite
contra 38% entre 18h e 23h.

Logo, "domingo para segunda" ou "turno da noite" NAO pode agrupar por dia
calendario: a maior metade da jornada cai no dia seguinte.

Para tratar a jornada que atravessa a meia-noite, deslocar a hora do CARIMBO
DE TRABALHO (nunca a DATA, que e truncada):

  TRUNC(m.DTINICIOOS - 12/24)   AS JORNADA

Assim tudo que acontece das 12h de um dia as 11h59 do seguinte conta como a
mesma jornada operacional — o turno 21h-07h cabe inteiro. Usar so quando a
pergunta for de turno; para faturamento e venda, TRUNC(DATA) normal.


## #68 - Nem toda coluna de data do Winthor tem hora

Medido em 28/07/2026 (14 dias, filial 18). CONFERIR antes de extrair hora:

  SEM HORA (truncada na meia-noite):
    PCMOVENDPEND.DATA
    PCCARREG.DTSAIDA
    PCPEDC.DATA

  COM HORA:
    PCMOVENDPEND.DTINICIOOS / DTFIMOS / DTFIMSEPARACAO / DTINICIOCONFERENCIA
    PCCARREG.DTSAIDAVEICULO
    PCCORTEI.DATA
    PCWMSCORTE.DATA

Nao da para adivinhar pelo nome nem pelo tipo: DATA e truncada na
PCMOVENDPEND e tem hora na PCCORTEI.

TO_CHAR sobre coluna truncada NAO DA ERRO — devolve '00' em todas as linhas.
A query roda, agrupa e apresenta resultado errado com cara de certo. Foi assim
que o T-LOG11 nasceu quebrado e passou no teste de execucao.

Teste antes de usar qualquer coluna para analise de hora:

  SELECT COUNT(DISTINCT TO_CHAR(<coluna>,'HH24')) FROM <tabela> WHERE ...

Se voltar 1, a coluna e truncada e nao serve.


## #69 - Movimento por endereco NAO e movimento por dia

Erro real cometido pelo agente em 28/07/2026: dividiu 29.305 movimentos por
136 enderecos, chegou a 215 e apresentou como "215 movimentos/dia por
endereco". Faltou dividir pelos 60 dias da janela. O valor certo era 3,6/dia.

O numero errado inflou a conclusao em ~60x e teria ido para reuniao de
diretoria como "operacao hiperconcentrada".

REGRA: toda densidade de armazem precisa de TRES denominadores explicitos:

  movimentos                       -> total bruto do periodo
  / enderecos                      -> intensidade por posicao NO PERIODO
  / dias                           -> intensidade por posicao POR DIA

E o rotulo tem que dizer qual dos tres e. "por endereco" e "por endereco por
dia" diferem pelo tamanho da janela inteira.

CUIDADO COM O DENOMINADOR DE ENDERECO: usar os enderecos CADASTRADOS e ATIVOS
(BLOQUEIO <> 'S'), nao os enderecos tocados no periodo. Contar so os tocados
esconde exatamente o problema que se quer achar — posicao ociosa. Em SBC ha
16.238 enderecos desativados; incluir ou excluir muda tudo.

## #70 - "Deposito" tem DOIS significados no Winthor

Nunca usar a palavra sem qualificar. Sao coisas diferentes:

  DEPOSITO-FILIAL   -> CODFILIAL 17 (Sao Pedro da Aldeia), 19 (Sao Luis),
                       23 (Petropolis). Sao CDs que aparecem em acl_filiais,
                       tem filial-mae, entram no mapa regional e tem ruptura
                       propria. E o sentido de "os depositos entram na
                       analise de logistica".

  PCENDERECO.DEPOSITO -> ZONA FISICA DENTRO de um CD, nivel mais alto da
                       hierarquia de enderecamento:
                       DEPOSITO / RUA / PREDIO / NIVEL / APTO
                       Em SBC sao 11 zonas; em Sao Luis, 20.

Exemplo concreto (EBD SBC): o deposito interno 1 e area seca e o 4 e camara
fria — o Ferrero fica na camara fria. Isso nao tem nenhuma relacao com as
filiais 17/19/23.

Ao responder, dizer "deposito interno N" ou "zona N do CD" para o sentido de
endereco, e "filial-deposito NN" para o outro.

NAO EXISTE TABELA no Winthor que nomeie o deposito interno. O numero e tudo o
que o banco tem. Se o nome nao estiver na tabela do KB (secao 17), citar pelo
NUMERO. NUNCA inferir o nome a partir do que o usuario mencionou na conversa —
foi assim que o agente chamou o deposito 1 de "area seca" e o 4 de "camara
fria" antes de ter qualquer confirmacao, acertando por sorte.


## #71 - Deposito virtual: ler do parametro, NUNCA cravar 99

O Winthor mantem um deposito ARTIFICIAL por filial, que recebe a quantidade
fracionada na entrada. Ele tem movimento real mas os enderecos nao sao
posicoes fisicas — entram inflando ocupacao e densidade do CD.

Qual e o numero: sai de PCPARAMETROWMS, NOME = 'DEPOSITOVIRTUAL'.

  Medido em 28/07/2026: e 99 em 20 filiais e **30 na filial 21 (Teresina)**.

Por isso NAO cravar 99 no SQL. Sempre:

  NOT EXISTS (SELECT 1 FROM EBD.PCPARAMETROWMS pw
               WHERE pw.CODFILIAL = e.CODFILIAL
                 AND pw.NOME = 'DEPOSITOVIRTUAL'
                 AND TRIM(pw.VALOR) = TO_CHAR(e.DEPOSITO))

REGRA DE APRESENTACAO: marcar, nao esconder. Se o agente sumir com o virtual
sem avisar, o total dele nao fecha com o da logistica e ninguem entende a
diferenca. Somar so o fisico para ocupacao e citar o virtual em separado.

HIPOTESE DESCARTADA: os depositos 40, 50 e 51 NAO sao virtuais — eu supus e o
parametro desmentiu. Sao zonas fisicas reais com pouco movimento. Deposito com
muitos enderecos e pouco giro e ociosidade a investigar, nao artefato de
sistema.

Outros parametros da mesma familia: DEPOSITOAUTOSERVICO (nulo em todas as
filiais da EBD) e QUEBRAOSARMAZPORDEPOSITO (= 'N' em todas).


## #72 - PCVOLUMEOS: so serve pra CONTAR volume, e nao tem indice em DATA

39,1 milhoes de linhas, viva (115 mil volumes em 7 dias, 12 mil O.S.). Mas a
rastreabilidade que o nome promete NAO EXISTE. Medido em 27/07/2026, 7 dias:

  PREENCHIDAS:  NUMVOL 100%, CODFUNC 60%, CODENDERECO 63%,
                DATAUTILIZACAO 36%
  ZERADAS:      NUMPALETE, CODFUNCMONTAPALETE, DATAPALETE, DTESTORNO,
                DTCORTE, CODFUNCCORTE, DATAAGRUPAMENTO, CODFUNCAGRUPAMENTO
  CONSTANTES:   EMBARCADO = 'N' em 100%, VOLUMECORTADO = 'N' em 100%,
                LETRA nula em 100%

EMBARCADO e VOLUMECORTADO NAO sao flags — sao constantes. Nao da pra saber por
esta tabela se um volume embarcou ou foi cortado. Corte continua sendo
PCCORTEI (valor) + PCWMSCORTE (responsavel).

PERFORMANCE: o unico indice e (NUMOS, NUMVOL, DTESTORNO, DATAAGRUPAMENTO).
NAO ha indice em DATA. Filtrar so por data varre a tabela inteira.

  ERRADO:  FROM EBD.PCVOLUMEOS WHERE DATA >= TRUNC(SYSDATE) - 30
  CERTO:   JOIN EBD.PCMOVENDPEND m ON m.NUMOS = v.NUMOS
           WHERE m.CODFILIAL = :codFilial AND m.DATA >= ...

O QUE DA PRA FAZER: contar volumes por O.S., por carga e por filial — que e
carga de trabalho de conferencia e embarque. Medido: Taquara 79,3 volumes por
O.S. contra 27,5 em SBC. Mediana geral 2, media 9,5, maximo 1.000.


## #73 - Baixa do romaneio e DTFECHA, nao DTRETORNO

Erro que eu cometi em 27/07/2026: medi 11 das 146 colunas da PCCARREG, vi
DTRETORNO com 3 registros e conclui que o retorno da carga nao era registrado.
Era, no DTFECHA — 93,8% das cargas validas.

  DTSAIDA         montagem da carga      100%
  DTSAIDAVEICULO  saida fisica           70,6%   (+0,3 dia)
  DTFECHA         BAIXA DO ROMANEIO      93,8%   (+3 dias)
  DTCAIXA         acerto de caixa        90,7%
  CODFUNCFECHA    quem deu baixa         93,8%
  DTRETORNO       rotina 907             3 linhas — NAO USAR

ARMADILHA: DTFECHA e TRUNCADO (so data). A hora esta em HORAFECHA e
MINUTOFECHA, colunas NUMBER separadas. Ciclo em dias funciona direto; em horas,
montar com as tres.

LICAO DE METODO: antes de declarar que um dado NAO existe, listar TODAS as
colunas candidatas do dicionario em vez de conferir as que vieram a cabeca:

  SELECT COLUMN_NAME FROM ALL_TAB_COLUMNS
  WHERE OWNER='EBD' AND TABLE_NAME=:t AND DATA_TYPE='DATE'


## #74 - MARCA nao e FORNECEDOR: procure nas duas tabelas

Caso real (28/07/2026): pediram analise da "Havaianas em SBC". O agente buscou
UPPER(FORNECEDOR) LIKE '%HAVAI%' na PCFORNEC, voltou ZERO linhas, e passou 7
minutos e 18 consultas analisando um conjunto vazio.

  Havaianas e MARCA:      PCMARCA.CODMARCA = 1272, MARCA = 'HAVAIANAS'
  O fornecedor e:         ALPARGATAS S.A. (CODFORNEC 25277, 25324, 25498;
                          raiz CODFORNECPRINC = 25277)
  Produtos:               1.771, TODOS com PCPRODUT.CODMARCA = 1272

A descricao do produto NAO contem 'HAVAIANAS' — a unica entrada por nome de
marca e a PCMARCA (573 marcas cadastradas). A PCFORNEC tambem tem a coluna
FANTASIA, alem de FORNECEDOR.

REGRA: nome de industria dado pelo usuario pode ser marca, razao social ou
fantasia. Procure nos QUATRO campos antes de concluir que nao existe:
PCFORNEC.FORNECEDOR, PCFORNEC.FANTASIA, PCMARCA.MARCA, PCPRODUT.DESCRICAO.
Ver T-RES01.

## #75 - ZERO LINHAS em consulta de cadastro NAO e resposta

'oracle_query_ok' significa "nao deu erro", nao "achou". Numa consulta de
CADASTRO (PCFORNEC, PCMARCA, PCCLIENT, PCPRODUT...), zero linha quase sempre
quer dizer que o termo esta na tabela errada.

Seguir a analise sobre conjunto vazio produz o pior tipo de erro: numeros
zerados com procedencia legitima. Nao e fabulacao — e conclusao falsa que
passa em qualquer verificacao de origem.

Em tabela de MOVIMENTO zero linha e resposta legitima ("nao houve venda no
periodo"). A distincao e essa.

O MCP passou a anexar aviso automatico quando isso acontece (funcao
aviso_zero_linhas em app/preflight.py). Se o aviso aparecer, PARE e resolva a
entidade antes de continuar.

## #76 - Resolva CODFORNEC UMA VEZ; NVL() no WHERE mata o indice

O mesmo caso: o agente recalculou esta CTE em TODA metrica, 18 vezes seguidas,
com 3 timeouts.

  LENTO (4,23s):  WITH prods AS (SELECT p.CODPROD FROM PCPRODUT p
                    JOIN PCFORNEC f ON f.CODFORNEC = p.CODFORNEC
                    WHERE NVL(f.CODFORNECPRINC, f.CODFORNEC) = :x)

  RAPIDO (0,64s): resolver a lista de CODFORNEC UMA VEZ e depois
                  WHERE p.CODFORNEC IN (25277, 25324, 25498)

Existe indice em PCPRODUT.CODFORNEC (PCPRODUT_IDX3 e PCPRODUT_IDX_DBAONL1). O
`NVL()` no WHERE impede o uso dele. Em 6 metricas seguidas: 7,22s contra 1,94s.

Referencia medida: os 1.771 produtos da Alpargatas em SBC, 30 dias, saem em
0,57s — 302 notas, 232 clientes, 371 SKUs, R$ 379.079,47.

## #77 - ALL_VIEWS usa VIEW_NAME, nao TABLE_NAME

  ERRADO: SELECT table_name FROM all_views WHERE owner='EBD'  -> ORA-00904
  CERTO:  SELECT view_name  FROM all_views WHERE owner='EBD'

ALL_TABLES e ALL_TAB_COLUMNS usam TABLE_NAME; ALL_VIEWS usa VIEW_NAME. O
pre-voo NAO pega isso: ele so valida tabelas do schema EBD, nao o dicionario.


## #78 - PCGMMETACOMB: somar VLFATURADO sem filtro conta 2x ou 4x

Cada meta tem linhas por INDICADOR (16 faturamento, 5 positivacao) e por
TIPOMETA (3 = por industria, 4 = META GERAL). O VLFATURADO se repete em todas.

Medido na meta 118452:
  soma de tudo                       = 503.463,20   (4x)
  so indicador 16                    = 251.731,60   (2x)
  indicador 16 + CODTIPOMETA = 3     = 125.865,80   CERTO
  VIEW_VENDAS_RESUMO_FATURAMENTO     = 126.189,58   (dif. 0,26%)

A linha META GERAL (CODTIPOMETA=4) repete o total das industrias e NAO PAGA
comissao — peso nulo, PESO_X_NIVEL = 0. Serve so para acompanhamento.

  PARA FATURAMENTO: WHERE mc.CODINDICADOR = 16 AND mc.CODTIPOMETA = 3

⚠️ **ESTE FILTRO NAO VALE PARA COMISSAO.** O premio tem componente dos DOIS
indicadores (16 faturamento e 5 positivacao). Filtrar CODINDICADOR = 16 ao
somar VLCOMISSAO APAGA a parcela de positivacao.

  PARA COMISSAO:    SUM(mc.VLCOMISSAO) sem filtro de indicador
                    (mantendo DTPREMIACAO IS NOT NULL e o mes fechado)

Medido em junho/2026: a positivacao vale ~15% do premio. Duque (05) R$ 546.371
corretos contra R$ 466.195 somando so o indicador 16 — R$ 80.175 apagados.
Fortaleza perde 19,3%, SBC 18,5%, Sao Luis 18,2%. Teresina e Santarem perdem 0%
porque ninguem bateu 85% de positivacao — abaixo disso a faixa paga zero.

Este erro JA ACONTECEU: em 28/07/2026 o agente gerou um PDF de comissionamento
de Duque com todos os valores 15% menores, seguindo esta cicatriz ao pe da
letra quando ela dizia so "SEMPRE".

## #79 - Nao existe apuracao de premio no MES CORRENTE

A comissao so e apurada DEPOIS do fechamento do mes. No mes corrente a consulta
RETORNA NUMERO, e o numero e lixo — sao fechamentos prematuros de algumas
metas, nao o resultado do mes.

Medido em 28/07/2026: julho tinha 1.888 metas e 13 fechadas; junho tinha 1.516
metas, 1.401 fechadas e 1.125 premios fechados.

Toda pergunta sobre premio ou comissao deve usar o ULTIMO MES FECHADO:

  WHERE mc.DTPREMIACAO IS NOT NULL
    AND mc.DATA < TRUNC(SYSDATE,'MM')

Se o usuario pedir o mes corrente, RESPONDA que ainda nao ha apuracao e ofereca
o mes anterior. NAO devolva o numero parcial.

## #80 - PERCOMPORIND esta NULO: a comissao sai da PCGMMETACOMBCOMPLE

Em dados de 2019 o PERCOMPORIND vinha preenchido e VLCOMISSAO = VLFATURADO x
PERCOMPORIND/100. Nos dados atuais ele e NULO — a formula nao vem mais dali.

  comissao_bruta = SOMA(VLFATPORPERCOM x PERCOMMOV/100)  [PCGMMETACOMBCOMPLE]
  VLCOMISSAO     = comissao_bruta x PERCPESOINDNIVELATING / 100

Validado ao centavo na meta 118452 (diferenca 0,0000 nas 3 industrias).

A comissao varia por PRODUTO dentro da mesma industria (Alpargatas tem 3%, 4%
e 5% na mesma meta). NAO existe "percentual da industria".

## #81 - CODFORNECPRINC esta na PCFORNEC, NAO na PCPRODUT

  ERRADO: SELECT ... FROM EBD.PCPRODUT pr WHERE pr.CODFORNECPRINC ...
  CERTO:  JOIN EBD.PCFORNEC f ON f.CODFORNEC = pr.CODFORNEC
          ... NVL(f.CODFORNECPRINC, f.CODFORNEC)

A PCPRODUT tem CODFORNEC (com indice PCPRODUT_IDX3); a raiz do grupo economico
esta na PCFORNEC.


## #82 - Existem DUAS bases de faturamento no GM, e elas diferem 3 a 6%

O `Realizado` do indicador 16 (base da META) NAO e igual ao `Valor Faturado`
que forma a comissao (base do PREMIO). Causa: PCGMPARAMETRO tem
`ABATER_VALOR_ST_META = N` e `ABATER_VALOR_ST_COMISSAO = S` — o ICMS-ST fica na
meta e sai da comissao.

Medido em Duque, junho/2026, na tela do GM:

  RCA        realizado da meta   base da comissao   dif
  Rosana        2.663.616,37       2.569.535,98    -3,53%
  Jorge           250.793,95         241.757,67    -3,60%
  Gabriela        100.160,27          97.306,49    -2,85%
  Renata          648.732,38         612.549,68    -5,58%

REGRA:
  "atingimento da meta"  -> PCGMMETACOMB.REALIZADO (indicador 16, tipo 3)
  "base do premio"       -> SOMA(PCGMMETACOMBCOMPLE.VLFATPORPERCOM) por meta

NUNCA chamar o realizado da meta de "faturamento base premio": o percentual de
comissao sobre faturamento sai diluido. E a COMBCOMPLE tambem carrega linhas
NEGATIVAS (devolucao) com PERCOMMOV = 0.

## #83 - Subconsulta em PCGMMETACOMBCOMPLE precisa filtrar A META, nao a filial

Erro real (28/07/2026): ao conferir uma RCA, o `IN (SELECT ... WHERE CODFILIAL
= '05')` trouxe TODAS as metas da filial. Resultado: R$ 20,5 milhoes de
faturado onde a pessoa tinha R$ 2,57 mi.

A PCGMMETACOMBCOMPLE nao tem filial nem RCA — so CODMETA e CODCOMBINACAO.
Sempre amarrar pelo CODMETA especifico.


## #84 - Preco e por REGIAO: o de-para e NUMREGIAOPADRAO, nao NUMREGIAO

`PCTABPR` tem chave CODPROD + NUMREGIAO e NAO tem CODFILIAL.

  ERRADO: PCFILIAL.NUMREGIAO        -> NULO em todas as 21 filiais
  CERTO:  PCFILIAL.NUMREGIAOPADRAO

Erro real (28/07/2026): usei NUMREGIAO num subselect, veio nulo, e quatro
blocos de analise voltaram vazios sem erro de SQL.

E ANTES disso eu cruzei PCTABPR (88 regioes) com custo da filial 18 sem
de-para nenhum — o resultado parecia plausivel e estava inflado.

## #85 - PCTABPR.INDICEPRECO e coluna MORTA (1,0 em 100%)

Vale exatamente 1,0 nas 1.919.086 linhas. NAO e o indice da formula da rotina
201, que e calculado na hora e nao fica gravado.

  ERRADO: PVENDA = CUSTOPRECIFIC / INDICEPRECO   -> bate em 812 de 204.960

O indice IMPLICITO (`CUSTOPRECIFIC / PVENDA`) e o que tem significado: varia de
0,37 a 0,88, com margem estavel em 20-23% e encargos de 21% a 63%.

## #86 - O preco da EBD e formado sobre o CUSTO FINANCEIRO

MEDIDO em SBC, regiao 81, 6.893 comparacoes: o CUSTOPRECIFIC bate com

  CUSTOFIN           5.367   77,9%   <- este
  CUSTOREAL          5.113   74,2%   (coincide quando nao ha custo financeiro)
  CUSTOULTENT        2.944   42,7%
  CUSTOREP (PCEST)   1.413   20,5%

E o parametro 1907 da rotina 132 na pratica. O artigo da TOTVS confirma que o
valor da ULTIMA ENTRADA nao entra na sugestao de preco.

## #87 - Ha 4x mais regiao de preco do que filial, e as orfas distorcem

Um produto de giro tem preco em 53 regioes; so 12 pertencem a alguma filial. As
outras 41 nao tem filial vinculada.

E o efeito e concreto: no NISSIN LAMEN GALINHA, as UNICAS 3 regioes com preco
abaixo do custo de reposicao (12, 13 e 45) sao todas ORFAS. Olhando so a
amostra, eu conclui "abaixo do custo em todas as regioes" — era falso.

  SEMPRE, ao falar de preco de uma FILIAL:
    JOIN EBD.PCFILIAL f ON t.NUMREGIAO = f.NUMREGIAOPADRAO

  E ao varrer todas as regioes, dizer QUANTAS tem filial.

Existe tambem a filial 70 (regiao 33, junto com Sao Luis) fora do mapa das 21
filiais operacionais — conferir antes de somar.

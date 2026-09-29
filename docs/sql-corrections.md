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

## #38 — NAO usar GD_FATO / GD_DIM (views desativadas)

⚠️ Esta cicatriz dizia o CONTRARIO ate 10/09/2026: mandava buscar as views do
DW antes de derivar de PC*. As views `GD_*` sao **legado GoodData e estao
desativadas** — a instrucao ficou meses em conflito com a secao 10 do
knowledge.md, no mesmo prompt.

| Em vez de | Use |
|---|---|
| `GD_FATO_VENDAFATURAMENTO` | `VIEW_VENDAS_RESUMO_FATURAMENTO` |
| `GD_FATO_ROTACLIENTE` | `PCROTACLI` + `PCMOVROTACLI` (respeita periodicidade) |
| `GD_DIM_CLIENTE` | `PCCLIENT` |
| `GD_DIM_RCA` | `PCUSUARI` |
| `GD_DIM_FILIAL` | `PCFILIAL` |

A licao que sobrevive: antes de derivar metrica de tabela PC* com filtros
chutados, procurar se ja existe view oficial pronta. So que a oficial hoje e
a familia `VIEW_*`, nao a `GD_*`.

---

## #40 - ROTA DE VISITAS: qual tabela, qual dia, e os 3 sentidos de "carteira"

### A tabela certa

`PCROTACLI` e a rota vigente (snapshot atual, alimentada pela rotina 354 e
atualizada pela 820 na madrugada). `PCMOVROTACLI` tem o historico com
periodicidade. **NAO usar `GD_FATO_ROTACLIENTE`** — desativada (#38) e nao tem
periodicidade nem DTPROXVISITA, o que infla o resultado com quinzenais e
mensais que nao seriam visitados hoje.

### Rota de HOJE

`DTPROXVISITA` e mais preciso que `DIASEMANA` — ele respeita a periodicidade
(7/14/28 dias) e avança sozinho apos a visita.

```sql
WHERE TRUNC(r.DTPROXVISITA) <= TRUNC(:dtRef)
  AND TRUNC(r.DTPROXVISITA) >= TRUNC(:dtRef) - 7   -- janela, evita historico
```

Se precisar de `DIASEMANA`: e texto em maiusculas e **TERÇA e SÁBADO tem
acento**, com cadastro misturado. Comparar sempre com as duas variantes:

```sql
WHERE UPPER(r.DIASEMANA) IN (:nome, REPLACE(:nome,'C','Ç'))
```

### Cobertura entre RCAs

RCA pode cobrir a rota do colega. Nao restringir as visitas ao mesmo
`CODUSUR` — usar o conjunto de clientes da rota.

⚠️ `PCROTACLI` NAO e limpa quando o RCA e desligado: o cadastro fica e o
desligado reaparece com clientes orfaos. Aplicar sempre o filtro da #90.

### "Carteira" tem 3 sentidos — perguntar antes

| Sentido | Onde |
|---|---|
| carteira de **pedidos** (posicao em aberto) | `PCPEDC`, `POSICAO IN ('L','M')` |
| carteira de **clientes** (quem e do RCA) | `PCCLIENT` |
| carteira de **rota** (quem ele visita) | `PCROTACLI` |

---

## #42 - RUPTURA: PCFALTA, filtro de filial e a pegadinha do BI

Ruptura vive na **PCFALTA**. Valor perdido = `SUM(QT * PVENDA)`. Colunas:
`CODFILIAL, DATA, QT, PVENDA, CODUSUR, CODCLI, CODPROD, NUMPED`.
**Nao existe DTFALTA** — a data e `DATA`.

### O filtro de filial DEPENDE do indicador (regra do briefing)

| Indicador | Filiais |
|---|---|
| **Vendas** (faturamento, carteira, meta) | as 20 comerciais, **sem** depositos |
| **Operacao / ruptura por filial** | INCLUI 17, 19 e 23 **remapeados** para a filial-mae |
| **Ruptura BR total** | **sem filtro nenhum** — o BI inclui os CDs no consolidado |

```sql
-- remapeamento para ruptura POR FILIAL DE VENDA
CASE CODFILIAL WHEN '17' THEN '10'   -- Sao Pedro da Aldeia -> Sao Goncalo
               WHEN '19' THEN '04'   -- CD Sao Luis -> Sao Luis
               WHEN '23' THEN '14'   -- Petropolis -> Pirai
               ELSE CODFILIAL END
```

⚠️ Pegadinha: a ruptura BR do BI e MAIOR que a soma das filiais comerciais,
porque inclui os depositos. Se o numero nao bate com o BI, e provavelmente
isto. Os depositos movimentam mas nao faturam — por isso nao aparecem no mapa
regional (#107).

---

## #45 - PCUSUARI: use TIPOVEND para funcao/cargo, nao FUNCAO

NÃO misturar vocabulário VIEW × FATO (ORA-00904 dentro da fonte canônica):
VIEW_VENDAS_RESUMO_FATURAMENTO → data=DTSAIDA, valor=VLATEND.
VIEW_VENDAS_RESUMO_FATURAMENTO → data=DTSAIDA (DATE), valor=VLATEND, filtro CONDVENDA=1.
Nunca usar o par de uma na outra.

---

## #46 - Colunas que o modelo inventa (o pre-voo ja recusa)

⚠️ Desde 10/09/2026 o **pre-voo do MCP valida toda coluna contra o dicionario
do Oracle e RECUSA antes de executar**. Esta tabela e referencia de onde esta
o campo certo — nao e mais preciso decorar.

| Tabela | Coluna inventada | Onde esta de verdade |
|---|---|---|
| PCPRODUT | `CODFILIAL`, `ATIVO`, `FORALINHA` | **PCPRODFILIAL** (status e por filial) |
| PCPRODUT | `DTULTENT` | **PCEST** |
| PCPRODUT | `CODFORNECPRINC` | **PCFORNEC** |
| PCPRODUT | `CODEAN` | e **`CODAUXILIAR`** |
| PCUSUARI | `FUNCAO` | e **`TIPOVEND`** |
| PCUSUARI | `ATIVO` | e `DTTERMINO` (ver #90) |
| PCVISITAFV | `CODFILIAL` | JOIN PCUSUARI -> `u.CODFILIAL` |
| PCVISITAFV | `DTVISITA`, `DTCHECKIN` | e **`DATA`** |
| PCCARREG | `CODFILIAL`, `DATA` | `CODFILIALDESTINO` e `DTSAIDA` |
| PCCARREG | `DTCANCEL` | e **`DT_CANCEL`** (com underscore) |
| PCNFSAID | `VLATEND`, `DTEMISSAO` | `VLTOTAL` e `DTSAIDA` (ver #89) |
| VIEW_VENDAS_RESUMO_FATURAMENTO | `QUANTIDADE` | e **`QT`** |

`PCMOVENDPEND` exige SEMPRE `CODFILIAL` **e** `DATA` no WHERE — sao 97 milhoes
de linhas e sem os dois a consulta estoura o tempo.

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

## #54 - Mix disponivel: os filtros validados

```sql
pf.REVENDA = 'S' AND pf.ATIVO = 'S'
AND pf.PROIBIDAVENDA = 'N'      -- com 'IDA': nao e PROIBVENDA
AND pf.FORALINHA = 'N'
AND EXISTS (PCEST com QTESTGER > 0)
```

NAO acrescentar filtro de `DTULTENT` — gera efetividade acima de 100%. E a
`PCPRODUT` nao tem `DTULTENT`; so a `PCEST` tem.

---

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

## #60 - DATAS E HORAS no Winthor: o que tem hora e o que nao tem

### Nem toda coluna DATE tem hora

| COM hora | SEM hora (truncada) |
|---|---|
| `PCMOVENDPEND.DTINICIOOS`, `DTFIMOS` | `PCMOVENDPEND.DATA` |
| `PCCORTEI.DATA`, `PCWMSCORTE.DATA` | `PCCARREG.DTSAIDA`, `PCPEDC.DATA` |
| | `PCCARREG.DTFECHA` (hora em HORAFECHA/MINUTOFECHA) |

`PCMOVENDPEND.HORA` e carimbo da O.S., nao do movimento — bate com
`DTINICIOOS` em apenas 5,3% das linhas. **E ruido: nao usar.**

### EXTRACT(HOUR FROM coluna DATE) da ORA-30076

O Oracle so aceita EXTRACT de TIMESTAMP. Para hora de uma coluna DATE:

```sql
TO_CHAR(m.DTINICIOOS, 'HH24')          -- correto
EXTRACT(HOUR FROM m.DTINICIOOS)        -- ORA-30076
```

### Turno que vira o dia

A separacao roda das 21h as 07h, com 57% do volume DEPOIS da meia-noite.
`TRUNC(DATA)` sozinho parte o turno em dois dias. Deslocar:

```sql
TRUNC(m.DTINICIOOS - 12/24) AS DIA_OPERACIONAL
```

`PCMOVENDPEND` exige SEMPRE `CODFILIAL` **e** `DATA` no WHERE — 97 milhoes de
linhas.

---

## #61 - Motivo de corte: PCTABDEV com TIPO = 'CO'

Os codigos de corte (62, 64, 65, 116, 118) sao da PCTABDEV, e sao exatamente
o subconjunto TIPO = 'CO'. PCMOTIVONAOATEND esta VAZIA e PCMOTIVOAVARIA so tem
9 codigos (1 a 9) — nao servem.

ARMADILHA DE TIPO: PCCORTEI.MOTIVO e VARCHAR2 e mistura codigo numerico com
texto livre digitado. PCTABDEV.CODDEVOL e NUMBER. Fazer o join pelo lado texto
para nao tomar ORA-01722:

  LEFT JOIN EBD.PCTABDEV d ON TO_CHAR(d.CODDEVOL) = TRIM(c.MOTIVO)

PCWMSCORTE.CODMOTIVO ja e NUMBER e junta direto.

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

## #73 - Carga: baixa e DTFECHA; km e prazo NAO EXISTEM

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



### KM e prazo nao existem — nao insistir

`PCCARREG.KMINICIAL/KMFINAL`: preenchidas em ~34% das linhas, mas com valor
ZERO em 100% dos casos desde 2019. `PCROTAEXP`: KMROTA, DIASENTREGA,
PRAZOPREVENT e QTENTREGA todas zeradas.

Esse dado vive na MaximaTech/MyFrota e a integracao e de mao unica
(PCMYFROTA_FILA com 560 mil saidas, tabelas de retorno zeradas).

---

## #74 - FORNECEDOR: raiz, busca por nome e o timeout de 80s

### Fornecedor raiz

`NVL(f.CODFORNECPRINC, f.CODFORNEC)` — quando nao tem principal, ele e o
proprio. `CODFORNECPRINC` fica na **PCFORNEC**, nunca na PCPRODUT.

### MARCA nao e FORNECEDOR

Sao coisas diferentes: Havaianas e MARCA (`PCMARCA`, cod 1272); o fornecedor
e ALPARGATAS (`PCFORNEC`, cods 25277/25324/25498). Procurar o termo nas
QUATRO: `PCFORNEC.FORNECEDOR`, `PCFORNEC.FANTASIA`, `PCMARCA.MARCA` e
`PCPRODUT.DESCRICAO`.

### ZERO LINHAS em cadastro NAO e resposta

Se a busca por nome em tabela de cadastro volta vazia, o termo esta na tabela
errada — nao e ausencia de dado. **Nao prosseguir com a analise sobre conjunto
vazio.** O MCP ja avisa isso no resultado.

### O timeout de 80s

`NVL()` no WHERE mata o indice `PCPRODUT_IDX3`. Resolver o `CODFORNEC` UMA VEZ
numa CTE e usar o codigo depois — 4,23s viram 0,64s.

```sql
WITH forn AS (SELECT CODFORNEC FROM EBD.PCFORNEC
               WHERE NVL(CODFORNECPRINC, CODFORNEC) = :cod)
SELECT ... FROM EBD.PCPRODUT p JOIN forn f ON f.CODFORNEC = p.CODFORNEC
```

---

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

## #88 - Canal Loja EBD: fonte, colunas e metricas

`VIEW_VENDAS_RESUMO_FATURAMENTO` **nao tem** `ORIGEMPED` nem `CODEMITENTE`
(ORA-00904). O canal so e isolavel pela **PCPEDC**; a view serve so como
denominador (faturamento total da companhia).

```sql
FROM EBD.PCPEDC p
WHERE p.DATA >= :inicio AND p.DATA < :fim
  AND p.POSICAO = 'F'                    -- FATURADO (secao 11.6)
  AND p.DTCANCEL IS NULL                 -- cancelado NUNCA conta como venda
  -- canal:       AND p.ORIGEMPED='W' AND p.CODEMITENTE=7777
  -- B2B:         AND NVL(cl.CODATV1,0) <> 31   (B2E e = 31, funcionarios)
  -- tradicional: AND NVL(p.ORIGEMPED,'X') <> 'W'
```

⚠️ A coluna e **`VLATEND`**, nao `VLTOTAL` — divergem 7,5%.

### Numeros de referencia (medidos 28/08/2026, 01 a 28/08)

| | Pedidos | Clientes | VLATEND |
|---|---|---|---|
| Loja B2B | 1.810 | 908 | R$ 1.172.905,55 |
| Tradicional | 122.134 | 43.197 | R$ 250.210.633,41 |
| Companhia | 125.704 | — | R$ 254.670.705,83 |

Participacao da Loja: **0,46%**.

**CONFERENCIA OBRIGATORIA: `ticket x pedidos` tem que bater com o total.** Em
28/08/2026 o painel declarou R$ 3,60 bi de tradicional — 13x o real —, e o
proprio painel se contradizia (0,46% no bloco 1 contra 0,03% no bloco 5).
Multiplicar ticket por pedidos teria pego na hora.

### Incrementalidade e recuperados SAO calculaveis

Em 28/08/2026 o agente declarou os dois como "nao disponivel na base atual".
**E falso.** A PCPEDC tem `CODCLI`, `DATA`, `ORIGEMPED`, `POSICAO` e `VLATEND`
na mesma tabela — tudo que a analise antes/depois precisa. Rodam em < 8s.

Incrementalidade (1.111 adotantes jan-mai/2026, janela 90 dias):
faturamento R$ 5,16 mi → R$ 7,88 mi (**+52,8%**), pedidos 5.846 → 9.458
(**+61,8%**), ticket R$ 922,40 → R$ 873,23 (-5,3%). O cliente compra mais
vezes, um pouco menor por vez — saldo incremental.

Recuperados (90+ dias parado, voltou pelo portal): **135** em agosto/2026.

⚠️ Declarar "dado nao disponivel" e pior que omitir: encerra a pergunta. So
declarar depois de tentar.

### Recompra NAO e retencao

RECOMPRA = 2a compra dentro de N dias da 1a. **CRESCE** com a janela:
30d 50,7% · 60d 63,5% · 90d 68,4% (3.355 clientes em 2026).

RETENCAO = quem comprou no mes e tambem comprou antes. **DECRESCE**.

O painel de 28/08 entregou 61,8% / 54,9% / 48,0% chamando de recompra — era
retencao. **Se o numero CAI quando a janela aumenta, e retencao.**

```sql
WITH ped AS (
    SELECT p.CODCLI, p.DATA,
           ROW_NUMBER() OVER (PARTITION BY p.CODCLI ORDER BY p.DATA) AS SEQ,
           MIN(p.DATA) OVER (PARTITION BY p.CODCLI)                  AS DT_1A
    FROM EBD.PCPEDC p
    WHERE p.ORIGEMPED='W' AND p.CODEMITENTE=7777 AND p.POSICAO='F'
      AND p.DATA >= :inicio
)
SELECT COUNT(DISTINCT CODCLI) AS CLIENTES,
       COUNT(DISTINCT CASE WHEN SEQ=2 AND DATA-DT_1A <= 30 THEN CODCLI END) AS R30,
       COUNT(DISTINCT CASE WHEN SEQ=2 AND DATA-DT_1A <= 60 THEN CODCLI END) AS R60,
       COUNT(DISTINCT CASE WHEN SEQ=2 AND DATA-DT_1A <= 90 THEN CODCLI END) AS R90
FROM ped
```

## #89 - COMPRA x VENDA: tabelas parecidas que trazem numero errado calado

O Winthor tem pares de tabelas com nomes proximos e as MESMAS chaves
(`NUMPED`, `CODPROD`). Confundir nem sempre da erro — as vezes traz numero de
compra num relatorio de venda, sem nenhum aviso. E o pior tipo de engano.

| Preciso de | Cabecalho | Item |
|---|---|---|
| **VENDA** (pedido de cliente) | `PCPEDC` | `PCPEDI` |
| **COMPRA** (pedido ao fornecedor) | `PCPEDIDO` | `PCITEM` |

Como saber de qual voce esta lendo, sem decorar:

- `PCPEDI` tem **`PVENDA`**, `QT`, `CODUSUR`, `CODCLI` -> e VENDA
- `PCITEM` tem **`PCOMPRA`**, `QTPEDIDA`, `QTENTREGUE`, `DTULTENT` -> e COMPRA

Se a coluna que voce quer e preco de venda e voce esta na PCITEM, esta na
tabela errada.

### Valor: cada tabela tem o seu

| Tabela | Coluna de valor |
|---|---|
| `PCPEDC` (pedido) | **`VLATEND`** |
| `PCNFSAID` (nota) | **`VLTOTAL`** |
| `PCPEDI` (item de venda) | `PVENDA` x `QT` |
| `PCITEM` (item de compra) | `PCOMPRA` x `QTPEDIDA` |

⚠️ A `PCNFSAID` **nao tem `VLATEND`** nem `DTEMISSAO` (a data e `DTSAIDA`).
Faturamento sai da PCPEDC com VLATEND — ver cicatriz #88.

### Outras confusoes de nome vistas em producao (ago/2026)

| Tentaram | O certo |
|---|---|
| `PCEST.QTUNITCX` | esta na **`PCPRODUT`** |
| `PCCLIENT.FONE` | **`TELENT`** (entrega) ou **`TELCOB`** (cobranca) |
| `PCCATEGORIA.DESCRICAO` | **`CATEGORIA`** (mas `PCDEPTO` e `PCSECAO` usam `DESCRICAO`) |
| `PCREDECLIENTE.CODCLI` | o vinculo e `PCCLIENT.CODREDE` |
| `PCSERVICOCLIENTETELEFONE.CODCLI` | **`CODCLIENTE`** |
| `PCPEDI.CODFILIAL` | nao tem — a filial vem da `PCPEDC` |

Estas o pre-voo ja recusa antes de executar. A distincao compra/venda NAO —
ali as colunas existem nas duas, e so o contexto do negocio diz qual e a
certa.

## #90 - RCA de campo: o filtro canonico (unico e obrigatorio)

Consolida quatro regras que estavam soltas dentro da #54 e se contradiziam
(jul/2026) — uma delas ensinava `NOT IN` sem `IS NOT NULL`, que zera o
resultado. Usar ESTE filtro em toda metrica de força de vendas: checkin,
cobertura, efetividade, positivacao, rota, produtividade.

```sql
FROM EBD.PCUSUARI u
WHERE u.CODUSUR NOT IN (SELECT COD_CADRCA FROM EBD.PCSUPERV
                         WHERE COD_CADRCA IS NOT NULL)
  AND (u.DTTERMINO IS NULL OR u.DTTERMINO >= TRUNC(SYSDATE))
  AND UPPER(NVL(u.NOME,'')) NOT LIKE '%ECOMMERCE%'
  AND UPPER(NVL(u.NOME,'')) NOT LIKE '%GM-RM%'
  AND UPPER(NVL(u.NOME,'')) NOT LIKE 'ORFAO%'
  AND UPPER(NVL(u.NOME,'')) NOT LIKE 'RCA VAGO%'
  AND UPPER(NVL(u.NOME,'')) NOT LIKE '%B2B%'
  AND UPPER(NVL(u.NOME,'')) NOT LIKE '%GERENTE%'
```

ORFAO e RCA VAGO sao codigos ficticios de filial usados como deposito de
clientes parados — nunca visitam, nunca vendem, e inflam qualquer metrica
de produtividade.

### As tres armadilhas

1. **`NOT IN` sem `IS NOT NULL` devolve ZERO linhas.** Comportamento do Oracle
   com NULL no subselect — silencioso, sem erro.
2. **`DTEXCLUSAO` e sempre NULL na PCUSUARI** — nao filtra nada. Quem marca
   desligamento e `DTTERMINO`.
3. **`PCROTACLI` nao e limpa quando o RCA sai.** O cadastro de rota fica e o
   desligado reaparece com clientes orfaos. Sempre juntar com PCUSUARI.

### Referencia (jul/2026)

| | |
|---|---|
| `DTTERMINO IS NULL` | 1.203 |
| desligados | 2.095 |
| **RCAs ativos BR, filtro completo** | **1.205** |
| EBD SBC sem filtro / com filtro | 34+ / **27** |

⚠️ O MESMO filtro no resumo e no detalhe. Resumo com "X vendedores sem pedido"
e detalhe com outro criterio gera numero que nao fecha.

---

## #91 - Projecao de faturamento do mes

Validada em 28/05/2026 com jan-mai:

- Projecao linear simples ERRA — o faturamento nao e uniforme no mes.
- A ultima semana concentra volume acima da media; projetar sem considerar
  isso subestima o fechamento.
- **Loja EBD (`ORIGEMPED='W'` + `CODEMITENTE=7777`) tem curva propria** e nao
  segue o padrao do canal tradicional.
- Dias uteis: contar seg a sab (domingo nao conta).

---

## #92 - Produtividade em rota: o valor vem do PEDIDO

O valor faturado sai de `PCPEDC.VLATEND`, nao e derivado da visita.

Relatorio de rota precisa trazer, alem do RCA: clientes na rota, visitados,
com pedido, valor e percentual de efetividade. Resumo sem essas colunas nao
permite conferir.

Aplicar o filtro de RCA de campo da cicatriz #90.

---

## #102 - Carteira de pedidos: os filtros canonicos da PCPEDC

carteira de pedidos usa PCPEDC com os filtros canônicos:
`POSICAO IN ('L','M')` (livre/montado) + `DTCANCEL IS NULL` + `CONDVENDA NOT IN (4,8,10,13,20,98,99)`.
Valor = VLATEND (atendido). Pedido BLOQUEADO = `POSICAO = 'B'`. Faturado = `POSICAO = 'F'`.

---

## #103 - PCPEDC: as colunas validadas em producao

PCPEDC — colunas validadas: CODFILIAL, DATA, VLATEND, NUMPED, POSICAO,
CODCLI, DTCANCEL, VLTOTAL, ORIGEMPED, CODUSUR, CONDVENDA, CODEMITENTE, CODCOB.
NÃO EXISTEM: VLPESO, BLOQUEIO (ORA-00904). Data do pedido = DATA (não DTSAIDA — essa é da VIEW).

---

## #104 - Meta: PCMETA com TIPOMETA='FL' (filial)

meta usa PCMETA — colunas: CODFILIAL, DATA, VLVENDAPREV (valor previsto),
TIPOMETA ('FL' = filial). Meta do mês corrente:
`TIPOMETA='FL' AND DATA BETWEEN TRUNC(SYSDATE,'MM') AND LAST_DAY(SYSDATE)`.

---

## #107 - MAPA REGIONAL: a fonte e o BANCO, nao este documento

```sql
SELECT rf.FANTASIAREGIONAL AS REGIONAL, rf.CODFILIAL
FROM EBD.EBD_REGIONAISFILIAIS rf
WHERE rf.PARTICIPAGERENCIAL = 'S'
```

`PARTICIPAGERENCIAL='S'` separa as 9 regionais operacionais dos agrupamentos
maiores (NORTE, NORDESTE, SAO PAULO, RIO DE JANEIRO, ORIGEM RJ), que sao 'N'.
A sigla vem em `FANTASIAREGIONAL` — **nao juntar com PCREGIONAL**, os
CODREGIONAL das duas divergem e o join produz lixo (NE1=Fortaleza).

Mapa medido em 01/09/2026, para conferencia:

| Regional | Filiais |
|---|---|
| N1 | 06 Manaus · 08 Boa Vista |
| N2 | 01 Matriz · 07 Macapa · 11 Santarem · 22 Maraba |
| NE1 | 04 Sao Luis · 12 Imperatriz |
| NE2 | 03 Fortaleza · 09 Juazeiro · 21 Teresina |
| NE3 | 52 Petrolina · 53 Caruaru |
| RJ1 | 10 Sao Goncalo · 13 Taquara |
| RJ2 | 05 Duque · 14 Pirai |
| SP1 | 02 SP · 16 Itapevi |
| SP2 | 15 Guarulhos · 18 SBC |

⚠️ O Norte e **`N1`/`N2`** no banco — a versao anterior desta cicatriz usava
NO1/NO2, e o T-PAINEL01 chegou a ter um mapa escrito a mao com NE1/NE2/NE3
trocadas. Nao reescrever o mapa: ler da tabela.

---

## #108 - hierarquia comercial tem dimensão pronta

RCA→supervisor→gerente vive em
PCUSUARI (CODUSUR, NOME, CODSUPERVISOR) + PCSUPERV (NOME, CODGERENTE) + PCGERENTE (NOMEGERENTE).
Não montar JOIN pesado de PCUSUARI+PCSUPERV para hierarquia; usar a dimensão.

---

## #115 - vendedor e filial do cliente

na PCCLIENT o vendedor dono do cliente é
CODUSUR1 (validado; existem também CODUSUR2/3 secundários). PCCLIENT NÃO tem CODFILIAL direta —
a filial do cliente vem pela filial do vendedor (JOIN PCUSUARI u ON u.CODUSUR = c.CODUSUR1,
filtra por u.CODFILIAL) OU por c.CODFILIALNF (filial da NF). Colunas validadas: CODCLI, CLIENTE
(nome), CODUSUR1, CODFILIALNF, DTEXCLUSAO, DTULTCOMP, CODATV1, DTCADASTRO. NÃO EXISTEM: NOME
(é CLIENTE), CODFILIAL, CIDADE, CGC.

---

## #116 - DOIS critérios de "ativo" — dão números diferentes

- CADASTRAL: `DTEXCLUSAO IS NULL` = cliente não excluído do sistema (quase todos ativos).
- COMERCIAL: 90 dias sem compra (PCCLIENT.DTULTCOMP) = cliente que parou de comprar.
Ex. SBC: cadastral 2.885 ativos/0 inativos vs comercial 2.619 ativos/266 inativos.
Diretor perguntando "clientes ativos" geralmente quer o COMERCIAL. Na dúvida, perguntar.

---

## #117 — Painel consolidado: o que soma, o que não soma, e onde não fecha

Medido em 29/09/2026 contra as tabelas `EBD_IA_PAINEL_*`, não repetido do
texto de apresentação — que estava errado em três pontos.

### 1. Contagem distinta não soma — e cada corte quebra uma diferente

202608, soma dos cortes contra o total da MES:

| Medida | soma FILIAL | soma INDUSTRIA |
|---|---|---|
| `VL_LIQUIDO`, `QT_UNIDADES` | soma | soma |
| `QT_NOTAS` | soma | **1,94×** (uma nota tem itens de várias indústrias) |
| `QT_CLIENTES` | ≈ 1,004× | **3,85×** |
| `QT_VENDEDORES` | ≈ 1,005× | **7,89×** |
| `QT_SKUS` | **3,71×** (mesmo SKU vende em várias filiais) | soma |

**Regra:** para qualquer contagem Brasil, leia da `EBD_IA_PAINEL_MES`. Nunca
agregue `QT_*` a partir dos cortes, exceto `QT_UNIDADES`.

### 2. A INDUSTRIA não reconcilia ao centavo

`FILIAL` fecha com a `MES` (máx. R$ 0,03). A `INDUSTRIA` **diverge em 16 de
20 meses** — pior caso **R$ 6.992,65 em 202509**, também 202606 (R$ 3.871)
e 202602 (R$ 874). Só fecha exatamente em 202502, 202505, 202603 e 202608.

É pequeno (≈0,002%), mas não é zero. Para o **total**, use a `MES`; a soma
da INDUSTRIA não é o total oficial.

### 3. `VL_TICKET_MEDIO` é BRUTO ÷ notas

Não líquido. Em 202608: 2.420,77 (bruto) contra 2.318,46 (líquido). Para
ticket líquido, calcule `VL_LIQUIDO / QT_NOTAS`.

### 4. `PERC_PART_FAT`

Sempre 100 na MES — não é medida. Nos cortes soma 100 e significa
participação.

### 5. Só mês fechado

Último mês é 202608. Para "como estamos hoje", use o faturamento ao vivo
(T210). Consultar o painel para o mês corrente devolve o mês anterior sem
aviso.

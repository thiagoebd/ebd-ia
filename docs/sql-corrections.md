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

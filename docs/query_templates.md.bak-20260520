# Query Templates — SQL pronto para o agente Winthor

> **Como funciona este arquivo:** templates SQL validados e estáveis que o
> agente DEVE preferir adaptar em vez de gerar SQL do zero. Cada template tem
> um nome, descrição, bind variables, e exemplo de uso.
>
> **Convenção:** templates usam SEMPRE bind variables (:userFilial, :dtInicio,
> :dtFim, etc), nunca string concatenation. SQL Guard valida.
>
> **Status atual (19/05/2026 v2):** REESCRITO baseado nas 224 views do Data
> Warehouse Oracle descobertas em winthor_discovery.md. Templates antigos
> (T001-T003) baseados em tabelas raw foram REMOVIDOS — todos usam views
> dimensionais agora.

---

## Convenções de bind variables

Toda query do projeto usa estas bind variables com nomes consistentes:

| Bind var | Tipo | Exemplo | Descrição |
|---|---|---|---|
| :userFilial | string | '05' | Código da filial (sempre obrigatório) |
| :userFiliais | lista | ('10','13') | Lista de filiais (regional) — usar com IN |
| :dtInicio | date | DATE '2026-05-01' | Início do período |
| :dtFim | date | DATE '2026-05-31' | Fim do período |
| :topN | number | 10 | Quantidade para Top N |
| :codFornec | number | 1 | Código do fornecedor (filtrado) |
| :codProduto | number | 1 | Código do produto (filtrado) |
| :codUsur | number | 146 | Código do vendedor/RCA |
| :codGerente | number | 12 | Código do gerente |

## Convenção crítica de datas em views GD_*

As views dimensionais retornam datas como STRINGS YYYYMMDD. SEMPRE converter
:dtInicio e :dtFim antes de comparar:

    AND DATAFATURAMENTO BETWEEN TO_CHAR(:dtInicio, 'YYYYMMDD')
                            AND TO_CHAR(:dtFim, 'YYYYMMDD')

---

## Template T100 — Faturamento por Filial (mês corrente)

**Descrição:** faturamento real (NF emitida) por filial no mês corrente.

**Quando usar:** usuário pede "faturamento do mês", "vendas da filial X",
"como está o mês até agora".

**View principal:** GD_FATO_VENDAFATURAMENTO

**Bind variables:** :userFilial

**SQL:**

    SELECT
        CODIGOFILIAL,
        COUNT(DISTINCT NUMEROTRANSVENDA) AS QTD_NOTAS,
        SUM(VALORTOTAL) AS FATURAMENTO_BRUTO,
        SUM(QUANTIDADE) AS QUANTIDADE_TOTAL
    FROM EBD.GD_FATO_VENDAFATURAMENTO
    WHERE CODIGOFILIAL = :userFilial
      AND DATAFATURAMENTO >= TO_CHAR(TRUNC(SYSDATE, 'MM'), 'YYYYMMDD')
      AND DATAFATURAMENTO <= TO_CHAR(SYSDATE, 'YYYYMMDD')
    GROUP BY CODIGOFILIAL

**Variações:**
- Para período customizado: substituir o BETWEEN por :dtInicio/:dtFim
- Para regional: trocar = :userFilial por IN (:userFiliais)
- Para líquido: subtrair GD_FATO_VENDADEVOLUCAO no mesmo período

**Latência esperada:** 1-3s (depende do tamanho da filial)

---

## Template T101 — Top N Fornecedores (Real vs AA vs Meta)

**Descrição:** ranking de fornecedores no período comparando Real (faturado),
AA (mesmo período ano anterior) e Meta (fornecedor).

**Quando usar:** "top 5 fornecedores", "quais marcas estão melhor",
"ranking de marcas vs meta".

**Views:** GD_FATO_VENDAFATURAMENTO + GD_DIM_PRODUTO + GD_FATO_METAFORNECEDOR

**Bind variables:** :userFilial, :dtInicio, :dtFim, :topN

**SQL:**

    WITH vendas AS (
        SELECT
            p.CODIGOFORNECEDOR,
            p.FORNECEDOR,
            SUM(CASE
                WHEN v.DATAFATURAMENTO BETWEEN TO_CHAR(:dtInicio, 'YYYYMMDD')
                                           AND TO_CHAR(:dtFim, 'YYYYMMDD')
                THEN v.VALORTOTAL END) AS REAL_VALOR,
            SUM(CASE
                WHEN v.DATAFATURAMENTO BETWEEN TO_CHAR(ADD_MONTHS(:dtInicio, -12), 'YYYYMMDD')
                                           AND TO_CHAR(ADD_MONTHS(:dtFim, -12), 'YYYYMMDD')
                THEN v.VALORTOTAL END) AS AA_VALOR
        FROM EBD.GD_FATO_VENDAFATURAMENTO v
        JOIN EBD.GD_DIM_PRODUTO p ON v.CODIGOPRODUTO = p.CODIGOPRODUTO
        WHERE v.CODIGOFILIAL = :userFilial
          AND v.DATAFATURAMENTO >= TO_CHAR(ADD_MONTHS(:dtInicio, -12), 'YYYYMMDD')
          AND v.DATAFATURAMENTO <= TO_CHAR(:dtFim, 'YYYYMMDD')
        GROUP BY p.CODIGOFORNECEDOR, p.FORNECEDOR
    ),
    metas AS (
        SELECT
            CODIGOENTIDADEMETA AS CODIGOFORNECEDOR,
            SUM(VALOR) AS META_VALOR
        FROM EBD.GD_FATO_METAFORNECEDOR
        WHERE CODIGOFILIAL = :userFilial
          AND DATA BETWEEN TO_CHAR(:dtInicio, 'YYYYMMDD')
                       AND TO_CHAR(:dtFim, 'YYYYMMDD')
        GROUP BY CODIGOENTIDADEMETA
    )
    SELECT
        v.CODIGOFORNECEDOR,
        v.FORNECEDOR,
        v.REAL_VALOR,
        v.AA_VALOR,
        m.META_VALOR,
        CASE WHEN m.META_VALOR > 0 THEN v.REAL_VALOR / m.META_VALOR END AS PCT_VS_META,
        CASE WHEN v.AA_VALOR > 0 THEN (v.REAL_VALOR - v.AA_VALOR) / v.AA_VALOR END AS PCT_VS_AA
    FROM vendas v
    LEFT JOIN metas m ON v.CODIGOFORNECEDOR = m.CODIGOFORNECEDOR
    ORDER BY v.REAL_VALOR DESC NULLS LAST
    FETCH FIRST :topN ROWS ONLY

**Latência esperada:** 3-8s (depende do período)

---

## Template T102 — Faturamento por Ramo de Atividade

**Descrição:** faturamento agrupado pelo ramo de atividade do cliente.

**Quando usar:** "vendas por ramo", "quanto vendi pra supermercado",
"split por canal".

**Views:** GD_FATO_VENDAFATURAMENTO + GD_DIM_CLIENTE

**Bind variables:** :userFilial, :dtInicio, :dtFim

**SQL:**

    SELECT
        c.RAMOATIVIDADE,
        COUNT(DISTINCT v.CODIGOCLIENTE) AS QTD_CLIENTES,
        SUM(v.VALORTOTAL) AS FATURAMENTO,
        SUM(v.VALORTOTAL) / SUM(SUM(v.VALORTOTAL)) OVER () AS PCT_PARTICIPACAO
    FROM EBD.GD_FATO_VENDAFATURAMENTO v
    JOIN EBD.GD_DIM_CLIENTE c ON v.CODIGOCLIENTE = c.CODIGOCLIENTE
    WHERE v.CODIGOFILIAL = :userFilial
      AND v.DATAFATURAMENTO BETWEEN TO_CHAR(:dtInicio, 'YYYYMMDD')
                                AND TO_CHAR(:dtFim, 'YYYYMMDD')
    GROUP BY c.RAMOATIVIDADE
    ORDER BY FATURAMENTO DESC NULLS LAST

**Variações:**
- Para "Ramo Principal" (refinamento mais granular): usar a coluna correta
  de GD_DIM_CLIENTE (CODIGORAMOATIVIDADE)

**Latência esperada:** 2-5s

---

## Template T103 — Top N RCAs (com hierarquia)

**Descrição:** ranking de vendedores no período, mostrando supervisor e
gerente.

**Quando usar:** "top 10 vendedores", "melhores RCAs do mês", "ranking time
do gerente X".

**Views:** GD_FATO_VENDAFATURAMENTO + GD_DIM_RCA

**Bind variables:** :userFilial, :dtInicio, :dtFim, :topN

**SQL:**

    SELECT
        r.CODIGORCA,
        r.RCA AS NOME_RCA,
        r.SUPERVISOR,
        r.GERENTE,
        r.SITUACAO,
        SUM(v.VALORTOTAL) AS FATURAMENTO,
        COUNT(DISTINCT v.CODIGOCLIENTE) AS POSITIVACAO,
        COUNT(DISTINCT v.NUMEROPEDIDO) AS QTD_PEDIDOS
    FROM EBD.GD_FATO_VENDAFATURAMENTO v
    JOIN EBD.GD_DIM_RCA r ON v.CODIGORCA = r.CODIGORCA
    WHERE v.CODIGOFILIAL = :userFilial
      AND v.DATAFATURAMENTO BETWEEN TO_CHAR(:dtInicio, 'YYYYMMDD')
                                AND TO_CHAR(:dtFim, 'YYYYMMDD')
    GROUP BY r.CODIGORCA, r.RCA, r.SUPERVISOR, r.GERENTE, r.SITUACAO
    ORDER BY FATURAMENTO DESC NULLS LAST
    FETCH FIRST :topN ROWS ONLY

**Variações:**
- Filtrar por gerente: adicionar AND r.CODIGOGERENTE = :codGerente
- Apenas ativos: adicionar AND r.SITUACAO = 'ATIVO'

**Latência esperada:** 2-5s

---

## Template T104 — Inadimplência por Filial (ou RCA)

**Descrição:** valor e quantidade de títulos inadimplentes, com dias de
atraso.

**Quando usar:** "qual a inadimplência?", "clientes em atraso", "valor
vencido por RCA".

**View principal:** GD_FATO_CONTASRECEBER

**Bind variables:** :userFilial

**SQL (por filial — visão agregada):**

    SELECT
        CODIGOFILIAL,
        COUNT(*) AS QTD_TITULOS_VENCIDOS,
        SUM(VALORTITULO) AS VALOR_TOTAL_VENCIDO,
        AVG(DIASATRASO) AS MEDIA_DIAS_ATRASO,
        SUM(CASE WHEN DIASATRASO BETWEEN 1 AND 30 THEN VALORTITULO END) AS VENCIDO_1_30,
        SUM(CASE WHEN DIASATRASO BETWEEN 31 AND 60 THEN VALORTITULO END) AS VENCIDO_31_60,
        SUM(CASE WHEN DIASATRASO BETWEEN 61 AND 90 THEN VALORTITULO END) AS VENCIDO_61_90,
        SUM(CASE WHEN DIASATRASO > 90 THEN VALORTITULO END) AS VENCIDO_91_MAIS
    FROM EBD.GD_FATO_CONTASRECEBER
    WHERE CODIGOFILIAL = :userFilial
      AND INADIMPLENCIA = 1
    GROUP BY CODIGOFILIAL

**SQL (por RCA — ranking de quem tem mais inadimplência):**

    SELECT
        r.CODIGORCA,
        r.RCA AS NOME_RCA,
        r.GERENTE,
        COUNT(*) AS QTD_TITULOS_VENCIDOS,
        SUM(cr.VALORTITULO) AS VALOR_VENCIDO,
        AVG(cr.DIASATRASO) AS MEDIA_DIAS_ATRASO
    FROM EBD.GD_FATO_CONTASRECEBER cr
    JOIN EBD.GD_DIM_RCA r ON cr.CODIGORCA = r.CODIGORCA
    WHERE cr.CODIGOFILIAL = :userFilial
      AND cr.INADIMPLENCIA = 1
    GROUP BY r.CODIGORCA, r.RCA, r.GERENTE
    ORDER BY VALOR_VENCIDO DESC NULLS LAST
    FETCH FIRST :topN ROWS ONLY

**Atenção:** GD_FATO_CONTASRECEBER já exclui códigos especiais (DEVP, DEVT,
BNF, etc) na view. Não precisamos filtrar manualmente.

**Latência esperada:** 1-3s

---

## Template T105 — Estoque + Cobertura por Produto

**Descrição:** posição de estoque por produto, com cobertura em dias e
classificação de giro.

**Quando usar:** "qual o estoque?", "produtos com alto estoque", "ruptura
de estoque", "dias de cobertura".

**Views:** GD_FATO_ESTOQUEATUAL + GD_DIM_PRODUTO + GD_DIM_ESTOQUEATUAL

**Bind variables:** :userFilial

**SQL (visão geral por produto, top N por valor de estoque):**

    SELECT
        p.CODIGOPRODUTO,
        p.PRODUTO,
        p.FORNECEDOR,
        p.LINHAPRODUTO AS FAMILIA,
        e.QUANTIDADEGERENCIAL AS QT_ESTOQUE,
        e.GIRODIA AS GIRO_DIARIO,
        ed.NIVELGIRODIA,
        ed.ESCALADIASESTOQUE AS COBERTURA_FAIXA,
        CASE WHEN e.GIRODIA > 0
             THEN ROUND(e.QUANTIDADEGERENCIAL / e.GIRODIA, 1)
             ELSE NULL END AS DIAS_COBERTURA,
        e.DIASSEMVENDA,
        e.CUSTOULTIMAENTRADA,
        e.QUANTIDADEGERENCIAL * e.CUSTOFINANCEIROUNITARIO AS VALOR_ESTOQUE
    FROM EBD.GD_FATO_ESTOQUEATUAL e
    JOIN EBD.GD_DIM_PRODUTO p ON e.CODIGOPRODUTO = p.CODIGOPRODUTO
    JOIN EBD.GD_DIM_ESTOQUEATUAL ed ON e.CODIGOPRODUTO = ed.CODIGOPRODUTO
                                   AND e.CODIGOFILIAL = ed.CODIGOFILIAL
    WHERE e.CODIGOFILIAL = :userFilial
      AND e.QUANTIDADEGERENCIAL > 0
    ORDER BY VALOR_ESTOQUE DESC NULLS LAST
    FETCH FIRST :topN ROWS ONLY

**Variações:**
- Produtos com ruptura: trocar > 0 por = 0 e remover ORDER BY
- Excesso de estoque: WHERE ed.ESCALADIASESTOQUE IN ('DE 30 A 60', 'ACIMA DE 60')
- Sem giro: WHERE ed.NIVELGIRODIA = 'SEM GIRO'

**Latência esperada:** 2-5s

---

## Template T106 — Clientes Ativos vs Inativos

**Descrição:** segmentação de clientes da filial em ATIVO/INATIVO/EXCLUÍDO
com faixas de inatividade.

**Quando usar:** "quantos clientes ativos?", "clientes sumidos", "base de
clientes da filial".

**View principal:** GD_DIM_CLIENTE

**Bind variables:** :userFilial (opcional — view não tem CODFILIAL direto,
filtra por RCA)

**SQL (segmentação geral):**

    SELECT
        STATUS,
        DIASINATIVOS,
        COUNT(*) AS QTD_CLIENTES
    FROM EBD.GD_DIM_CLIENTE
    GROUP BY STATUS, DIASINATIVOS
    ORDER BY STATUS, DIASINATIVOS

**Atenção:** GD_DIM_CLIENTE NÃO tem coluna CODFILIAL direta. Pra restringir
a uma filial, joinar com últimas vendas:

**SQL (clientes ativos da filial — via última venda):**

    SELECT
        c.CODIGOCLIENTE,
        c.CLIENTE,
        c.NOMEFANTASIA,
        c.RAMOATIVIDADE,
        c.CLASSIFICACAO AS VIP,
        c.STATUS,
        c.DIASINATIVOS,
        c.DTULTCOMP
    FROM EBD.GD_DIM_CLIENTE c
    WHERE c.STATUS = 'ATIVO'
      AND EXISTS (
          SELECT 1 FROM EBD.GD_FATO_VENDAFATURAMENTO v
          WHERE v.CODIGOCLIENTE = c.CODIGOCLIENTE
            AND v.CODIGOFILIAL = :userFilial
            AND v.DATAFATURAMENTO >= TO_CHAR(SYSDATE - 90, 'YYYYMMDD')
      )

**Latência esperada:** 5-15s (depende do volume — base tem 203k clientes)

---

## Template T107 — Positivação de RCA

**Descrição:** quantos clientes únicos cada vendedor faturou no período
(positivação).

**Quando usar:** "positivação dos vendedores", "quantos clientes o RCA X
atendeu", "cobertura da carteira".

**Views:** GD_FATO_VENDAFATURAMENTO + GD_DIM_RCA

**Bind variables:** :userFilial, :dtInicio, :dtFim

**SQL:**

    SELECT
        r.CODIGORCA,
        r.RCA AS NOME_RCA,
        r.SUPERVISOR,
        r.GERENTE,
        COUNT(DISTINCT v.CODIGOCLIENTE) AS POSITIVACAO,
        SUM(v.VALORTOTAL) AS FATURAMENTO,
        SUM(v.VALORTOTAL) / NULLIF(COUNT(DISTINCT v.CODIGOCLIENTE), 0) AS TICKET_MEDIO
    FROM EBD.GD_FATO_VENDAFATURAMENTO v
    JOIN EBD.GD_DIM_RCA r ON v.CODIGORCA = r.CODIGORCA
    WHERE v.CODIGOFILIAL = :userFilial
      AND v.DATAFATURAMENTO BETWEEN TO_CHAR(:dtInicio, 'YYYYMMDD')
                                AND TO_CHAR(:dtFim, 'YYYYMMDD')
      AND r.SITUACAO = 'ATIVO'
    GROUP BY r.CODIGORCA, r.RCA, r.SUPERVISOR, r.GERENTE
    HAVING COUNT(DISTINCT v.CODIGOCLIENTE) > 0
    ORDER BY POSITIVACAO DESC

**Variações:**
- Apenas time de um gerente: AND r.CODIGOGERENTE = :codGerente
- Comparar com mês anterior: query duplicada com UNION ALL e label de período

**Latência esperada:** 2-5s

---

## Templates a criar (backlog)

Conforme avançarmos, adicionar templates para:

- [ ] **T108** — Tendência vs Meta do mês corrente (projeção fim do mês)
- [ ] **T109** — Curva ABC de clientes (top 20% que fazem 80% do faturamento)
- [ ] **T110** — Faturamento por Linha/Família de Produto
- [ ] **T111** — Margem por produto (Real - Custo) — depende de validar custo
- [ ] **T112** — Devoluções no período (% vs faturamento bruto)
- [ ] **T113** — Pedidos em aberto (POSICAO L/M) para projeção Real+Ped
- [ ] **T114** — Comparativo mensal (12 meses) por filial
- [ ] **T115** — Análise de Bonificação (CONDVENDA 5,6)
- [ ] **T116** — Clientes novos cadastrados no período
- [ ] **T117** — Faturamento Regional (com IN de CODFILIAIS)
- [ ] **T118** — Carteira do RCA — clientes que NÃO compraram no período
- [ ] **T119** — Análise de Mix (produtos distintos por cliente)
- [ ] **T120** — DRE consolidado da filial (usar GD_FATO_DRE_*)

---

## Notas de implementação

### Quando o agente DEVE usar template vs gerar SQL

1. **Sempre** consultar este arquivo primeiro
2. Se houver template que cobre 80%+ do pedido → adaptar
3. Se nenhum template cobre → gerar SQL novo, validar via SQL Guard, e
   **propor adicionar como template** se útil
4. **Nunca** copiar SQL antigo sem entender — Oracle Winthor tem nuances

### Por que TODOS os templates usam views GD_*

- **Performance:** views já têm joins otimizados
- **Manutenção:** se a regra de negócio mudar, muda na view (não no agente)
- **Confiabilidade:** views já aplicam exclusões corretas (CONDVENDA, códigos
  de cobrança especiais, etc) — agente não precisa replicar
- **Segurança:** views podem ter controle de acesso por coluna (futuro
  usuário de produção)

### Validação pendente

Os templates desta versão são **rascunhos sólidos baseados nas definições
das views**, mas ainda **não foram executados no Oracle real**. Próxima
sessão: rodar T100 e T103 (mais simples) com filial 01 (MATRIZ) pra validar
sintaxe e latência. Conforme validados, marcar com "✅ Validado em
YYYY-MM-DD" no cabeçalho do template.

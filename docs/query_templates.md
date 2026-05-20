# Query Templates EBD.ia — v2 consolidado (20/05/2026)

Catálogo de queries validadas centavo-a-centavo contra ERP/BI Winthor da EBD.

## Convenções universais

- **Período "mês corrente"** = `BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE` (até ESTE SEGUNDO, nunca até ontem)
- **Faturamento Bruto** = `EBD.GD_FATO_VENDAFATURAMENTO.VALORTOTAL` (já filtra cancelamento/bonificação internamente)
- **Venda Líquida Oficial EBD** = `VIEW_VENDAS_RESUMO_FATURAMENTO` + `CONDVENDA=1` menos devoluções (2 views UNION)
- **Meta de fornecedor** = `PCMETA TIPOMETA='F' AND CODIGO = CODFORNECPRINC` (NÃO CODFORNEC qualquer)
- **Alias mínimo 2 letras** descritivos (vf, dr, fp...) — alias `v` quebra com PLS-306
- **PCFILIAL** apenas com `CODIGO + FANTASIA` (UF/Cidade não usado; SELECT * quebra serializer)
- **Cache Redis 5-10min** obrigatório em produção pra queries com VENDAFATURAMENTO

---

# Parte 1 — Templates Single-Filial (T100-T107)

Todos rodam contra UMA filial via `:codFilial`. Validados em filial 06 (Manaus).

## T100 — Faturamento Bruto Filial (✅ ERP centavo)

```sql
-- Faturamento Bruto consolidado da filial no periodo
SELECT
    :codFilial                                   AS CODFILIAL,
    SUM(vf.VALORTOTAL)                           AS FATURAMENTO_BRUTO,
    COUNT(DISTINCT vf.NUMEROTRANSVENDA)          AS QTD_NOTAS,
    COUNT(DISTINCT vf.CODIGOCLIENTE)             AS QTD_CLIENTES,
    COUNT(DISTINCT vf.CODIGOPRODUTO)             AS QTD_SKUS
FROM EBD.GD_FATO_VENDAFATURAMENTO vf
WHERE vf.CODIGOFILIAL = :codFilial
  AND vf.DATAFATURAMENTO BETWEEN TO_CHAR(:dtInicio,'YYYYMMDD')
                            AND TO_CHAR(:dtFim,'YYYYMMDD')
```

**Validado:** filial 06, 01-19/05/2026: MCP R$ 11.444.947,76 = ERP Winthor R$ 11.444.947,76 (centavo). Latência: 13s warm.

---

## T101 v2 — Top N Fornecedores Filial (✅ via fórmula universal)

```sql
WITH fornec_principal AS (
    SELECT CODFORNEC, NVL(CODFORNECPRINC, CODFORNEC) AS COD_RAIZ
    FROM EBD.PCFORNEC
),
real_forn AS (
    SELECT fp.COD_RAIZ, SUM(v.VLATEND) AS REAL_FATURADO
    FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
    JOIN EBD.PCPRODUT p  ON p.CODPROD  = v.CODPROD
    JOIN fornec_principal fp ON fp.CODFORNEC = p.CODFORNEC
    WHERE v.DTSAIDA BETWEEN :dtInicio AND :dtFim
      AND v.CONDVENDA = 1
      AND v.CODFILIAL = :codFilial
    GROUP BY fp.COD_RAIZ
),
dev_vinc AS (
    SELECT fp.COD_RAIZ, SUM(d.VLDEVOLUCAO) AS DEV
    FROM EBD.VIEW_DEVOL_RESUMO_FATURAMENTO d
    JOIN EBD.PCPRODUT p  ON p.CODPROD  = d.CODPROD
    JOIN fornec_principal fp ON fp.CODFORNEC = p.CODFORNEC
    WHERE d.DTENT BETWEEN :dtInicio AND :dtFim
      AND d.CONDVENDA = 1
      AND d.CODFILIAL = :codFilial
    GROUP BY fp.COD_RAIZ
),
dev_avul AS (
    SELECT fp.COD_RAIZ, SUM(d.VLDEVOLUCAO) AS DEV
    FROM EBD.VIEW_DEVOL_RESUMO_FATURAVULSA d
    JOIN EBD.PCPRODUT p  ON p.CODPROD  = d.CODPROD
    JOIN fornec_principal fp ON fp.CODFORNEC = p.CODFORNEC
    WHERE d.DTENT BETWEEN :dtInicio AND :dtFim
      AND d.CODFILIAL = :codFilial
    GROUP BY fp.COD_RAIZ
),
meta_forn AS (
    SELECT CODIGO AS COD_RAIZ, SUM(VLVENDAPREV) AS META
    FROM EBD.PCMETA
    WHERE TIPOMETA = 'F'
      AND TRUNC(DATA,'MM') = TRUNC(SYSDATE,'MM')
      AND CODFILIAL = :codFilial
    GROUP BY CODIGO
)
SELECT
    rf.COD_RAIZ,
    SUBSTR(NVL(f.FORNECEDOR,'?'),1,32)  AS FORNECEDOR,
    rf.REAL_FATURADO,
    NVL(dv.DEV,0) + NVL(da.DEV,0)        AS DEV_TOTAL,
    rf.REAL_FATURADO - NVL(dv.DEV,0) - NVL(da.DEV,0)   AS REAL_LIQUIDO,
    NVL(m.META,0)                        AS META,
    CASE WHEN NVL(m.META,0) > 0
         THEN ROUND((rf.REAL_FATURADO - NVL(dv.DEV,0) - NVL(da.DEV,0))/m.META*100,2)
         ELSE NULL END                   AS PCT_META
FROM real_forn rf
LEFT JOIN dev_vinc dv ON dv.COD_RAIZ = rf.COD_RAIZ
LEFT JOIN dev_avul da ON da.COD_RAIZ = rf.COD_RAIZ
LEFT JOIN EBD.PCFORNEC f ON f.CODFORNEC = rf.COD_RAIZ
LEFT JOIN meta_forn m ON m.COD_RAIZ = rf.COD_RAIZ
ORDER BY REAL_LIQUIDO DESC NULLS LAST
FETCH FIRST :topN ROWS ONLY
```

**Validado:** filial 06, mês corrente até agora. Kraft Heinz #1 Manaus 71,7% meta. Latência: 1,3s warm.

---

## T102 — Faturamento por Ramo de Atividade

```sql
SELECT
    SUBSTR(NVL(dc.RAMOATIVIDADE,'(sem ramo)'),1,30) AS RAMO,
    COUNT(DISTINCT vf.CODIGOCLIENTE)                AS QTD_CLIENTES,
    SUM(vf.VALORTOTAL)                              AS FATURAMENTO
FROM EBD.GD_FATO_VENDAFATURAMENTO vf
JOIN EBD.GD_DIM_CLIENTE dc ON dc.CODIGOCLIENTE = vf.CODIGOCLIENTE
WHERE vf.CODIGOFILIAL = :codFilial
  AND vf.DATAFATURAMENTO BETWEEN TO_CHAR(:dtInicio,'YYYYMMDD')
                            AND TO_CHAR(:dtFim,'YYYYMMDD')
GROUP BY dc.RAMOATIVIDADE
ORDER BY FATURAMENTO DESC NULLS LAST
FETCH FIRST :topN ROWS ONLY
```

**Validado:** top 15 ramos concentram 89,9% filial 06.

---

## T103 — Top N RCAs Filial (validado vs ERP)

```sql
SELECT
    vf.CODIGORCA,
    SUBSTR(NVL(dr.RCA,'?'),1,32)    AS RCA,
    SUBSTR(NVL(dr.SUPERVISOR,'-'),1,25) AS SUPERVISOR,
    SUM(vf.VALORTOTAL)                AS REAL,
    COUNT(DISTINCT vf.CODIGOCLIENTE)  AS POSITIVACAO,
    COUNT(DISTINCT vf.NUMEROPEDIDO)   AS PEDIDOS
FROM EBD.GD_FATO_VENDAFATURAMENTO vf
JOIN EBD.GD_DIM_RCA dr ON dr.CODIGORCA = vf.CODIGORCA
WHERE vf.CODIGOFILIAL = :codFilial
  AND vf.DATAFATURAMENTO BETWEEN TO_CHAR(:dtInicio,'YYYYMMDD')
                            AND TO_CHAR(:dtFim,'YYYYMMDD')
GROUP BY vf.CODIGORCA, dr.RCA, dr.SUPERVISOR
ORDER BY REAL DESC NULLS LAST
FETCH FIRST :topN ROWS ONLY
```

**Validado:** Michelly Keytiane #1 Manaus R$ 2.130.804 = ERP centavo.

---

## T104 — Inadimplência por Filial (rápido)

```sql
SELECT
    :codFilial                                                  AS CODFILIAL,
    COUNT(*)                                                    AS QTD_TITULOS,
    COUNT(DISTINCT CODIGOCLIENTE)                               AS QTD_CLIENTES,
    SUM(VALORTITULO)                                            AS CARTEIRA_ABERTA,
    SUM(CASE WHEN INADIMPLENCIA = 1 THEN VALORTITULO ELSE 0 END) AS VALOR_INAD,
    ROUND(SUM(CASE WHEN INADIMPLENCIA=1 THEN VALORTITULO ELSE 0 END)
          / NULLIF(SUM(VALORTITULO),0) * 100, 2)                AS PCT_INAD
FROM EBD.GD_FATO_CONTASRECEBER
WHERE CODIGOFILIAL = :codFilial
  AND DATAPAGAMENTO IS NULL
```

**Validado:** Manaus 9,3% inadimplência sobre R$ 21M carteira. Latência: 3,6s.

---

## T105 — Estoque + Cobertura por Produto

```sql
SELECT
    dp.CODIGOPRODUTO,
    SUBSTR(dp.PRODUTO,1,40)        AS PRODUTO,
    SUBSTR(dp.FORNECEDOR,1,25)     AS FORNECEDOR,
    ea.QUANTIDADELIVRE             AS ESTOQUE,
    ea.VALORCMC                    AS VALORCMC_UNIT,
    ea.QUANTIDADELIVRE * ea.VALORCMC AS VALOR_ESTOQUE,
    -- Cobertura em dias (estoque / venda media diaria)
    ROUND(ea.QUANTIDADELIVRE / NULLIF(
        (SELECT SUM(vf.QUANTIDADE)
         FROM EBD.GD_FATO_VENDAFATURAMENTO vf
         WHERE vf.CODIGOPRODUTO = dp.CODIGOPRODUTO
           AND vf.CODIGOFILIAL = ea.CODIGOFILIAL
           AND vf.DATAFATURAMENTO BETWEEN
               TO_CHAR(SYSDATE-30,'YYYYMMDD')
               AND TO_CHAR(SYSDATE,'YYYYMMDD')) / 30, 0), 0) AS DIAS_COBERTURA
FROM EBD.GD_FATO_ESTOQUEATUAL ea
JOIN EBD.GD_DIM_PRODUTO dp ON dp.CODIGOPRODUTO = ea.CODIGOPRODUTO
WHERE ea.CODIGOFILIAL = :codFilial
  AND ea.QUANTIDADELIVRE > 0
ORDER BY VALOR_ESTOQUE DESC NULLS LAST
FETCH FIRST :topN ROWS ONLY
```

**Validado:** Nissin Lamen top em Manaus. Latência: 0,6s.

---

## T106 — Clientes Ativos por Filial

```sql
SELECT
    dc.SITUACAO,
    COUNT(*) AS QTD_CLIENTES,
    SUM(vf.VALORTOTAL) AS FATURAMENTO_MES
FROM EBD.GD_DIM_CLIENTE dc
LEFT JOIN EBD.GD_FATO_VENDAFATURAMENTO vf
    ON vf.CODIGOCLIENTE = dc.CODIGOCLIENTE
   AND vf.CODIGOFILIAL = :codFilial
   AND vf.DATAFATURAMENTO BETWEEN TO_CHAR(TRUNC(SYSDATE,'MM'),'YYYYMMDD')
                              AND TO_CHAR(SYSDATE,'YYYYMMDD')
WHERE dc.CODIGOFILIAL = :codFilial
GROUP BY dc.SITUACAO
ORDER BY QTD_CLIENTES DESC
```

**Validado:** 1.970 clientes ativos filial 06.

---

## T107 — Positivação por RCA

```sql
SELECT
    vf.CODIGORCA,
    SUBSTR(NVL(dr.RCA,'?'),1,32)             AS RCA,
    COUNT(DISTINCT vf.CODIGOCLIENTE)         AS POSITIVACAO,
    COUNT(DISTINCT vf.NUMEROPEDIDO)          AS PEDIDOS,
    SUM(vf.VALORTOTAL)                       AS REAL
FROM EBD.GD_FATO_VENDAFATURAMENTO vf
JOIN EBD.GD_DIM_RCA dr ON dr.CODIGORCA = vf.CODIGORCA
WHERE vf.CODIGOFILIAL = :codFilial
  AND vf.DATAFATURAMENTO BETWEEN TO_CHAR(:dtInicio,'YYYYMMDD')
                            AND TO_CHAR(:dtFim,'YYYYMMDD')
GROUP BY vf.CODIGORCA, dr.RCA
ORDER BY POSITIVACAO DESC NULLS LAST
FETCH FIRST :topN ROWS ONLY
```

**Validado:** Rosangela #1 positivação Manaus (139 clientes/260 pedidos).

---

# Parte 2 — Templates Executivos BR (T200-T209)

Visão consolidada Brasil. Todos com filtro **até este segundo** (`<= SYSDATE`).

## ★ Bloco Líquido Oficial EBD (reutilizado em vários templates)

```sql
-- "Venda Liquida EBD" - formula oficial validada centavo
WITH faturamento AS (
    SELECT CODFILIAL, SUM(VLATEND) AS BRUTO
    FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO
    WHERE DTSAIDA BETWEEN :dtInicio AND :dtFim
      AND CONDVENDA = 1
    GROUP BY CODFILIAL
),
dev_vinc AS (
    SELECT CODFILIAL, SUM(VLDEVOLUCAO) AS DEV
    FROM EBD.VIEW_DEVOL_RESUMO_FATURAMENTO
    WHERE DTENT BETWEEN :dtInicio AND :dtFim
      AND CONDVENDA = 1
    GROUP BY CODFILIAL
),
dev_avul AS (
    SELECT CODFILIAL, SUM(VLDEVOLUCAO) AS DEV
    FROM EBD.VIEW_DEVOL_RESUMO_FATURAVULSA
    WHERE DTENT BETWEEN :dtInicio AND :dtFim
    GROUP BY CODFILIAL
)
SELECT
    fa.CODFILIAL,
    fa.BRUTO,
    NVL(dv.DEV,0) + NVL(da.DEV,0)               AS DEV_TOTAL,
    fa.BRUTO - NVL(dv.DEV,0) - NVL(da.DEV,0)    AS LIQUIDO
FROM faturamento fa
LEFT JOIN dev_vinc dv ON dv.CODFILIAL = fa.CODFILIAL
LEFT JOIN dev_avul da ON da.CODFILIAL = fa.CODFILIAL
```

**Validado:** filial 06, 01-19/05/2026: MCP R$ 9.412.716,30 = BI EBD R$ 9.412.716,30 (centavo). Latência: 1,4s.

---

## T200 — Faturamento Brasil consolidado

Reusa bloco líquido oficial; SOMA todas filiais; junta meta nacional (`TIPOMETA='FL'`).

```sql
WITH liq_por_filial AS (
    -- bloco líquido oficial (sem WHERE CODFILIAL)
    -- ... (ver bloco acima) ...
)
SELECT
    SUM(BRUTO)       AS FATURADO_BR,
    SUM(DEV_TOTAL)   AS DEVOLUCAO_BR,
    SUM(LIQUIDO)     AS LIQUIDO_BR,
    (SELECT SUM(VLVENDAPREV) FROM EBD.PCMETA
     WHERE TIPOMETA='FL' AND TRUNC(DATA,'MM')=TRUNC(SYSDATE,'MM')) AS META_BR
FROM liq_por_filial
```

**Validado:** R$ 120.699.647 líquido / 36,23% meta R$ 333.173.015 (até 20/05 16:31). Latência: 24,6s.

---

## T201 — Top 10 Filiais BR

Bloco líquido + JOIN PCFILIAL pra fantasia + meta `TIPOMETA='FL'` por filial.

**Validado:** EBD DUQUE #1 R$ 15,1M / 33,3% meta. Soma top 10 ≈ R$ 91,6M (76% do BR).

---

## T202 — Top Regionais BR

Mapping regional **hardcoded** (validado vs `CLASSIFICACAO` defasada):
01→NO2 | 02→SP1 | 03→NE2 | 04→NE1 | 05→RJ2 | 06→NO1 | 07→NO2 | 08→NO1
09→NE2 | 10→RJ1 | 11→NO1 | 12→NE1 | 13→RJ1 | 14→RJ2 | 15→SP2 | 16→SP1
18→SP2 | 21→NE2 | 52→NE3 | 53→NE3

**Validado:** RJ1 #1 R$ 23M (São Gonçalo + Taquara).

---

## T203 — Top GCs (Gerentes Comerciais) BR

```sql
WITH vendas_gc AS (
    SELECT dr.CODIGOGERENTE, MAX(dr.GERENTE) AS GERENTE,
           SUM(vf.VALORTOTAL) AS REAL
    FROM EBD.GD_FATO_VENDAFATURAMENTO vf
    JOIN EBD.GD_DIM_RCA dr ON vf.CODIGORCA = dr.CODIGORCA
    WHERE vf.DATAFATURAMENTO BETWEEN TO_CHAR(TRUNC(SYSDATE,'MM'),'YYYYMMDD')
                                 AND TO_CHAR(SYSDATE,'YYYYMMDD')
      AND dr.CODIGOGERENTE IS NOT NULL
    GROUP BY dr.CODIGOGERENTE
),
meta_gc AS (
    SELECT CODIGO AS CODIGOGERENTE, SUM(VLVENDAPREV) AS META
    FROM EBD.PCMETA
    WHERE TIPOMETA='GC' AND TRUNC(DATA,'MM')=TRUNC(SYSDATE,'MM')
    GROUP BY CODIGO
)
SELECT vg.CODIGOGERENTE, SUBSTR(vg.GERENTE,1,35) AS GERENTE,
       vg.REAL, NVL(mg.META,0) AS META,
       ROUND(vg.REAL/NULLIF(mg.META,0)*100,2) AS PCT_META
FROM vendas_gc vg LEFT JOIN meta_gc mg ON mg.CODIGOGERENTE=vg.CODIGOGERENTE
ORDER BY vg.REAL DESC NULLS LAST FETCH FIRST 10 ROWS ONLY
```

**Validado:** Marcus Vinicius #1 R$ 15,5M / 40,6% meta.

---

## T204 — Top Supervisores BR

Mesma estrutura T203 com `TIPOMETA='SV'` e `CODIGOSUPERVISOR`.

**Validado:** Itamar Pinho #1 R$ 5,19M. Pedro Raesky 113,8% meta (stourou).

---

## T205 — Top RCAs BR

Sem meta de RCA por enquanto (pendente validar `TIPOMETA='R'`).

```sql
SELECT vf.CODIGORCA, SUBSTR(dr.RCA,1,35) AS NOME_RCA,
       SUBSTR(dr.SUPERVISOR,1,25) AS SUPERVISOR,
       SUM(vf.VALORTOTAL) AS REAL,
       COUNT(DISTINCT vf.CODIGOCLIENTE) AS POSITIVACAO,
       COUNT(DISTINCT vf.NUMEROPEDIDO) AS PEDIDOS
FROM EBD.GD_FATO_VENDAFATURAMENTO vf
JOIN EBD.GD_DIM_RCA dr ON dr.CODIGORCA = vf.CODIGORCA
WHERE vf.DATAFATURAMENTO BETWEEN TO_CHAR(TRUNC(SYSDATE,'MM'),'YYYYMMDD')
                             AND TO_CHAR(SYSDATE,'YYYYMMDD')
GROUP BY vf.CODIGORCA, dr.RCA, dr.SUPERVISOR
ORDER BY REAL DESC NULLS LAST FETCH FIRST 10 ROWS ONLY
```

**Validado:** Michelly Keytiane #1 BR (também #1 Manaus — bate cruzado).

---

## T206 v2 — Top Fornecedores BR (✅ Pandurata bate BI)

**Versão FINAL** após descoberta do CODFORNECPRINC. Estrutura idêntica ao T101 v2 sem o filtro de filial. Validado 20/05: Pandurata 47,8% meta = exatamente o BI.

```sql
-- Identica ao T101 v2, SEM "AND v.CODFILIAL = :codFilial"
-- e SEM "AND CODFILIAL = :codFilial" na meta_forn
-- (ver T101 v2 acima como template-base)
```

**Validado:** Nissin #1 R$ 16,5M / 31,2% meta. Top 10 = 74% do BR.

---

## T207 — Top Clientes BR

```sql
WITH vendas_cli AS (
    SELECT vf.CODIGOCLIENTE,
           SUM(vf.VALORTOTAL) AS REAL,
           COUNT(DISTINCT vf.NUMEROTRANSVENDA) AS QTD_NOTAS,
           COUNT(DISTINCT vf.CODIGOFILIAL) AS QTD_FILIAIS
    FROM EBD.GD_FATO_VENDAFATURAMENTO vf
    WHERE vf.DATAFATURAMENTO BETWEEN TO_CHAR(TRUNC(SYSDATE,'MM'),'YYYYMMDD')
                                 AND TO_CHAR(SYSDATE,'YYYYMMDD')
    GROUP BY vf.CODIGOCLIENTE
)
SELECT vc.CODIGOCLIENTE, SUBSTR(NVL(dc.CLIENTE,'?'),1,40) AS CLIENTE,
       SUBSTR(NVL(dc.RAMOATIVIDADE,'-'),1,25) AS RAMO,
       NVL(dc.CIDADE,'-') AS CIDADE, NVL(dc.UF,'?') AS UF,
       vc.QTD_NOTAS, vc.QTD_FILIAIS, vc.REAL
FROM vendas_cli vc
LEFT JOIN EBD.GD_DIM_CLIENTE dc ON dc.CODIGOCLIENTE = vc.CODIGOCLIENTE
ORDER BY vc.REAL DESC NULLS LAST FETCH FIRST 10 ROWS ONLY
```

**Validado:** SERVI SUPERMERCADOS #1 R$ 1,63M. Top 10 = 7% BR (atacado MUITO pulverizado).

---

## T208 — Inadimplência BR (Top 10 Filiais)

```sql
WITH inad_filial AS (
    SELECT CODIGOFILIAL,
           COUNT(*) AS QTD_TITULOS,
           COUNT(DISTINCT CODIGOCLIENTE) AS QTD_CLIENTES,
           SUM(VALORTITULO) AS CARTEIRA_ABERTA,
           SUM(CASE WHEN INADIMPLENCIA=1 THEN VALORTITULO ELSE 0 END) AS INAD
    FROM EBD.GD_FATO_CONTASRECEBER
    WHERE DATAPAGAMENTO IS NULL
    GROUP BY CODIGOFILIAL
)
SELECT ip.CODIGOFILIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,28) AS FILIAL,
       ip.QTD_TITULOS, ip.QTD_CLIENTES,
       ip.CARTEIRA_ABERTA, ip.INAD,
       ROUND(ip.INAD / NULLIF(ip.CARTEIRA_ABERTA,0) * 100, 2) AS PCT_INAD
FROM inad_filial ip
LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = ip.CODIGOFILIAL
ORDER BY ip.INAD DESC NULLS LAST FETCH FIRST 10 ROWS ONLY
```

**Validado:** EBD FORTALEZA #1 R$ 6,8M (26,6%!) — alerta crítico. Boa Vista 25,4%.

---

## T209 — Top Produtos BR

```sql
WITH dim_prod_dedup AS (
    SELECT CODIGOPRODUTO, MAX(PRODUTO) AS PRODUTO, MAX(FORNECEDOR) AS FORNECEDOR
    FROM EBD.GD_DIM_PRODUTO GROUP BY CODIGOPRODUTO
),
vendas_prod AS (
    SELECT vf.CODIGOPRODUTO, SUM(vf.VALORTOTAL) AS REAL,
           SUM(vf.QUANTIDADE) AS QTD,
           COUNT(DISTINCT vf.CODIGOFILIAL) AS QTD_FILIAIS,
           COUNT(DISTINCT vf.CODIGOCLIENTE) AS QTD_CLIENTES
    FROM EBD.GD_FATO_VENDAFATURAMENTO vf
    WHERE vf.DATAFATURAMENTO BETWEEN TO_CHAR(TRUNC(SYSDATE,'MM'),'YYYYMMDD')
                                 AND TO_CHAR(SYSDATE,'YYYYMMDD')
    GROUP BY vf.CODIGOPRODUTO
)
SELECT vp.CODIGOPRODUTO, SUBSTR(NVL(dp.PRODUTO,'?'),1,40) AS PRODUTO,
       SUBSTR(NVL(dp.FORNECEDOR,'?'),1,25) AS FORNECEDOR,
       vp.QTD, vp.REAL, vp.QTD_FILIAIS, vp.QTD_CLIENTES
FROM vendas_prod vp
LEFT JOIN dim_prod_dedup dp ON dp.CODIGOPRODUTO = vp.CODIGOPRODUTO
ORDER BY vp.REAL DESC NULLS LAST FETCH FIRST 10 ROWS ONLY
```

**Validado:** NISSIN LAMEN GALINHA 85GR #1 R$ 4,8M (4.830 clientes BR).

---

# Parte 3 — Pendências (Templates planejados, não validados ainda)

## Validação pendente

- [ ] TIPOMETA='R' (meta de RCA individual via `PCMETA WHERE TIPOMETA='R' AND CODIGO=CODUSUR`)
- [ ] PCPEDC.POSICAO — mapear estados (liberado/preso financeiro/preso comercial/digitação)

## Templates a desenhar

| ID | Pergunta | Quem usa |
|---|---|---|
| T110 | Pedidos abertos por filial | Diretor, GN |
| T111 | Top 10 pedidos travados financeiro | Diretor, Financeiro |
| T112 | Top 10 pedidos travados comercial | Gerente, Supervisor |
| T113 | Top 10 RCAs com pipeline | Supervisor, Gerente |
| T114 | Top 10 clientes com pedido aberto | Comercial |
| T210 | Real + Pedido por filial BR | Diretor |
| T211 | Real + Pedido por fornecedor BR | Comercial Nacional |
| T212 | Top 10 pedidos travados nacional | Diretor |


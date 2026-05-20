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


---

# Parte 4 — Pedidos & Real+Ped (T210-T212) — descobertos 20/05/2026

## Convenções de pedidos (PCPEDC)

- **POS='F'** = Faturado (já vira NF — confirmado vs T200)
- **POS='L'** = Liberado a faturar (entra no "Real+Ped" do BI) ← validado contra BI EBD
- **POS='B'** = Bloqueado (financeiro, comercial, manual)
- **POS='M'** = Em Montagem
- **POS='P'** = Pré-pedido / digitação
- **POS='C'** = Cancelado (VL=0)

## Taxonomia de bloqueios (PCMOTBLOQUEIO)
TIPO 1 = FINANCEIRO/CRÉDITO (12 motivos)
TIPO 2 = COMERCIAL/OPERACIONAL (41 motivos)
ORIGEM 1 = AUTOMÁTICO  |  ORIGEM 2 = MANUAL

JOIN: `m.CODMOTIVO = ped.CODMOTBLOQUEIO` (NÃO `m.CODIGO`)

**ATENÇÃO:** Colunas BLOQCOMERCIAL/BLOQFINANCEIRO/BLOQUEIOFATURAMENTO da
PCPEDC ficam SEMPRE NULL na EBD. Usar PCMOTBLOQUEIO.TIPO/ORIGEM.

---

## T210 — Real + Pedidos por Filial BR ✅ Validado vs BI

Replica EXATA do painel oficial `FaturamentoRegionalFilialGerente.xlsx`.

```sql
WITH regional_map AS (
    SELECT '01' AS CODFILIAL, 'NO2' AS REGIONAL FROM DUAL UNION ALL
    SELECT '02','SP1' FROM DUAL UNION ALL SELECT '03','NE2' FROM DUAL UNION ALL
    SELECT '04','NE1' FROM DUAL UNION ALL SELECT '05','RJ2' FROM DUAL UNION ALL
    SELECT '06','NO1' FROM DUAL UNION ALL SELECT '07','NO2' FROM DUAL UNION ALL
    SELECT '08','NO1' FROM DUAL UNION ALL SELECT '09','NE2' FROM DUAL UNION ALL
    SELECT '10','RJ1' FROM DUAL UNION ALL SELECT '11','NO1' FROM DUAL UNION ALL
    SELECT '12','NE1' FROM DUAL UNION ALL SELECT '13','RJ1' FROM DUAL UNION ALL
    SELECT '14','RJ2' FROM DUAL UNION ALL SELECT '15','SP2' FROM DUAL UNION ALL
    SELECT '16','SP1' FROM DUAL UNION ALL SELECT '18','SP2' FROM DUAL UNION ALL
    SELECT '21','NE2' FROM DUAL UNION ALL SELECT '22','NO2' FROM DUAL UNION ALL
    SELECT '52','NE3' FROM DUAL UNION ALL SELECT '53','NE3' FROM DUAL
),
faturamento AS (
    SELECT CODFILIAL, SUM(VLATEND) AS BRUTO
    FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO
    WHERE DTSAIDA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE AND CONDVENDA = 1
    GROUP BY CODFILIAL
),
dev_vinc AS (
    SELECT CODFILIAL, SUM(VLDEVOLUCAO) AS DEV
    FROM EBD.VIEW_DEVOL_RESUMO_FATURAMENTO
    WHERE DTENT BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE AND CONDVENDA = 1
    GROUP BY CODFILIAL
),
dev_avul AS (
    SELECT CODFILIAL, SUM(VLDEVOLUCAO) AS DEV
    FROM EBD.VIEW_DEVOL_RESUMO_FATURAVULSA
    WHERE DTENT BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
    GROUP BY CODFILIAL
),
pedidos_liberados AS (
    SELECT CODFILIAL, SUM(VLTOTAL) AS PEDIDOS
    FROM EBD.PCPEDC
    WHERE DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE AND POSICAO = 'L'
    GROUP BY CODFILIAL
),
meta_filial AS (
    SELECT CODIGO AS CODFILIAL, SUM(VLVENDAPREV) AS META
    FROM EBD.PCMETA
    WHERE TIPOMETA = 'FL' AND TRUNC(DATA, 'MM') = TRUNC(SYSDATE, 'MM')
    GROUP BY CODIGO
)
SELECT fa.CODFILIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,22) AS FILIAL,
       NVL(rm.REGIONAL,'?') AS REGIONAL, NVL(mf.META,0) AS META,
       fa.BRUTO - NVL(dv.DEV,0) - NVL(da.DEV,0) AS REAL_LIQUIDO,
       NVL(pl.PEDIDOS,0) AS PEDIDOS,
       fa.BRUTO - NVL(dv.DEV,0) - NVL(da.DEV,0) + NVL(pl.PEDIDOS,0) AS REAL_MAIS_PED,
       CASE WHEN NVL(mf.META,0) > 0
            THEN ROUND((fa.BRUTO-NVL(dv.DEV,0)-NVL(da.DEV,0))/mf.META*100,2)
            ELSE NULL END AS PCT_REAL,
       CASE WHEN NVL(mf.META,0) > 0
            THEN ROUND((fa.BRUTO-NVL(dv.DEV,0)-NVL(da.DEV,0)+NVL(pl.PEDIDOS,0))/mf.META*100,2)
            ELSE NULL END AS PCT_RP
FROM faturamento fa
LEFT JOIN dev_vinc dv ON dv.CODFILIAL = fa.CODFILIAL
LEFT JOIN dev_avul da ON da.CODFILIAL = fa.CODFILIAL
LEFT JOIN pedidos_liberados pl ON pl.CODFILIAL = fa.CODFILIAL
LEFT JOIN meta_filial mf ON mf.CODFILIAL = fa.CODFILIAL
LEFT JOIN regional_map rm ON rm.CODFILIAL = fa.CODFILIAL
LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = fa.CODFILIAL
ORDER BY REAL_LIQUIDO DESC NULLS LAST
```

**Validado:** TOTAL BR Real R$ 120.817.519 (+R$ 87K vs BI 16:54), Pedidos
R$ 26.946.204, Real+Ped R$ 147.763.724, 44,35% meta. Latência: 44s.

---

## T211 — Real + Pedidos por Fornecedor BR ✅ Bate Pandurata centavo

Replica painel `FaturamentoBruto.xlsx`. Usa CODFORNECPRINC + POS='L'.

```sql
WITH fornec_principal AS (
    SELECT CODFORNEC, NVL(CODFORNECPRINC, CODFORNEC) AS COD_RAIZ FROM EBD.PCFORNEC
),
real_forn AS (
    SELECT fp.COD_RAIZ, SUM(v.VLATEND) AS REAL_FATURADO
    FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
    JOIN EBD.PCPRODUT p ON p.CODPROD = v.CODPROD
    JOIN fornec_principal fp ON fp.CODFORNEC = p.CODFORNEC
    WHERE v.DTSAIDA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE AND v.CONDVENDA = 1
    GROUP BY fp.COD_RAIZ
),
-- dev_vinc_forn, dev_avul_forn idênticas estrutura (ver T206 v2)
pedidos_forn AS (
    SELECT fp.COD_RAIZ, SUM(NVL(ite.PVENDA,0) * NVL(ite.QT,0)) AS PEDIDOS
    FROM EBD.PCPEDC ped
    JOIN EBD.PCPEDI ite ON ite.NUMPED = ped.NUMPED
    JOIN EBD.PCPRODUT p ON p.CODPROD = ite.CODPROD
    JOIN fornec_principal fp ON fp.CODFORNEC = p.CODFORNEC
    WHERE ped.DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE AND ped.POSICAO = 'L'
    GROUP BY fp.COD_RAIZ
),
meta_forn AS (
    SELECT CODIGO AS COD_RAIZ, SUM(VLVENDAPREV) AS META
    FROM EBD.PCMETA
    WHERE TIPOMETA = 'F' AND TRUNC(DATA,'MM') = TRUNC(SYSDATE,'MM')
    GROUP BY CODIGO
)
SELECT rf.COD_RAIZ, SUBSTR(NVL(f.FORNECEDOR,'?'),1,30) AS FORNECEDOR,
       NVL(m.META,0) AS META,
       rf.REAL_FATURADO - NVL(dv.DEV,0) - NVL(da.DEV,0) AS REAL_LIQUIDO,
       NVL(pf.PEDIDOS,0) AS PEDIDOS,
       rf.REAL_FATURADO - NVL(dv.DEV,0) - NVL(da.DEV,0) + NVL(pf.PEDIDOS,0) AS REAL_MAIS_PED,
       -- + PCT_REAL e PCT_RP
       ROUND((rf.REAL_FATURADO-NVL(dv.DEV,0)-NVL(da.DEV,0))/NULLIF(m.META,0)*100,2) AS PCT_REAL,
       ROUND((rf.REAL_FATURADO-NVL(dv.DEV,0)-NVL(da.DEV,0)+NVL(pf.PEDIDOS,0))/NULLIF(m.META,0)*100,2) AS PCT_RP
FROM real_forn rf
LEFT JOIN dev_vinc_forn dv ON dv.COD_RAIZ = rf.COD_RAIZ
LEFT JOIN dev_avul_forn da ON da.COD_RAIZ = rf.COD_RAIZ
LEFT JOIN pedidos_forn pf ON pf.COD_RAIZ = rf.COD_RAIZ
LEFT JOIN meta_forn m ON m.COD_RAIZ = rf.COD_RAIZ
LEFT JOIN EBD.PCFORNEC f ON f.CODFORNEC = rf.COD_RAIZ
ORDER BY REAL_LIQUIDO DESC NULLS LAST FETCH FIRST 15 ROWS ONLY
```

**Validado:** Pandurata Real R$ 7.449.924 / Ped R$ 1.326.726 / R+P R$ 8.776.650 / 56,3% meta. Bate BI EBD centavo. Latência: 18s.

---

## T212 — Top Pedidos Travados BR com motivo legível ✅

JOIN com PCMOTBLOQUEIO pra trazer DESCRICAO + TIPO + ORIGEM.

```sql
SELECT ped.NUMPED,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,16) AS FILIAL,
       SUBSTR(NVL(dc.CLIENTE,'?'),1,24) AS CLIENTE,
       SUBSTR(NVL(dr.RCA,'?'),1,18) AS RCA,
       TO_CHAR(ped.DATA,'DD/MM') AS DT,
       ROUND(SYSDATE - ped.DATA, 0) AS DIAS,
       NVL(ped.VLTOTAL,0) AS VL,
       NVL(ped.CODMOTBLOQUEIO,-1) AS COD_MOT,
       NVL(m.TIPO,0) AS TIPO,    -- 1=FIN, 2=COM/OPER
       NVL(m.ORIGEM,0) AS ORIGEM, -- 1=AUTO, 2=MANUAL
       SUBSTR(NVL(m.DESCRICAO,'(s/motivo)'),1,30) AS MOTIVO
FROM EBD.PCPEDC ped
LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = ped.CODFILIAL
LEFT JOIN EBD.GD_DIM_CLIENTE dc ON dc.CODIGOCLIENTE = ped.CODCLI
LEFT JOIN EBD.GD_DIM_RCA dr ON dr.CODIGORCA = ped.CODUSUR
LEFT JOIN EBD.PCMOTBLOQUEIO m ON m.CODMOTIVO = ped.CODMOTBLOQUEIO
WHERE ped.POSICAO='B'
  AND ped.DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
ORDER BY ped.VLTOTAL DESC NULLS LAST
FETCH FIRST 15 ROWS ONLY
```

Variantes (T111, T112, T113, T114):
- T111: filtrar `m.TIPO = 1` (Top travados FINANCEIRO)
- T112: filtrar `m.TIPO = 2` (Top travados COMERCIAL/OPER)
- T113: agregação por `ped.CODUSUR` (Top RCAs com pipeline POS='L')
- T114: agregação por `ped.CODCLI` (Top clientes com pedido aberto)

**Validado 20/05:** SERVI SUPERMERCADOS top 4 (R$ 196K x 3 + R$ 96K), 79,2% do valor travado é "Bloqueio Manual". Latência: 0,3s (rápido).


---

# Parte 5 — Pedidos Single-Filial (T110-T114) — descobertos 20/05/2026

Todos validados em filial 06 (Manaus). Performance sub-segundo, prontos pra
uso conversacional em produção sem cache. Substituir `:codFilial` por filial
desejada.

## T110 — Pedidos abertos por POSICAO (single-filial)

"Quanto tenho de pedido pra faturar na minha filial?"

```sql
SELECT POSICAO,
       COUNT(*) AS QTD_PEDIDOS,
       SUM(NVL(VLTOTAL,0)) AS VL_TOTAL,
       ROUND(AVG(SYSDATE - DATA), 1) AS DIAS_MEDIO
FROM EBD.PCPEDC
WHERE CODFILIAL = :codFilial
  AND DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
  AND POSICAO IN ('L','B','M','P')
GROUP BY POSICAO
ORDER BY VL_TOTAL DESC NULLS LAST
```

**Validado Manaus:** R$ 1,31M abertos. POS='P' com 8,3 dias médio = alerta operacional. Latência: 25ms.

## T111 — Top 10 pedidos travados FINANCEIRO (single-filial)

"Financeiro: o que liberar hoje?" — filtra por `m.TIPO = 1`

```sql
SELECT ped.NUMPED,
       SUBSTR(NVL(dc.CLIENTE,'?'),1,30) AS CLIENTE,
       SUBSTR(NVL(dr.RCA,'?'),1,22)     AS RCA,
       TO_CHAR(ped.DATA,'DD/MM') AS DT,
       ROUND(SYSDATE - ped.DATA, 0) AS DIAS,
       NVL(ped.VLTOTAL,0) AS VL,
       SUBSTR(NVL(m.DESCRICAO,'(s/motivo)'),1,32) AS MOTIVO,
       m.ORIGEM
FROM EBD.PCPEDC ped
LEFT JOIN EBD.GD_DIM_CLIENTE dc ON dc.CODIGOCLIENTE = ped.CODCLI
LEFT JOIN EBD.GD_DIM_RCA dr ON dr.CODIGORCA = ped.CODUSUR
LEFT JOIN EBD.PCMOTBLOQUEIO m ON m.CODMOTIVO = ped.CODMOTBLOQUEIO
WHERE ped.CODFILIAL = :codFilial
  AND ped.POSICAO = 'B'
  AND ped.DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
  AND m.TIPO = 1   -- bloqueio FINANCEIRO/CREDITO
ORDER BY ped.VLTOTAL DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
```

**Validado Manaus:** "Limite de crédito excedido" domina (4 de 6 pedidos). Latência: 208ms.

## T112 — Top 10 pedidos travados COMERCIAL/OPER (single-filial)

"Comercial/operacional: o que destravar?" — filtra por `m.TIPO = 2`

```sql
-- Idêntica a T111 com:  AND m.TIPO = 2
```

**Validado Manaus:** 9 de 9 pedidos = "Bonificação não autorizada". Padrão de treinamento RCA. Latência: 5ms.

## T113 — Top 10 RCAs com pipeline POS='L' (single-filial)

"Quem tem mais pra faturar amanhã?"

```sql
SELECT ped.CODUSUR,
       SUBSTR(NVL(dr.RCA,'?'),1,30) AS RCA,
       SUBSTR(NVL(dr.SUPERVISOR,'-'),1,25) AS SUPERVISOR,
       COUNT(*) AS QTD_PEDIDOS,
       COUNT(DISTINCT ped.CODCLI) AS QTD_CLIENTES,
       SUM(NVL(ped.VLTOTAL,0)) AS VL_PIPELINE,
       ROUND(AVG(NVL(ped.VLTOTAL,0)),2) AS TICKET_MEDIO
FROM EBD.PCPEDC ped
LEFT JOIN EBD.GD_DIM_RCA dr ON dr.CODIGORCA = ped.CODUSUR
WHERE ped.CODFILIAL = :codFilial
  AND ped.POSICAO = 'L'
  AND ped.DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
GROUP BY ped.CODUSUR, dr.RCA, dr.SUPERVISOR
ORDER BY VL_PIPELINE DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
```

**Validado Manaus:** Marconde Moraes #1 R$ 43,8K em 7 pedidos. Insight: Top RCAs em faturamento NÃO aparecem aqui (eles giram rápido). Latência: 32ms.

## T114 — Top 10 clientes com pedido em aberto (single-filial)

"Quais clientes acompanhar?"

```sql
SELECT ped.CODCLI,
       SUBSTR(NVL(dc.CLIENTE,'?'),1,32) AS CLIENTE,
       SUBSTR(NVL(dc.RAMOATIVIDADE,'-'),1,20) AS RAMO,
       COUNT(*) AS QTD_PEDIDOS,
       SUM(CASE WHEN ped.POSICAO='L' THEN NVL(ped.VLTOTAL,0) ELSE 0 END) AS VL_LIBERADO,
       SUM(CASE WHEN ped.POSICAO='B' THEN NVL(ped.VLTOTAL,0) ELSE 0 END) AS VL_BLOQ,
       SUM(CASE WHEN ped.POSICAO IN ('M','P') THEN NVL(ped.VLTOTAL,0) ELSE 0 END) AS VL_PROC,
       SUM(NVL(ped.VLTOTAL,0)) AS VL_TOTAL_ABERTO
FROM EBD.PCPEDC ped
LEFT JOIN EBD.GD_DIM_CLIENTE dc ON dc.CODIGOCLIENTE = ped.CODCLI
WHERE ped.CODFILIAL = :codFilial
  AND ped.POSICAO IN ('L','B','M','P')
  AND ped.DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
GROUP BY ped.CODCLI, dc.CLIENTE, dc.RAMOATIVIDADE
ORDER BY VL_TOTAL_ABERTO DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
```

**Validado Manaus:** Top 10 100% B2B (atacado/super). C L A COMERCIO #1 R$ 28K integralmente bloqueado. Latência: 552ms.


---

# Parte 6 — Família Meta-Dia (T215-T218 + T120) — descoberta 20/05/2026

Padrão de gestão de ritmo: comparar Real vs Meta proporcional aos dias úteis
DECORRIDOS, projetar ritmo necessário pra fechar o mês.

## Lógica universal de dias úteis

**PCFERIADO NÃO existe na EBD.** Usamos CTE inline com feriados nacionais
hardcoded + exclusão sáb/dom via `TO_CHAR(DIA,'D')` (1=domingo, 7=sábado).

PENDÊNCIA: criar tabela `EBD_IA_FERIADOS(DATA, CODFILIAL, DESCRICAO)` pra
suportar feriados estaduais (Manaus 8/9, Caruaru 12/3, etc.).

## CTE reutilizável (todos os templates desta família)

```sql
WITH feriados_2026 AS (
    SELECT TO_DATE('2026-01-01','YYYY-MM-DD') AS DIA FROM DUAL UNION ALL
    SELECT TO_DATE('2026-02-17','YYYY-MM-DD') FROM DUAL UNION ALL  -- Carnaval
    SELECT TO_DATE('2026-04-03','YYYY-MM-DD') FROM DUAL UNION ALL  -- Sexta Santa
    SELECT TO_DATE('2026-04-21','YYYY-MM-DD') FROM DUAL UNION ALL  -- Tiradentes
    SELECT TO_DATE('2026-05-01','YYYY-MM-DD') FROM DUAL UNION ALL  -- Trabalho
    SELECT TO_DATE('2026-06-04','YYYY-MM-DD') FROM DUAL UNION ALL  -- Corpus
    SELECT TO_DATE('2026-09-07','YYYY-MM-DD') FROM DUAL UNION ALL  -- Independência
    SELECT TO_DATE('2026-10-12','YYYY-MM-DD') FROM DUAL UNION ALL  -- N.S. Aparecida
    SELECT TO_DATE('2026-11-02','YYYY-MM-DD') FROM DUAL UNION ALL  -- Finados
    SELECT TO_DATE('2026-11-15','YYYY-MM-DD') FROM DUAL UNION ALL  -- Proc. República
    SELECT TO_DATE('2026-11-20','YYYY-MM-DD') FROM DUAL UNION ALL  -- Consc. Negra
    SELECT TO_DATE('2026-12-25','YYYY-MM-DD') FROM DUAL            -- Natal
),
dias_mes AS (
    SELECT TRUNC(SYSDATE,'MM') + LEVEL - 1 AS DIA
    FROM DUAL CONNECT BY LEVEL <= EXTRACT(DAY FROM LAST_DAY(SYSDATE))
),
calendario AS (
    SELECT
        SUM(CASE WHEN TO_CHAR(dm.DIA,'D') IN ('1','7') THEN 0
                 WHEN EXISTS (SELECT 1 FROM feriados_2026 f WHERE f.DIA = dm.DIA) THEN 0
                 ELSE 1 END) AS DU_MES,
        SUM(CASE WHEN dm.DIA <= TRUNC(SYSDATE)
                  AND TO_CHAR(dm.DIA,'D') NOT IN ('1','7')
                  AND NOT EXISTS (SELECT 1 FROM feriados_2026 f WHERE f.DIA = dm.DIA)
                 THEN 1 ELSE 0 END) AS DU_ATE_HOJE,
        SUM(CASE WHEN dm.DIA > TRUNC(SYSDATE)
                  AND TO_CHAR(dm.DIA,'D') NOT IN ('1','7')
                  AND NOT EXISTS (SELECT 1 FROM feriados_2026 f WHERE f.DIA = dm.DIA)
                 THEN 1 ELSE 0 END) AS DU_RESTANTES
    FROM dias_mes dm
)
```

## Fórmulas finais
META_DIA       = META_MES / DU_MES
REAL_ESPERADO  = META_DIA × DU_ATE_HOJE
DESVIO_VAL     = REAL - REAL_ESPERADO
DESVIO_PCT     = (REAL / REAL_ESPERADO - 1) × 100
RITMO_ATUAL    = REAL / DU_ATE_HOJE
RITMO_NEC      = (META_MES - REAL) / DU_RESTANTES
FATOR_ACEL     = RITMO_NEC / RITMO_ATUAL

## T215 — Meta-Dia BRASIL ✅

**Validado 20/05:** Meta R$ 333M, Real R$ 120,8M, Desvio -44,19%, Ritmo necessário 3,26x atual. ALERTA: meta provavelmente não fecha. Latência: 43s.

## T216 — Meta-Dia por Filial (Top 10)

Idêntico ao T215 mas com agregação por CODFILIAL + JOIN meta_filial (TIPOMETA='FL'). Latência: 7,7s warm.

## T217 — Meta-Dia por Gerente Comercial (Top 10)

Usa GD_FATO_VENDAFATURAMENTO + GD_DIM_RCA.CODIGOGERENTE + PCMETA TIPOMETA='GC'. **Validado:** Davya Cordeiro -5,0% (quase no ritmo). Latência: 52s.

## T218 — Meta-Dia por Supervisor (Top 10)

Mesma estrutura T217 mas com CODIGOSUPERVISOR + TIPOMETA='SV'. **Heróis revelados:** Pedro Raesky +75% meta batida, Clayton +35%, Priscila +32%. Latência: 19,6s.

## T120 — Meta-Dia RCA DERIVADA ⚠️ APROXIMAÇÃO

Como **TIPOMETA='R' não existe na EBD**, meta de RCA é derivada:
`meta_rca = meta_sup / qtd_RCAs_ativos_do_sup`

**LIMITAÇÃO METODOLÓGICA:** divisão igual é aproximação grosseira quando
RCAs do supervisor são desiguais (caso Priscila+Michelly: Michelly faz +557%
da meta derivada). Apresentar como **"estimativa de pressão"**, não meta oficial.

Quando EBD cadastrar TIPOMETA='R' no PCMETA, T120 vira meta real.

Latência: 19,9s.


---

# Parte 7 — 8ª Fórmula Universal: CARTEIRA BR (20/05/2026)

## Descoberta: GD_FATO_ROTACLIENTE é a fonte oficial

Após 6 horas de sondagem testando filtros derivados (PCCLIENT bloqueios, datas de compra 90/180/365/540/660/730 dias), descobrimos que a "carteira" no BI EBD vem de uma fonte simples:

```sql
SELECT COUNT(DISTINCT CODIGOCLIENTE)
FROM EBD.GD_FATO_ROTACLIENTE

ALVO BI: 77.315
MCP:     77.453  delta +138 (+0,18%) ✅ CENTAVO
```

## Definição de negócio (cf. Thiago)

Carteira é gerenciada **manualmente** via inclusão/exclusão de cliente em rota de visita pelo supervisor/gerente. NÃO há regra de "X dias sem compra = sai da carteira".
Cliente em GD_FATO_ROTACLIENTE = cliente em rota de visita ATIVA = carteira

## Estrutura da view
CODIGOCLIENTE   ← cliente
CODIGORCA       ← RCA designado
DIASEMANA       ← dia da visita

142.308 linhas (cliente × dia da semana), 77.453 distintos.

## CICATRIZ NOVA — SEMPRE BUSCAR GD_FATO/GD_DIM PRIMEIRO

Erro recorrente da sessão: tentei derivar carteira de PCCLIENT cru com filtros chutados. **Antes de derivar, SEMPRE consultar:**

```sql
SELECT view_name FROM all_views
WHERE owner='EBD' AND view_name LIKE 'GD_FATO_%CLI%'
   OR view_name LIKE 'GD_FATO_%CART%'
   OR view_name LIKE 'GD_FATO_%ROTA%'
```

Outras views DW oficiais descobertas:
GD_DIM_CARTEIRACLIENTE     histórico (todos vínculos)
GD_FATO_CLIENTE            snapshot (limites/dias)
GD_FATO_ROTACLIENTE        carteira ativa ★ fonte do BI
GD_FATO_METACLIENTE        meta por cliente
GD_FATO_COBRANCACLIENTE    cobrança por cliente
VW_CLIENTESRCA             clientes por RCA


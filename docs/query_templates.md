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


---

# Parte 8 — Aproveitamento de Rota (T180+) — descoberto 20/05/2026 23h

## Conceito de negócio

"Da rota DO DIA da FILIAL X, quantos clientes foram atendidos hoje?"

Atendimento = qualquer pedido aberto, INCLUINDO cobertura entre RCAs
quando o titular falta. RCAs órfãos (ORFAO%, RCA VAGO%) são fictícios:
servem só como "depósito" de clientes parados. Excluídos das métricas.

## Mapeamento de DIASEMANA (cicatriz nova)
Oracle TO_CHAR(DT,'D')   → texto da tabela
'1' DOMINGO              → 'DOMINGO'
'2' SEGUNDA              → 'SEGUNDA'
'3' TERCA                → 'TERCA' OU 'TERÇA' (inconsistência!)
'4' QUARTA               → 'QUARTA'
'5' QUINTA               → 'QUINTA'
'6' SEXTA                → 'SEXTA'
'7' SABADO               → 'SABADO' OU 'SÁBADO' (inconsistência!)

Bug de cadastro: terça e sábado têm variantes com Ç. Solução:
`UPPER(DIASEMANA) IN (NOME, REPLACE(NOME,'C','Ç'))`

## T180 — Aproveitamento de Rota por Filial ✅ Validado

Validado Manaus 20/05 quarta-feira (parcial 22h40):
- 1.530 clientes na rota
- 125 RCAs ativos (sem órfãos)
- 224 visitados → APROV 14,6% (dia ainda fechando)
- 91 NF → CONV 5,9%
- Latência: 0,6s

```sql
WITH dia_ref AS (
    SELECT TRUNC(SYSDATE) AS DT,
           CASE TO_CHAR(TRUNC(SYSDATE),'D')
             WHEN '1' THEN 'DOMINGO' WHEN '2' THEN 'SEGUNDA'
             WHEN '3' THEN 'TERCA'   WHEN '4' THEN 'QUARTA'
             WHEN '5' THEN 'QUINTA'  WHEN '6' THEN 'SEXTA'
             WHEN '7' THEN 'SABADO' END AS NOME
    FROM DUAL
),
rota_filial AS (
    SELECT DISTINCT r.CODIGOCLIENTE
    FROM EBD.GD_FATO_ROTACLIENTE r
    JOIN EBD.GD_DIM_RCA dr ON dr.CODIGORCA = r.CODIGORCA
    JOIN EBD.PCCLIENT cli ON cli.CODCLI = r.CODIGOCLIENTE
    , dia_ref d
    WHERE UPPER(r.DIASEMANA) IN (d.NOME, REPLACE(d.NOME,'C','Ç'))
      AND UPPER(NVL(dr.RCA,'')) NOT LIKE 'ORFAO%'
      AND UPPER(NVL(dr.RCA,'')) NOT LIKE 'RCA VAGO%'
      AND cli.CODFILIALNF = :codFilial
)
SELECT (SELECT COUNT(*) FROM rota_filial) AS NA_ROTA,
       (SELECT COUNT(DISTINCT ped.CODCLI) FROM EBD.PCPEDC ped, dia_ref d
        WHERE TRUNC(ped.DATA) = d.DT AND ped.POSICAO != 'C'
          AND ped.CODFILIAL = :codFilial
          AND ped.CODCLI IN (SELECT CODIGOCLIENTE FROM rota_filial)) AS VISITADOS,
       (SELECT COUNT(DISTINCT v.CODCLI) FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v, dia_ref d
        WHERE TRUNC(v.DTSAIDA) = d.DT AND v.CONDVENDA = 1
          AND v.CODFILIAL = :codFilial
          AND v.CODCLI IN (SELECT CODIGOCLIENTE FROM rota_filial)) AS FATURADOS
FROM DUAL
```

## T181 — Aproveitamento por RCA (com cobertura) ✅

JOIN com rota_rca cruzado com PCPEDC e VIEW_VENDAS pra atribuir
visitas/fat aos clientes da rota DO RCA (mesmo se outro coberto).

**Cicatriz #40:** RCA pode cobrir rota de colega. Não restringir visitas
ao mesmo CODUSUR; usar conjunto de clientes da rota do RCA.


---

# Parte 9 — Família Ruptura (T130+) — descoberta 21/05/2026

## 9ª Fórmula universal validada

```sql
-- RUPTURA BR (mes/ano) = SUM(QT*PVENDA) FROM PCFALTA WHERE DATA BETWEEN :ini AND :fim
-- IMPORTANTE: NÃO filtrar CODFILIAL (BI inclui CDs 17, 23 no total)
-- Validacao: Mes R$ 8,14M (BI R$ 8,11M, +0,35%) | Ano R$ 77,17M (BI R$ 77,14M, +0,04%)
```

## Regra critica: remapeamento de CDs (so ruptura/operacao)

```sql
CASE CODFILIAL
  WHEN '17' THEN '10'  -- SAO PEDRO ALDEIA -> SAO GONCALO
  WHEN '23' THEN '14'  -- PETROPOLIS -> PIRAI
  ELSE CODFILIAL
END AS CODFILIAL_COM
```

Em VENDAS o sistema faz automatico. Em RUPTURA precisa forcar.

## T130 v2 — Ruptura por Filial (com remapeamento) ✅
Latencia 9,7s. Validado contra BI Object3+Object4.
Top: Duque R$ 1,14M | Pirá R$ 1,10M | Taquara R$ 1,00M | São Gonçalo R$ 930K | Manaus R$ 733K

## T133 — Ruptura por RCA (Top 15 piores) ✅
Latencia 21,4s. Mostra RCA + Supervisor + Gerente + valor + %FTR.
Top pior absoluto: Eliane Garcia R$ 468K (22,9%)
Top pior relativo: Leonardo Calixto 91,9% (R$ 216K / R$ 235K FTR)

## T134 — Ruptura por Supervisor (Top 15) ✅
Latencia 20,9s. Mostra Supervisor + Gerente + valor + %FTR.
Top pior absoluto: Francisco Humberto R$ 554K (64,5% FTR!!)

## T136 — Ruptura por Cliente (Top 15) ✅
Latencia 0,2s. Mostra Cliente + Fantasia + valor.
Top: SERVI Deposito R$ 395K | HNT/Americanas R$ 142K | Mixter R$ 90K

## PCFALTA esquema completo (10 colunas)
NUMPED      NOT NULL  - pedido
DATA        NOT NULL  - data ruptura
CODPROD     NOT NULL  - produto
CODUSUR              - vendedor (TEM!)
CODCLI               - cliente (TEM!)
QT                   - qtd
PVENDA               - preco
CODFILIAL            - filial
NUMSEQ      NOT NULL  - sequencia no pedido
DTMXSALTER           - auditoria

## Insight estrategico extraido

Gabriel Barbosa Werneck Veiga (gerente) tem ruptura HIPER-CONCENTRADA:
- 2 supervisores no top 10 (Francisco Humberto 64,5% + Thiago Henrique 30,7%)
- 2 RCAs no top 6 (Leonardo Calixto 91,9% + Nubya Martins 63,4%)
- Toda essa cadeia está em Pirá (filial 14, que agora soma o CD 23 Petrópolis)
- T131 confirmou Gabriel = 47,95% ruptura/FTR pior gerente BR

Provavelmente: problema de abastecimento do CD Petrópolis → Pirá.


---

# Parte 11 — Família Visita Real + Motivos (T160-T163) — 21/05/2026

## ★ FONTE OFICIAL: PCVISITAFV (app de força de vendas com GPS)

Volume 2026: 140-180k visitas/mês. 74,5% adoção do app (922 de 1.238 RCAs ativos).
Coluna LATITUDE/LONGITUDE preenchida com GPS real.

## ★ Catalogo de motivos (PCMOTNAOCOMPRA - hardcoded no agente):
COD 1   AGUARDANDO APROVAÇÃO DO ORÇAMENTO   PIPELINE
COD 2   ATRASO NA ÚLTIMA ENTREGA            PROBLEMA_LOGISTICA
COD 4   CLIENTE ESTOCADO                    SAUDAVEL
COD 5   CLIENTE FECHADO                     TIMING
COD 6   CLIENTE SEM DINHEIRO                PROBLEMA_FINANCEIRO
COD 7   COMPRA CENTRALIZADA                 CADEIA
COD 8   COMPRA SUSPENSA                     ALERTA
COD 9   COMPRADOR AUSENTE                   TIMING
COD 11  COMPROU DO CONCORRENTE              ALERTA_COMPETITIVO
COD 13  CLIENTE INADIMPLENTE                PROBLEMA_FINANCEIRO
COD 15  PROBLEMAS COM TROCA                 PROBLEMA_LOGISTICA
COD 20  CD - COMPRA CENTRAL                 CADEIA
COD 22  PEDIDO E-COMMERCE                   ONLINE
COD 23  AGUARDANDO COTAÇÃO                  PIPELINE
COD 999 LEGADO/NAO CADASTRADO               OUTRO
COD 16,17,18,19,21,90 - aparecem em PCVISITAFV mas nao em PCMOTNAOCOMPRA

## T160 — Funil de Cobertura BR ✅
Latencia 42s (cold). Mostra rota / visitas GPS / dentro+fora rota / faturados.
Quarta 20/05: 23.611 rota / 7.232 visitados (30,6% cobertura real) / 660 fora rota / 4.348 faturados.

## T161 — Motivos de Não-Venda BR ✅ (parametrizado: semana/mes/ano)
Latencia 1,2s. Distribuicao CODMOTIVO no periodo.
Mes 2026: top motivos sao "Estocado" (20%), "Aguardando Orcamento" (18%), "Suspensa" (15%).
Aprox 1/3 das visitas sao PIPELINE ativa (cod 1+23).

## T161B — Mix de Motivos por Filial ✅
Latencia 1,4s. Heatmap operacional.
Achados: Matriz tem 31% Compra Suspensa, Macapá 42%, Pirá tem 25% Atraso Entrega.

## T162 — Cobertura por Filial ✅
Latencia 1,4s. Mostra rota / vis_dentro / vis_fora por filial.
Top cobertura: Taquara 80,3%, Caruaru 55,8%, Duque 54,9%.
Pior: Imperatriz 16,4%, Teresina 18,3%.

## T163 — Top RCAs Fora de Rota ✅ (parametrizado periodo)
Latencia 12s. Mostra DENTRO/FORA/PCT_FORA com supervisor+gerente.
Top alertas: Alexandre Sebastiao cod 3119 = 100% fora (provavel cadastro duplicado),
Geiza Oliveira 100% fora, Giannini Menezes 87,8% fora.
Pedro Raesky (supervisor) tem 4 RCAs no top 20 = problema sistemico de cadastro.


---

# Parte 12 — Mix + Cobertura por hierarquia (T141-T153) — 21/05/2026

## Fonte: GD_FATO_VENDAFATURAMENTO mes corrente (formulas 6 e 7)

T141 Mix (SKUs) por GC               - 60s LENTO
T142 Mix + Cobertura por RCA         - 42s LENTO  
T143 Mix por Supervisor              - 17s
T151 Cobertura (CLIs) por GC         - 18s
T152 Cobertura por RCA               - 20s
T153 Cobertura por Supervisor        - 17s

Total: 46 templates validados.

ALERTA performance: TODO proximo = Cache Redis + view materializada.

Insights operacionais BR mes corrente:
- Vagner Andrelino lidera Mix BR (1.507 SKUs)
- Joao Paulo Vale lidera Cobertura BR (3.375 CLIs)
- Christiano Neves lidera Mix sup (1.167 SKUs)
- Clayton Anjos lidera Cobertura sup (1.486 CLIs)
- Luis Carlos top RCA: 565 SKUs + 35 CLIs + R$553K


---

# Parte 13 — Familia Efetividade do Mix (T140, T144-T147) — 21/05/2026

## Conceito
"Efetividade" = SKUs vendidos / SKUs disponiveis no portfolio
Mostra QUANTO do portfolio disponivel o gestor/RCA esta efetivamente vendendo.

## Filtros validados (mix disponivel)
PCPRODFILIAL: REVENDA=S + ATIVO=S + PROIBIDAVENDA=N + FORALINHA=N
AND EXISTS PCEST.QTESTGER > 0

ATENÇÃO: NÃO filtrar DTULTENT - produto parado deve aparecer no denominador.
(Filtrar gera efetividade > 100% impossivel.)

## Hierarquia (1 RCA = 1 filial)

PCUSUARI.CODFILIAL define a filial do RCA (1 RCA = 1 filial).
Supervisor/Gerente herdam via GD_DIM_RCA + PCUSUARI dos seus RCAs.

## Templates

T140 Efetividade BR - 3-4s
T144 Efetividade por Filial - 4,3s
T145 Efetividade por GC - 25,2s LENTO
T146 Efetividade por Supervisor - 20,8s LENTO
T147 Efetividade por RCA - 17,3s LENTO

Total: 51 templates validados.

## Disclaimer OBRIGATORIO ao exibir

"Esta análise considera como mix disponível todos os produtos com
REVENDA=S, ATIVO=S, PROIBIDAVENDA=N, FORALINHA=N e estoque>0 na filial.
SKUs sem venda no período aparecem como 'parados' — útil pra identificar
produtos com problema de venda. Período: mês corrente."

## Insights operacionais brutais (21/05/2026)

GERENTES:
- Joao Gabriel Mourao: 93,4% TOP performer (1.003 disp / 937 vend)
- Marcus Carvalho: 34,6% PIOR com rota grande (1.680 SKUs parados sob ele!)
- Vagner Andrelino: 69,7% (paradoxo - lidera Mix BR absoluto mas eficiencia média)
- Gabriel Veiga: 25,0% (confirma alerta da ruptura - cadeia inteira mal)

FILIAIS:
- Caruaru 96,9% / Manaus 96,8% TOP eficiencia
- Duque 65,2% / Santarem 63,7% BOTTOM (785 SKUs parados em Duque)
- Pirá (com acento!) 68,2% confirma alerta operacional



<!-- AUTO-APPEND PROP-C221ABB8 aprovado por Thiago -->


## T-CARTEIRA-01 — Carteira em Pedido por Filial (VLATEND)

**Validado em:** 21/05/2026
**Validação:** bateu na vírgula contra BI EBD (divergências residuais = delay operacional normal)
**Uso:** visão gerencial/diretoria de pedidos liberados ainda não faturados

```sql
SELECT
    p.CODFILIAL,
    SUBSTR(NVL(pf.FANTASIA, '?'), 1, 30) AS FILIAL,
    COUNT(DISTINCT p.NUMPED)             AS QTD_PEDIDOS,
    SUM(p.VLATEND)                       AS CARTEIRA
FROM EBD.PCPEDC p
JOIN EBD.PCFILIAL pf ON pf.CODIGO = p.CODFILIAL
WHERE p.POSICAO IN ('L', 'M')
  AND p.DTCANCEL IS NULL
  AND p.CONDVENDA NOT IN (4, 5, 6, 8, 10, 11, 12, 13, 20, 98, 99)
GROUP BY p.CODFILIAL, pf.FANTASIA
ORDER BY CARTEIRA DESC
```

### Regras aplicadas
| Regra | Detalhe |
|---|---|
| `POSICAO IN ('L','M')` | Liberado + Montado — pedidos prontos pra faturar |
| `DTCANCEL IS NULL` | Exclui cancelados |
| `CONDVENDA NOT IN (...)` | Exclui bonificações, transferências, consignações, manifestos |
| `VLATEND` | Valor atendido do pedido (não VLPEDIDO que pode incluir itens sem estoque) |
| `PCFILIAL.CODIGO` | Atenção: PCFILIAL usa CODIGO, não CODFILIAL |

### Variações comuns
- **1 filial específica:** adicionar `AND p.CODFILIAL = :userFilial`
- **Regional:** `AND p.CODFILIAL IN ('05','14')` (ex: RJ2)
- **1 RCA:** adicionar `AND p.CODUSUR = :codUsur`
- **1 supervisor:** JOIN com PCUSUARI + filtro CODSUPERVISOR

### Resultado referência (21/05/2026 ~momento da validação)
Total BR: R$ 24.021.297 | 21 filiais | maior: EBD MATRIZ R$ 4.728.460



<!-- AUTO-APPEND PROP-C2892673 aprovado por Thiago -->

## T201 — Pedidos Pendentes (Carteira) — Query oficial BI EBD

> Fonte: query oficial do BI EBD, fornecida pelo time em 21/05/2026.
> Retorna itens de pedidos ainda não faturados (POSICAO = 'L' ou 'M').

### Filtros-chave obrigatórios
- `PCPEDC.POSICAO IN ('L', 'M')` — Liberado / Montado
- `PCPEDC.DTCANCEL IS NULL` — exclui cancelados
- `PCPEDC.CONDVENDA IN (1,2,3,7,9,14,15,17,18,19,98)` — tipos de venda válidos
- `PCUSUARI.CODSUPERVISOR NOT IN ('9999')` — exclui RCAs fantasma/vago

### Cálculo de VALORUNITARIO e VALORTOTAL
CONDVENDA 5, 6, 11, 12 → valor zerado (bonificação/brinde/troca)
Demais → PVENDA + VLFRETE + VLOUTRASDESP + VLFRETE_RATEIO + VLOUTROS

### NOVADATAVENDA
Pedidos de meses anteriores têm data "trazida" para hoje:
```sql
TRUNC(CASE 
  WHEN TO_CHAR(PCPEDC.DATA, 'YYYY-MM') < TO_CHAR(TRUNC(SYSDATE), 'YYYY-MM') 
  THEN TRUNC(SYSDATE) 
  ELSE PCPEDC.DATA 
END) AS NOVADATAVENDA
```

### Query completa (nível item)

```sql
SELECT PCPEDI.CODUSUR        AS CODIGORCA,
       PCPEDI.CODCLI         AS CODIGOCLIENTE,
       PCPEDC.CODFILIAL      AS CODIGOFILIAL,
       PCPEDI.CODPROD        AS CODIGOPRODUTO,
       PCPEDC.CODPLPAG       AS CODIGOPLANOPAGAMENTO,
       PCPEDC.CODCOB         AS CODIGOCOBRANCA,
       PCPEDI.BONIFIC        AS CODIGOTIPOITEMVENDA,
       PCPEDC.CODEMITENTE    AS CODIGOEMITENTE,
       PCPEDI.NUMPED         AS NUMEROPEDIDO,
       PCPEDC.NUMCAR         AS NUMEROCARREGAMENTO,
       TRUNC(PCPEDC.DATA)    AS DATAVENDA,
       TRUNC(CASE
               WHEN TO_CHAR(PCPEDC.DATA, 'YYYY-MM') < TO_CHAR(TRUNC(SYSDATE), 'YYYY-MM')
               THEN TRUNC(SYSDATE)
               ELSE PCPEDC.DATA
             END)            AS NOVADATAVENDA,
       PCPEDI.QT             AS QUANTIDADE,
       CAST(
         DECODE(PCPEDC.CONDVENDA,
                5, 0, 6, 0, 11, 0, 12, 0,
                NVL(NVL(PCPEDI.PVENDA,0)
                  + NVL(PCPEDI.VLFRETE,0)
                  + NVL(PCPEDI.VLOUTRASDESP,0)
                  + NVL(PCPEDI.VLFRETE_RATEIO,0)
                  + NVL(PCPEDI.VLOUTROS,0), 0))
       AS NUMERIC(18,6))     AS VALORUNITARIO,
       (PCPEDI.QT *
        CAST(
          DECODE(PCPEDC.CONDVENDA,
                 5, 0, 6, 0, 11, 0, 12, 0,
                 NVL(NVL(PCPEDI.PVENDA,0)
                   + NVL(PCPEDI.VLFRETE,0)
                   + NVL(PCPEDI.VLOUTRASDESP,0)
                   + NVL(PCPEDI.VLFRETE_RATEIO,0)
                   + NVL(PCPEDI.VLOUTROS,0), 0))
        AS NUMERIC(18,6)))   AS VALORTOTAL
  FROM EBD.PCPEDI, EBD.PCPEDC, EBD.PCPRODUT, EBD.PCFORNEC,
       EBD.PCDEPTO, EBD.PCCLIENT, EBD.PCUSUARI, EBD.PCATIVI,
       EBD.PCPRACA, EBD.PCCIDADE, EBD.PCSUPERV, EBD.PCDISTRIB,
       EBD.PCREGIAO, EBD.PCGERENTE,
       EBD.PCEMPR COMPRADOR, EBD.PCEMPR EMITENTE,
       EBD.PCPLPAG
 WHERE PCPEDI.NUMPED          = PCPEDC.NUMPED
   AND PCUSUARI.CODSUPERVISOR NOT IN ('9999')
   AND PCCLIENT.CODCIDADE     = PCCIDADE.CODCIDADE(+)
   AND PCPEDC.CODCLI          = PCCLIENT.CODCLI
   AND PCSUPERV.CODSUPERVISOR = PCUSUARI.CODSUPERVISOR
   AND PCCLIENT.CODATV1       = PCATIVI.CODATIV(+)
   AND PCPEDC.DTCANCEL        IS NULL
   AND PCPEDI.CODPROD         = PCPRODUT.CODPROD
   AND PCPRODUT.CODEPTO       = PCDEPTO.CODEPTO
   AND PCPRODUT.CODFORNEC     = PCFORNEC.CODFORNEC
   AND PCPEDC.CODUSUR         = PCUSUARI.CODUSUR
   AND PCPEDC.CODPRACA        = PCPRACA.CODPRACA
   AND PCPEDC.CODPLPAG        = PCPLPAG.CODPLPAG(+)
   AND PCPEDC.NUMREGIAO       = PCREGIAO.NUMREGIAO(+)
   AND PCPEDC.CODEMITENTE     = EMITENTE.MATRICULA(+)
   AND PCFORNEC.CODCOMPRADOR  = COMPRADOR.MATRICULA(+)
   AND PCPRODUT.CODDISTRIB    = PCDISTRIB.CODDISTRIB(+)
   AND PCSUPERV.CODGERENTE    = PCGERENTE.CODGERENTE(+)
   AND PCPEDC.CONDVENDA       IN (1,2,3,7,9,14,15,17,18,19,98)
   AND PCPEDC.POSICAO         IN ('L','M')
   AND PCPEDC.CODFILIAL       = :userFilial   -- ← OBRIGATÓRIO
```

### Variante agregada por filial (para painel executivo)
```sql
SELECT PCPEDC.CODFILIAL,
       COUNT(DISTINCT PCPEDC.NUMPED)  AS QTD_PEDIDOS,
       COUNT(DISTINCT PCPEDC.CODCLI)  AS QTD_CLIENTES,
       SUM(PCPEDI.QT *
           CAST(DECODE(PCPEDC.CONDVENDA,
                       5,0,6,0,11,0,12,0,
                       NVL(NVL(PCPEDI.PVENDA,0)
                         + NVL(PCPEDI.VLFRETE,0)
                         + NVL(PCPEDI.VLOUTRASDESP,0)
                         + NVL(PCPEDI.VLFRETE_RATEIO,0)
                         + NVL(PCPEDI.VLOUTROS,0),0))
                AS NUMERIC(18,6)))    AS VALOR_CARTEIRA
  FROM EBD.PCPEDI, EBD.PCPEDC, EBD.PCUSUARI
 WHERE PCPEDI.NUMPED          = PCPEDC.NUMPED
   AND PCPEDC.CODUSUR         = PCUSUARI.CODUSUR
   AND PCUSUARI.CODSUPERVISOR NOT IN ('9999')
   AND PCPEDC.DTCANCEL        IS NULL
   AND PCPEDC.CONDVENDA       IN (1,2,3,7,9,14,15,17,18,19,98)
   AND PCPEDC.POSICAO         IN ('L','M')
   AND PCPEDC.CODFILIAL       = :userFilial
 GROUP BY PCPEDC.CODFILIAL
```

### Observações
- `POSICAO = 'L'` = Liberado (pronto pra faturar)
- `POSICAO = 'M'` = Montado (em separação/carregamento)
- `CONDVENDA IN (1,2,3,7,9,14,15,17,18,19,98)` = vendas reais (exclui bonif, transferência, consignação)
- Esta query equivale ao "Em Pedido" / "Carteira" do BI EBD
- SEMPRE adicionar `AND PCPEDC.CODFILIAL = :userFilial` (obrigatório por regra #9)


**Cicatriz #46:** PCUSUARI NÃO tem coluna FUNCAO (ORA-00904 — "FUNCAO": invalid identifier, 15/07). Para função/cargo/tipo do vendedor usar TIPOVEND (validada 31x em produção). DTTERMINO EXISTE e está validada (31x ok) — usar `(DTTERMINO IS NULL OR DTTERMINO >= TRUNC(SYSDATE))` para "equipe ativa". Colunas de PCUSUARI validadas em prod: CODUSUR, NOME, CODFILIAL, TIPOVEND, DTTERMINO.

# Parte 12 — Família Equipe em Campo / Check-in (T170-T174) — 08/07/2026
Origem: mineração do queries.jsonl (177 queries; padrões ok=7/3/3/2/2). SQLs reconstruídos de
prefixos validados em produção — confirmar cada um na 1ª execução. Não confundir com a
Parte 11 (T160-T163 = Funil/Motivos de Não-Venda): aqui é PRESENÇA/CHECK-IN da equipe.

**Cicatriz #41:** PCVISITAFV NÃO tem CODFILIAL. A filial vem SEMPRE via JOIN:
`PCVISITAFV v JOIN PCUSUARI u ON u.CODUSUR = v.CODUSUR` → `u.CODFILIAL`.
Usar `v.CODFILIAL` = ORA-00904 (causa real dos erros do relatório de 08/07).

**Cicatriz #42:** a coluna de data da PCVISITAFV é `DATA` (tipo DATE) — confirmada ok em
produção (`vf.DATA >=`, `DATA = TRUNC(SYSDATE)-1`). Não usar DTVISITA/DTCHECKIN.

**Cicatriz #43 (v2, provada pelo Oracle em 15/07):** PCUSUARI — colunas que EXISTEM:
CODFILIAL, CODUSUR, NOME, DTTERMINO, TIPOVEND, CODSUPERVISOR.
NAO EXISTEM: `ATIVO` (ORA-00904, 2x) e `FUNCAO` (ORA-00904) — para "equipe ativa" use
`(DTTERMINO IS NULL OR DTTERMINO >= TRUNC(SYSDATE))`; para função/tipo use TIPOVEND;
o supervisor é `CODSUPERVISOR` (não SUPERVISOR).
Filial: `LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = u.CODFILIAL`.

**Cicatriz #44:** excluir cadastros fantasma da equipe (ORFAO / RCA VAGO / ECOMMERCE):
`AND UPPER(u.NOME) NOT LIKE '%ORFAO%' AND UPPER(u.NOME) NOT LIKE '%VAGO%' AND UPPER(u.NOME) NOT LIKE '%ECOMMERCE%'`

**Cicatriz #45:** NÃO misturar vocabulário VIEW × FATO (ORA-00904 dentro da fonte canônica):
VIEW_VENDAS_RESUMO_FATURAMENTO → data=DTSAIDA, valor=VLATEND.
GD_FATO_VENDAFATURAMENTO → data=DATAFATURAMENTO, valor=VALORTOTAL.
Nunca usar o par de uma na outra.

## T170 — Equipe: cadastro de RCAs por filial (reconstruído 08/07 — validar 1ª execução)
Pergunta: "quais vendedores temos na filial X?" · padrão ok=7 no log
```sql
SELECT u.CODUSUR,
       SUBSTR(NVL(u.NOME,'?'),1,40)        AS NOME,
       u.TIPOVEND,
       u.CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,30)   AS FILIAL
FROM EBD.PCUSUARI u
LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = u.CODFILIAL
WHERE u.CODFILIAL = :codFilial
  AND UPPER(u.NOME) NOT LIKE '%ORFAO%'
  AND UPPER(u.NOME) NOT LIKE '%VAGO%'
  AND UPPER(u.NOME) NOT LIKE '%ECOMMERCE%'
ORDER BY u.NOME
```
Variante BR: remover o filtro :codFilial e ordenar por u.CODFILIAL, u.NOME.

## T171 — Equipe em campo hoje, por filial (reconstruído 08/07 — validar 1ª execução)
Pergunta: "quantos RCAs estão em campo hoje?" · padrão ok=3, mediana ~1s
```sql
SELECT u.CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,25) AS FILIAL,
       COUNT(DISTINCT v.CODUSUR)         AS EM_CAMPO_HOJE
FROM EBD.PCVISITAFV v
JOIN EBD.PCUSUARI u  ON u.CODUSUR = v.CODUSUR
LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = u.CODFILIAL
WHERE v.DATA >= TRUNC(SYSDATE) AND v.DATA < TRUNC(SYSDATE) + 1
GROUP BY u.CODFILIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,25)
ORDER BY EM_CAMPO_HOJE DESC
```

## T172 — Cobertura de visitas no período, por filial (reconstruído 08/07 — validar 1ª execução)
Pergunta: "quantos RCAs visitaram no período?" · padrão ok=2, ~2,2s
```sql
SELECT u.CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,30) AS FILIAL,
       COUNT(DISTINCT v.CODUSUR)         AS RCAS_COM_VISITA,
       COUNT(*)                          AS TOTAL_VISITAS
FROM EBD.PCVISITAFV v
JOIN EBD.PCUSUARI u  ON u.CODUSUR = v.CODUSUR
LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = u.CODFILIAL
WHERE v.DATA >= TO_DATE(:dataIni,'YYYY-MM-DD')
  AND v.DATA <  TO_DATE(:dataFim,'YYYY-MM-DD') + 1
GROUP BY u.CODFILIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,30)
ORDER BY RCAS_COM_VISITA DESC
```

## T173 — Vendedores SEM check-in no dia, por filial (reconstruído 08/07 — validar 1ª execução)
Pergunta: "quais vendedores estão sem checkin hoje (em Belém)?" · anti-join validado ok=3
```sql
WITH visitas_dia AS (
    SELECT DISTINCT v.CODUSUR
    FROM EBD.PCVISITAFV v
    WHERE v.DATA >= TRUNC(SYSDATE) AND v.DATA < TRUNC(SYSDATE) + 1
)
SELECT u.CODUSUR,
       SUBSTR(NVL(u.NOME,'?'),1,40)      AS NOME,
       u.TIPOVEND,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,25) AS FILIAL
FROM EBD.PCUSUARI u
LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = u.CODFILIAL
WHERE u.CODFILIAL = :codFilial
  AND UPPER(u.NOME) NOT LIKE '%ORFAO%'
  AND UPPER(u.NOME) NOT LIKE '%VAGO%'
  AND UPPER(u.NOME) NOT LIKE '%ECOMMERCE%'
  AND u.CODUSUR NOT IN (SELECT CODUSUR FROM visitas_dia)
ORDER BY u.NOME
```
Para "ontem": TRUNC(SYSDATE)-1 nas duas pontas do CTE.

## T174 — Aderência check-in × rota planejada, dia anterior (ESQUELETO — completar na validação)
Pergunta: "quantos usaram o app vs rota planejada ontem?" · padrão ok=2, subquery truncada no log
```sql
SELECT (SELECT COUNT(DISTINCT CODUSUR)
          FROM EBD.PCVISITAFV
         WHERE DATA = TRUNC(SYSDATE) - 1)      AS RCAS_APP,
       (SELECT COUNT(DISTINCT r.CODIGORCA)
          FROM EBD.GD_FATO_ROTACLIENTE r)      AS RCAS_ROTA
FROM DUAL
```
Nota: a subquery de rota tinha um JOIN GD_* adicional cortado no log — estender no 1º uso.

# Parte 13 — Família Produto / EAN / Catálogo (T190-T193) — 15/07/2026
Origem: mineração do queries.jsonl (86 queries PCPRODUT, 52 padrões) + veredito de coluna com
prova do Oracle (mine_cols.py). Motivo: família responsável pelo eixo dos ORA-00904 do ciclo 2
e pelos turns mais caros (Excel de EAN: R$ 10,83 em 8 tools — discovery repetida de schema).

**Cicatriz #47:** o EAN do produto é `PCPRODUT.CODAUXILIAR` (7+ usos ok). `CODEAN` NÃO EXISTE
(ORA-00904 — alucinação recorrente). Variantes fiscais existentes: GTINCODAUXILIAR,
GTINCODAUXILIAR2, GTINCODAUXILIARTRIB.

**Cicatriz #48:** PCPRODUT é cadastro NACIONAL do produto — NÃO tem CODFILIAL, ATIVO nem
FORALINHA (ORA-00904 provado). O status comercial por filial vive em `PCPRODFILIAL`
(fórmula universal #5: REVENDA='S' + ATIVO='S' + PROIBIDAVENDA='N' + FORALINHA='N').
Produto "ativo/disponível" = JOIN com PCPRODFILIAL por CODPROD+CODFILIAL, nunca filtro na PCPRODUT.

**Cicatriz #49:** `DTULTENT` NÃO está em PCPRODUT (ORA-00904, 8x — campeão de erro da família).
Última entrada vive em `PCEST` (confirma cicatriz #21).

**Cicatriz #50:** `CODFORNECPRINC` NÃO está em PCPRODUT (ORA-00904, 2x) — é coluna de `PCFORNEC`.
Fornecedor raiz: `PCPRODUT p JOIN PCFORNEC f ON f.CODFORNEC = p.CODFORNEC` e então
`NVL(f.CODFORNECPRINC, f.CODFORNEC)`.

**Cicatriz #51:** `QUANTIDADE` existe em GD_FATO_VENDAFATURAMENTO (`vf.QUANTIDADE`, ok) e NÃO na
VIEW_VENDAS_RESUMO_FATURAMENTO (ORA-00904) — caso particular da cicatriz #45 (vocabulário VIEW×FATO).

**Colunas de PCPRODUT validadas em produção:** CODPROD, DESCRICAO, CODAUXILIAR, CODFORNEC,
CODMARCA, CODEPTO, REVENDA, DTEXCLUSAO, GTINCODAUXILIAR, GTINCODAUXILIAR2, GTINCODAUXILIARTRIB.

## T190 — Catálogo de produtos com EAN, fornecedor e departamento (minerado de padrão ok=4)
Pergunta: "lista de EANs por fornecedor / categoria" · a pergunta do Excel caro de 15/07
```sql
SELECT p.CODPROD,
       SUBSTR(NVL(p.DESCRICAO,'?'),1,60)                        AS PRODUTO,
       p.CODAUXILIAR                                            AS EAN,
       SUBSTR(NVL(f.FORNECEDOR,'?'),1,50)                       AS FORNECEDOR,
       SUBSTR(NVL(d.CODEPTO||' - '||d.DESCRICAO,'?'),1,50)      AS DEPARTAMENTO
FROM EBD.PCPRODUT p
JOIN EBD.PCFORNEC f ON f.CODFORNEC = p.CODFORNEC
LEFT JOIN EBD.PCDEPTO d ON d.CODEPTO = p.CODEPTO
WHERE NVL(f.CODFORNECPRINC, f.CODFORNEC) = :codFornecRaiz
  AND p.DTEXCLUSAO IS NULL
ORDER BY p.CODPROD
```
Variante "todos os fornecedores": remover o filtro :codFornecRaiz (usar max_rows alto — base grande).

## T191 — Produtos ATIVOS/disponíveis por filial (fórmula universal #5 — validar 1ª execução)
Pergunta: "produtos ativos / mix disponível da filial X" · status comercial vem de PCPRODFILIAL
```sql
SELECT p.CODPROD,
       SUBSTR(NVL(p.DESCRICAO,'?'),1,60) AS PRODUTO,
       p.CODAUXILIAR                     AS EAN,
       pf.CODFILIAL
FROM EBD.PCPRODUT p
JOIN EBD.PCPRODFILIAL pf ON pf.CODPROD = p.CODPROD
WHERE pf.CODFILIAL     = :codFilial
  AND pf.REVENDA       = 'S'
  AND pf.ATIVO         = 'S'
  AND pf.PROIBIDAVENDA = 'N'
  AND pf.FORALINHA     = 'N'
  AND p.DTEXCLUSAO IS NULL
ORDER BY p.CODPROD
```

## T192 — Produtos vendidos no período (minerado de padrão ok=2 · fonte FATO)
Pergunta: "o que vendemos de tal produto/fornecedor no período" · QUANTIDADE só existe na FATO
```sql
SELECT vf.CODIGOPRODUTO                        AS CODPROD,
       SUBSTR(NVL(pr.DESCRICAO,'?'),1,50)      AS PRODUTO,
       pr.CODAUXILIAR                          AS EAN,
       SUM(vf.QUANTIDADE)                      AS QT_VENDIDA,
       SUM(vf.VALORTOTAL)                      AS BRUTO,
       MAX(vf.DATAFATURAMENTO)                 AS ULTIMA_VENDA
FROM EBD.GD_FATO_VENDAFATURAMENTO vf
JOIN EBD.PCPRODUT pr ON pr.CODPROD = vf.CODIGOPRODUTO
WHERE vf.DATAFATURAMENTO BETWEEN :dataIni AND :dataFim
GROUP BY vf.CODIGOPRODUTO, SUBSTR(NVL(pr.DESCRICAO,'?'),1,50), pr.CODAUXILIAR
ORDER BY BRUTO DESC
```

## T193 — Vendas por marca e filial (minerado de padrão ok=2)
Pergunta: "faturamento por marca" · CODMARCA vive na PCPRODUT
```sql
SELECT vf.CODIGOFILIAL,
       pp.CODMARCA,
       COUNT(DISTINCT vf.CODIGOCLIENTE) AS CLIENTES,
       SUM(vf.VALORTOTAL)               AS BRUTO
FROM EBD.GD_FATO_VENDAFATURAMENTO vf
JOIN EBD.PCPRODUT pp ON pp.CODPROD = vf.CODIGOPRODUTO
WHERE vf.DATAFATURAMENTO BETWEEN :dataIni AND :dataFim
GROUP BY vf.CODIGOFILIAL, pp.CODMARCA
ORDER BY BRUTO DESC
```


<!-- AUTO-APPEND PROP-492EAFAE aprovado por Thiago -->


## T182 — Produtividade em Rota por RCA (PCMOVROTACLI) ✅ Validado 16/07/2026

> Substitui o uso de `GD_FATO_ROTACLIENTE` para "rota do dia" quando se quer
> respeitar periodicidade (7/14/28 dias). Validado em EBD MATRIZ (01) quarta 15/07/2026.

### Por que PCMOVROTACLI e não GD_FATO_ROTACLIENTE

| Fonte | Periodicidade | DTPROXVISITA | Resultado |
|---|:---:|:---:|---|
| `GD_FATO_ROTACLIENTE` | ❌ Não tem | ❌ Não tem | Inflado — inclui quinzenais/mensais que não são visitados hoje |
| `PCMOVROTACLI` | ✅ 7/14/28 | ✅ Sim | Correto — só clientes cuja visita está agendada para o dia |

### Estrutura de PCMOVROTACLI

| Campo | Tipo | Significado |
|---|---|---|
| `CODUSUR` | NUMBER | RCA |
| `CODCLI` | NUMBER | Cliente |
| `DIASEMANA` | VARCHAR2 | Dia fixo da rota (SEGUNDA, TERCA, QUARTA...) |
| `PERIODICIDADE` | NUMBER | 7=semanal, 14=quinzenal, 28=mensal |
| `DTPROXVISITA` | DATE | Próxima visita agendada |

> ⚠️ `DTPROXVISITA` avança automaticamente após a visita ser registrada.
> Clientes com `DTPROXVISITA` no futuro distante = não foram visitados ainda.

### Filtro correto para "rota de hoje"

```sql
-- Dia da semana atual (Oracle: 1=Dom, 2=Seg, ..., 5=Qui, ..., 7=Sab)
WHERE UPPER(r.DIASEMANA) IN (
    CASE TO_CHAR(:dtRef, 'D')
      WHEN '2' THEN 'SEGUNDA'
      WHEN '3' THEN 'TERCA'
      WHEN '4' THEN 'QUARTA'
      WHEN '5' THEN 'QUINTA'
      WHEN '6' THEN 'SEXTA'
      WHEN '7' THEN 'SABADO'
    END,
    CASE TO_CHAR(:dtRef, 'D')
      WHEN '3' THEN 'TERÇA'
      WHEN '7' THEN 'SÁBADO'
      ELSE NULL
    END
)
AND TRUNC(r.DTPROXVISITA) <= TRUNC(:dtRef)        -- visita deveria ocorrer hoje ou estava atrasada
AND TRUNC(r.DTPROXVISITA) >= TRUNC(:dtRef) - 7    -- janela de 1 semana (evita histórico antigo)
```

> Cicatriz #40 (TERCA/TERÇA e SABADO/SÁBADO): usar sempre as 2 variantes com e sem acento.

### T182 — Query completa: Produtividade em Rota por RCA, por filial

```sql
WITH dia_ref AS (
    SELECT TRUNC(:dtRef) AS DT,
           CASE TO_CHAR(TRUNC(:dtRef),'D')
             WHEN '2' THEN 'SEGUNDA' WHEN '3' THEN 'TERCA'
             WHEN '4' THEN 'QUARTA'  WHEN '5' THEN 'QUINTA'
             WHEN '6' THEN 'SEXTA'   WHEN '7' THEN 'SABADO'
           END AS NOME_DIA
    FROM DUAL
),
rota_dia AS (
    -- Clientes realmente agendados para :dtRef por periodicidade
    SELECT r.CODUSUR, r.CODCLI
    FROM EBD.PCMOVROTACLI r, dia_ref d
    WHERE (UPPER(r.DIASEMANA) = d.NOME_DIA
           OR UPPER(r.DIASEMANA) = REPLACE(d.NOME_DIA,'C','Ç'))
      AND TRUNC(r.DTPROXVISITA) <= d.DT
      AND TRUNC(r.DTPROXVISITA) >= d.DT - 7
),
pedidos_dia AS (
    -- Pedidos digitados no dia (excluindo bonificações e cancelados)
    SELECT p.NUMPED, p.CODUSUR, p.CODCLI, p.CODFILIAL,
           NVL(p.VLATEND,0) AS VALOR,
           CASE WHEN r.CODCLI IS NOT NULL THEN 1 ELSE 0 END AS NA_ROTA
    FROM EBD.PCPEDC p
    LEFT JOIN rota_dia r ON r.CODUSUR = p.CODUSUR AND r.CODCLI = p.CODCLI
    WHERE TRUNC(p.DATA) = (SELECT DT FROM dia_ref)
      AND p.POSICAO != 'C'
      AND p.DTCANCEL IS NULL
      AND p.CONDVENDA NOT IN (4,5,6,8,10,11,12,13,20,98,99)
      AND p.CODFILIAL = :codFilial
)
SELECT
    u.CODUSUR,
    SUBSTR(NVL(u.NOME,'?'),1,40)           AS VENDEDOR,
    COUNT(DISTINCT rt.CODCLI)              AS CLIENTES_ROTA,
    -- Pedidos NA rota
    COUNT(DISTINCT CASE WHEN pd.NA_ROTA=1 THEN pd.CODCLI END) AS POSIT_ROTA,
    COUNT(DISTINCT CASE WHEN pd.NA_ROTA=1 THEN pd.NUMPED END) AS PEDS_ROTA,
    NVL(SUM(CASE WHEN pd.NA_ROTA=1 THEN pd.VALOR END),0)      AS VALOR_ROTA,
    -- Pedidos FORA da rota
    COUNT(DISTINCT CASE WHEN pd.NA_ROTA=0 THEN pd.CODCLI END) AS POSIT_FORA,
    COUNT(DISTINCT CASE WHEN pd.NA_ROTA=0 THEN pd.NUMPED END) AS PEDS_FORA,
    NVL(SUM(CASE WHEN pd.NA_ROTA=0 THEN pd.VALOR END),0)      AS VALOR_FORA,
    -- Total
    COUNT(DISTINCT pd.NUMPED)              AS PEDS_TOTAL,
    NVL(SUM(pd.VALOR),0)                  AS VALOR_TOTAL,
    -- % positivação na rota
    CASE WHEN COUNT(DISTINCT rt.CODCLI) > 0
         THEN ROUND(COUNT(DISTINCT CASE WHEN pd.NA_ROTA=1 THEN pd.CODCLI END)
                    / COUNT(DISTINCT rt.CODCLI) * 100, 1)
         ELSE 0 END                        AS PCT_POSIT_ROTA
FROM EBD.PCUSUARI u
LEFT JOIN rota_dia rt  ON rt.CODUSUR = u.CODUSUR
LEFT JOIN pedidos_dia pd ON pd.CODUSUR = u.CODUSUR
WHERE u.CODFILIAL = :codFilial
  AND (u.DTTERMINO IS NULL OR u.DTTERMINO >= TRUNC(SYSDATE))
  AND u.CODUSUR NOT IN (
      SELECT COD_CADRCA FROM EBD.PCSUPERV WHERE COD_CADRCA IS NOT NULL
  )
  AND UPPER(NVL(u.NOME,'')) NOT LIKE '%ORFAO%'
  AND UPPER(NVL(u.NOME,'')) NOT LIKE '%VAGO%'
  AND UPPER(NVL(u.NOME,'')) NOT LIKE '%ECOMMERCE%'
  AND UPPER(NVL(u.NOME,'')) NOT LIKE '%GM-RM%'
  AND UPPER(NVL(u.NOME,'')) NOT LIKE '%GERENTE%'
GROUP BY u.CODUSUR, u.NOME
ORDER BY VALOR_TOTAL DESC NULLS LAST
```

### Binds obrigatórios

| Bind | Tipo | Exemplo |
|---|---|---|
| `:dtRef` | DATE | `TRUNC(SYSDATE)` (hoje) ou `TRUNC(SYSDATE)-1` (ontem) |
| `:codFilial` | VARCHAR2 | `'01'` |

### Variantes

- **1 RCA específico:** adicionar `AND u.CODUSUR = :codUsur`
- **Regional:** substituir `u.CODFILIAL = :codFilial` por `u.CODFILIAL IN ('05','14')`
- **BR completo:** remover filtro de filial (atenção: query pesada, usar com max_rows)
- **Ontem:** `:dtRef = TRUNC(SYSDATE) - 1`

### Resultado de referência (quarta 15/07/2026 · EBD MATRIZ 01)

| Métrica | Valor |
|---|---|
| RCAs com rota no dia | 123 |
| Total pedidos | ~220 |
| Maior positivação rota | FRANCISCO ROBERTO 76,2% |
| Maior valor fora de rota | SHARLENY LADISLAU R$ 28.690 |

### Comparativo ANTONIO KELVEN (1343) — antes vs depois

| Métrica | GD_FATO_ROTACLIENTE (errado) | PCMOVROTACLI (correto) |
|---|---:|---:|
| Clientes na rota | 60 | 58 |
| Valor NA rota | R$ 1.208 | R$ 13.456 |
| Valor FORA da rota | R$ 12.879 | R$ 631 |

> O dado anterior estava **invertido** porque `GD_FATO_ROTACLIENTE` não respeita
> periodicidade — incluía todos os clientes de quarta, mesmo os quinzenais/mensais
> que não eram visitados naquele dia.

### Cicatriz associada

> Nunca usar `GD_FATO_ROTACLIENTE` para "clientes da rota hoje" quando precisar
> respeitar periodicidade. Usar sempre `PCMOVROTACLI` com filtro `DTPROXVISITA`.
> `GD_FATO_ROTACLIENTE` é válida apenas para visão de carteira total (quem pertence
> à rota de quem), sem recorte por dia específico.


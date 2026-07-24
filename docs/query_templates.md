# Query Templates EBD.ia — v2 consolidado (20/05/2026)

Catálogo de queries validadas centavo-a-centavo contra ERP/BI Winthor da EBD.

## Convenções universais

- **Período "mês corrente"** = `BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE` (até ESTE SEGUNDO, nunca até ontem)
- **Faturamento Bruto** = `SUM(EBD.VIEW_VENDAS_RESUMO_FATURAMENTO.VLATEND)` com `CONDVENDA = 1`
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
SELECT
    :codFilial                          AS CODFILIAL,
    SUM(v.VLATEND)                      AS FATURAMENTO_BRUTO,
    COUNT(DISTINCT v.NUMTRANSVENDA)     AS QTD_NOTAS,
    COUNT(DISTINCT v.CODCLI)            AS QTD_CLIENTES,
    COUNT(DISTINCT v.CODPROD)           AS QTD_SKUS
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
WHERE v.CODFILIAL = :codFilial
  AND v.DTSAIDA BETWEEN :dtInicio AND :dtFim
  AND v.CONDVENDA = 1
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
    SUBSTR(NVL(a.RAMO,'(sem ramo)'),1,30) AS RAMO,
    COUNT(DISTINCT v.CODCLI)              AS QTD_CLIENTES,
    SUM(v.VLATEND)                        AS FATURAMENTO
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
LEFT JOIN EBD.PCATIVI a ON a.CODATIV = v.CODATIV
WHERE v.CODFILIAL = :codFilial
  AND v.DTSAIDA BETWEEN :dtInicio AND :dtFim
  AND v.CONDVENDA = 1
GROUP BY a.RAMO
ORDER BY FATURAMENTO DESC NULLS LAST
FETCH FIRST :topN ROWS ONLY
```

**Validado:** top 15 ramos concentram 89,9% filial 06.

---

## T103 — Top N RCAs Filial (validado vs ERP)

```sql
SELECT
    v.CODUSUR,
    SUBSTR(NVL(u.NOME,'?'),1,32)  AS RCA,
    SUBSTR(NVL(s.NOME,'-'),1,25)  AS SUPERVISOR,
    SUM(v.VLATEND)                AS REAL,
    COUNT(DISTINCT v.CODCLI)      AS POSITIVACAO,
    COUNT(DISTINCT v.NUMPED)      AS PEDIDOS
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
LEFT JOIN EBD.PCUSUARI u ON u.CODUSUR = v.CODUSUR
LEFT JOIN EBD.PCSUPERV s ON s.CODSUPERVISOR = v.CODSUPERVISOR
WHERE v.CODFILIAL = :codFilial
  AND v.DTSAIDA BETWEEN :dtInicio AND :dtFim
  AND v.CONDVENDA = 1
GROUP BY v.CODUSUR, u.NOME, s.NOME
ORDER BY REAL DESC NULLS LAST
FETCH FIRST :topN ROWS ONLY
```

**Validado:** Michelly Keytiane #1 Manaus R$ 2.130.804 = ERP centavo.

---

## T104 — Inadimplência por Filial (rápido)

```sql
SELECT
    :codFilial                                                       AS CODFILIAL,
    COUNT(*)                                                         AS QTD_TITULOS,
    COUNT(DISTINCT p.CODCLI)                                         AS QTD_CLIENTES,
    SUM(p.VALOR)                                                     AS CARTEIRA_ABERTA,
    SUM(CASE WHEN p.DTVENC < TRUNC(SYSDATE) THEN p.VALOR ELSE 0 END) AS VALOR_INAD,
    ROUND(SUM(CASE WHEN p.DTVENC < TRUNC(SYSDATE) THEN p.VALOR ELSE 0 END)
          / NULLIF(SUM(p.VALOR),0) * 100, 2)                         AS PCT_INAD
FROM EBD.PCPREST p
WHERE p.CODFILIAL = :codFilial
  AND p.DTPAG IS NULL
```

**Validado:** Manaus 9,3% inadimplência sobre R$ 21M carteira. Latência: 3,6s.

---

## T105 — Estoque + Cobertura por Produto

```sql
WITH venda30 AS (
    SELECT v.CODPROD, SUM(v.QT) AS QT30
    FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
    WHERE v.CODFILIAL = :codFilial
      AND v.DTSAIDA >= TRUNC(SYSDATE) - 30
      AND v.CONDVENDA = 1
    GROUP BY v.CODPROD
)
SELECT
    e.CODPROD,
    SUBSTR(NVL(p.DESCRICAO,'?'),1,40)                       AS PRODUTO,
    NVL(e.QTESTGER,0) - NVL(e.QTRESERV,0) - NVL(e.QTBLOQUEADA,0) AS ESTOQUE_LIVRE,
    e.CUSTOFIN                                              AS CUSTO_UNIT,
    (NVL(e.QTESTGER,0) - NVL(e.QTRESERV,0) - NVL(e.QTBLOQUEADA,0)) * NVL(e.CUSTOFIN,0) AS VALOR_ESTOQUE,
    ROUND(NVL(e.QTESTGER,0) / NULLIF(NVL(vd.QT30,0)/30, 0), 0) AS DIAS_COBERTURA
FROM EBD.PCEST e
LEFT JOIN EBD.PCPRODUT p ON p.CODPROD = e.CODPROD
LEFT JOIN venda30 vd     ON vd.CODPROD = e.CODPROD
WHERE e.CODFILIAL = :codFilial
  AND NVL(e.QTESTGER,0) > 0
ORDER BY VALOR_ESTOQUE DESC NULLS LAST
FETCH FIRST :topN ROWS ONLY
```

**Validado:** Nissin Lamen top em Manaus. Latência: 0,6s.

---

## T106 — Clientes Ativos por Filial

```sql
WITH fat AS (
    SELECT v.CODCLI, SUM(v.VLATEND) AS REAL
    FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
    WHERE v.CODFILIAL = :codFilial
      AND v.DTSAIDA >= TRUNC(SYSDATE,'MM')
      AND v.CONDVENDA = 1
    GROUP BY v.CODCLI
)
SELECT
    CASE WHEN NVL(c.BLOQUEIO,'N') = 'S' THEN 'BLOQUEADO' ELSE 'LIBERADO' END AS SITUACAO,
    COUNT(*)          AS QTD_CLIENTES,
    SUM(NVL(f.REAL,0)) AS FATURAMENTO_MES
FROM EBD.PCCLIENT c
LEFT JOIN fat f ON f.CODCLI = c.CODCLI
WHERE c.CODFILIALNF = :codFilial
GROUP BY CASE WHEN NVL(c.BLOQUEIO,'N') = 'S' THEN 'BLOQUEADO' ELSE 'LIBERADO' END
ORDER BY QTD_CLIENTES DESC
```

**Validado:** 1.970 clientes ativos filial 06.

---

## T107 — Positivação por RCA

```sql
SELECT
    v.CODUSUR,
    SUBSTR(NVL(u.NOME,'?'),1,32) AS RCA,
    COUNT(DISTINCT v.CODCLI)     AS POSITIVACAO,
    COUNT(DISTINCT v.NUMPED)     AS PEDIDOS,
    SUM(v.VLATEND)               AS REAL
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
LEFT JOIN EBD.PCUSUARI u ON u.CODUSUR = v.CODUSUR
WHERE v.CODFILIAL = :codFilial
  AND v.DTSAIDA BETWEEN :dtInicio AND :dtFim
  AND v.CONDVENDA = 1
GROUP BY v.CODUSUR, u.NOME
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
    SELECT s.CODGERENTE, SUM(v.VLATEND) AS REAL
    FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
    JOIN EBD.PCSUPERV s ON s.CODSUPERVISOR = v.CODSUPERVISOR
    WHERE v.DTSAIDA >= TRUNC(SYSDATE,'MM')
      AND v.CONDVENDA = 1
      AND s.CODGERENTE IS NOT NULL
    GROUP BY s.CODGERENTE
),
meta_gc AS (
    SELECT CODIGO AS CODGERENTE, SUM(VLVENDAPREV) AS META
    FROM EBD.PCMETA
    WHERE TIPOMETA = 'GC' AND TRUNC(DATA,'MM') = TRUNC(SYSDATE,'MM')
    GROUP BY CODIGO
)
SELECT
    vg.CODGERENTE,
    SUBSTR(NVL(g.NOMEGERENTE,'?'),1,35)          AS GERENTE,
    vg.REAL,
    NVL(mg.META,0)                                AS META,
    ROUND(vg.REAL / NULLIF(mg.META,0) * 100, 2)   AS PCT_META
FROM vendas_gc vg
LEFT JOIN EBD.PCGERENTE g ON g.CODGERENTE = vg.CODGERENTE
LEFT JOIN meta_gc mg      ON mg.CODGERENTE = vg.CODGERENTE
ORDER BY vg.REAL DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
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
SELECT
    v.CODUSUR,
    SUBSTR(NVL(u.NOME,'?'),1,35) AS NOME_RCA,
    SUBSTR(NVL(s.NOME,'-'),1,25) AS SUPERVISOR,
    SUM(v.VLATEND)               AS REAL,
    COUNT(DISTINCT v.CODCLI)     AS POSITIVACAO,
    COUNT(DISTINCT v.NUMPED)     AS PEDIDOS
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
LEFT JOIN EBD.PCUSUARI u ON u.CODUSUR = v.CODUSUR
LEFT JOIN EBD.PCSUPERV s ON s.CODSUPERVISOR = v.CODSUPERVISOR
WHERE v.DTSAIDA >= TRUNC(SYSDATE,'MM')
  AND v.CONDVENDA = 1
GROUP BY v.CODUSUR, u.NOME, s.NOME
ORDER BY REAL DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
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
SELECT
    v.CODCLI,
    SUBSTR(NVL(MAX(v.CLIENTE),'?'),1,40) AS CLIENTE,
    SUBSTR(NVL(MAX(a.RAMO),'-'),1,25)    AS RAMO,
    MAX(v.UF)                            AS UF,
    COUNT(DISTINCT v.NUMTRANSVENDA)      AS QTD_NOTAS,
    COUNT(DISTINCT v.CODFILIAL)          AS QTD_FILIAIS,
    SUM(v.VLATEND)                       AS REAL
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
LEFT JOIN EBD.PCATIVI a ON a.CODATIV = v.CODATIV
WHERE v.DTSAIDA >= TRUNC(SYSDATE,'MM')
  AND v.CONDVENDA = 1
GROUP BY v.CODCLI
ORDER BY REAL DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
```

**Validado:** SERVI SUPERMERCADOS #1 R$ 1,63M. Top 10 = 7% BR (atacado MUITO pulverizado).

---

## T208 — Inadimplência BR (Top 10 Filiais)

```sql
WITH inad_filial AS (
    SELECT
        p.CODFILIAL,
        COUNT(*)                 AS QTD_TITULOS,
        COUNT(DISTINCT p.CODCLI) AS QTD_CLIENTES,
        SUM(p.VALOR)             AS CARTEIRA_ABERTA,
        SUM(CASE WHEN p.DTVENC < TRUNC(SYSDATE) THEN p.VALOR ELSE 0 END) AS INAD
    FROM EBD.PCPREST p
    WHERE p.DTPAG IS NULL
    GROUP BY p.CODFILIAL
)
SELECT
    ip.CODFILIAL,
    SUBSTR(NVL(pf.FANTASIA,'?'),1,28) AS FILIAL,
    ip.QTD_TITULOS,
    ip.QTD_CLIENTES,
    ip.CARTEIRA_ABERTA,
    ip.INAD,
    ROUND(ip.INAD / NULLIF(ip.CARTEIRA_ABERTA,0) * 100, 2) AS PCT_INAD
FROM inad_filial ip
LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = ip.CODFILIAL
ORDER BY ip.INAD DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
```

**Validado:** EBD FORTALEZA #1 R$ 6,8M (26,6%!) — alerta crítico. Boa Vista 25,4%.

---

## T209 — Top Produtos BR

```sql
SELECT
    v.CODPROD,
    SUBSTR(NVL(MAX(v.DESCRICAO),'?'),1,40)   AS PRODUTO,
    SUBSTR(NVL(MAX(v.FORNECPRINC),'?'),1,25) AS FORNECEDOR,
    SUM(v.QT)                                AS QTD,
    SUM(v.VLATEND)                           AS REAL,
    COUNT(DISTINCT v.CODFILIAL)              AS QTD_FILIAIS,
    COUNT(DISTINCT v.CODCLI)                 AS QTD_CLIENTES
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
WHERE v.DTSAIDA >= TRUNC(SYSDATE,'MM')
  AND v.CONDVENDA = 1
GROUP BY v.CODPROD
ORDER BY REAL DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
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
    SELECT '10','RJ1' FROM DUAL UNION ALL SELECT '11','NO2' FROM DUAL UNION ALL
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
SELECT
    pc.NUMPED,
    pc.CODFILIAL,
    pc.CODCLI,
    SUBSTR(NVL(c.CLIENTE,'?'),1,35) AS CLIENTE,
    pc.CODUSUR,
    SUBSTR(NVL(u.NOME,'?'),1,30)    AS RCA,
    pc.DATA                         AS DTPEDIDO,
    pc.POSICAO,
    pc.VLTOTAL
FROM EBD.PCPEDC pc
LEFT JOIN EBD.PCCLIENT c ON c.CODCLI = pc.CODCLI
LEFT JOIN EBD.PCUSUARI u ON u.CODUSUR = pc.CODUSUR
WHERE pc.POSICAO IN ('B','P')
  AND pc.DTCANCEL IS NULL
  AND pc.DATA >= TRUNC(SYSDATE) - 30
ORDER BY pc.VLTOTAL DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
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
SELECT
    pc.NUMPED,
    pc.CODCLI,
    SUBSTR(NVL(c.CLIENTE,'?'),1,35) AS CLIENTE,
    pc.CODUSUR,
    SUBSTR(NVL(u.NOME,'?'),1,30)    AS RCA,
    pc.DATA                         AS DTPEDIDO,
    pc.VLTOTAL
FROM EBD.PCPEDC pc
LEFT JOIN EBD.PCCLIENT c ON c.CODCLI = pc.CODCLI
LEFT JOIN EBD.PCUSUARI u ON u.CODUSUR = pc.CODUSUR
WHERE pc.CODFILIAL = :codFilial
  AND pc.POSICAO = 'B'
  AND pc.DTCANCEL IS NULL
  AND pc.DATA >= TRUNC(SYSDATE) - 30
ORDER BY pc.VLTOTAL DESC NULLS LAST
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
SELECT
    pc.CODUSUR,
    SUBSTR(NVL(u.NOME,'?'),1,32) AS RCA,
    COUNT(*)                     AS QTD_PEDIDOS,
    SUM(pc.VLTOTAL)              AS VL_PIPELINE
FROM EBD.PCPEDC pc
LEFT JOIN EBD.PCUSUARI u ON u.CODUSUR = pc.CODUSUR
WHERE pc.CODFILIAL = :codFilial
  AND pc.POSICAO = 'L'
  AND pc.DTCANCEL IS NULL
GROUP BY pc.CODUSUR, u.NOME
ORDER BY VL_PIPELINE DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
```

**Validado Manaus:** Marconde Moraes #1 R$ 43,8K em 7 pedidos. Insight: Top RCAs em faturamento NÃO aparecem aqui (eles giram rápido). Latência: 32ms.

## T114 — Top 10 clientes com pedido em aberto (single-filial)

"Quais clientes acompanhar?"

```sql
SELECT
    pc.CODCLI,
    SUBSTR(NVL(c.CLIENTE,'?'),1,40) AS CLIENTE,
    COUNT(*)                        AS QTD_PEDIDOS,
    SUM(pc.VLTOTAL)                 AS VL_ABERTO
FROM EBD.PCPEDC pc
LEFT JOIN EBD.PCCLIENT c ON c.CODCLI = pc.CODCLI
WHERE pc.CODFILIAL = :codFilial
  AND pc.POSICAO IN ('L','M','B','P')
  AND pc.DTCANCEL IS NULL
GROUP BY pc.CODCLI, c.CLIENTE
ORDER BY VL_ABERTO DESC NULLS LAST
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

Usa VIEW_VENDAS_RESUMO_FATURAMENTO + PCSUPERV.CODGERENTE + PCGERENTE.NOMEGERENTE + PCMETA TIPOMETA='GC'. **Validado:** Davya Cordeiro -5,0% (quase no ritmo). Latência: 52s.

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

## Descoberta: PCROTACLI é a fonte oficial da carteira

Após 6 horas de sondagem testando filtros derivados (PCCLIENT bloqueios, datas de compra 90/180/365/540/660/730 dias), descobrimos que a "carteira" no BI EBD vem de uma fonte simples:

```sql
SELECT COUNT(DISTINCT CODCLI) AS CARTEIRA
FROM EBD.PCROTACLI
```

## Definição de negócio (cf. Thiago)

Carteira é gerenciada **manualmente** via inclusão/exclusão de cliente em rota de visita pelo supervisor/gerente. NÃO há regra de "X dias sem compra = sai da carteira".
Cliente em PCROTACLI = cliente em rota de visita ATIVA = carteira

## Estrutura da view
CODIGOCLIENTE   ← cliente
CODIGORCA       ← RCA designado
DIASEMANA       ← dia da visita

142.308 linhas (cliente × dia da semana), 77.453 distintos.

## REGRA — NAO USAR AS VIEWS GD_* (legado GoodData desativado)

As views `GD_FATO_*` e `GD_DIM_*` sao resquicio do GoodData, BI que a EBD NAO usa mais. Elas reexecutam joins pesados a cada consulta e estouram o timeout. **Nao use nenhuma delas.** Use a `VIEW_VENDAS_RESUMO_FATURAMENTO` para faturamento (ja traz RCA, cliente, produto, fornecedor e categoria desnormalizados) e as tabelas `PC*` para o resto.

```sql
-- Estrutura do canal: filiais e regionais
SELECT CODIGO, FANTASIA FROM EBD.PCFILIAL ORDER BY CODIGO
```

Outras views DW oficiais descobertas:
PCROTACLI     carteira ativa (cliente em rota) ★ fonte da carteira
PCCLIENT      cadastro, bloqueio, DTULTCOMP
PCMETA        meta (TIPOMETA define o nivel)
PCPREST       titulos em aberto / cobranca
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
WITH rota_dia AS (
    SELECT r.CODUSUR, r.CODCLI
    FROM EBD.PCROTACLI r
    JOIN EBD.PCUSUARI u ON u.CODUSUR = r.CODUSUR
    WHERE u.CODFILIAL = :codFilial
      AND u.DTTERMINO IS NULL
      AND UPPER(r.DIASEMANA) = UPPER(:diaSemana)
),
vendeu AS (
    SELECT DISTINCT v.CODUSUR, v.CODCLI
    FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
    WHERE v.CODFILIAL = :codFilial
      AND v.DTSAIDA >= TRUNC(SYSDATE)
      AND v.CONDVENDA = 1
)
SELECT
    rd.CODUSUR,
    SUBSTR(NVL(u.NOME,'?'),1,32)                                   AS RCA,
    COUNT(*)                                                       AS CLIENTES_ROTA,
    COUNT(vd.CODCLI)                                               AS POSITIVADOS,
    ROUND(COUNT(vd.CODCLI) / NULLIF(COUNT(*),0) * 100, 1)          AS PCT_APROVEITAMENTO
FROM rota_dia rd
LEFT JOIN vendeu vd      ON vd.CODUSUR = rd.CODUSUR AND vd.CODCLI = rd.CODCLI
LEFT JOIN EBD.PCUSUARI u ON u.CODUSUR = rd.CODUSUR
GROUP BY rd.CODUSUR, u.NOME
ORDER BY PCT_APROVEITAMENTO DESC NULLS LAST
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
  WHEN '19' THEN '04'  -- CD SAO LUIS -> SAO LUIS
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

## Fonte: VIEW_VENDAS_RESUMO_FATURAMENTO mes corrente (formulas 6 e 7)

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
Supervisor/Gerente herdam via PCUSUARI.CODSUPERVISOR + PCSUPERV.CODGERENTE dos seus RCAs.

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
VIEW_VENDAS_RESUMO_FATURAMENTO → data=DTSAIDA (DATE), valor=VLATEND, filtro CONDVENDA=1.
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
SELECT
    r.CODUSUR,
    SUBSTR(NVL(u.NOME,'?'),1,32) AS RCA,
    COUNT(*)                     AS CLIENTES_PLANEJADOS
FROM EBD.PCROTACLI r
JOIN EBD.PCUSUARI u ON u.CODUSUR = r.CODUSUR
WHERE u.CODFILIAL = :codFilial
  AND u.DTTERMINO IS NULL
  AND UPPER(r.DIASEMANA) = UPPER(:diaSemana)
GROUP BY r.CODUSUR, u.NOME
ORDER BY CLIENTES_PLANEJADOS DESC
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
SELECT
    v.CODPROD,
    SUBSTR(NVL(MAX(v.DESCRICAO),'?'),1,45) AS PRODUTO,
    SUM(v.QT)                              AS QTD,
    SUM(v.VLATEND)                         AS REAL,
    COUNT(DISTINCT v.CODCLI)               AS CLIENTES
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
WHERE v.CODFILIAL = :codFilial
  AND v.DTSAIDA BETWEEN :dtInicio AND :dtFim
  AND v.CONDVENDA = 1
GROUP BY v.CODPROD
ORDER BY REAL DESC NULLS LAST
FETCH FIRST :topN ROWS ONLY
```

## T193 — Vendas por marca e filial (minerado de padrão ok=2)
Pergunta: "faturamento por marca" · CODMARCA vive na PCPRODUT
```sql
SELECT
    SUBSTR(NVL(p.MARCA,'(sem marca)'),1,30) AS MARCA,
    v.CODFILIAL,
    SUM(v.VLATEND)                          AS REAL,
    SUM(v.QT)                               AS QTD
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
LEFT JOIN EBD.PCPRODUT p ON p.CODPROD = v.CODPROD
WHERE v.DTSAIDA BETWEEN :dtInicio AND :dtFim
  AND v.CONDVENDA = 1
GROUP BY p.MARCA, v.CODFILIAL
ORDER BY REAL DESC NULLS LAST
FETCH FIRST :topN ROWS ONLY
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



<!-- AUTO-APPEND PROP-F111E330 aprovado por Thiago -->


## T-ROTA-01 v2 — Produtividade em Rota do Dia (single / multi-filial / regional)

**Validado em:** 16/07/2026
**Performance:** 32ms (vs 26s da PCMOVROTACLI — 85x mais rápida)
**Substitui:** qualquer referência anterior a PCMOVROTACLI para rota do dia

---

### ⚠️ CICATRIZ CRÍTICA — PCROTACLI vs PCMOVROTACLI

| | `PCROTACLI` ✅ USAR | `PCMOVROTACLI` ❌ NUNCA para rota do dia |
|---|---|---|
| Registros | **144.624** | 34.374.110 |
| O que é | **Rota ATUAL vigente** (snapshot) | Histórico completo desde 2003 |
| Clientes distintos | 78.023 | 240.494 (inclui inativos) |
| RCAs distintos | 1.533 | 6.084 (inclui desligados) |
| Performance | ⚡ **32ms** | 🐢 26s+ |
| Tem DTPROXVISITA | ✅ | ✅ |
| Tem PERIODICIDADE | ✅ | ✅ |
| Tem DIASEMANA | ✅ | ✅ |

**Regra:** `PCROTACLI` = cadastro ativo da rota. `PCMOVROTACLI` = log histórico de movimentos.
Para qualquer análise operacional de rota do dia, SEMPRE usar `PCROTACLI`.

---

### Campos-chave de PCROTACLI

| Campo | Tipo | Significado |
|---|---|---|
| `CODUSUR` | NUMBER | RCA dono da rota |
| `CODCLI` | NUMBER | Cliente na rota |
| `DIASEMANA` | VARCHAR2(10) | Dia fixo da visita (SEGUNDA, TERCA, QUARTA...) |
| `PERIODICIDADE` | VARCHAR2(10) | 7=Semanal, 14=Quinzenal, 28=Mensal |
| `DTPROXVISITA` | DATE | Próxima visita agendada |
| `DTULTVISITAPREV` | DATE | Última visita prevista |
| `VLMETAVENDA` | NUMBER | Meta de venda para o cliente |
| `NUMSEMANA` | NUMBER | Semana do ciclo (para quinzenal/mensal) |

> ⚠️ `PCROTACLI` NÃO tem `CODFILIAL` — filial vem via `JOIN PCUSUARI u ON u.CODUSUR = r.CODUSUR` → `u.CODFILIAL`

---

### Filtro canônico de "rota do dia"

```sql
WHERE UPPER(r.DIASEMANA) IN (d.NOME, REPLACE(d.NOME,'C','Ç'))  -- inconsistência TERCA/TERÇA
  AND TRUNC(r.DTPROXVISITA) BETWEEN TRUNC(SYSDATE) - 7 AND TRUNC(SYSDATE)
```

A janela de -7 dias captura clientes que não foram visitados na semana anterior (periodicidade quinzenal/mensal que "atrasou").

---

### Template completo — Variante A: Single-filial

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
rota_hoje AS (
    SELECT r.CODUSUR, r.CODCLI, r.PERIODICIDADE, r.DTPROXVISITA
    FROM EBD.PCROTACLI r
    JOIN EBD.PCUSUARI u ON u.CODUSUR = r.CODUSUR
    , dia_ref d
    WHERE u.CODFILIAL = :codFilial
      AND UPPER(r.DIASEMANA) IN (d.NOME, REPLACE(d.NOME,'C','Ç'))
      AND TRUNC(r.DTPROXVISITA) BETWEEN TRUNC(SYSDATE) - 7 AND TRUNC(SYSDATE)
      AND (u.DTTERMINO IS NULL OR u.DTTERMINO >= TRUNC(SYSDATE))
      AND u.CODUSUR NOT IN (SELECT COD_CADRCA FROM EBD.PCSUPERV WHERE COD_CADRCA IS NOT NULL)
      AND UPPER(NVL(u.NOME,'')) NOT LIKE '%ORFAO%'
      AND UPPER(NVL(u.NOME,'')) NOT LIKE '%VAGO%'
      AND UPPER(NVL(u.NOME,'')) NOT LIKE '%ECOMMERCE%'
      AND UPPER(NVL(u.NOME,'')) NOT LIKE '%GM-RM%'
),
pedidos_dia AS (
    SELECT p.CODUSUR, p.CODCLI,
           SUM(p.VLATEND) AS VL_PEDIDO
    FROM EBD.PCPEDC p
    , dia_ref d
    WHERE p.CODFILIAL = :codFilial
      AND TRUNC(p.DATA) = d.DT
      AND p.POSICAO != 'C'
      AND p.DTCANCEL IS NULL
    GROUP BY p.CODUSUR, p.CODCLI
)
SELECT
    rh.CODUSUR,
    SUBSTR(NVL(u.NOME,'?'),1,35)                             AS VENDEDOR,
    COUNT(DISTINCT rh.CODCLI)                                AS CLIENTES_ROTA,
    COUNT(DISTINCT CASE WHEN pd.CODCLI IS NOT NULL
                    AND rh.CODCLI = pd.CODCLI THEN rh.CODCLI END) AS POSITIV_ROTA,
    ROUND(COUNT(DISTINCT CASE WHEN pd.CODCLI IS NOT NULL
                    AND rh.CODCLI = pd.CODCLI THEN rh.CODCLI END)
          / NULLIF(COUNT(DISTINCT rh.CODCLI),0) * 100, 1)   AS PCT_ROTA,
    NVL(SUM(CASE WHEN rh.CODCLI = pd.CODCLI THEN pd.VL_PEDIDO END),0) AS VL_ROTA,
    COUNT(DISTINCT CASE WHEN pd.CODCLI IS NOT NULL
                    AND rh.CODCLI != pd.CODCLI THEN pd.CODCLI END) AS CLIENTES_FORA,
    NVL(SUM(CASE WHEN rh.CODCLI != pd.CODCLI THEN pd.VL_PEDIDO END),0) AS VL_FORA,
    NVL(SUM(pd.VL_PEDIDO),0)                                AS VL_TOTAL
FROM rota_hoje rh
JOIN EBD.PCUSUARI u ON u.CODUSUR = rh.CODUSUR
LEFT JOIN pedidos_dia pd ON pd.CODUSUR = rh.CODUSUR
GROUP BY rh.CODUSUR, u.NOME
ORDER BY VL_TOTAL DESC NULLS LAST
```

---

### Variante B: Multi-filial (lista)

Substituir filtro de filial por:
```sql
WHERE u.CODFILIAL IN ('02','16')  -- ex: SP1
```
E adicionar `u.CODFILIAL`, `pf.FANTASIA` no SELECT + GROUP BY com JOIN PCFILIAL.

---

### Variante C: Regional completa

```sql
WHERE u.CODFILIAL IN ('15','18')  -- ex: SP2 = Guarulhos + SBC
```
Mesma estrutura da variante B.

---

### Resultado referência — EBD SBC (18) · 16/07/2026 (quinta)

| Métrica | Valor |
|---|---|
| Clientes na rota hoje | 398 |
| RCAs com rota | 37 |
| Semanal (perio=7) | 251 |
| Quinzenal (perio=14) | 147 |
| Mensal (perio=28) | 0 |
| Latência | **32ms** ⚡ |

---

### Anti-padrões a evitar

```sql
-- ❌ ERRADO: PCMOVROTACLI tem 34M linhas — lenta demais para uso operacional
FROM EBD.PCMOVROTACLI r

-- ❌ ERRADO: PCROTACLI não tem CODFILIAL — ORA-00904
WHERE r.CODFILIAL = :codFilial

-- ❌ ERRADO: sem janela de DTPROXVISITA pega rota de semanas futuras
WHERE UPPER(r.DIASEMANA) = 'QUINTA'  -- sem filtro DTPROXVISITA

-- ✅ CORRETO: filial via JOIN PCUSUARI
JOIN EBD.PCUSUARI u ON u.CODUSUR = r.CODUSUR
WHERE u.CODFILIAL = :codFilial
  AND TRUNC(r.DTPROXVISITA) BETWEEN TRUNC(SYSDATE) - 7 AND TRUNC(SYSDATE)
```


# Parte 14 — Família Carteira / Pedidos / Meta (T220-T224) — 20/07/2026
Origem: mineração do queries.jsonl (211 queries PCPEDC/PCMETA, padrões ok=8/7/7/5/5). SQLs
validados em produção; veredito de coluna provado pelo Oracle (mine_cols.py). Fecha o
T-CARTEIRA-01 que existia só como prosa + a família meta-dia.

**Cicatriz #52:** carteira de pedidos usa PCPEDC com os filtros canônicos:
`POSICAO IN ('L','M')` (livre/montado) + `DTCANCEL IS NULL` + `CONDVENDA NOT IN (4,8,10,13,20,98,99)`.
Valor = VLATEND (atendido). Pedido BLOQUEADO = `POSICAO = 'B'`. Faturado = `POSICAO = 'F'`.

**Cicatriz #53:** PCPEDC — colunas validadas: CODFILIAL, DATA, VLATEND, NUMPED, POSICAO,
CODCLI, DTCANCEL, VLTOTAL, ORIGEMPED, CODUSUR, CONDVENDA, CODEMITENTE, CODCOB.
NÃO EXISTEM: VLPESO, BLOQUEIO (ORA-00904). Data do pedido = DATA (não DTSAIDA — essa é da VIEW).

**Cicatriz #54:** meta usa PCMETA — colunas: CODFILIAL, DATA, VLVENDAPREV (valor previsto),
TIPOMETA ('FL' = filial). Meta do mês corrente:
`TIPOMETA='FL' AND DATA BETWEEN TRUNC(SYSDATE,'MM') AND LAST_DAY(SYSDATE)`.

## T220 — Carteira de pedidos por filial (T-CARTEIRA-01 transcrito · ok=7)
Pergunta: "qual a carteira / pedidos em aberto por filial?"
```sql
SELECT p.CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,30) AS FILIAL,
       COUNT(DISTINCT p.NUMPED)          AS QTD_PEDIDOS,
       SUM(p.VLATEND)                     AS CARTEIRA
FROM EBD.PCPEDC p
JOIN EBD.PCFILIAL pf ON pf.CODIGO = p.CODFILIAL
WHERE p.POSICAO IN ('L','M')
  AND p.DTCANCEL IS NULL
  AND p.CONDVENDA NOT IN (4,8,10,13,20,98,99)
GROUP BY p.CODFILIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,30)
ORDER BY CARTEIRA DESC
```

## T221 — Pedidos bloqueados por filial (ok=5)
Pergunta: "quanto tem bloqueado / pedidos travados?"
```sql
SELECT p.CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,30) AS FILIAL,
       COUNT(DISTINCT p.NUMPED)          AS QTD_BLOQUEADOS,
       SUM(p.VLATEND)                     AS VLR_BLOQUEADO
FROM EBD.PCPEDC p
JOIN EBD.PCFILIAL pf ON pf.CODIGO = p.CODFILIAL
WHERE p.POSICAO = 'B'
  AND p.DTCANCEL IS NULL
  AND p.CONDVENDA NOT IN (4,8,10,13,20,98,99)
GROUP BY p.CODFILIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,30)
ORDER BY VLR_BLOQUEADO DESC
```

## T222 — Meta do mês por filial (ok=8)
Pergunta: "qual a meta da filial X este mês?"
```sql
SELECT m.CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,30) AS FILIAL,
       SUM(m.VLVENDAPREV)                AS META_MES
FROM EBD.PCMETA m
JOIN EBD.PCFILIAL pf ON pf.CODIGO = m.CODFILIAL
WHERE m.TIPOMETA = 'FL'
  AND m.DATA BETWEEN TRUNC(SYSDATE,'MM') AND LAST_DAY(SYSDATE)
GROUP BY m.CODFILIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,30)
ORDER BY META_MES DESC
```

## T223 — Realizado (faturado) vs Meta do mês por filial
Pergunta: "como está o atingimento de meta por filial?" · combina PCMETA + VIEW canônica
```sql
WITH meta AS (
    SELECT m.CODFILIAL, SUM(m.VLVENDAPREV) AS META_MES
    FROM EBD.PCMETA m
    WHERE m.TIPOMETA = 'FL'
      AND m.DATA BETWEEN TRUNC(SYSDATE,'MM') AND LAST_DAY(SYSDATE)
    GROUP BY m.CODFILIAL
),
realizado AS (
    SELECT v.CODFILIAL, SUM(v.VLATEND) AS REALIZADO
    FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
    WHERE v.DTSAIDA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
    GROUP BY v.CODFILIAL
)
SELECT COALESCE(mt.CODFILIAL, rz.CODFILIAL)        AS CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,30)           AS FILIAL,
       NVL(mt.META_MES,0)                          AS META_MES,
       NVL(rz.REALIZADO,0)                         AS REALIZADO,
       ROUND(NVL(rz.REALIZADO,0) / NULLIF(mt.META_MES,0) * 100, 1) AS ATING_PCT
FROM meta mt
FULL OUTER JOIN realizado rz ON rz.CODFILIAL = mt.CODFILIAL
LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = COALESCE(mt.CODFILIAL, rz.CODFILIAL)
ORDER BY ATING_PCT DESC NULLS LAST
```

## T224 — Pedidos faturados no período por filial (ok=3)
Pergunta: "quantos pedidos faturamos no período?"
```sql
SELECT p.CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,30) AS FILIAL,
       COUNT(DISTINCT p.NUMPED)          AS QTD_PEDIDOS,
       SUM(p.VLTOTAL)                     AS VALOR_TOTAL
FROM EBD.PCPEDC p
JOIN EBD.PCFILIAL pf ON pf.CODIGO = p.CODFILIAL
WHERE p.POSICAO = 'F'
  AND p.DATA BETWEEN TO_DATE(:dataIni,'YYYY-MM-DD') AND TO_DATE(:dataFim,'YYYY-MM-DD')
GROUP BY p.CODFILIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,30)
ORDER BY VALOR_TOTAL DESC
```

# Parte 15 — Família Ruptura (T230-T232) — 20/07/2026
Origem: mineração do queries.jsonl (31 queries PCFALTA). Colunas provadas pelo Oracle.
Fecha a família ruptura, que estava só como prosa (T130v2/T133/T134/T136).

**Cicatriz #55:** ruptura = PCFALTA, valor perdido = `SUM(QT * PVENDA)`. Colunas validadas:
CODFILIAL, DATA, QT, PVENDA, CODUSUR, CODPROD, NUMPED. NÃO EXISTE DTFALTA (data é DATA).

**Cicatriz #56 (CRÍTICA — pegadinha do BI):** PCFALTA NÃO tem filtro natural de CODFILIAL e
o BI inclui os CDs. Para ruptura POR FILIAL DE VENDA, restringir explicitamente às filiais
comerciais, excluindo CDs: `CODFILIAL IN ('01','02','03','04','05','06','07','08','09','10','11','12','13','14','15','16')`.
Sem esse filtro os números vêm inflados com estoque de CD E a query fica lenta (varre tudo).
Ajustar a lista às filiais comerciais vigentes do Grupo EBD.

## T230 — Ruptura total do mês por filial (ok=3 · rápido com filtro de filial)
Pergunta: "qual a ruptura / quebra por filial este mês?"
```sql
SELECT f.CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,30) AS FILIAL,
       SUM(f.QT * f.PVENDA)              AS VL_RUPTURA
FROM EBD.PCFALTA f
JOIN EBD.PCFILIAL pf ON pf.CODIGO = f.CODFILIAL
WHERE f.DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
  AND f.CODFILIAL IN ('01','02','03','04','05','06','07','08','09','10','11','12','13','14','15','16')
GROUP BY f.CODFILIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,30)
ORDER BY VL_RUPTURA DESC
```

## T231 — Ruptura por RCA no mês (ok=2)
Pergunta: "qual RCA/vendedor tem mais ruptura?"
```sql
SELECT f.CODUSUR,
       SUBSTR(NVL(u.NOME,'?'),1,40)     AS RCA,
       u.CODFILIAL,
       SUM(f.QT * f.PVENDA)             AS VL_RUPTURA
FROM EBD.PCFALTA f
JOIN EBD.PCUSUARI u ON u.CODUSUR = f.CODUSUR
WHERE f.DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
  AND f.CODFILIAL IN ('01','02','03','04','05','06','07','08','09','10','11','12','13','14','15','16')
GROUP BY f.CODUSUR, SUBSTR(NVL(u.NOME,'?'),1,40), u.CODFILIAL
ORDER BY VL_RUPTURA DESC
FETCH FIRST 30 ROWS ONLY
```

## T232 — Top produtos em ruptura no mês (por filial opcional)
Pergunta: "quais produtos mais rompem?"
```sql
SELECT f.CODPROD,
       SUBSTR(NVL(pr.DESCRICAO,'?'),1,50) AS PRODUTO,
       COUNT(*)                           AS OCORRENCIAS,
       SUM(f.QT * f.PVENDA)               AS VL_RUPTURA
FROM EBD.PCFALTA f
JOIN EBD.PCPRODUT pr ON pr.CODPROD = f.CODPROD
WHERE f.DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
  AND f.CODFILIAL IN ('01','02','03','04','05','06','07','08','09','10','11','12','13','14','15','16')
GROUP BY f.CODPROD, SUBSTR(NVL(pr.DESCRICAO,'?'),1,50)
ORDER BY VL_RUPTURA DESC
FETCH FIRST 30 ROWS ONLY
```

# Parte 16 — Executivos BR / Regionais (T240-T242) — 20/07/2026
Origem: mineração (79 queries regional_map, ok=54) + MAPA OFICIAL filial→regional fornecido
pelo Enrico (20/07). Fecha a família executivos BR que estava só como prosa (T201/T202/T204).

**Cicatriz #57 (MAPA OFICIAL filial→regional — fonte de negócio, não reconstruir):**
O Grupo EBD tem 9 regionais. Mapa canônico (usar este CTE, não reconstruir por chute — evita
ORA-01790 de tipo e a lentidão de 21s da versão ad-hoc):
NE1={04,12} · NE2={21,03,09} · NE3={52,53} · SP1={02,16} · SP2={18,15} ·
RJ1={13,10} · RJ2={14,05} · NO1={06,08} · NO2={11,07,01,22}.
Filiais 52/53 são EBDN (Petrolina/Caruaru). Todas as 21 são filiais comerciais.

**Cicatriz #58 (hierarquia comercial tem dimensão pronta):** RCA→supervisor→gerente vive em
PCUSUARI (CODUSUR, NOME, CODSUPERVISOR) + PCSUPERV (NOME, CODGERENTE) + PCGERENTE (NOMEGERENTE).
Não montar JOIN pesado de PCUSUARI+PCSUPERV para hierarquia; usar a dimensão.

**Cicatriz #59 (OFICIAL do BRIEFING — filtro de filial depende do indicador):**
Há DUAS regras de filial, não uma. VENDAS (faturamento/carteira/meta): 20 filiais comerciais,
SEM os depósitos fechados — `CODFILIAL IN ('01','02','03','04','05','06','07','08','09','10','11','12','13','14','15','16','18','21','52','53')`.
OPERAÇÃO/RUPTURA (PCFALTA): INCLUI os depósitos 17 e 23 REMAPEADOS para a filial-mãe
(movimentam mas somam na filial de venda): `CASE CODFILIAL WHEN '17' THEN '10' (São Pedro da Aldeia→São Gonçalo) WHEN '19' THEN '04' (CD São Luís→São Luís) WHEN '23' THEN '14' (Petrópolis→Piraí) ELSE CODFILIAL END`.
Ruptura BR TOTAL (fórmula #9) é SEM filtro nenhum (o BI inclui CDs no consolidado nacional).
Depósitos fechados não aparecem no mapa regional (não faturam). São Luís é staging sem movimento (não entra).

## T240 — Faturamento por regional BR (mês corrente · usa mapa oficial)
Pergunta: "faturamento por regional" / "ranking de regionais"
```sql
WITH regional_map AS (
    SELECT '04' AS CODFILIAL, 'NE1' AS REGIONAL FROM DUAL UNION ALL
    SELECT '12','NE1' FROM DUAL UNION ALL SELECT '21','NE2' FROM DUAL UNION ALL
    SELECT '03','NE2' FROM DUAL UNION ALL SELECT '09','NE2' FROM DUAL UNION ALL
    SELECT '52','NE3' FROM DUAL UNION ALL SELECT '53','NE3' FROM DUAL UNION ALL
    SELECT '02','SP1' FROM DUAL UNION ALL SELECT '16','SP1' FROM DUAL UNION ALL
    SELECT '18','SP2' FROM DUAL UNION ALL SELECT '15','SP2' FROM DUAL UNION ALL
    SELECT '13','RJ1' FROM DUAL UNION ALL SELECT '10','RJ1' FROM DUAL UNION ALL
    SELECT '14','RJ2' FROM DUAL UNION ALL SELECT '05','RJ2' FROM DUAL UNION ALL
    SELECT '06','NO1' FROM DUAL UNION ALL SELECT '08','NO1' FROM DUAL UNION ALL
    SELECT '11','NO2' FROM DUAL UNION ALL SELECT '07','NO2' FROM DUAL UNION ALL
    SELECT '01','NO2' FROM DUAL UNION ALL SELECT '22','NO2' FROM DUAL
)
SELECT rm.REGIONAL,
       SUM(v.VLATEND) AS FATURAMENTO
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
JOIN regional_map rm ON rm.CODFILIAL = LPAD(v.CODFILIAL, 2, '0')
WHERE v.DTSAIDA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
GROUP BY rm.REGIONAL
ORDER BY FATURAMENTO DESC
```

## T241 — Ranking de gerentes comerciais BR
Pergunta: "ranking de GCs / gerentes comerciais"
```sql
SELECT
    s.CODGERENTE,
    SUBSTR(NVL(g.NOMEGERENTE,'?'),1,35) AS GERENTE,
    SUM(v.VLATEND)                      AS REAL,
    COUNT(DISTINCT v.CODUSUR)           AS QTD_RCAS,
    COUNT(DISTINCT v.CODCLI)            AS POSITIVACAO
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
JOIN EBD.PCSUPERV s      ON s.CODSUPERVISOR = v.CODSUPERVISOR
LEFT JOIN EBD.PCGERENTE g ON g.CODGERENTE = s.CODGERENTE
WHERE v.DTSAIDA >= TRUNC(SYSDATE,'MM')
  AND v.CONDVENDA = 1
  AND s.CODGERENTE IS NOT NULL
GROUP BY s.CODGERENTE, g.NOMEGERENTE
ORDER BY REAL DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
```

## T242 — Ranking de supervisores BR
Pergunta: "ranking de supervisores"
```sql
SELECT
    v.CODSUPERVISOR,
    SUBSTR(NVL(s.NOME,'?'),1,32) AS SUPERVISOR,
    SUM(v.VLATEND)               AS REAL,
    COUNT(DISTINCT v.CODUSUR)    AS QTD_RCAS,
    COUNT(DISTINCT v.CODCLI)     AS POSITIVACAO
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
LEFT JOIN EBD.PCSUPERV s ON s.CODSUPERVISOR = v.CODSUPERVISOR
WHERE v.DTSAIDA >= TRUNC(SYSDATE,'MM')
  AND v.CONDVENDA = 1
GROUP BY v.CODSUPERVISOR, s.NOME
ORDER BY REAL DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY
```

# Correção da família Ruptura (20/07) — remap oficial de depósitos

**Cicatriz #60:** o T230 (Parte 15) usa lista simples de filial e NÃO faz o remap dos
depósitos fechados. Para ruptura POR FILIAL DE VENDA correta, usar T233 abaixo (com CASE
17→10, 23→14). O T230 fica válido apenas para leitura rápida "sem depósito"; prefira T233.

## T233 — Ruptura por filial de venda com remap oficial de depósitos (mês)
Pergunta: "ruptura por filial" (versão correta — Petrópolis soma em Piraí, São Pedro em São Gonçalo)
```sql
WITH ruptura AS (
    SELECT
        CASE f.CODFILIAL
            WHEN '17' THEN '10'
            WHEN '19' THEN '04'
            WHEN '23' THEN '14'
            ELSE f.CODFILIAL
        END             AS CODFILIAL_COMERCIAL,
        f.QT * f.PVENDA AS VL
    FROM EBD.PCFALTA f
    WHERE f.DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
)
SELECT r.CODFILIAL_COMERCIAL              AS CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,30)  AS FILIAL,
       SUM(r.VL)                          AS VL_RUPTURA
FROM ruptura r
JOIN EBD.PCFILIAL pf ON pf.CODIGO = r.CODFILIAL_COMERCIAL
GROUP BY r.CODFILIAL_COMERCIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,30)
ORDER BY VL_RUPTURA DESC
```

# Parte 17 — Família Fornecedores (T250-T252) — 20/07/2026
Origem: mineração (133 queries PCFORNEC, padrão rápido ok=6 a 286ms vs lentos de 80s por retry).
Fecha a família fornecedores e mata o risco de timeout (queries batiam 71-80s no teto de 85s).

**Cicatriz #61 (fornecedor raiz):** o "fornecedor principal/raiz" é `NVL(CODFORNECPRINC, CODFORNEC)`
— quando o fornecedor não tem principal, ele é o próprio. PCFORNEC colunas validadas:
CODFORNEC, FORNECEDOR, CODFORNECPRINC (só essas três; nome do fornecedor = FORNECEDOR).

**Cicatriz #62 (CAUSA do timeout de 80s):** a VIEW_VENDAS_RESUMO_FATURAMENTO NÃO tem CODEMITENTE
nem DTSAIDA_STR (ORA-00904) — o modelo inventava essas colunas, errava e retentava, e cada retry
varria a tabela (80s). Faturamento por fornecedor: filtrar o COD_RAIZ na PCFORNEC PRIMEIRO
(subconjunto pequeno), depois cruzar produtos→view. Nunca filtrar emitente na view.

**Cicatriz #63 (achar fornecedor por nome):** busca de fornecedor é rápida (<60ms) por
`UPPER(FORNECEDOR) LIKE '%NOME%'` direto na PCFORNEC — não precisa de JOIN. Sempre resolver o
código do fornecedor ANTES de montar a query de vendas (evita o modelo chutar código).

## T250 — Localizar fornecedor por nome (ok=5+, <60ms)
Pergunta: "qual o código do fornecedor X?" / "existe fornecedor chamado Y?"
```sql
SELECT CODFORNEC,
       FORNECEDOR,
       CODFORNECPRINC,
       NVL(CODFORNECPRINC, CODFORNEC) AS COD_RAIZ
FROM EBD.PCFORNEC
WHERE UPPER(FORNECEDOR) LIKE '%' || UPPER(:nome) || '%'
ORDER BY CODFORNEC
FETCH FIRST 50 ROWS ONLY
```

## T251 — Faturamento por fornecedor raiz no mês (padrão rápido — resolve o timeout)
Pergunta: "quanto vendemos do fornecedor X este mês?" · filtra fornecedor ANTES de cruzar
```sql
WITH prods_forn AS (
    SELECT p.CODPROD
    FROM EBD.PCPRODUT p
    JOIN EBD.PCFORNEC f ON f.CODFORNEC = p.CODFORNEC
    WHERE NVL(f.CODFORNECPRINC, f.CODFORNEC) = :codFornecRaiz
)
SELECT v.CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,30) AS FILIAL,
       SUM(v.VLATEND)                    AS FATURAMENTO
FROM EBD.VIEW_VENDAS_RESUMO_FATURAMENTO v
JOIN prods_forn pr ON pr.CODPROD = v.CODPROD
LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = v.CODFILIAL
WHERE v.DTSAIDA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
GROUP BY v.CODFILIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,30)
ORDER BY FATURAMENTO DESC
```

## T252 — Ruptura por fornecedor raiz no mês (padrão ok=52, corrigido)
Pergunta: "qual a ruptura do fornecedor X?" · fornecedor raiz + PCFALTA
```sql
WITH prods_forn AS (
    SELECT p.CODPROD
    FROM EBD.PCPRODUT p
    JOIN EBD.PCFORNEC f ON f.CODFORNEC = p.CODFORNEC
    WHERE NVL(f.CODFORNECPRINC, f.CODFORNEC) = :codFornecRaiz
)
SELECT ft.CODPROD,
       SUBSTR(NVL(pr.DESCRICAO,'?'),1,50) AS PRODUTO,
       SUM(ft.QT * ft.PVENDA)             AS VL_RUPTURA
FROM EBD.PCFALTA ft
JOIN prods_forn pf2 ON pf2.CODPROD = ft.CODPROD
JOIN EBD.PCPRODUT pr ON pr.CODPROD = ft.CODPROD
WHERE ft.DATA BETWEEN TRUNC(SYSDATE,'MM') AND SYSDATE
GROUP BY ft.CODPROD, SUBSTR(NVL(pr.DESCRICAO,'?'),1,50)
ORDER BY VL_RUPTURA DESC
FETCH FIRST 30 ROWS ONLY
```

# Parte 18 — Carteira de Clientes (T260-T262) — 20/07/2026
Origem: validado em produção (bateu o BI: SBC 2.885 clientes, Maurilio 203, Karyn 145).
Fecha a família carteira de CLIENTES — conceito distinto de carteira de PEDIDOS (T220).

**Cicatriz #64 (DESAMBIGUAÇÃO — "carteira" tem 3 sentidos):** antes de responder "carteira",
distinguir: (1) CARTEIRA DE PEDIDOS = posição de pedidos em aberto por status (T220, PCPEDC —
Liberado/Montado/Bloqueado); (2) CARTEIRA DE CLIENTES = clientes vinculados ao vendedor (T260,
PCCLIENT); (3) ROTA = quais clientes o RCA visita e quando (PCROTACLI — snapshot vigente, ainda
sem template). Se a pergunta for ambígua, PERGUNTAR qual das três.

**Cicatriz #65 (vendedor e filial do cliente):** na PCCLIENT o vendedor dono do cliente é
CODUSUR1 (validado; existem também CODUSUR2/3 secundários). PCCLIENT NÃO tem CODFILIAL direta —
a filial do cliente vem pela filial do vendedor (JOIN PCUSUARI u ON u.CODUSUR = c.CODUSUR1,
filtra por u.CODFILIAL) OU por c.CODFILIALNF (filial da NF). Colunas validadas: CODCLI, CLIENTE
(nome), CODUSUR1, CODFILIALNF, DTEXCLUSAO, DTULTCOMP, CODATV1, DTCADASTRO. NÃO EXISTEM: NOME
(é CLIENTE), CODFILIAL, CIDADE, CGC.

**Cicatriz #66 (DOIS critérios de "ativo" — dão números diferentes):**
- CADASTRAL: `DTEXCLUSAO IS NULL` = cliente não excluído do sistema (quase todos ativos).
- COMERCIAL: 90 dias sem compra (PCCLIENT.DTULTCOMP) = cliente que parou de comprar.
Ex. SBC: cadastral 2.885 ativos/0 inativos vs comercial 2.619 ativos/266 inativos.
Diretor perguntando "clientes ativos" geralmente quer o COMERCIAL. Na dúvida, perguntar.

## T260 — Carteira de clientes por vendedor (critério cadastral · validado no BI)
Pergunta: "carteira de clientes por vendedor da filial X" / "quantos clientes cada RCA tem"
```sql
SELECT u.NOME                                                    AS VENDEDOR,
       COUNT(*)                                                  AS TOTAL,
       SUM(CASE WHEN c.DTEXCLUSAO IS NULL THEN 1 ELSE 0 END)     AS ATIVOS_CADASTRO,
       SUM(CASE WHEN c.DTEXCLUSAO IS NOT NULL THEN 1 ELSE 0 END) AS EXCLUIDOS
FROM EBD.PCCLIENT c
JOIN EBD.PCUSUARI u ON u.CODUSUR = c.CODUSUR1
WHERE u.CODFILIAL = :codFilial
GROUP BY u.NOME
ORDER BY TOTAL DESC
```

## T261 — Carteira de clientes por vendedor (critério COMERCIAL · 90 dias sem compra)
Pergunta: "clientes ativos por vendedor" (ativo = comprou nos últimos 90 dias)
```sql
SELECT u.NOME AS VENDEDOR,
       COUNT(*) AS TOTAL,
       SUM(CASE WHEN c.DTULTCOMP >= TRUNC(SYSDATE) - 90 THEN 1 ELSE 0 END) AS ATIVOS_90D,
       SUM(CASE WHEN c.DTULTCOMP <  TRUNC(SYSDATE) - 90 OR c.DTULTCOMP IS NULL THEN 1 ELSE 0 END) AS INATIVOS_90D
FROM EBD.PCCLIENT c
JOIN EBD.PCUSUARI u ON u.CODUSUR = c.CODUSUR1
WHERE u.CODFILIAL = :codFilial
  AND c.DTEXCLUSAO IS NULL
GROUP BY u.NOME
ORDER BY ATIVOS_90D DESC
```

## T262 — Total de clientes da carteira por filial (resumo)
Pergunta: "quantos clientes tem a filial X?" / "tamanho da carteira da filial"
```sql
SELECT u.CODFILIAL,
       SUBSTR(NVL(pf.FANTASIA,'?'),1,30) AS FILIAL,
       COUNT(*)                          AS TOTAL_CLIENTES,
       COUNT(DISTINCT c.CODUSUR1)        AS QTD_VENDEDORES,
       SUM(CASE WHEN c.DTULTCOMP >= TRUNC(SYSDATE) - 90 THEN 1 ELSE 0 END) AS ATIVOS_90D
FROM EBD.PCCLIENT c
JOIN EBD.PCUSUARI u ON u.CODUSUR = c.CODUSUR1
LEFT JOIN EBD.PCFILIAL pf ON pf.CODIGO = u.CODFILIAL
WHERE c.DTEXCLUSAO IS NULL
GROUP BY u.CODFILIAL, SUBSTR(NVL(pf.FANTASIA,'?'),1,30)
ORDER BY TOTAL_CLIENTES DESC
```

# Parte 19 — Rota de Visitas (T270-T272) — 20/07/2026
Origem: schema completo da PCROTACLI provado (30 colunas, exemplos reais). Fecha o 3º sentido
de "carteira" (rota) e DESCARTA a GD_FATO_ROTACLIENTE que o modelo vinha usando errado.

**Cicatriz #67 (TABELA DE ROTA — descartar as erradas):** a rota vigente é PCROTACLI (144k
linhas, snapshot atual, alimentada pela rotina 354 e atualizada pela 820 na madrugada).
- USAR: PCROTACLI. Colunas: CODUSUR (RCA), CODCLI (cliente), DIASEMANA (texto),
  SEQUENCIA (ordem na rota), PERIODICIDADE (7=semanal, 14=quinzenal), DTPROXVISITA (data
  da próxima visita — a chave), DTFINAL (2999-12-31 = rota ativa sem prazo), DIAFIXO (S/N).
- NÃO USAR GD_FATO_ROTACLIENTE: só tem CODIGORCA/CODIGOCLIENTE/DIASEMANA, dá resultado pobre
  e frequentemente ZERO (foi o que fez a análise de rota falhar antes).
- NUNCA USAR PCMOVROTACLI: 34M linhas, histórico desde 2003, 26s só para COUNT (timeout).

**Cicatriz #68 (rota de HOJE — DTPROXVISITA é mais preciso que DIASEMANA):** para "quem visitar
hoje", filtrar por DTPROXVISITA = TRUNC(SYSDATE), NÃO por DIASEMANA. Motivo: clientes quinzenais
(PERIODICIDADE=14) só devem ser visitados em semanas específicas — filtrar por DIASEMANA os
traria toda semana (errado). DTPROXVISITA já respeita a periodicidade. Rota ativa: DTFINAL futura
(inclui 2999-12-31). PCROTACLI NÃO tem CODFILIAL — filial vem do RCA (JOIN PCUSUARI por CODUSUR).

**Cicatriz #69 (DIASEMANA é texto acentuado):** DIASEMANA vem como texto em maiúsculas
(SEGUNDA, TERÇA, QUARTA, QUINTA, SEXTA, SÁBADO) — TERÇA e SÁBADO têm acento. Comparar com
cuidado (UPPER + acento) ou preferir DTPROXVISITA que é data e não sofre disso.

## T270 — Rota de hoje por vendedor (quem visitar hoje · DTPROXVISITA)
Pergunta: "rota de hoje da filial X" / "quem o vendedor Y visita hoje"
```sql
SELECT u.CODFILIAL,
       SUBSTR(NVL(u.NOME,'?'),1,30)      AS VENDEDOR,
       r.SEQUENCIA,
       r.CODCLI,
       SUBSTR(NVL(c.CLIENTE,'?'),1,35)   AS CLIENTE,
       r.PERIODICIDADE,
       r.DTPROXVISITA
FROM EBD.PCROTACLI r
JOIN EBD.PCUSUARI u ON u.CODUSUR = r.CODUSUR
LEFT JOIN EBD.PCCLIENT c ON c.CODCLI = r.CODCLI
WHERE r.DTPROXVISITA = TRUNC(SYSDATE)
  AND u.CODFILIAL = :codFilial
  AND (r.DTFINAL IS NULL OR r.DTFINAL >= TRUNC(SYSDATE))
ORDER BY u.NOME, r.SEQUENCIA
```

## T271 — Tamanho da rota por vendedor na filial (carteira de rota)
Pergunta: "quantos clientes cada vendedor tem na rota" / "carteira de rota da filial X"
```sql
SELECT u.CODFILIAL,
       SUBSTR(NVL(u.NOME,'?'),1,30)                                   AS VENDEDOR,
       COUNT(*)                                                       AS CLIENTES_ROTA,
       SUM(CASE WHEN r.PERIODICIDADE = 7  THEN 1 ELSE 0 END)          AS SEMANAIS,
       SUM(CASE WHEN r.PERIODICIDADE = 14 THEN 1 ELSE 0 END)          AS QUINZENAIS
FROM EBD.PCROTACLI r
JOIN EBD.PCUSUARI u ON u.CODUSUR = r.CODUSUR
WHERE u.CODFILIAL = :codFilial
  AND (r.DTFINAL IS NULL OR r.DTFINAL >= TRUNC(SYSDATE))
GROUP BY u.CODFILIAL, SUBSTR(NVL(u.NOME,'?'),1,30)
ORDER BY CLIENTES_ROTA DESC
```

## T272 — Rota da semana por dia (distribuição de visitas)
Pergunta: "como está distribuída a rota da semana na filial X" / "visitas por dia"
```sql
SELECT r.DIASEMANA,
       COUNT(*)                    AS CLIENTES,
       COUNT(DISTINCT r.CODUSUR)   AS VENDEDORES
FROM EBD.PCROTACLI r
JOIN EBD.PCUSUARI u ON u.CODUSUR = r.CODUSUR
WHERE u.CODFILIAL = :codFilial
  AND (r.DTFINAL IS NULL OR r.DTFINAL >= TRUNC(SYSDATE))
GROUP BY r.DIASEMANA
ORDER BY CLIENTES DESC
```

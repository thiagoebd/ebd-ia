# Query Templates — SQL pronto para o agente Winthor

> **Como funciona este arquivo:** templates SQL validados e estáveis que o
> agente DEVE preferir adaptar em vez de gerar SQL do zero. Cada template
> tem um nome, descrição, bind variables, e exemplo de uso.
>
> **Convenção:** templates usam SEMPRE bind variables (`:userFilial`, `:dtInicio`,
> `:dtFim`, etc), nunca string concatenation. SQL Guard valida.
>
> **Início:** 19/05/2026 — versão minimalista. Vai crescer conforme descobrirmos
> queries que o agente acerta e queremos travar.

---

## Convenções de bind variables padronizadas

Toda query do projeto usa estas bind variables com nomes consistentes:

| Bind var | Tipo | Exemplo | Descrição |
|---|---|---|---|
| `:userFilial` | string | `'05'` | Código da filial (sempre obrigatório em PCMOV/PCNFSAID/PCPEDC) |
| `:userFiliais` | lista | `('10','13')` | Lista de filiais (para regional — usar com `IN`) |
| `:dtInicio` | date | `2026-05-01` | Início do período de análise |
| `:dtFim` | date | `2026-05-31` | Fim do período de análise |
| `:topN` | number | `10` | Quantidade de linhas para Top N |
| `:codFornec` | string | `'1'` | Código do fornecedor (quando filtrado) |
| `:codProduto` | number | `1` | Código do produto (quando filtrado) |
| `:codUsur` | string | `'146'` | Código do vendedor/RCA |

---

## Template T001 — Faturamento por Filial (mês corrente)

**Descrição:** Faturamento líquido por filial no mês corrente.

**Quando usar:** usuário pede "faturamento do mês", "vendas da filial X", "como
está o mês até agora".

**Bind variables:** `:userFilial`

**SQL:**

```sql
-- T001: Faturamento por Filial no mês corrente
-- TODO: validar nomes exatos das colunas (NUMNOTA, DTSAIDA, VLTOTAL, etc)
SELECT
    s.CODFILIAL,
    f.FANTASIA,
    COUNT(DISTINCT s.NUMNOTA) AS QTD_NOTAS,
    SUM(s.VLTOTAL) AS FATURAMENTO_LIQUIDO
FROM EBD.PCNFSAID s
JOIN EBD.PCFILIAL f ON s.CODFILIAL = f.CODFILIAL
WHERE s.CODFILIAL = :userFilial
  AND s.DTSAIDA >= TRUNC(SYSDATE, 'MM')
  AND s.DTSAIDA < TRUNC(SYSDATE, 'MM') + INTERVAL '1' MONTH
  AND s.CONDVENDA = 1  -- venda real, não devolução [CONFIRMAR código]
GROUP BY s.CODFILIAL, f.FANTASIA
```

**Variações comuns:**
- Para período customizado: substituir `DTSAIDA >= TRUNC(SYSDATE, 'MM')` por `DTSAIDA BETWEEN :dtInicio AND :dtFim`
- Para regional: trocar `s.CODFILIAL = :userFilial` por `s.CODFILIAL IN (:userFiliais)`

---

## Template T002 — Top N Fornecedores (com Real vs AA vs Meta)

**Descrição:** ranking de fornecedores no período, comparando Real, AA, Meta.

**Quando usar:** usuário pede "top 5 fornecedores", "quais marcas estão melhor",
"ranking de marcas".

**Bind variables:** `:userFilial`, `:dtInicio`, `:dtFim`, `:topN`

**SQL:**

```sql
-- T002: Top N Fornecedores com Real vs AA vs Meta
-- TODO: ajustar nome da tabela de metas (PCMETAFV? outra?)
-- TODO: definir período AA (mesmo mês ano anterior)
SELECT * FROM (
    SELECT
        p.CODFORNEC,
        forn.FANTASIA AS FORNECEDOR,
        SUM(CASE
            WHEN s.DTSAIDA BETWEEN :dtInicio AND :dtFim
            THEN i.QT * i.PUNITARIO END) AS REAL,
        SUM(CASE
            WHEN s.DTSAIDA BETWEEN ADD_MONTHS(:dtInicio, -12) AND ADD_MONTHS(:dtFim, -12)
            THEN i.QT * i.PUNITARIO END) AS AA
        -- META: subquery em PCMETAFV (a definir)
    FROM EBD.PCNFSAIDI i
    JOIN EBD.PCNFSAID s ON i.NUMNOTA = s.NUMNOTA AND i.CODFILIAL = s.CODFILIAL
    JOIN EBD.PCPRODUT p ON i.CODPROD = p.CODPROD
    JOIN EBD.PCFORNEC forn ON p.CODFORNEC = forn.CODFORNEC
    WHERE s.CODFILIAL = :userFilial
      AND s.DTSAIDA >= ADD_MONTHS(:dtInicio, -12)
      AND s.DTSAIDA <= :dtFim
    GROUP BY p.CODFORNEC, forn.FANTASIA
)
ORDER BY REAL DESC NULLS LAST
FETCH FIRST :topN ROWS ONLY
```

---

## Template T003 — Faturamento por Ramo de Atividade

**Descrição:** faturamento agrupado por ramo de atividade do cliente.

**Quando usar:** "vendas por ramo", "quanto vendi pra supermercado", "split por
canal".

**Bind variables:** `:userFilial`, `:dtInicio`, `:dtFim`

**SQL:**

```sql
-- T003: Faturamento por Ramo de Atividade
-- TODO: confirmar coluna de ramo em PCCLIENT (RAMOATV? CODRAMO?)
SELECT
    c.RAMOATV,
    COUNT(DISTINCT s.CODCLI) AS QTD_CLIENTES,
    SUM(s.VLTOTAL) AS FATURAMENTO,
    SUM(s.VLTOTAL) / SUM(SUM(s.VLTOTAL)) OVER () AS PCT_PARTICIPACAO
FROM EBD.PCNFSAID s
JOIN EBD.PCCLIENT c ON s.CODCLI = c.CODCLI
WHERE s.CODFILIAL = :userFilial
  AND s.DTSAIDA BETWEEN :dtInicio AND :dtFim
GROUP BY c.RAMOATV
ORDER BY FATURAMENTO DESC NULLS LAST
```

---

## Templates a criar (backlog)

Conforme avançarmos, adicionar templates para:

- [ ] **T004 — Top N RCAs/Vendedores** (por filial, no mês)
- [ ] **T005 — Top N Clientes** (curva ABC)
- [ ] **T006 — Posição de Estoque** por produto/filial
- [ ] **T007 — Inadimplência por gerente** ([definição a confirmar])
- [ ] **T008 — Positivação de RCA** (clientes com compra no período)
- [ ] **T009 — Cobertura de estoque** (dias)
- [ ] **T010 — Faturamento por Família de Produto**
- [ ] **T011 — Tendência vs Meta** do mês corrente
- [ ] **T012 — Faturamento Regional** (com `CODFILIAL IN (...)`)
- [ ] **T013 — Comparativo mensal** (12 meses) por filial

---

## Notas de implementação

### Como o agente DEVE escolher entre template existente vs SQL novo

1. **Sempre** consultar este arquivo primeiro
2. Se houver template que cobre 80%+ do pedido → adaptar
3. Se nenhum template cobre → gerar SQL novo, validar via SQL Guard, **e propor adicionar como template** se útil
4. **Nunca** copiar SQL antigo sem entender — Oracle Winthor tem nuances

### Validação de templates antes de adicionar aqui

Todo template adicionado deve ter sido:
- [x] Executado pelo menos uma vez com sucesso no Oracle real
- [x] Latência medida e aceitável (<5s tipicamente)
- [x] Documentado com bind variables explícitas
- [x] Revisado por humano (Thiago)

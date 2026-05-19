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

## Entradas

### 2026-05-19 — Filtro CODFILIAL é obrigatório (REGRA INVIOLÁVEL)

**Tabelas grandes do Winthor** (`PCMOV`, `PCNFSAID`, `PCPEDC`, `PCEST`) têm
dezenas de milhões de linhas. **TODA query nessas tabelas DEVE incluir
`WHERE CODFILIAL = :userFilial`** (ou `IN (...)` para regional).

Sem o filtro:
- Query estoura timeout (30s)
- Pode comprometer performance geral do ODA
- Resultado retornado seria inutilizável (totaliza 20 filiais misturadas)

**Aplicável a:** `PCMOV`, `PCNFSAID`, `PCNFSAIDI`, `PCPEDC`, `PCPEDI`, `PCEST`,
qualquer tabela com coluna `CODFILIAL`.

**Não aplicável a:** dimensões pequenas como `PCFILIAL`, `PCFORNEC`, `PCPRODUT`
(estoque mestre de produto), `PCEMPR`. Mas mesmo nelas, filtrar quando possível.

### 2026-05-19 — EBD.PCLIB tem 25.882.874 linhas

A tabela `EBD.PCLIB` (usada para permissionamento da rotina 131) **não é
pequena**. Tem ~25,9 milhões de linhas. `SELECT COUNT(*)` leva 4.1s na
primeira vez (cold cache) e ~1s nas vezes seguintes (cache aquecido).

**Implicação:**
- Em produção (quando consultarmos PCLIB), SEMPRE filtrar por usuário antes:
  `SELECT ... FROM EBD.PCLIB WHERE CODUSUR = :u AND CODACESSO = '01'`
- Cache do resultado em Redis (TTL 15min) é OBRIGATÓRIO
- Nunca fazer `SELECT * FROM PCLIB` sem WHERE

### 2026-05-19 — V$VERSION retorna múltiplas linhas

`SELECT BANNER FROM V$VERSION` retorna ~5 linhas (Oracle Database, NLSRTL,
TNS, Unicode, Network Vsnnnn). Para o banner principal, usar:

```sql
SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1
```

Ou:

```sql
SELECT BANNER FROM V$VERSION WHERE BANNER LIKE 'Oracle Database%'
```

### 2026-05-19 — Convenção de bind variable: `:userFilial`

Pra evitar SQL injection, o agente NUNCA concatena CODFILIAL na string SQL.
Sempre usa bind variable com nome padronizado `:userFilial`.

Errado:
```python
sql = f"SELECT ... WHERE CODFILIAL = '{user_filial}'"  # ❌ SQL injection
```

Certo:
```python
sql = "SELECT ... WHERE CODFILIAL = :userFilial"  # ✅
cursor.execute(sql, userFilial=user_filial)
```

### 2026-05-19 — Oracle 19c usa FETCH FIRST, não LIMIT

Diferente de Postgres/MySQL, Oracle não tem `LIMIT`. Sintaxe SQL:2008:

```sql
SELECT * FROM tabela WHERE ... FETCH FIRST 10 ROWS ONLY
```

Para paginação:
```sql
SELECT * FROM tabela WHERE ... OFFSET 0 ROWS FETCH FIRST 10 ROWS ONLY
```

Por convenção do projeto: queries sem `FETCH FIRST` recebem cap automático
de 10.000 linhas via SQL Guard.

---

## Formato sugerido pra novas entradas
---

## Anti-padrões para o agente evitar

### ❌ SELECT * em tabelas grandes

Nunca usar `SELECT *` em PCMOV, PCNFSAID etc. Listar colunas explicitamente.

### ❌ Concatenar strings em WHERE

Sempre usar bind variables.

### ❌ JOIN sem CODFILIAL nos dois lados

Quando juntar tabelas com CODFILIAL, **ambas devem ser filtradas** pela mesma filial:

```sql
-- ❌ Errado (joina filiais cruzadas)
SELECT ... FROM PCNFSAID s
JOIN PCNFSAIDI i ON s.NUMNOTA = i.NUMNOTA
WHERE s.CODFILIAL = :userFilial

-- ✅ Certo
SELECT ... FROM PCNFSAID s
JOIN PCNFSAIDI i ON s.NUMNOTA = i.NUMNOTA AND s.CODFILIAL = i.CODFILIAL
WHERE s.CODFILIAL = :userFilial
```

### ❌ Função em coluna indexada

Quando filtrar por data, evitar TRUNC/TO_CHAR na coluna do banco
(quebra uso de índice):

```sql
-- ❌ Errado
WHERE TRUNC(DTSAIDA) = TRUNC(SYSDATE)

-- ✅ Certo (usa índice)
WHERE DTSAIDA >= TRUNC(SYSDATE) AND DTSAIDA < TRUNC(SYSDATE) + 1
```

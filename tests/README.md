# Testes do EBD.ia — rodam SEM Oracle

```bash
python3 -m venv .venv && .venv/bin/pip install -q \
  oracledb python-dotenv structlog sqlglot pydantic pydantic-settings \
  starlette mcp httpx anthropic pytest
.venv/bin/python -m pytest tests/ -q
```

69 testes, ~0,2s. O pool Oracle e substituido por um falso (`conftest.py`)
alimentado com linhas de `ALL_TAB_COLUMNS` iguais as reais, medidas em
27/07/2026.

## O que cobre

| arquivo | o que garante |
|---|---|
| `test_ora904.py` | sugestao de colunas reais: rotulos [VAZIA]/[QUASE VAZIA]/[VALOR UNICO], guarda de estatistica velha, casamento de nome curto, conexao devolvida ao pool, nunca levanta excecao |
| `test_erro_classificacao.py` | erro de SQL manda CORRIGIR (nao "o banco caiu"), timeout manda aliviar a query, infra manda esperar, escopo nao vira falha de banco, marcador `__ORACLE_ERROR__` intacto |
| `test_kb.py` | cerca ``` balanceada, template/cicatriz/secao sem duplicata, SQL canonico parseia em Oracle, T-LOG filtra CODFILIAL, nenhum template usa view GD_* nem tabela-fotografia |

## Bugs reais que esta suite pega

Todos ja aconteceram e custaram rodada de scp:

- `datetime` nao importado no `server.py` — NameError engolido por `except`
- `KM` nao casava com `KMROTA` (difflib 0.50 < corte 0.55)
- `cat >>` rodado duas vezes duplicando template
- cerca ``` aberta deixando o `get_template` cego
- template varrendo PCMOVENDPEND sem CODFILIAL (estoura o timeout de 85s)

## O que NAO cobre

Tempo de execucao real e dado do banco. Isso e o `test_tlog2.py`, que roda
dentro do container e precisa de Oracle. Os dois se complementam: este aqui
roda a cada alteracao, aquele antes de liberar para o usuario.

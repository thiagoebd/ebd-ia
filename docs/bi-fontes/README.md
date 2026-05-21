# 📚 BI Fontes Oficiais — EBD

Este diretório armazena SQL e fórmulas oficiais do BI da EBD,
usadas como **fonte canônica** para replicar no agente EBD.ia.

## Arquivos

- `fato_estoque_oficial.sql` — Estoque (21/05/2026)
  - 45 colunas, 3 visões (GERENCIAL/DISPONIVEL/EBD), 4 tipos de custo
  - Base para Família 14+ (Inteligência de Estoque)
  - Documentação completa: https://www.notion.so/3676695d346681558fb5ff88a6d1296a

## Regra de uso

Estes SQLs são **fonte de verdade**. Toda métrica do agente deve
replicar exatamente as fórmulas, e validar centavo-a-centavo contra
o BI antes de virar template (Tnnn) na knowledge base.

Se o agente sugerir uma fórmula diferente, é cicatriz a documentar:
ou o BI está errado, ou o agente está errado. Investigar.

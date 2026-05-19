# Knowledge Base — EBD.ia

> **Como funciona este arquivo:** carregado em wake-up de cada sessão do agente.
> Contém TODAS as regras de negócio que o Oracle não conhece (regional, sinônimos,
> definições). Atualizado manualmente por Thiago via commit Git.
>
> **Última atualização:** 19/05/2026 — esqueleto inicial criado.
> **Fonte primária dos dados:** arquivos Excel do BI atual (FaturamentoRegionalFilialGerente etc.)

---

## 1. Vocabulário e sinônimos

O agente DEVE aceitar os termos abaixo como equivalentes ao escutar usuários:

| Termo do usuário | Termo técnico (campo Oracle) | Observação |
|---|---|---|
| Vendedor, Rep, Representante, RCA | `CODUSUR` / `PCUSUARI` | Apesar do nome "RCA" (Representante Comercial Autônomo) no Winthor, **EBD usa CLT, não autônomos**. Tratar como sinônimos. |
| Faturamento, Vendas, Real | `SUM(...)` em `PCNFSAID` | Notas emitidas no período |
| Em Pedido, Em Carteira, Pedidos | `SUM(...)` em `PCPEDC` (com status) | Pedidos digitados mas ainda não faturados |
| Real + Ped | Real + Em Pedido | Projeção total |
| AA | Ano Anterior (mesmo período) | Comparação YoY |
| Meta | Meta Fornecedor / Cota | Tabela a confirmar (`PCMETAFV`?) |
| Tendência | Projeção fim do mês | Ritmo atual extrapolado |
| Cxs / Caixas | Volume físico (unidade) | Diferente de R$ |
| Família (de produto) | `LINHAPRODUTO` ou similar | Ex: LAMEN, CUP NOODLES |
| Fornecedor | `PCFORNEC` | Ex: NISSIN, FERRERO |
| Regional | **Construção interna EBD** (NÃO está no Oracle) | Ver seção 4 |

## 2. Hierarquia comercial

Regional (construção EBD, não existe no Oracle — 9 regionais)
└── Filial (CODFILIAL — 20 filiais ativas)
└── Gerente (~76)
└── Supervisor (~194)
└── Vendedor/RCA (~1199)
└── Cliente

## 3. Lista oficial de filiais (extraída do BI atual em 19/05/2026)

**Total: 20 filiais ativas em 9 regionais.**

| Código | Filial | Regional |
|---|---|---|
| 01 | EBD MATRIZ | NO2 |
| 02 | EBD SP | SP1 |
| 03 | EBD FORTALEZA | NE2 |
| 04 | EBD SAO LUIS | NE1 |
| 05 | EBD DUQUE | RJ2 |
| 06 | EBD MANAUS | NO1 |
| 07 | EBD MACAPA | NO2 |
| 08 | EBD BOA VISTA | NO1 |
| 09 | EBD JUAZEIRO | NE2 |
| 10 | EBD SÃO GONÇALO | RJ1 |
| 11 | EBD SANTAREM | NO1 |
| 12 | EBD IMPERATRIZ | NE1 |
| 13 | EBD TAQUARA | RJ1 |
| 14 | EBD PIRAÍ | RJ2 |
| 15 | EBD GUARULHOS | SP2 |
| 16 | EBD ITAPEVI | SP1 |
| 18 | EBD SBC | SP2 |
| 21 | EBD TERESINA | NE2 |
| 52 | EBDN PETROLINA | NE3 |
| 53 | EBDN CARUARU | NE3 |

> 📌 Note: códigos 17, 19, 20, 22-51 não aparecem — provavelmente filiais
> descontinuadas ou nunca usadas.

## 4. Mapeamento Regional → Filiais (REGRA INVIOLÁVEL)

> ⚠️ **REGRA DE NEGÓCIO INTERNA — não existe no Oracle.**
> Quando o usuário pedir "vendas da regional RJ1", o agente DEVE traduzir para
> `WHERE CODFILIAL IN ('10', '13')` usando o mapeamento abaixo.

| Regional | Códigos Filial | Filiais |
|---|---|---|
| NE1 | 04, 12 | EBD SAO LUIS, EBD IMPERATRIZ |
| NE2 | 03, 09, 21 | EBD FORTALEZA, EBD JUAZEIRO, EBD TERESINA |
| NE3 | 52, 53 | EBDN PETROLINA, EBDN CARUARU |
| NO1 | 06, 08, 11 | EBD MANAUS, EBD BOA VISTA, EBD SANTAREM |
| NO2 | 01, 07 | EBD MATRIZ, EBD MACAPA |
| RJ1 | 10, 13 | EBD SÃO GONÇALO, EBD TAQUARA |
| RJ2 | 05, 14 | EBD DUQUE, EBD PIRAÍ |
| SP1 | 02, 16 | EBD SP, EBD ITAPEVI |
| SP2 | 15, 18 | EBD GUARULHOS, EBD SBC |

**Soma de verificação:** 20 filiais em 9 regionais.
- NE1 = 2 filiais
- NE2 = 3 filiais
- NE3 = 2 filiais
- NO1 = 3 filiais
- NO2 = 2 filiais
- RJ1 = 2 filiais
- RJ2 = 2 filiais
- SP1 = 2 filiais
- SP2 = 2 filiais
- **Total = 20 ✓**

## 5. Dimensões de análise suportadas

O agente deve suportar análises nas seguintes dimensões (visto nos relatórios do BI atual):

1. **Por Fornecedor** (NISSIN, FERRERO, RED BULL, PEPSICO...)
2. **Por Família de Produto** (LAMEN, CUP NOODLES, NUTELLA...)
3. **Por Produto (SKU)** (com código)
4. **Por Regional** (NE1, NE2, NE3, NO1, NO2, RJ1, RJ2, SP1, SP2)
5. **Por Filial** (CODFILIAL — 20 valores)
6. **Por Gerente / Supervisor / RCA**
7. **Por Ramo de Atividade** (AS 5-9, AS 10-19, ATACADO, CONVENIENCIA, FARMA, BOMBONIERE)
8. **Por Ramo Principal** (refinamento: Supermercado 5/9, Hipermercado 20/49, etc)

## 6. Métricas padrão do negócio

Toda análise comparativa deve apresentar (quando aplicável):

| Métrica | Cálculo | Observação |
|---|---|---|
| Real | Faturamento líquido período | |
| Meta | Cota acordada com fornecedor/filial | |
| % vs Meta | Real / Meta | |
| $ vs Meta | Real - Meta | Pode ser negativo |
| Pedidos | Pedidos abertos no período | |
| Real + Ped | Real + Pedidos | Projeção otimista |
| AA | Mesmo período ano anterior | |
| % vs AA | (Real - AA) / AA | Crescimento YoY |
| % Part. | Real / Total | Participação no grupo |
| Cxs Real | Volume físico em caixas | |
| Cxs AA | Volume caixas ano anterior | |
| Tendência | Projeção fim do mês baseada em ritmo | |

## 7. Convenções de tempo

- **Mês corrente** = `TRUNC(SYSDATE, 'MM')` até `SYSDATE` (calendário, não comercial) — **[A CONFIRMAR]**
- **Ano corrente (YTD)** = `TRUNC(SYSDATE, 'YYYY')` até `SYSDATE` — **[A CONFIRMAR]**
- **AA (Ano Anterior)** = mesmo período do ano passado
- **Fechamento mensal** — **[A CONFIRMAR se há dia de corte]**

## 8. Definições pendentes (a preencher conforme aparecerem nas queries)

- [ ] **Cliente ativo** — definição? (compra últimos 60 dias? 90? Status PCCLIENT?)
- [ ] **Inadimplência** — cutoff de dias vencidos? Tabela?
- [ ] **Perdas com crédito** — como calcula? Tabela?
- [ ] **Faturamento Bruto vs Líquido** — regra de cada um?
- [ ] **Tabela de metas** — `PCMETAFV`? Outra? Estrutura?
- [ ] **Estoque atual** — `PCEST`? Por filial?
- [ ] **Cobertura de estoque** — fórmula de dias de cobertura?
- [ ] **Curva ABC** — regras de classificação A/B/C
- [ ] **Mix de produtos** — definição operacional
- [ ] **Positivação** — clientes com compra no período?
- [ ] **Status de pedido** — quais valores em `PCPEDC` significam "em aberto"?

## 9. Filtros obrigatórios — REGRA INVIOLÁVEL

**TODA query de análise DEVE incluir filtro `CODFILIAL = :userFilial`** (ou `IN (...)` para regional).

Razão: tabelas grandes (PCMOV, PCNFSAID) têm dezenas de milhões de linhas.
Sem filtro de filial, query estoura timeout e/ou compromete o banco.

Aplicável a:
- `EBD.PCMOV` (movimentação)
- `EBD.PCNFSAID` (notas saída)
- `EBD.PCPEDC` (pedidos cabeçalho)
- `EBD.PCEST` (estoque)
- Qualquer outra tabela com `CODFILIAL`

**Em homologação:** filial vem do contexto da conversa (usuário informa).
**Em produção:** filial vem da PCLIB (rotina 131 do Winthor).

A diferença é a **fonte do filtro**, NUNCA a presença dele.

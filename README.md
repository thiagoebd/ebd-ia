# EBD.ia

Agente comercial conversacional do Grupo EBD. O gestor pergunta em português
— *"quanto a filial 18 faturou ontem?"*, *"quais produtos estão em ruptura em
Boa Vista?"* — e o agente escreve o SQL, consulta o Winthor e devolve o
número.

Não é BI com painel pronto: a consulta é montada na hora, inclusive para
perguntas que ninguém previu.

---

## Visão geral

Atende a rede comercial — vendedores, RCAs, gerentes e diretoria — em dois
canais:

- **Chat web** — React + Vite, resposta em streaming (SSE)
- **Telegram** — bot com as mesmas capacidades

Consulta o **Winthor (Oracle/TOTVS)** em modo somente-leitura, com escopo
automático por filial. Lê imagem e planilha, gera Excel, PDF, PowerPoint,
gráficos e mapas de rota.

**Em produção.** Cerca de 30 usuários ativos.

---

## O que ele faz

**Consulta o Winthor** — faturamento, carteira, ruptura, positivação, mix,
metas e comissão, estoque, logística e roteirização.

**Lê imagem.** Foto de produto, print de tela ou documento fotografado. O
agente identifica o que é e oferece a leitura comercial: temos no cadastro?
qual o estoque por filial? está girando?

**Importa planilha** (xlsx, csv, multi-aba) e cruza com o Winthor. A planilha
vai para o Postgres — nunca para o prompt — e o cruzamento acontece em
Python, em blocos de 1.000 chaves. O agente recebe quantas linhas casaram,
quantas não, e exemplos das que ficaram de fora.

**Resolve nome para código.** Planilha com "thiago parreira" em vez do código
do RCA: busca por tokens, casa com "THIAGO MARTINS PARREIRA", e quando há
vários candidatos **mostra e pergunta** em vez de escolher.

**Gera arquivos** — `create_excel`, `create_pdf`, `create_pptx`,
`create_chart`, `create_route_map`.

---

## Stack

| Camada | Tecnologia |
|---|---|
| Runtime | Ubuntu Server 24.04 · Docker + Compose v2 |
| LLM | **DeepSeek** — `deepseek-flash` (padrão, lê imagem) / `deepseek-v4-pro` |
| Backend | Python 3.12 · FastAPI · PostgreSQL 16 · Redis |
| Frontend | React 19 · Vite 8 · TypeScript |
| Dados | Winthor (Oracle) read-only via MCP |
| Observabilidade | Grafana · Prometheus · Loki · Promtail |

> O projeto usou Claude no início. Migrou para DeepSeek em 09/2026 — o
> `deepseek-flash` custa cerca de 20× menos na entrada e lê imagem.

---

## Arquitetura

```
  navegador / Telegram
          │
      nginx (TLS, proxy)
          │
  ebdia-gateway ── systemd, uvicorn :8000
          │          FastAPI · Azure AD · histórico no Postgres · SSE
          │          serve o frontend compilado
          │
     core/agent.py ── monta o prompt, chama o modelo, executa ferramentas
          │
     MCP oracle :8990 (Docker)
          │
     Winthor / Oracle
```

O core **não abre conexão** com o Oracle. Fala com o MCP por HTTP, e o MCP é
dono da conexão e do pool.

O gateway **não roda em container** — é serviço systemd com o Python do
sistema. Biblioteca nova precisa de
`sudo pip3 install --break-system-packages`.

---

## Como o conhecimento é organizado

O que o agente sabe do Winthor vive em `docs/` e vira o system prompt a cada
conversa.

| Arquivo | O que é |
|---|---|
| `CLAUDE.md` | regras de comportamento do agente |
| `knowledge.md` | vocabulário do gestor → tabela do Winthor |
| `query_templates.md` | consultas prontas e validadas |
| `sql-corrections.md` | **as cicatrizes** — erros já cometidos e corrigidos |
| `winthor_discovery.md` | dicionário do banco |

As **cicatrizes** são o ativo mais caro. Cada uma registra um erro real com o
caso que o gerou — de coluna que não existe a regra de negócio que parecia
óbvia e não era. Leia antes de escrever consulta nova.

Há também um catálogo de templates (`core/app/data/templates.json`, 91
consultas) que o agente busca sob demanda com `list_templates` e
`get_template`, em vez de carregar tudo no prompt.

---

## Princípios

Cada um veio de um problema real em produção.

**Nunca inventar número.** Se o dado não está lá, dizer que não está.

**Nunca afirmar que algo não existe sem consultar.** "Não temos esse produto"
sem olhar é afirmação sobre a base sem base.

**Dizer o que ficou de fora.** Cruzamento em que 480 de 500 linhas casaram
precisa dizer isso. Apresentar como completo é pior que não entregar.

**Não escolher entre candidatos ambíguos.** Mostrar as opções e perguntar.

**Registrar cada erro como cicatriz.** É o que impede o erro de voltar daqui
a dois meses.

---

## Operação

### Reiniciar o gateway

`systemctl restart` sozinho não basta — o processo antigo pode continuar
segurando a porta 8000 enquanto o systemd reporta `active`.

```bash
sudo systemctl stop ebdia-gateway
sudo pkill -f "uvicorn gateway.app.main"
sleep 3
sudo systemctl start ebdia-gateway
sleep 8
systemctl is-active ebdia-gateway
sudo lsof -i :8000 -sTCP:LISTEN -P -n    # um PID só
```

### Depois de mexer no frontend

```bash
cd frontend && npm run build
```

E `Ctrl+Shift+R` no navegador.

### Trocar o modelo

O nome do modelo vive em cinco arquivos. Use sempre o script:

```bash
bash scripts/troca_modelo.sh                   # só diagnostica
bash scripts/troca_modelo.sh deepseek-flash    # troca em todos
```

### Testes

```bash
.venv/bin/python -m pytest tests/ -q
```

---

## Estrutura

```
core/          agente, ferramentas, leitura de anexo, prompt
gateway/       FastAPI, rotas, auth, banco
frontend/      React + Vite
channels/      bot do Telegram
mcps/          servidores MCP (oracle, excel, pptx)
docs/          o conhecimento do Winthor
scripts/       operação e manutenção
observability/ Grafana, Loki, Promtail, Prometheus
tests/         suíte (pytest)
```

---

## Projeto irmão

**Dealer.ia** (`thiagoebd/ebd-ia-conc`) — mesma arquitetura aplicada às 31
concessionárias do grupo, com dois DMS (NBS/Oracle e DealerNet/SQL Server).
Boa parte do que existe lá foi portada daqui.

---

**Autor:** Thiago Martins Parreira

*Projeto interno Grupo EBD — repositório privado.*

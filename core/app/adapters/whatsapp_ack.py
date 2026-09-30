"""Aviso de "estou trabalhando nisso" que entende o pedido.

O antigo "🔎 Consultando…" saia sempre, antes de tudo. Agora:

1. o aviso so sai se a resposta passar de WA_ACK_APOS_S (padrao 15 s) —
   pergunta simples chega direto, sem mensagem intermediaria
2. a frase depende da intencao: painel, "como estamos", comparacao,
   ranking, estoque, meta...
3. saudacao e conversa curta nunca recebem aviso; WA_ACK=false desliga tudo

POR QUE REGRAS E NAO O MODELO
    Instantaneo e sem custo. E o aviso nao pode prometer o que a resposta
    nao entrega — o modelo poderia dizer "vou te mandar o PDF", e arquivo
    nao chega pelo WhatsApp.
"""
from __future__ import annotations

import os
import random
import re
import unicodedata


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower()).strip()


# ordem importa: a primeira intencao que casar vence
INTENCOES: list[tuple[str, re.Pattern, list[str]]] = [
    ("painel", re.compile(r"\b(painel|relatorio|resumo|dashboard|report|fechamento|emit[ae]|emitir|ger[ae]|gerar|mont[ae]|montar|prepar[ae]|preparar)\b"), [
        "É pra já{n}! Vou montar e já te retorno.",
        "Deixa comigo{n} — montando aqui, já volto com ele.",
        "Pode deixar{n}, vou preparar e te mando em seguida.",
    ]),
    ("meta", re.compile(r"\b(meta|metas|atingiment\w*|objetivo|batemos|bater)\b"), [
        "Deixa eu ver como está contra a meta e já te falo{n}.",
        "Vou checar o atingimento e já te retorno.",
    ]),
    ("ranking", re.compile(r"\b(ranking|top \d*|maiores|melhores|piores|lideres|quem mais|quem menos)\b"), [
        "Vou montar o ranking e já te passo{n}.",
        "Deixa eu ordenar aqui e já te mostro.",
    ]),
    ("compara", re.compile(r"\b(compar\w*|versus|vs|contra|ano passado|aa|evolu\w*|cresc\w*|varia\w*)\b"), [
        "Vou cruzar os períodos e já te mostro{n}.",
        "Deixa eu comparar os números e já te falo.",
        "Boa pergunta{n} — vou colocar lado a lado e já volto.",
    ]),
    ("estoque", re.compile(r"\b(estoque|ruptura|falta|cobertura|giro)\b"), [
        "Vou checar o estoque e já te falo{n}.",
        "Deixa eu olhar a posição de estoque e já volto.",
    ]),
    ("agora", re.compile(r"\b(como estamos|como esta|como ta|hoje|agora|parcial|ate agora|nesse mes|este mes|esse mes|andamento)\b"), [
        "Deixa eu ver aqui e já te falo{n}.",
        "Vou olhar os números de agora e já te passo.",
        "Um instante{n}, estou vendo como está.",
    ]),
]
GENERICAS = [
    "Deixa eu verificar e já te respondo{n}.",
    "Já vejo isso pra você{n}.",
    "Um instante, vou consultar e já volto.",
]
# nunca recebem aviso: a resposta ja e curta
_CONVERSA = re.compile(
    r"^(oi|ola|opa|e ai|bom dia|boa tarde|boa noite|ta ai|esta ai|tudo bem|"
    r"valeu|obrigad\w*|brigad\w*|ok|beleza|blz|show|top|legal|perfeito|"
    r"entendi|certo|sim|nao)\b[\s!?.,]*$")


_PERGUNTA_DE_DADO = re.compile(
    r"\d|\b(quanto|quantos|quantas|qual|quais|quem|onde|lista|listar|mostra|"
    r"mostrar|traz|trazer|faturamento|venda|vendas|pedido|pedidos|filial|cliente)\b")


def intencao(pergunta: str) -> str | None:
    """Rotulo da intencao, ou None para conversa (sem aviso).

    Pergunta curta sem assunto de negocio e conversa ("e ai doutor?"): a
    resposta vem rapido e o aviso so atrapalha. Generica so ganha aviso se
    tiver cara de pedido de dado.
    """
    t = _norm(pergunta)
    if not t or _CONVERSA.match(t) or len(t) <= 3:
        return None
    for nome, padrao, _ in INTENCOES:
        if padrao.search(t):
            return nome
    if len(t.split()) < 4 or not _PERGUNTA_DE_DADO.search(t):
        return None
    return "generica"


def primeiro_nome(push_name: str | None) -> str:
    n = (push_name or "").strip().split()
    return n[0].capitalize() if n and n[0].isalpha() else ""


def frase_de_aviso(pergunta: str, nome: str = "", rng: random.Random | None = None) -> str | None:
    """Frase de aviso para a pergunta, ou None se nao deve haver aviso."""
    it = intencao(pergunta)
    if it is None:
        return None
    rng = rng or random
    pool = next((f for n, _, f in INTENCOES if n == it), GENERICAS)
    return rng.choice(pool).replace("{n}", f", {nome}" if nome else "")


def espera_antes_do_aviso() -> float:
    """Toda resposta leva ~6 s so pelo tamanho do prompt: com 4 s o aviso
    saia um segundo antes da resposta. 15 s deixa o aviso para o que demora."""
    try:
        return max(0.0, float(os.getenv("WA_ACK_APOS_S", "15")))
    except ValueError:
        return 15.0


def aviso_ligado() -> bool:
    return os.getenv("WA_ACK", "true").strip().lower() == "true"

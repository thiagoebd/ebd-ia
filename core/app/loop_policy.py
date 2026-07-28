"""Politica de parada do loop de tool-use.

Isolado em modulo proprio de proposito: e decisao pura, sem I/O, e precisa ser
testavel sem carregar anthropic, xlsxwriter e o resto da cadeia do agent.py.

Bug que originou este arquivo (28/07/2026): o orcamento de falhas era
CUMULATIVO no turno inteiro. Uma analise de 12 passos com 9 consultas boas e 3
falhas espalhadas abortava e descartava as 9, respondendo ao usuario que nao
tinha conseguido montar a consulta.
"""
from __future__ import annotations


AVISO_CONCLUA = (
    "PARE de consultar o banco agora. Voce JA TEM dados suficientes das "
    "consultas que deram certo. Escreva a resposta final AGORA usando apenas o "
    "que voce ja obteve, e diga de forma explicita e curta o que NAO conseguiu "
    "apurar. NUNCA invente numeros para preencher a lacuna."
)


def decidir_parada(tool_outcomes, max_fails: int = 3,
                   ja_pediu_conclusao: bool = False) -> str:
    """O que fazer depois de uma rodada de tools.

    Conta falha CONSECUTIVA, nao acumulada: sucesso zera o contador. E quando
    ja ha dado apurado, pede fechamento em vez de jogar tudo fora.

      'seguir'   — continua o loop normalmente
      'concluir' — manda o modelo fechar com o que ja obteve
      'parar'    — encerra sem mensagem de falha (a conclusao ja foi pedida)
      'abortar'  — nada aproveitavel; mensagem de falha ao usuario
    """
    oq = [ok for (nome, ok) in tool_outcomes if nome == "oracle_query"]
    if not oq:
        return "seguir"

    ok_total = sum(1 for ok in oq if ok)

    seguidas = 0
    for ok in reversed(oq):
        if ok:
            break
        seguidas += 1

    # com dado na mao vale insistir mais: perder a analise inteira custa muito
    # mais que algumas tentativas a mais
    limite = max_fails if ok_total == 0 else max_fails + 3
    if seguidas < limite:
        return "seguir"
    if ok_total == 0:
        return "abortar"
    return "parar" if ja_pediu_conclusao else "concluir"

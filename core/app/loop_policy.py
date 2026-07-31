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


# ============================================================
# SILENCIO — o usuario nunca pode receber uma bolha vazia.
#
# Mapeado em 31/07/2026 lendo agent.py: tokens so sao emitidos em DOIS pontos
# (o texto e acumulado no stream, nao transmitido ao vivo). Logo, tres saidas
# podem entregar NADA:
#
#   A  sem tool_use          -> silencio SE text_acc vier vazio
#   C  decisao 'parar'       -> silencio SEMPRE (yield done, sem token)
#   D  iteracoes esgotadas   -> silencio SEMPRE (yield done, sem token)
#
# A saida B ('abortar') ja emite FALHA_WINTHOR e nao entra aqui.
#
# REGRA DE SEGURANCA: estas mensagens SO aparecem quando nada mais foi
# emitido. Nunca acrescentam texto a uma resposta que funcionou.
# ============================================================

MOTIVO_SEM_TEXTO = "sem_texto"       # modelo terminou sem escrever nada
MOTIVO_PARCIAL = "parcial"           # pediu conclusao e ainda assim nao fechou
MOTIVO_MAX_ITERACOES = "max_iteracoes"

_MSG = {
    MOTIVO_SEM_TEXTO: {
        True: ("Consultei os dados, mas o modelo encerrou sem escrever a "
               "resposta. Pode repetir a pergunta? Se acontecer de novo, "
               "peca menos coisas de uma vez — uma filial ou um periodo por "
               "vez costuma resolver."),
        False: ("O modelo encerrou sem produzir resposta para essa pergunta. "
                "Pode repetir? Se persistir, tente reformular de forma mais "
                "especifica — dizendo a filial e o periodo."),
    },
    MOTIVO_PARCIAL: {
        True: ("Consultei os dados, mas nao consegui fechar a resposta depois "
               "de algumas tentativas. Nao vou arriscar numeros sem base. "
               "Pode reformular, de preferencia com filial e periodo?"),
        False: ("Nao consegui montar uma resposta para essa pergunta. Pode "
                "reformular, de preferencia com filial e periodo?"),
    },
    MOTIVO_MAX_ITERACOES: {
        True: ("A analise ficou longa demais e atingi o limite de passos antes "
               "de escrever a conclusao. Os dados foram consultados, mas a "
               "resposta nao chegou a ser montada. Tente quebrar em partes — "
               "por exemplo, uma filial ou um indicador por vez."),
        False: ("Atingi o limite de passos sem chegar a uma resposta. A "
                "pergunta pode estar ampla demais; tente quebrar em partes."),
    },
}


def teve_dado_apurado(tool_outcomes) -> bool:
    """True se alguma consulta ao Winthor deu certo neste turno."""
    return any(ok for (nome, ok) in (tool_outcomes or [])
               if nome == "oracle_query")


def mensagem_silencio(motivo: str, tool_outcomes=None) -> str:
    """Mensagem para o usuario quando o turno terminaria sem nada.

    Retorna '' para motivo desconhecido — na duvida, nao inventa texto.
    """
    tabela = _MSG.get(motivo)
    if not tabela:
        return ""
    return tabela[teve_dado_apurado(tool_outcomes)]

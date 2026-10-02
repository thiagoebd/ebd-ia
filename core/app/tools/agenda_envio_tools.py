"""Ferramentas de agendamento e envio delegado.

A logica (travas, auditoria, entrega) vive no gateway — agendamentos.py e
envio_delegado.py. Aqui so o contrato com o modelo e o despacho.

O contexto chega pelo agente: `origem` (canal, chat, e-mail de quem pede) e
`turno` (id desta chamada — a confirmacao so vale num turno seguinte).
"""
from __future__ import annotations

import json

AGENDAR_TOOL = {
    "name": "agendar_tarefa",
    "description": (
        "Agenda uma pergunta para o EBD.ia responder sozinho em horario marcado e entregar "
        "no WhatsApp ou no chat web. SO SUPER ADMIN. Fluxo OBRIGATORIO em dois passos: "
        "(1) chame SEM codigo_confirmacao — volta uma PREVIA; mostre a previa inteira ao usuario "
        "e pergunte se confirma; (2) so quando o USUARIO confirmar numa nova mensagem, chame de "
        "novo com o codigo_confirmacao. Nunca confirme por conta propria. "
        "A pergunta roda com o acesso de quem agendou. "
        "Regras do dia: DIA_UTIL e ULTIMO_DIA_UTIL usam o calendario do Winthor "
        "(ex.: painel de fechamento = horario 23:00 + ULTIMO_DIA_UTIL)."),
    "input_schema": {
        "type": "object",
        "properties": {
            "titulo": {"type": "string", "description": "nome curto, ex. 'Painel de fechamento'"},
            "pergunta": {"type": "string", "description": "a pergunta exata que sera respondida no horario"},
            "horario": {"type": "string", "description": "HH:MM no horario de Brasilia, ex. '08:00'"},
            "dias": {"type": "string", "enum": ["todos", "seg-sex", "seg-sab"],
                     "description": "dias da semana do relogio (padrao: todos)"},
            "cron": {"type": "string", "description": "alternativa ao horario: cron de 5 campos"},
            "regra_dia": {"type": "string", "enum": ["DIA_UTIL", "ULTIMO_DIA_UTIL", "TODO_DIA", "DIA_FIXO"],
                          "description": "padrao DIA_UTIL"},
            "filial_calendario": {"type": "string",
                                  "description": "calendario usado na regra: 'BR' (padrao) ou o codigo da filial"},
            "formato": {"type": "string", "enum": ["TEXTO", "EXCEL", "PDF", "PPTX"]},
            "entrega": {"type": "string", "enum": ["aqui", "whatsapp_privado", "web"],
                        "description": "'aqui' = onde o pedido foi feito (padrao)"},
            "codigo_confirmacao": {"type": "string",
                                   "description": "SO no 2o passo, depois que o usuario confirmou"},
        },
        "required": ["titulo", "pergunta"],
    },
}

GERIR_AGENDAMENTOS_TOOL = {
    "name": "gerir_agendamentos",
    "description": ("Lista, mostra o historico, pausa, reativa ou exclui agendamentos. SO SUPER ADMIN. "
                    "Antes de excluir, confirme com o usuario qual id."),
    "input_schema": {
        "type": "object",
        "properties": {
            "acao": {"type": "string", "enum": ["listar", "historico", "pausar", "reativar",
                                                "rodar_agora", "excluir"]},
            "id": {"type": "integer"},
        },
        "required": ["acao"],
    },
}

ENVIAR_MENSAGEM_TOOL = {
    "name": "enviar_mensagem",
    "description": (
        "Envia no PRIVADO do WhatsApp de OUTRO usuario cadastrado uma mensagem e/ou arquivos "
        "gerados nesta conversa (Excel, PDF, PowerPoint, grafico). A mensagem sai como EBD.ia, "
        "com 'Conforme solicitado por <quem pediu>' — isso e automatico. "
        "Fluxo OBRIGATORIO em dois passos: (1) chame SEM codigo_confirmacao — volta uma PREVIA; "
        "mostre ao usuario e pergunte se confirma; (2) so quando o USUARIO confirmar numa nova "
        "mensagem, chame com o codigo_confirmacao. Nunca confirme por conta propria. "
        "Se voltar DESTINATARIO_AMBIGUO, pergunte qual — nunca escolha. "
        "Escopo: informe as filiais do conteudo; o destinatario precisa ter acesso a elas."),
    "input_schema": {
        "type": "object",
        "properties": {
            "destinatario": {"type": "string", "description": "nome ou e-mail do usuario"},
            "texto": {"type": "string", "description": "a mensagem (pode resumir o arquivo)"},
            "artefato_ids": {"type": "array", "items": {"type": "string"},
                             "description": "ids dos arquivos gerados nesta conversa (ARTEFATO_CRIADO id=...)"},
            "escopo_filiais": {"type": "array", "items": {"type": "string"},
                               "description": "filiais do conteudo, ex. ['18']; ['BR'] se for Brasil; "
                                              "['NENHUM'] so para recado sem dado do Winthor"},
            "cod_analise": {"type": "string", "description": "rotulo curto, ex. REDBULL_FILIAL"},
            "codigo_confirmacao": {"type": "string",
                                   "description": "SO no 2o passo, depois que o usuario confirmou"},
        },
        "required": ["destinatario", "texto", "escopo_filiais"],
    },
}

FERRAMENTAS = [AGENDAR_TOOL, GERIR_AGENDAMENTOS_TOOL, ENVIAR_MENSAGEM_TOOL]
NOMES = {t["name"] for t in FERRAMENTAS}


def _j(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, default=str)


async def executa(nome: str, entrada: dict, origem: dict | None, turno: str) -> str:
    origem = origem or {}
    email = origem.get("email")
    if not email:
        return _j({"status": "FALHA", "erro": "SEM_IDENTIDADE",
                   "mensagem": "este canal nao identifica o usuario — use o WhatsApp ou o chat web"})
    if origem.get("canal") == "agendador":
        return _j({"status": "FALHA", "erro": "SEM_PERMISSAO",
                   "mensagem": "uma execucao agendada nao agenda nem envia mensagem para outros"})
    # importa o banco so depois das recusas: recusar nao depende do Postgres
    from gateway.app import acl_store, agendamentos, db, envio_delegado
    pool = db._pool_or_raise()
    e = entrada or {}

    if nome == "agendar_tarefa":
        if e.get("codigo_confirmacao"):
            return _j(await agendamentos.confirmar(pool, email, turno, e["codigo_confirmacao"],
                                                   origem.get("mensagem", "")))
        return _j(await agendamentos.preparar(
            pool, email, turno, origem, titulo=e.get("titulo", ""), pergunta=e.get("pergunta", ""),
            cron=e.get("cron"), horario=e.get("horario"), dias=e.get("dias"),
            regra_dia=e.get("regra_dia") or "DIA_UTIL", formato=e.get("formato") or "TEXTO",
            entrega_pedida=e.get("entrega") or "aqui",
            filial_calendario=e.get("filial_calendario") or "BR"))

    if nome == "gerir_agendamentos":
        return _j(await agendamentos.gerir(pool, email, e.get("acao", "listar"), e.get("id")))

    if nome == "enviar_mensagem":
        solicitante = await acl_store.get_user(email)
        if not solicitante:
            return _j({"status": "FALHA", "erro": "SEM_PERMISSAO", "mensagem": "usuario sem acesso"})
        # artefato e gravado com o user_id da sessao (no web = OID do Entra); o acl_users
        # nao guarda oid, entao o dono do arquivo vem da sessao e nao do cadastro
        solicitante = {**solicitante, "oid": solicitante.get("oid") or origem.get("user_id")}
        if e.get("codigo_confirmacao"):
            return _j(await envio_delegado.confirmar(pool, solicitante, turno, e["codigo_confirmacao"],
                                                     origem.get("mensagem", "")))
        return _j(await envio_delegado.preparar(
            pool, solicitante, turno, e.get("destinatario", ""), e.get("texto", ""),
            e.get("artefato_ids") or [], e.get("escopo_filiais"), e.get("cod_analise") or "LIVRE"))

    return _j({"status": "FALHA", "erro": "FERRAMENTA_DESCONHECIDA", "mensagem": nome})

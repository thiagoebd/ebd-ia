"""Envio delegado — o EBD.ia entrega no privado de OUTRO usuario, a pedido.

Spec "Tool de Envio de Mensagens" (set/2026). Decisao do Thiago (01/10/2026):
qualquer usuario ATIVO pode pedir o envio (a spec previa so admin); todas as
outras travas continuam:

  1. destinatario na whitelist — usuario ATIVO com WhatsApp na tela de Acessos
  2. escopo — as filiais do conteudo tem que estar no escopo de quem pede E
     de quem recebe (interseção). Brasil so para quem e Brasil
  3. atribuicao — escrita pelo SERVIDOR com o nome do ACL; a ferramenta nao
     tem parametro para isso, entao o bot nao tem como se passar por alguem
  4. previa + confirmacao numa nova mensagem (confirmacoes.py)
  5. rate limit por solicitante e global (a instancia nao e oficial)
  6. idempotencia — a mesma chave nao envia duas vezes
  7. auditoria de tudo, inclusive das recusas

Nenhum erro termina em silencio: toda saida e um dict com status e mensagem.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid

from gateway.app import confirmacoes, entrega

ESCOPO_NENHUM, ESCOPO_BR = "NENHUM", "BR"


def _lim(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except ValueError:
        return padrao


# ─── Escopo ──────────────────────────────────────────────────────────────

def normaliza_escopo(escopo) -> tuple[str, list[str]]:
    """-> ('NENHUM', []) | ('BR', []) | ('FILIAIS', ['05','14'])"""
    if isinstance(escopo, str):
        escopo = [escopo]
    itens = [str(x).strip().upper() for x in (escopo or []) if str(x).strip()]
    if not itens:
        raise ValueError("informe o escopo do conteudo: filiais (ex. ['05']), 'BR' ou 'NENHUM'")
    if itens == [ESCOPO_NENHUM]:
        return ESCOPO_NENHUM, []
    if ESCOPO_BR in itens or "*" in itens or "BRASIL" in itens:
        return ESCOPO_BR, []
    cods = sorted({i.zfill(2) for i in itens})
    if not all(c.isalnum() and len(c) <= 3 for c in cods):
        raise ValueError(f"filiais invalidas no escopo: {cods}")
    return "FILIAIS", cods


def cobre(filiais_usuario, tipo: str, cods: list[str]) -> bool:
    if tipo == ESCOPO_NENHUM or filiais_usuario == "*":
        return True
    if tipo == ESCOPO_BR:
        return False
    return set(cods) <= {str(f).zfill(2) for f in (filiais_usuario or [])}


def descreve_escopo(tipo: str, cods: list[str]) -> str:
    return {"NENHUM": "sem dado do Winthor", "BR": "Brasil"}.get(tipo) or "filiais " + ", ".join(cods)


# ─── Destinatario ────────────────────────────────────────────────────────

async def resolver_destinatario(pool, termo: str) -> list[dict]:
    """Usuarios ATIVOS com WhatsApp que casam com nome ou e-mail."""
    termo = (termo or "").strip()
    if not termo:
        return []
    rows = await pool.fetch(
        "SELECT email, nome, whatsapp FROM acl_users "
        "WHERE active AND whatsapp IS NOT NULL AND "
        "(lower(email) = lower($1) OR nome ILIKE '%' || $1 || '%' "
        " OR split_part(lower(email), '@', 1) ILIKE '%' || $1 || '%') "
        "ORDER BY nome LIMIT 6", termo)
    exatos = [dict(r) for r in rows if (r["email"] or "").lower() == termo.lower()]
    return exatos or [dict(r) for r in rows]


def mascara(numero: str) -> str:
    d = "".join(c for c in (numero or "") if c.isdigit())
    return f"+{d[:2]} {d[2:4]} •••••-{d[-4:]}" if len(d) >= 8 else "•••"


# ─── Auditoria e limites ─────────────────────────────────────────────────

async def _audita(pool, **c) -> int:
    return await pool.fetchval(
        """INSERT INTO ebdia_envio_delegado
           (solicitante, role_solicit, destinatario, destino_chat, canal_saida, cod_analise,
            parametros, escopo_aplic, formato, artefatos, idempot_key, status, msg_status)
           VALUES ($1,$2,$3,$4,'whatsapp',$5,$6::jsonb,$7,$8,$9,$10,$11,$12)
           ON CONFLICT (idempot_key) DO NOTHING RETURNING id""",
        c["solicitante"], c["role"], c["destinatario"], c.get("destino_chat"),
        c.get("cod_analise") or "LIVRE", json.dumps(c.get("parametros") or {}, ensure_ascii=False),
        c.get("escopo"), c.get("formato") or "TEXTO", c.get("artefatos") or [],
        c["idempot_key"], c["status"], c.get("msg"))


async def _estourou_limite(pool, solicitante: str) -> str | None:
    hora, dia, glob = (_lim("ENVIO_MAX_HORA", 10), _lim("ENVIO_MAX_DIA", 30),
                       _lim("ENVIO_MAX_GLOBAL_HORA", 60))
    r = await pool.fetchrow(
        """SELECT
             count(*) FILTER (WHERE lower(solicitante) = lower($1)
                              AND dt_pedido > now() - interval '1 hour') AS h,
             count(*) FILTER (WHERE lower(solicitante) = lower($1)
                              AND dt_pedido > now() - interval '1 day')  AS d,
             count(*) FILTER (WHERE dt_pedido > now() - interval '1 hour') AS g
           FROM ebdia_envio_delegado WHERE status IN ('ENVIADO', 'PENDENTE')""", solicitante)
    if r["h"] >= hora:
        return f"limite de {hora} envios por hora atingido — tente mais tarde"
    if r["d"] >= dia:
        return f"limite de {dia} envios por dia atingido"
    if r["g"] >= glob:
        return "limite geral de envios por hora da instancia atingido — protege o numero do bloqueio"
    return None


def chave_idempotencia(solic: str, dest: str, texto: str, artefatos: list[str]) -> str:
    janela = int(time.time() // 600)                       # 10 minutos
    base = "|".join([solic.lower(), dest.lower(), texto.strip(), ",".join(sorted(artefatos)), str(janela)])
    return hashlib.sha256(base.encode()).hexdigest()[:40]


def atribuicao(nome_solicitante: str) -> str:
    return f"📨 _Conforme solicitado por {nome_solicitante}:_"


# ─── Fluxo ───────────────────────────────────────────────────────────────

def _erro(codigo: str, mensagem: str, **extra) -> dict:
    return {"status": "FALHA", "erro": codigo, "mensagem": mensagem, **extra}


async def _valida(pool, solicitante: dict, destinatario: str, texto: str,
                  artefato_ids: list[str], escopo, cod_analise: str) -> dict:
    """Todas as travas. -> {'ok': True, ...} ou dict de erro (e audita a recusa)."""
    from gateway.app import acl_store
    email = solicitante["email"]
    base = {"solicitante": email, "role": solicitante.get("role") or "?",
            "cod_analise": cod_analise}

    async def recusa(codigo, msg, dest_email="?", status="RECUSADO", escopo_txt=None):
        await _audita(pool, **base, destinatario=dest_email, status=status, msg=f"{codigo}: {msg}",
                      escopo=escopo_txt, idempot_key=f"recusa-{uuid.uuid4().hex}")
        return _erro(codigo, msg)

    if not (texto or "").strip():
        return _erro("TEXTO_VAZIO", "a mensagem nao pode ser vazia")
    try:
        tipo, cods = normaliza_escopo(escopo)
    except ValueError as e:
        return _erro("ESCOPO_INVALIDO", str(e))
    if artefato_ids and tipo == ESCOPO_NENHUM:
        return _erro("ESCOPO_INVALIDO", "arquivo gerado tem dado: informe as filiais ou 'BR', nao 'NENHUM'")
    escopo_txt = descreve_escopo(tipo, cods)

    candidatos = await resolver_destinatario(pool, destinatario)
    if not candidatos:
        return await recusa("FORA_DA_WHITELIST",
                            f"'{destinatario}' nao e um usuario ativo com WhatsApp cadastrado na "
                            "tela de Acessos", dest_email=destinatario)
    if len(candidatos) > 1:
        return _erro("DESTINATARIO_AMBIGUO", "mais de um usuario casa com esse nome — pergunte qual",
                     candidatos=[{"nome": c["nome"], "email": c["email"]} for c in candidatos])
    dest = candidatos[0]
    u_dest = await acl_store.get_user(dest["email"])
    if not u_dest:
        return await recusa("FORA_DA_WHITELIST", "destinatario inativo", dest_email=dest["email"])

    if not cobre(solicitante.get("filiais"), tipo, cods):
        return await recusa("ESCOPO_NEGADO", f"o conteudo ({escopo_txt}) esta fora do SEU escopo",
                            dest["email"], "BLOQUEADO_ESCOPO", escopo_txt)
    if not cobre(u_dest.get("filiais"), tipo, cods):
        return await recusa("ESCOPO_NEGADO",
                            f"{dest['nome']} nao tem acesso a {escopo_txt} — o envio viraria porta "
                            "lateral de acesso ao dado", dest["email"], "BLOQUEADO_ESCOPO", escopo_txt)
    try:
        arquivos = await entrega.arquivos_dos_artefatos(
            artefato_ids, [email, solicitante.get("oid")])
    except entrega.EntregaFalhou as e:
        return _erro(e.codigo, f"arquivo {e.detalhe} nao encontrado ou nao e seu — gere de novo")
    limite = await _estourou_limite(pool, email)
    if limite:
        return await recusa("RATE_LIMIT", limite, dest["email"])
    return {"ok": True, "dest": dest, "tipo": tipo, "cods": cods, "escopo_txt": escopo_txt,
            "arquivos": arquivos}


async def preparar(pool, solicitante: dict, turno: str, destinatario: str, texto: str,
                   artefato_ids: list[str] | None = None, escopo=None,
                   cod_analise: str = "LIVRE") -> dict:
    artefato_ids = [str(a) for a in (artefato_ids or [])]
    v = await _valida(pool, solicitante, destinatario, texto, artefato_ids, escopo, cod_analise)
    if not v.get("ok"):
        return v
    dest, nome_solic = v["dest"], solicitante.get("nome") or solicitante["email"]
    dados = {"destinatario": dest["email"], "texto": texto, "artefato_ids": artefato_ids,
             "escopo": escopo, "cod_analise": cod_analise}
    codigo = confirmacoes.cria("enviar", solicitante["email"], turno, dados)
    arqs = ", ".join(a.nome for a in v["arquivos"]) or "nenhum"
    previa = (f"📨 PRÉVIA DO ENVIO — nada saiu ainda\n"
              f"Para: {dest['nome']} ({mascara(dest['whatsapp'])}), no privado do WhatsApp\n"
              f"Escopo do conteúdo: {v['escopo_txt']}\n"
              f"Arquivos: {arqs}\n"
              f"Vai chegar assim:\n{atribuicao(nome_solic)}\n{texto[:600]}"
              f"{'…' if len(texto) > 600 else ''}\n"
              f"Mensagem enviada não se desfaz. Para enviar, o usuário responde confirmando.\n"
              f"Código de confirmação: {codigo}")
    return {"status": "PREVIA", "previa": previa, "codigo_confirmacao": codigo}


async def confirmar(pool, solicitante: dict, turno: str, codigo: str,
                    mensagem: str | None = None) -> dict:
    try:
        d = confirmacoes.consome(codigo, "enviar", solicitante["email"], turno, mensagem)
    except confirmacoes.ConfirmacaoInvalida as e:
        return _erro("CONFIRMACAO_INVALIDA", str(e))
    # revalida: escopo ou acesso podem ter mudado nos minutos da previa
    v = await _valida(pool, solicitante, d["destinatario"], d["texto"], d["artefato_ids"],
                      d["escopo"], d["cod_analise"])
    if not v.get("ok"):
        return v
    dest = v["dest"]
    chave = chave_idempotencia(solicitante["email"], dest["email"], d["texto"], d["artefato_ids"])
    reg = await _audita(pool, solicitante=solicitante["email"], role=solicitante.get("role") or "?",
                        destinatario=dest["email"], destino_chat=dest["whatsapp"],
                        cod_analise=d["cod_analise"], escopo=v["escopo_txt"],
                        formato="ARQUIVO" if d["artefato_ids"] else "TEXTO",
                        artefatos=d["artefato_ids"], idempot_key=chave, status="PENDENTE")
    if reg is None:
        st = await pool.fetchval("SELECT status FROM ebdia_envio_delegado WHERE idempot_key = $1", chave)
        return {"status": "JA_ENVIADO" if st == "ENVIADO" else st,
                "mensagem": "esse mesmo envio ja foi feito nos ultimos minutos — nao repeti"}
    nome_solic = solicitante.get("nome") or solicitante["email"]
    try:
        r = await entrega.whatsapp(entrega.jid_privado(dest["whatsapp"]),
                                   f"{atribuicao(nome_solic)}\n\n{d['texto']}", v["arquivos"])
    except entrega.EntregaFalhou as e:
        await pool.execute("UPDATE ebdia_envio_delegado SET status = 'FALHA_CANAL', msg_status = $2 "
                           "WHERE id = $1", reg, f"{e.codigo}: {e.detalhe}"[:1000])
        return _erro(e.codigo, f"nao consegui entregar ({e.codigo}). Nada foi enviado ao destinatario"
                     if e.codigo != "FALHA_CANAL" else f"falha no envio: {e.detalhe}")
    await pool.execute("UPDATE ebdia_envio_delegado SET status = 'ENVIADO', dt_envio = now(), "
                       "message_id = $2 WHERE id = $1", reg, r.message_id)
    return {"status": "ENVIADO", "para": dest["nome"], "arquivos": r.arquivos_enviados,
            "dt_envio": time.strftime("%d/%m/%Y %H:%M")}

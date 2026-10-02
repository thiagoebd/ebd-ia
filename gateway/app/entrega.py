"""Camada UNICA de entrega — usada pelo agendador e pelo envio delegado.

Spec "Tool de Envio", secao 7: "Nao construir dois caminhos de envio: quem
entrega e a tool; quem decide quando e o agendador." Tudo que sai do EBD.ia
para um chat que nao e a conversa corrente passa por aqui.

Canais:
  whatsapp — grupo (JID) ou privado (numero E.164), pela Evolution
  web      — conversa fixada "Agendamentos" do usuario no chat web
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("uvicorn.error")
TITULO_CONVERSA_AGENDA = "📅 Agendamentos"


class EntregaFalhou(RuntimeError):
    """`codigo` segue os codigos da spec (INSTANCIA_OFFLINE, CHAT_ID_INVALIDO...)."""
    def __init__(self, codigo: str, detalhe: str = ""):
        super().__init__(f"{codigo}: {detalhe}" if detalhe else codigo)
        self.codigo = codigo
        self.detalhe = detalhe


@dataclass
class Arquivo:
    caminho: Path
    nome: str


@dataclass
class Resultado:
    ok: bool
    message_id: str | None = None
    arquivos_enviados: list[str] = field(default_factory=list)


# ─── WhatsApp ────────────────────────────────────────────────────────────

async def instancia_online() -> bool:
    """A sessao da Evolution esta conectada? Mantida por QR: pode cair."""
    import httpx
    url = os.getenv("EVO_URL", "http://127.0.0.1:8081").rstrip("/")
    inst = os.getenv("EVO_INSTANCE", "ebdia")
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.get(f"{url}/instance/connectionState/{inst}",
                              headers={"apikey": os.getenv("EVO_APIKEY", "")})
        d = r.json() if r.status_code < 300 else {}
        return (d.get("instance") or d).get("state") == "open"
    except Exception as e:
        log.warning("entrega: estado da instancia indisponivel: %s", e)
        return False


def jid_privado(numero_e164: str) -> str:
    dig = "".join(c for c in (numero_e164 or "") if c.isdigit())
    if len(dig) < 12:
        raise EntregaFalhou("CHAT_ID_INVALIDO", f"numero incompleto: {numero_e164!r}")
    return f"{dig}@s.whatsapp.net"


async def whatsapp(chat: str, texto: str, arquivos: list[Arquivo] | None = None) -> Resultado:
    from app.adapters.whatsapp import envia_arquivo, envia_texto, md_para_whatsapp
    if not await instancia_online():
        raise EntregaFalhou("INSTANCIA_OFFLINE", "sessao da Evolution desconectada")
    if not (chat.endswith("@g.us") or chat.endswith("@s.whatsapp.net") or chat.endswith("@lid")):
        raise EntregaFalhou("CHAT_ID_INVALIDO", chat)
    if not await envia_texto(chat, md_para_whatsapp(texto) or texto):
        raise EntregaFalhou("FALHA_CANAL", "a Evolution recusou o texto")
    enviados = []
    for a in arquivos or []:
        if await envia_arquivo(chat, a.caminho.read_bytes(), a.nome):
            enviados.append(a.nome)
        else:
            raise EntregaFalhou("FALHA_CANAL", f"a Evolution recusou o arquivo {a.nome}")
    return Resultado(ok=True, arquivos_enviados=enviados)


# ─── Web ─────────────────────────────────────────────────────────────────

async def conversa_agenda(pool, oid: str) -> str:
    """A conversa 'Agendamentos' do usuario — fixada, fora da rotacao."""
    conv = await pool.fetchval(
        "SELECT id::text FROM conversations WHERE user_oid = $1 AND title = $2 "
        "ORDER BY created_at LIMIT 1", oid, TITULO_CONVERSA_AGENDA)
    if conv:
        return conv
    return await pool.fetchval(
        "INSERT INTO conversations (user_oid, title, pinned, pinned_at) "
        "VALUES ($1, $2, true, now()) RETURNING id::text", oid, TITULO_CONVERSA_AGENDA)


async def web(email: str, texto: str, artefato_ids: list[str] | None = None) -> Resultado:
    from gateway.app import db
    pool = db._pool_or_raise()
    oid = await pool.fetchval("SELECT oid FROM acl_users WHERE lower(email) = lower($1)", email)
    if not oid:
        raise EntregaFalhou("CHAT_ID_INVALIDO", f"{email} nunca entrou no chat web (sem oid)")
    conv = await conversa_agenda(pool, oid)
    await db.add_message(conv, "assistant", {"text": texto, "tools": [],
                                             "agendamento": True,
                                             "artefatos": artefato_ids or []})
    return Resultado(ok=True, message_id=conv)


# ─── Artefatos ───────────────────────────────────────────────────────────

async def arquivos_dos_artefatos(ids: list[str], donos: list[str]) -> list[Arquivo]:
    """Caminhos dos artefatos — SO os que pertencem a quem pede (`donos`)."""
    if not ids:
        return []
    from gateway.app import db
    pool = db._pool_or_raise()
    saida = []
    for i in ids:
        row = await pool.fetchrow(
            "SELECT file_path, filename FROM artifacts WHERE id::text = $1 "
            "AND user_oid = ANY($2::text[])", str(i), [d for d in donos if d])
        if not row or not row["file_path"] or not Path(row["file_path"]).exists():
            raise EntregaFalhou("ARTEFATO_NAO_ENCONTRADO", str(i))
        saida.append(Arquivo(Path(row["file_path"]), row["filename"] or Path(row["file_path"]).name))
    return saida

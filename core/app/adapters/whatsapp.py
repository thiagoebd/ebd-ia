"""WhatsApp via Evolution API — o EBD.ia em grupo e em conversa privada.

GRUPO: quando alguem chama `@ebd.ia` num grupo autorizado, o agente responde
citando a pergunta. O resto do grupo e descartado sem ser guardado.

PRIVADO: toda mensagem e para o bot (sem precisar de @). Mesma permissao:
numero cadastrado no campo WhatsApp de um usuario ativo da tela de Acessos.

POR QUE NAO A API OFICIAL
    A Cloud API da Meta so fala em grupos que ela mesma criou, com ate 8
    participantes, e exige Official Business Account. Para entrar num grupo
    que ja existe, o caminho e um numero comum pareado por QR (Evolution).
    Isto e piloto: o uso automatizado vai contra os termos do WhatsApp, entao
    o numero e DEDICADO — nunca pessoal, nunca o da empresa.

SEGURANCA — as quatro portas, nesta ordem
    1. o webhook exige o segredo WA_WEBHOOK_TOKEN no cabecalho
    2. grupo: so os de WA_GRUPOS (JID). Privado: se WA_PRIVADO=true
    3. grupo: so mensagem que chama o bot (mencao, "@ebd.ia" ou resposta a
       ele). Privado: toda mensagem
    4. o numero de quem chamou precisa estar cadastrado no campo WhatsApp de
       um usuario ATIVO na tela de Acessos. Sem cadastro: "sem permissao".

    A pergunta roda COMO a pessoa: o e-mail vai ao MCP, que aplica o papel e
    as filiais dela. Gerente regional no grupo continua vendo so a regional.

LID
    Em grupo, o WhatsApp pode esconder o telefone atras de um identificador
    "@lid". O parser tenta os campos alternativos que trazem o telefone; se
    so houver o LID, ele pode ser mapeado em WA_NUMEROS como
    "lid:<digitos>=email" — excecao, a regra e o cadastro na tela.

NONO DIGITO
    Celular brasileiro antigo aparece no WhatsApp SEM o 9 (553188887777). A
    tela grava e o webhook busca pelo mesmo formato canonico: celular BR
    sempre COM o 9. Sem isso, quem esta cadastrado levaria "sem permissao".
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# ─── configuracao ────────────────────────────────────────────────────────

GATILHOS_TEXTO = ("@ebd.ia", "@ebdia", "@ebd ia")
JID_PESSOA = ("@s.whatsapp.net", "@lid")   # conversa privada; o resto (status,
                                          # canal, broadcast) e ignorado
MAX_CHARS_MSG = 3500          # o WhatsApp aceita mais; o celular le mal
JID_GRUPO = "@g.us"


def _lista_env(nome: str) -> list[str]:
    return [x.strip() for x in os.getenv(nome, "").split(",") if x.strip()]


def grupos_autorizados() -> set[str]:
    return set(_lista_env("WA_GRUPOS"))


def mapa_numeros() -> dict[str, str]:
    """WA_NUMEROS="lid:1234=ciclano@..." — so para o caso de LID sem telefone.

    Telefone se cadastra na tela de Acessos (campo WhatsApp), nao aqui.
    Aceita ainda "5511...=email" por compatibilidade.
    """
    mapa: dict[str, str] = {}
    for par in _lista_env("WA_NUMEROS"):
        if "=" not in par:
            continue
        num, email = (x.strip() for x in par.split("=", 1))
        if not email:
            continue
        if num.lower().startswith("lid:"):
            chave = "lid:" + re.sub(r"\D", "", num)
        else:
            chave = re.sub(r"\D", "", num)
        if chave and chave != "lid:":
            mapa[chave] = email.lower()
    return mapa


def normaliza_whatsapp(numero: str | None) -> str | None:
    """Qualquer grafia -> E.164 canonico ('+5511999998888'), ou None.

    '+55 (11) 99999-8888', '11999998888', '5511999998888' -> '+5511999998888'
    '553188887777' (celular sem o 9, como o WhatsApp manda) -> '+5531988887777'
    '551133334444' (fixo) fica como esta.
    """
    if not numero:
        return None
    bruto = str(numero).strip()
    d = re.sub(r"\D", "", bruto)
    # com "+" o codigo do pais e respeitado; sem ele, 10-11 digitos = DDD+numero
    if not bruto.startswith("+") and len(d) in (10, 11) and not d.startswith("55"):
        d = "55" + d
    if d.startswith("55") and len(d) == 12 and d[4] in "6789":
        d = d[:4] + "9" + d[4:]                       # celular sem o nono digito
    if not (8 <= len(d) <= 15) or d[0] == "0":
        return None
    if d.startswith("55") and len(d) not in (12, 13):
        return None
    return "+" + d


# ─── o evento ────────────────────────────────────────────────────────────

def privado_ligado() -> bool:
    return os.getenv("WA_PRIVADO", "true").strip().lower() == "true"


@dataclass
class Mensagem:
    grupo: str                      # JID da CONVERSA (grupo ou privada)
    msg_id: str
    texto: str
    remetente_jid: str              # como veio (pode ser @lid)
    telefone: str | None            # so digitos, se descoberto
    lid: str | None                 # digitos do LID, se houver
    nome: str = ""
    mencionados: list[str] = field(default_factory=list)
    responde_a: str | None = None   # participante da mensagem citada
    citado: str | None = None       # texto da mensagem citada (resposta a uma mensagem)
    de_mim: bool = False
    privado: bool = False
    # {"tipo": imagem|audio|documento, "mimetype", "nome", "base64", "bruto"}
    midia: dict | None = None


def _digitos_de_jid(jid: str | None, sufixo: str) -> str | None:
    if jid and jid.endswith(sufixo):
        d = re.sub(r"\D", "", jid.split("@")[0].split(":")[0])
        return d or None
    return None


def _texto_de(msg: dict) -> tuple[str, dict]:
    """(texto, contextInfo) de qualquer formato de mensagem de texto."""
    if not isinstance(msg, dict):
        return "", {}
    if isinstance(msg.get("conversation"), str):
        return msg["conversation"], msg.get("contextInfo") or {}
    ext = msg.get("extendedTextMessage") or {}
    if ext:
        return ext.get("text") or "", ext.get("contextInfo") or {}
    for tipo in ("imageMessage", "videoMessage", "documentMessage"):
        m = msg.get(tipo) or {}
        if m:
            return m.get("caption") or "", m.get("contextInfo") or {}
    return "", {}


_TIPOS_MIDIA = {"imageMessage": "imagem", "audioMessage": "audio",
               "documentMessage": "documento"}


def _midia_de(data: dict) -> dict | None:
    """Foto, audio ou documento do evento — com o base64 se o webhook trouxe."""
    msg = data.get("message") or {}
    if "documentWithCaptionMessage" in msg:                # documento com legenda
        msg = (msg["documentWithCaptionMessage"] or {}).get("message") or msg
    for chave, tipo in _TIPOS_MIDIA.items():
        m = msg.get(chave)
        if isinstance(m, dict):
            b64 = (data.get("message") or {}).get("base64") or data.get("base64")
            return {"tipo": tipo, "mimetype": (m.get("mimetype") or "").split(";")[0],
                    "nome": m.get("fileName") or "", "base64": b64,
                    "voz": bool(m.get("ptt")),
                    "bruto": {"key": data.get("key"), "message": data.get("message")}}
    return None


def parse_evento(payload: dict) -> Mensagem | None:
    """Evento MESSAGES_UPSERT da Evolution -> Mensagem, ou None se nao for
    mensagem de texto de grupo. Tolerante aos formatos que variam entre
    versoes (data como objeto ou lista, contextInfo em dois lugares)."""
    if not isinstance(payload, dict):
        return None
    ev = str(payload.get("event") or "").lower().replace("_", ".")
    if ev and ev != "messages.upsert":
        return None
    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        return None

    key = data.get("key") or {}
    grupo = key.get("remoteJid") or ""
    privado = grupo.endswith(JID_PESSOA)
    if not (grupo.endswith(JID_GRUPO) or privado):
        return None                 # status, canal, broadcast

    msg = data.get("message") or {}
    if "documentWithCaptionMessage" in msg:
        msg = (msg["documentWithCaptionMessage"] or {}).get("message") or msg
    texto, ctx = _texto_de(msg)
    if not ctx:
        ctx = ((msg.get("audioMessage") or {}).get("contextInfo")
               or data.get("contextInfo") or {})
    midia = _midia_de(data)
    if not texto.strip() and midia is None:
        return None

    if privado:
        # no privado o remetente E a conversa; o telefone pode vir no Alt
        remetente = grupo
        alternativos = (key.get("remoteJidAlt"), key.get("senderPn"),
                        data.get("senderPn"), remetente)
    else:
        remetente = key.get("participant") or data.get("participant") or ""
        alternativos = (key.get("participantAlt"), key.get("participantPn"),
                        key.get("senderPn"), data.get("participantAlt"),
                        data.get("senderPn"), remetente)
    # o telefone pode vir em campos alternativos quando o id e LID
    telefone = None
    for cand in alternativos:
        telefone = _digitos_de_jid(cand, "@s.whatsapp.net")
        if telefone:
            break
    lid = None
    for cand in (remetente, key.get("participantLid"), data.get("participantLid"),
                 key.get("remoteJidAlt")):
        lid = _digitos_de_jid(cand, "@lid")
        if lid:
            break

    return Mensagem(
        grupo=grupo,
        msg_id=key.get("id") or "",
        texto=texto,
        remetente_jid=remetente,
        telefone=telefone,
        lid=lid,
        nome=data.get("pushName") or "",
        mencionados=list(ctx.get("mentionedJid") or []),
        responde_a=ctx.get("participant"),
        citado=(_texto_de(ctx.get("quotedMessage") or {})[0] or "").strip() or None,
        de_mim=bool(key.get("fromMe")),
        privado=privado,
        midia=midia,
    )


# ─── foi chamado? ────────────────────────────────────────────────────────

def _base_jid(jid: str) -> str:
    """'5511999@s.whatsapp.net' e '5511999:12@s.whatsapp.net' -> '5511999'."""
    return (jid or "").split("@")[0].split(":")[0]


def foi_chamado(m: Mensagem, ids_do_bot: set[str]) -> bool:
    """Mencao real, "@ebd.ia" digitado, ou resposta a uma mensagem do bot.

    `ids_do_bot`: JIDs/LIDs do numero do bot (so a parte antes do @).
    No privado, toda mensagem e para o bot."""
    if m.de_mim:
        return False
    if m.privado:
        return True
    bases = {_base_jid(x) for x in ids_do_bot if x}
    if m.midia and m.midia["tipo"] == "audio":
        # audio nao tem como marcar ninguem: no grupo, so se RESPONDER ao bot
        return bool(m.responde_a and _base_jid(m.responde_a) in bases)
    if any(_base_jid(j) in bases for j in m.mencionados):
        return True
    if m.responde_a and _base_jid(m.responde_a) in bases:
        return True
    baixo = m.texto.lower()
    return any(g in baixo for g in GATILHOS_TEXTO)


def limpa_pergunta(texto: str) -> str:
    """Tira a mencao ("@5511999...", "@ebd.ia") e sobra so a pergunta."""
    t = re.sub(r"@ebd[\s.]?ia\b", " ", texto, flags=re.I)
    t = re.sub(r"@\d{6,}", " ", t)
    return re.sub(r"\s+", " ", t).strip(" ,:;-")


def email_do_remetente(m: Mensagem, mapa: dict[str, str] | None = None) -> str | None:
    mapa = mapa if mapa is not None else mapa_numeros()
    if m.telefone and m.telefone in mapa:
        return mapa[m.telefone]
    if m.lid and f"lid:{m.lid}" in mapa:
        return mapa[f"lid:{m.lid}"]
    return None


# ─── markdown -> WhatsApp ────────────────────────────────────────────────

_SEP_TABELA = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _celulas(linha: str) -> list[str]:
    s = linha.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _tabela_para_lista(linhas: list[str]) -> list[str]:
    """O WhatsApp nao renderiza tabela. Cada linha vira um item:
    **primeira coluna** — Col2: v · Col3: v   (vira *negrito* no fim)"""
    cab = _celulas(linhas[0])
    corpo = [l for l in linhas[1:] if not _SEP_TABELA.match(l)]
    saida = []
    for l in corpo:
        cel = _celulas(l)
        if not any(cel):
            continue
        titulo = cel[0].replace("**", "").strip()
        resto = [f"{cab[i]}: {cel[i]}" for i in range(1, min(len(cab), len(cel)))
                 if cel[i].strip()]
        # emite MARKDOWN (**x**): a conversao para o WhatsApp acontece uma vez,
        # no fim. Emitir *x* aqui fazia o passo do italico virar _x_.
        saida.append(f"**{titulo}**" + (" — " + " · ".join(resto) if resto else ""))
    return saida


def md_para_whatsapp(texto: str) -> str:
    """Markdown do agente -> formatacao do WhatsApp.

    **negrito** -> *negrito* · *italico* -> _italico_ · # titulo -> *titulo*
    tabela -> lista · [texto](url) -> texto (url) · codigo em bloco mantido
    """
    linhas = texto.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    em_codigo = False
    while i < len(linhas):
        l = linhas[i]
        if l.strip().startswith("```"):
            em_codigo = not em_codigo
            out.append("```")
            i += 1
            continue
        if em_codigo:
            out.append(l)
            i += 1
            continue
        # tabela: linha com | seguida de separador
        if "|" in l and i + 1 < len(linhas) and _SEP_TABELA.match(linhas[i + 1]):
            bloco = [l]
            j = i + 1
            while j < len(linhas) and "|" in linhas[j]:
                bloco.append(linhas[j])
                j += 1
            out.extend(_tabela_para_lista(bloco))
            i = j
            continue
        out.append(l)
        i += 1

    s = "\n".join(out)
    # protege o que ja e bloco de codigo
    partes = re.split(r"(```.*?```)", s, flags=re.S)
    for k, p in enumerate(partes):
        if p.startswith("```"):
            continue
        p = re.sub(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", r"**\1**", p, flags=re.M)
        p = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", p)
        # italico markdown (*x*) antes do negrito, com o negrito protegido
        p = re.sub(r"\*\*(.+?)\*\*", "\x00\\1\x00", p, flags=re.S)
        p = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"_\1_", p)
        p = p.replace("\x00", "*")
        p = re.sub(r"__(.+?)__", r"*\1*", p)
        p = re.sub(r"^\s*[-*]\s+", "• ", p, flags=re.M)
        p = re.sub(r"^\s*-{3,}\s*$", "", p, flags=re.M)
        p = re.sub(r"`([^`\n]+)`", r"\1", p)
        partes[k] = p
    s = "".join(partes)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def fatiar(texto: str, limite: int = MAX_CHARS_MSG) -> list[str]:
    """Quebra em paragrafos, sem cortar no meio de uma linha quando possivel."""
    if len(texto) <= limite:
        return [texto]
    pedacos, atual = [], ""
    for par in texto.split("\n\n"):
        cand = f"{atual}\n\n{par}" if atual else par
        if len(cand) <= limite:
            atual = cand
            continue
        if atual:
            pedacos.append(atual)
        while len(par) > limite:
            corte = par.rfind("\n", 0, limite)
            corte = corte if corte > limite // 2 else limite
            pedacos.append(par[:corte])
            par = par[corte:].lstrip("\n")
        atual = par
    if atual:
        pedacos.append(atual)
    return pedacos


# ─── cliente Evolution ───────────────────────────────────────────────────

def payload_texto(grupo: str, texto: str, citar: Mensagem | None = None) -> dict:
    """Corpo de POST /message/sendText/{instancia} (Evolution v2)."""
    corpo: dict = {"number": grupo, "text": texto}
    # no privado nao cita: a conversa e so entre os dois
    if citar is not None and citar.msg_id and not citar.privado:
        corpo["quoted"] = {
            "key": {"remoteJid": citar.grupo, "fromMe": False,
                    "id": citar.msg_id, "participant": citar.remetente_jid},
            "message": {"conversation": citar.texto[:500]},
        }
    return corpo


async def envia_texto(grupo: str, texto: str, citar: Mensagem | None = None) -> bool:
    """Envia ao grupo. So a primeira parte cita a pergunta."""
    import httpx
    url = os.getenv("EVO_URL", "http://127.0.0.1:8081").rstrip("/")
    inst = os.getenv("EVO_INSTANCE", "ebdia")
    headers = {"apikey": os.getenv("EVO_APIKEY", ""),
               "Content-Type": "application/json"}
    ok = True
    async with httpx.AsyncClient(timeout=30) as cli:
        for n, parte in enumerate(fatiar(texto)):
            cita = citar if n == 0 else None
            r = await cli.post(f"{url}/message/sendText/{inst}", headers=headers,
                               json=payload_texto(grupo, parte, cita))
            if r.status_code >= 300 and cita is not None:
                # citacao de participante @lid pode ser recusada: manda sem citar
                import logging
                logging.getLogger("uvicorn.error").warning(
                    "wa: envio citando recusado (%s): %s — reenviando sem citar",
                    r.status_code, r.text[:200])
                r = await cli.post(f"{url}/message/sendText/{inst}", headers=headers,
                                   json=payload_texto(grupo, parte, None))
            if r.status_code >= 300:
                import logging
                logging.getLogger("uvicorn.error").warning(
                    "wa: envio recusado (%s): %s", r.status_code, r.text[:200])
                ok = False
    return ok


# ─── midia: baixar, enviar audio e arquivo ───────────────────────────────

def _evo():
    url = os.getenv("EVO_URL", "http://127.0.0.1:8081").rstrip("/")
    inst = os.getenv("EVO_INSTANCE", "ebdia")
    headers = {"apikey": os.getenv("EVO_APIKEY", ""), "Content-Type": "application/json"}
    return url, inst, headers


async def _post(caminho: str, corpo: dict, timeout: int = 120):
    import httpx
    import logging
    url, inst, headers = _evo()
    async with httpx.AsyncClient(timeout=timeout) as cli:
        r = await cli.post(f"{url}/{caminho}/{inst}", headers=headers, json=corpo)
    if r.status_code >= 300:
        logging.getLogger("uvicorn.error").warning(
            "wa: %s recusado (%s): %s", caminho, r.status_code, r.text[:200])
    return r


async def baixa_midia(m: Mensagem) -> bytes:
    """Bytes da midia. Usa o base64 do webhook; sem ele, pede a Evolution
    passando a mensagem INTEIRA — so pelo ID nao funciona, porque a Evolution
    esta configurada para nao guardar mensagens."""
    import base64
    if not m.midia:
        return b""
    b64 = m.midia.get("base64")
    if not b64:
        r = await _post("chat/getBase64FromMediaMessage",
                        {"message": m.midia["bruto"], "convertToMp4": False})
        b64 = (r.json() or {}).get("base64") if r.status_code < 300 else None
    if not b64:
        return b""
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    return base64.b64decode(b64)


def _citacao(citar: Mensagem | None) -> dict | None:
    if citar is None or not citar.msg_id or citar.privado:
        return None
    return {"key": {"remoteJid": citar.grupo, "fromMe": False,
                    "id": citar.msg_id, "participant": citar.remetente_jid},
            "message": {"conversation": (citar.texto or "")[:500]}}


async def envia_audio(chat: str, wav: bytes, citar: Mensagem | None = None) -> bool:
    """Nota de voz. A Evolution converte o WAV para ogg/opus (encoding=true)."""
    import base64
    corpo = {"number": chat, "audio": base64.b64encode(wav).decode(), "encoding": True}
    q = _citacao(citar)
    if q:
        corpo["quoted"] = q
    r = await _post("message/sendWhatsAppAudio", corpo)
    if r.status_code >= 300 and q:
        corpo.pop("quoted")
        r = await _post("message/sendWhatsAppAudio", corpo)
    return r.status_code < 300


_MIME = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "pdf": "application/pdf",
         "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
         "png": "image/png", "jpg": "image/jpeg", "html": "text/html",
         "csv": "text/csv", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


async def envia_arquivo(chat: str, dados: bytes, nome: str, legenda: str = "") -> bool:
    """Documento (ou imagem, se for png/jpg). A Evolution exige fileName."""
    import base64
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    tipo = "image" if ext in ("png", "jpg", "jpeg") else "document"
    corpo = {"number": chat, "mediatype": tipo,
             "mimetype": _MIME.get(ext, "application/octet-stream"),
             "media": base64.b64encode(dados).decode(), "fileName": nome}
    if legenda:
        corpo["caption"] = legenda[:900]
    r = await _post("message/sendMedia", corpo)
    return r.status_code < 300

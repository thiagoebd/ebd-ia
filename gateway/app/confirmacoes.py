"""Previa + confirmacao que o modelo NAO consegue pular.

Spec "Tool de Envio", secao 4: "Preview antes de enviar. Instancia propria
nao desfaz mensagem enviada." Instrucao no prompt nao basta — o modelo pode
chamar a ferramenta duas vezes seguidas. Entao:

  1. a 1a chamada valida tudo e devolve a PREVIA com um codigo
  2. o codigo so e aceito num TURNO DIFERENTE — uma nova mensagem do usuario
  3. o codigo e do usuario que pediu, vale 15 minutos e e usado uma vez so

O turno e um id gerado a cada chamada do agente (run_turn_stream).
"""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field

VALIDADE_S = 15 * 60
_pendentes: dict[str, "Pendencia"] = {}


@dataclass
class Pendencia:
    tipo: str                 # agendar | enviar
    email: str
    turno: str
    dados: dict
    criada: float = field(default_factory=time.time)


class ConfirmacaoInvalida(ValueError):
    pass


def _limpa() -> None:
    agora = time.time()
    for k in [k for k, p in _pendentes.items() if agora - p.criada > VALIDADE_S]:
        _pendentes.pop(k, None)


def cria(tipo: str, email: str, turno: str, dados: dict) -> str:
    _limpa()
    codigo = secrets.token_hex(3).upper()          # 6 caracteres, ex. 4F9A2C
    _pendentes[codigo] = Pendencia(tipo, (email or "").lower(), turno, dados)
    return codigo


_SIM = re.compile(r"\b(sim|confirm\w*|pode|manda|mande|envia|envie|ok|okay|isso|"
                  r"certo|fechado|beleza|blz|positivo|agenda|agende|grava|grave|bora|vai)\b|👍|✅", re.I)
_NAO = re.compile(r"\b(n[aã]o|nunca|cancel\w*|pare|espera|espere|aguarda|errad\w*|"
                  r"muda|mude|corrig\w*|altera|altere)\b|❌", re.I)


def parece_confirmacao(mensagem: str | None, codigo: str | None = None) -> bool:
    """A ultima mensagem do USUARIO concorda? Negacao vence ("nao confirmo")."""
    # marcas do sistema entre colchetes (grupo, audio, planilha) nao sao o usuario
    m = re.sub(r"\[[^\]]*\]", " ", mensagem or "").strip()
    if not m or _NAO.search(m):
        return False
    return bool(_SIM.search(m) or (codigo and codigo.strip().upper() in m.upper()))


def consome(codigo: str, tipo: str, email: str, turno: str, mensagem: str | None = None) -> dict:
    _limpa()
    p = _pendentes.get((codigo or "").strip().upper())
    if p is None or p.tipo != tipo:
        raise ConfirmacaoInvalida("codigo de confirmacao inexistente ou expirado — gere a previa de novo")
    if p.email != (email or "").lower():
        raise ConfirmacaoInvalida("este codigo e de outro usuario")
    if p.turno == turno:
        raise ConfirmacaoInvalida(
            "a confirmacao precisa vir do USUARIO numa nova mensagem. Mostre a previa "
            "e espere ele responder — nao confirme na mesma rodada")
    if mensagem is not None and not parece_confirmacao(mensagem, codigo):
        raise ConfirmacaoInvalida(
            "a ultima mensagem do usuario nao confirma (ou nega). Pergunte de novo se confirma")
    _pendentes.pop(codigo.strip().upper(), None)
    return p.dados

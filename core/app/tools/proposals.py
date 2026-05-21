"""Gerenciador de propostas pendentes de auto-append.

Cada proposta tem PROPOSAL_ID, tipo, conteudo, justificativa e expira em 30min.
Persistido em /tmp/ebd_ia_proposals.json (sobrevive reinicio do agent).
"""
import json
import time
import uuid
from pathlib import Path
from typing import Literal

PROPOSALS_FILE = Path("/tmp/ebd_ia_proposals.json")
PROPOSAL_TTL_SECONDS = 30 * 60  # 30min

TipoProposal = Literal["template", "cicatriz", "conhecimento"]


def _load() -> dict:
    if not PROPOSALS_FILE.exists():
        return {}
    try:
        return json.loads(PROPOSALS_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    PROPOSALS_FILE.write_text(json.dumps(data, indent=2, default=str))


def _cleanup_expired(data: dict) -> dict:
    now = time.time()
    return {k: v for k, v in data.items() if (now - v.get("created_at", 0)) < PROPOSAL_TTL_SECONDS}


def create_proposal(
    tipo: TipoProposal,
    titulo: str,
    conteudo: str,
    justificativa: str,
    user_id: str,
) -> str:
    """Cria proposta pendente e retorna PROPOSAL_ID."""
    data = _cleanup_expired(_load())
    pid = f"PROP-{uuid.uuid4().hex[:8].upper()}"
    data[pid] = {
        "id": pid,
        "tipo": tipo,
        "titulo": titulo,
        "conteudo": conteudo,
        "justificativa": justificativa,
        "user_id": user_id,
        "created_at": time.time(),
        "status": "pending",
    }
    _save(data)
    return pid


def get_proposal(pid: str) -> dict | None:
    data = _cleanup_expired(_load())
    return data.get(pid)


def mark_approved(pid: str) -> None:
    data = _load()
    if pid in data:
        data[pid]["status"] = "approved"
        data[pid]["approved_at"] = time.time()
        _save(data)


def mark_discarded(pid: str) -> None:
    data = _load()
    if pid in data:
        data[pid]["status"] = "discarded"
        _save(data)


def list_pending(user_id: str | None = None) -> list[dict]:
    data = _cleanup_expired(_load())
    pending = [p for p in data.values() if p.get("status") == "pending"]
    if user_id:
        pending = [p for p in pending if p.get("user_id") == user_id]
    return pending

"""Tela 'Tarefas agendadas' — TODOS os endpoints exigem super_admin (server-side).

Reaproveita agendamentos.gerir, a mesma funcao que o agente usa: a tela e a
conversa veem e mudam exatamente a mesma coisa.
"""
from fastapi import APIRouter, Depends, HTTPException

from gateway.app import agendamentos, db
from gateway.app.routes.admin_acl import require_super_admin

router = APIRouter(prefix="/admin/agendamentos", tags=["agendamentos"])


async def _gerir(email: str, acao: str, id_agend: int | None = None) -> dict:
    r = await agendamentos.gerir(db._pool_or_raise(), email, acao, id_agend)
    if r.get("status") != "OK":
        raise HTTPException(404 if r.get("erro") == "NAO_ENCONTRADO" else 400,
                            r.get("mensagem") or r.get("erro"))
    return r


@router.get("")
async def listar(email: str = Depends(require_super_admin)):
    return await _gerir(email, "listar")


@router.get("/{id_agend}/historico")
async def historico(id_agend: int, email: str = Depends(require_super_admin)):
    return await _gerir(email, "historico", id_agend)


@router.post("/{id_agend}/{acao}")
async def acao(id_agend: int, acao: str, email: str = Depends(require_super_admin)):
    if acao not in ("pausar", "reativar", "rodar_agora"):
        raise HTTPException(400, "acao: pausar, reativar ou rodar_agora")
    return await _gerir(email, acao, id_agend)


@router.delete("/{id_agend}")
async def excluir(id_agend: int, email: str = Depends(require_super_admin)):
    return await _gerir(email, "excluir", id_agend)

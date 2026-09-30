"""GET /api/conversations e /api/conversations/{id} — historico persistente."""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from gateway.app.auth.entra import verify_token
from gateway.app import db

logger = logging.getLogger("uvicorn.error")
router = APIRouter()


def _uid(claims: dict) -> str:
    return claims.get("oid") or claims.get("sub") or "web-user"


@router.get("/conversations")
async def list_convs(claims: dict = Depends(verify_token)):
    convs = await db.list_conversations(_uid(claims))
    return [
        {"id": str(c["id"]), "title": c["title"], "model": c["model"],
         "updated_at": c["updated_at"].isoformat(),
         "pinned": bool(c.get("pinned"))}
        for c in convs
    ]


@router.get("/conversations/{conv_id}")
async def get_conv(conv_id: str, claims: dict = Depends(verify_token)):
    uid = _uid(claims)
    conv = await db.get_conversation(conv_id, uid)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada")
    msgs = await db.get_messages(conv_id, uid)
    out_msgs = []
    for m in msgs:
        c = m["content"] if isinstance(m["content"], dict) else {}
        out_msgs.append({"role": m["role"], "text": c.get("text", ""),
                         "imagens": c.get("imagens") or None,
                         "anexo": c.get("anexo") or None,
                         "tools": c.get("tools", []),
                         "artifacts": m.get("artifacts", [])})
    return {"id": str(conv["id"]), "title": conv["title"],
            "model": conv["model"], "messages": out_msgs}


@router.delete("/conversations/{conv_id}")
async def delete_conv(conv_id: str, claims: dict = Depends(verify_token)):
    uid = _uid(claims)
    ok = await db.delete_conversation(conv_id, uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada")
    return {"deleted": True, "id": conv_id}


class PinBody(BaseModel):
    pinned: bool


@router.patch("/conversations/{conv_id}")
async def pin_conv(conv_id: str, body: PinBody,
                   claims: dict = Depends(verify_token)):
    """Fixa / desafixa. Conversa fixada fica fora da rotacao das 8."""
    try:
        uuid.UUID(conv_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada")
    try:
        conv = await db.set_pinned(conv_id, _uid(claims), body.pinned)
    except db.LimiteFixadas as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada")
    logger.info("conversa %s %s", conv_id, "fixada" if body.pinned else "desafixada")
    return {"id": str(conv["id"]), "pinned": conv["pinned"]}

"""GET /api/conversations e /api/conversations/{id} — historico persistente."""
import logging
from fastapi import APIRouter, Depends, HTTPException

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
         "updated_at": c["updated_at"].isoformat()}
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
                         "tools": c.get("tools", [])})
    return {"id": str(conv["id"]), "title": conv["title"],
            "model": conv["model"], "messages": out_msgs}


@router.delete("/conversations/{conv_id}")
async def delete_conv(conv_id: str, claims: dict = Depends(verify_token)):
    uid = _uid(claims)
    ok = await db.delete_conversation(conv_id, uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada")
    return {"deleted": True, "id": conv_id}


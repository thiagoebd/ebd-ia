"""POST /api/chat — conversa com o agente EBD.ia via streaming SSE, com persistencia.

Fluxo:
  1. Resolve a conversa (conversation_id do corpo, ou cria nova).
  2. Salva a pergunta do usuario no Postgres.
  3. Carrega uma JANELA leve (so texto, ultimas trocas) e passa pro agente.
  4. Faz streaming; ao terminar, salva a resposta (texto + flag de tools usados).
"""
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from gateway.app.auth.entra import verify_token
from gateway.app import db

from app.agent import run_turn_stream
from app.config import settings

logger = logging.getLogger("uvicorn.error")
router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    history: list | None = None  # compatibilidade; IGNORADO (janela vem do banco)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _title_from(text: str) -> str:
    t = text.strip().replace("\n", " ")
    return (t[:42] + "…") if len(t) > 42 else (t or "Nova conversa")


@router.post("/chat")
async def chat(body: ChatRequest, claims: dict = Depends(verify_token)):
    user_id = claims.get("oid") or claims.get("sub") or "web-user"
    user_role = "admin"
    user_filiais = "*"

    async def event_stream():
        conv_id = body.conversation_id
        new_conv = False
        try:
            if conv_id:
                conv = await db.get_conversation(conv_id, user_id)
                if not conv:
                    conv = await db.create_conversation(user_id, _title_from(body.message), settings.claude_model)
                    new_conv = True
            else:
                conv = await db.create_conversation(user_id, _title_from(body.message), settings.claude_model)
                new_conv = True
            conv_id = str(conv["id"])

            yield _sse({"type": "conversation", "id": conv_id,
                        "title": conv["title"], "new": new_conv})

            window = await db.build_model_window(conv_id, user_id)
            await db.add_message(conv_id, "user", {"text": body.message})

            assistant_text = ""
            tools_used = []
            saved = False
            try:
                async for ev in run_turn_stream(
                    user_message=body.message,
                    conversation_history=window,
                    user_id=user_id,
                    user_role=user_role,
                    user_filiais=user_filiais,
                    channel="web",
                ):
                    etype = ev.get("type")
                    if etype == "token":
                        assistant_text += ev.get("text", "")
                    elif etype == "tool":
                        name = ev.get("name")
                        if name and name not in tools_used:
                            tools_used.append(name)
                    elif etype == "done":
                        await db.add_message(conv_id, "assistant",
                                             {"text": assistant_text, "tools": tools_used})
                        saved = True
                        ev.pop("history", None)  # nao precisa mandar o historico cru pro front
                    yield _sse(ev)
            finally:
                if not saved and assistant_text:
                    await db.add_message(conv_id, "assistant",
                                         {"text": assistant_text, "tools": tools_used})
        except Exception as e:
            logger.exception("Erro no /api/chat stream")
            yield _sse({"type": "error", "detail": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

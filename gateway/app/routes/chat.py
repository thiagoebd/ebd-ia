"""POST /api/chat — conversa com o agente EBD.ia via streaming SSE.

Recebe pergunta + histórico, valida o token Entra (Depends verify_token),
chama core.agent.run_turn_stream() e repassa os eventos como Server-Sent Events.

Eventos SSE emitidos (cada um é uma linha `data: {json}\\n\\n`):
  {"type":"status","text":"Consultando o Winthor..."}
  {"type":"token","text":"..."}            ← pedaço de texto da resposta
  {"type":"tool","name":"oracle_query","input":{...}}
  {"type":"done","usage":{...},"tool_calls":[...],"history":[...]}
  {"type":"error","detail":"..."}          ← se algo falhar no meio
"""
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from gateway.app.auth.entra import verify_token

# core/ já está no sys.path (configurado em main.py)
from app.agent import run_turn_stream

logger = logging.getLogger("uvicorn.error")
router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    history: list | None = None


def _sse(payload: dict) -> str:
    """Formata um dict como linha SSE."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(body: ChatRequest, claims: dict = Depends(verify_token)):
    # Identidade vem do token validado (não do corpo — segurança)
    user_id = claims.get("oid") or claims.get("sub") or "web-user"
    user_name = claims.get("name", "")

    # Por enquanto todo logado é admin/visão BR (ACL real vem na Semana 3)
    user_role = "admin"
    user_filiais = "*"

    async def event_stream():
        try:
            async for ev in run_turn_stream(
                user_message=body.message,
                conversation_history=body.history,
                user_id=user_id,
                user_role=user_role,
                user_filiais=user_filiais,
                channel="web",
            ):
                yield _sse(ev)
        except Exception as e:
            logger.exception("Erro no /api/chat stream")
            yield _sse({"type": "error", "detail": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx não bufferiza (SSE flui)
            "Connection": "keep-alive",
        },
    )

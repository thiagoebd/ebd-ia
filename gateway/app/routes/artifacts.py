"""GET /api/artifacts e /api/artifacts/{id}/download — listar e baixar."""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from gateway.app.auth.entra import verify_token
from gateway.app import db

logger = logging.getLogger("uvicorn.error")
router = APIRouter()


def _uid(claims: dict) -> str:
    return claims.get("oid") or claims.get("sub") or "web-user"


# MIME types por kind
MIME_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf":  "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "chart": "image/png",  # se rasterizado; chart inline usa outro caminho
}


@router.get("/artifacts")
async def list_arts(
    kind: str | None = None,
    claims: dict = Depends(verify_token),
):
    arts = await db.list_artifacts(_uid(claims), kind=kind)
    return [
        {
            "id": str(a["id"]),
            "kind": a["kind"],
            "filename": a["filename"],
            "title": a["title"],
            "size_bytes": a["size_bytes"],
            "created_at": a["created_at"].isoformat(),
        }
        for a in arts
    ]


@router.get("/artifacts/{artifact_id}/download")
async def download_art(artifact_id: str, claims: dict = Depends(verify_token)):
    uid = _uid(claims)
    art = await db.get_artifact(artifact_id, uid)
    if not art:
        raise HTTPException(status_code=404, detail="Artefato nao encontrado")
    file_path = Path(art["file_path"])
    if not file_path.is_file():
        logger.error(f"Arquivo de artefato sumiu do disco: {file_path}")
        raise HTTPException(status_code=410, detail="Arquivo expirou ou foi removido")
    mime = MIME_TYPES.get(art["kind"], "application/octet-stream")
    return FileResponse(
        path=file_path,
        media_type=mime,
        filename=art["filename"],
    )

"""Camada de persistência (Postgres) do gateway EBD.ia.

Guarda conversas e mensagens do chat web por usuário (oid do Entra).
Reusa as credenciais do .env da raiz (mesmas do docker-compose). O Postgres
publica 127.0.0.1:5432 no host e o gateway roda no host -> conecta direto.
"""
import os
import json
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

PG_HOST = os.getenv("GATEWAY_PG_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("GATEWAY_PG_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD")
PG_DB = os.getenv("POSTGRES_DB")

_pool = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_oid    text        NOT NULL,
    title       text        NOT NULL DEFAULT 'Nova conversa',
    model       text        NOT NULL DEFAULT 'deepseek-v4-flash',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS messages (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid        NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            text        NOT NULL CHECK (role IN ('user','assistant')),
    content         jsonb       NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conv_user_updated ON conversations (user_oid, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_msg_conv_created  ON messages (conversation_id, created_at);
"""


async def init_db():
    """Cria o pool e garante o schema (idempotente). Chamado no startup."""
    global _pool
    _pool = await asyncpg.create_pool(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, database=PG_DB,
        min_size=1, max_size=5,
    )
    async with _pool.acquire() as con:
        await con.execute(SCHEMA_SQL)


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def _pool_or_raise():
    if _pool is None:
        raise RuntimeError("Pool Postgres nao inicializado")
    return _pool


import os

MAX_CONVERSATIONS_PER_USER = int(os.getenv("MAX_CONVERSATIONS_PER_USER", "5"))


async def _enforce_conversation_cap(conn, user_oid: str) -> int:
    """Mantém as N conversas mais recentes (updated_at) do usuário; deleta o resto.

    messages caem via ON DELETE CASCADE; artifacts sobrevivem via ON DELETE SET NULL
    (rotacionar chat não destrói entregável — ele segue na Biblioteca).
    Usa idx_conv_user_updated (user_oid, updated_at DESC): index scan, custo ~zero.
    """
    result = await conn.execute(
        """DELETE FROM conversations
           WHERE user_oid = $1
             AND id NOT IN (
                 SELECT id FROM conversations
                 WHERE user_oid = $1
                 ORDER BY updated_at DESC
                 LIMIT $2
             )""",
        user_oid, MAX_CONVERSATIONS_PER_USER,
    )
    return int(result.split()[-1]) if result else 0


async def create_conversation(user_oid: str, title: str, model: str) -> dict:
    row = await _pool_or_raise().fetchrow(
        """INSERT INTO conversations (user_oid, title, model)
           VALUES ($1, $2, $3)
           RETURNING id, title, model, created_at, updated_at""",
        user_oid, title, model,
    )
    # rotação: mantém as N mais recentes do usuário (a recém-criada conta)
    await _enforce_conversation_cap(_pool_or_raise(), user_oid)
    return dict(row)


async def get_conversation(conv_id: str, user_oid: str):
    row = await _pool_or_raise().fetchrow(
        """SELECT id, title, model, created_at, updated_at
           FROM conversations WHERE id = $1::uuid AND user_oid = $2""",
        conv_id, user_oid,
    )
    return dict(row) if row else None


async def list_conversations(user_oid: str, limit: int = 100) -> list:
    rows = await _pool_or_raise().fetch(
        """SELECT id, title, model, updated_at
           FROM conversations WHERE user_oid = $1
           ORDER BY updated_at DESC LIMIT $2""",
        user_oid, limit,
    )
    return [dict(r) for r in rows]


async def add_message(conv_id: str, role: str, content: dict):
    pool = _pool_or_raise()
    async with pool.acquire() as con:
        await con.execute(
            """INSERT INTO messages (conversation_id, role, content)
               VALUES ($1::uuid, $2, $3::jsonb)""",
            conv_id, role, json.dumps(content, ensure_ascii=False),
        )
        await con.execute(
            "UPDATE conversations SET updated_at = now() WHERE id = $1::uuid",
            conv_id,
        )


async def get_messages(conv_id: str, user_oid: str, limit=None) -> list:
    pool = _pool_or_raise()
    owner = await pool.fetchval(
        "SELECT 1 FROM conversations WHERE id = $1::uuid AND user_oid = $2",
        conv_id, user_oid,
    )
    if not owner:
        return []
    if limit:
        rows = await pool.fetch(
            """SELECT role, content, created_at FROM messages
               WHERE conversation_id = $1::uuid
               ORDER BY created_at DESC LIMIT $2""",
            conv_id, limit,
        )
        rows = list(reversed(rows))
    else:
        rows = await pool.fetch(
            """SELECT role, content, created_at FROM messages
               WHERE conversation_id = $1::uuid ORDER BY created_at""",
            conv_id,
        )
    # Busca artifacts da conversa e associa por janela temporal a cada msg do assistant
    artifact_rows = await pool.fetch(
        """SELECT id, kind, filename, size_bytes, created_at FROM artifacts
           WHERE conversation_id = $1::uuid ORDER BY created_at""",
        conv_id,
    )
    out = []
    for i, r in enumerate(rows):
        content = r["content"]
        if isinstance(content, str):
            content = json.loads(content)
        msg_artifacts = []
        if r["role"] == "assistant":
            t_start = r["created_at"]
            t_end = rows[i+1]["created_at"] if i+1 < len(rows) else None
            for a in artifact_rows:
                if a["created_at"] >= t_start and (t_end is None or a["created_at"] < t_end):
                    msg_artifacts.append({
                        "id": str(a["id"]),
                        "kind": a["kind"],
                        "filename": a["filename"],
                        "size_bytes": a["size_bytes"],
                    })
        out.append({"role": r["role"], "content": content,
                    "artifacts": msg_artifacts,
                    "created_at": r["created_at"].isoformat()})
    return out


async def build_model_window(conv_id: str, user_oid: str, max_pairs: int = 10) -> list:
    """Janela LEVE (so texto) pro Claude: ultimas N trocas, sem blocos de tool.
    Mantem o contexto conversacional sem reenviar tabelas SQL antigas."""
    msgs = await get_messages(conv_id, user_oid, limit=max_pairs * 2)
    window = []
    for m in msgs:
        c = m["content"]
        text = c.get("text", "") if isinstance(c, dict) else str(c)
        if text:
            window.append({"role": m["role"], "content": text})
    return window

async def delete_conversation(conv_id: str, user_oid: str) -> bool:
    """Apaga a conversa SE pertencer ao user_oid. ON DELETE CASCADE
    do schema cuida das mensagens. Retorna True se algo foi apagado."""
    result = await _pool_or_raise().execute(
        "DELETE FROM conversations WHERE id = $1::uuid AND user_oid = $2",
        conv_id, user_oid,
    )
    # asyncpg retorna 'DELETE N' — N=1 sucesso, N=0 não existia ou não era do user
    return result.endswith(" 1")


# ─── ARTEFATOS ──────────────────────────────────────────────────────────
async def create_artifact(
    user_oid: str,
    kind: str,
    filename: str,
    title: str,
    file_path: str,
    size_bytes: int,
    conversation_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Registra metadado do artefato no Postgres. Arquivo já deve estar em disco."""
    import json
    pool = _pool_or_raise()
    row = await pool.fetchrow(
        """INSERT INTO artifacts
           (user_oid, conversation_id, kind, filename, title, file_path, size_bytes, metadata)
           VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8::jsonb)
           RETURNING id, kind, filename, title, size_bytes, created_at""",
        user_oid, conversation_id, kind, filename, title, file_path, size_bytes,
        json.dumps(metadata or {}, ensure_ascii=False),
    )
    return dict(row)


async def get_artifact(artifact_id: str, user_oid: str) -> dict | None:
    """Busca artefato SE pertence ao user_oid. Retorna inclui file_path."""
    row = await _pool_or_raise().fetchrow(
        """SELECT id, user_oid, kind, filename, title, file_path, size_bytes,
                  metadata, created_at, conversation_id
           FROM artifacts WHERE id = $1::uuid AND user_oid = $2""",
        artifact_id, user_oid,
    )
    return dict(row) if row else None


async def list_artifacts(user_oid: str, kind: str | None = None, limit: int = 50) -> list:
    """Lista artefatos do user. Opcional: filtrar por kind (xlsx/pdf/pptx/chart)."""
    if kind:
        rows = await _pool_or_raise().fetch(
            """SELECT id, kind, filename, title, size_bytes, created_at
               FROM artifacts WHERE user_oid = $1 AND kind = $2
               ORDER BY created_at DESC LIMIT $3""",
            user_oid, kind, limit,
        )
    else:
        rows = await _pool_or_raise().fetch(
            """SELECT id, kind, filename, title, size_bytes, created_at
               FROM artifacts WHERE user_oid = $1
               ORDER BY created_at DESC LIMIT $2""",
            user_oid, limit,
        )
    return [dict(r) for r in rows]


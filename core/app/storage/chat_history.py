"""Persistencia de historico de chat em SQLite local.

Schema simples:
  - chat_history: snapshot do historico por chat_id (cada turn re-salva)
  - chat_resets: marca o /reset pra cortar historico antigo
"""
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "chat_history.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                ts REAL NOT NULL,
                messages_json TEXT NOT NULL
            )
        """)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_resets (
                chat_id INTEGER PRIMARY KEY,
                last_reset_ts REAL NOT NULL
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_ts ON chat_history(chat_id, ts)")
        _conn.commit()
    return _conn


# Campos válidos por tipo de bloco na API Anthropic
_ALLOWED_FIELDS = {
    "text": {"type", "text"},
    "tool_use": {"type", "id", "name", "input"},
    "tool_result": {"type", "tool_use_id", "content", "is_error"},
    "image": {"type", "source"},
    "thinking": {"type", "thinking", "signature"},
}


def _clean_block(block):
    """Converte bloco pydantic em dict e remove campos extras (ex: caller, citations)."""
    if isinstance(block, dict):
        d = dict(block)
    elif hasattr(block, "model_dump"):
        d = block.model_dump(exclude_none=True)
    elif hasattr(block, "__dict__"):
        d = {k: v for k, v in block.__dict__.items() if not k.startswith("_")}
    else:
        return block

    btype = d.get("type")
    allowed = _ALLOWED_FIELDS.get(btype)
    if allowed:
        return {k: v for k, v in d.items() if k in allowed}
    return d


def _serializable(obj):
    return _clean_block(obj)


def load_history(chat_id: int, max_age_hours: int = 24) -> list:
    """Carrega o snapshot mais recente do chat_id, respeitando /reset."""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT last_reset_ts FROM chat_resets WHERE chat_id = ?",
        (chat_id,)
    )
    row = cur.fetchone()
    reset_ts = row[0] if row else 0.0
    min_ts = max(reset_ts, time.time() - max_age_hours * 3600)
    cur = conn.execute(
        "SELECT messages_json FROM chat_history "
        "WHERE chat_id = ? AND ts >= ? ORDER BY ts DESC LIMIT 1",
        (chat_id, min_ts)
    )
    row = cur.fetchone()
    if row:
        try:
            return json.loads(row[0])
        except Exception:
            return []
    return []


def save_history(chat_id: int, messages: list) -> None:
    """Salva snapshot do historico. Mantem so os ultimos 5 snapshots por chat_id."""
    conn = _get_conn()
    safe = []
    for m in messages:
        if isinstance(m, dict):
            content = m.get("content")
            if isinstance(content, list):
                safe_content = []
                for block in content:
                    if isinstance(block, dict):
                        safe_content.append(block)
                    else:
                        safe_content.append(_serializable(block))
                safe.append({"role": m["role"], "content": safe_content})
            else:
                safe.append(m)
        else:
            safe.append(_serializable(m))

    conn.execute(
        "INSERT INTO chat_history (chat_id, ts, messages_json) VALUES (?, ?, ?)",
        (chat_id, time.time(), json.dumps(safe, ensure_ascii=False, default=str))
    )
    conn.execute("""
        DELETE FROM chat_history
        WHERE chat_id = ? AND id NOT IN (
            SELECT id FROM chat_history WHERE chat_id = ? ORDER BY ts DESC LIMIT 5
        )
    """, (chat_id, chat_id))
    conn.commit()


def reset_history(chat_id: int) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO chat_resets (chat_id, last_reset_ts) VALUES (?, ?)",
        (chat_id, time.time())
    )
    conn.commit()

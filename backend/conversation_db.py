import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


DEFAULT_WELCOME_TEXT = (
    "Traductor de Lengua de Señas Colombiana (LSC) Activo: Reconoce las 27 letras del "
    "Abecedario LSC (A–Z + Ñ), +45 señas conversacionales y traduce frases habladas o "
    "escritas mediante el Modelo 3D de Manos."
)


class ConversationDB:
    """Repositorio SQLite para persistir conversaciones y mensajes (CRUD completo)."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(base_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "conversations.db")
        else:
            parent = os.path.dirname(os.path.abspath(db_path))
            if parent:
                os.makedirs(parent, exist_ok=True)

        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    is_auto_title INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    sender TEXT NOT NULL,
                    sender_label TEXT NOT NULL,
                    text TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    sign_ids TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conv_id
                    ON messages(conversation_id, id);
                """
            )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Dict[str, Any]:
        try:
            sign_ids = json.loads(row["sign_ids"] or "[]")
        except Exception:
            sign_ids = []
        return {
            "id": f"msg_{row['id']}",
            "db_id": row["id"],
            "conversation_id": row["conversation_id"],
            "sender": row["sender"],
            "sender_label": row["sender_label"],
            "text": row["text"],
            "timestamp": row["timestamp"],
            "sign_ids": sign_ids,
            "created_at": row["created_at"],
        }

    def ensure_default_conversation(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM conversations ORDER BY updated_at DESC, id DESC LIMIT 1"
            ).fetchone()
            if row:
                return int(row["id"])
        created = self.create_conversation(title="Conversación #1", is_auto_title=True)
        return int(created["id"])

    def list_conversations(self) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.id,
                    c.title,
                    c.is_auto_title,
                    c.created_at,
                    c.updated_at,
                    (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id AND m.sender != 'SYSTEM') AS message_count,
                    (SELECT m.text FROM messages m WHERE m.conversation_id = c.id AND m.sender != 'SYSTEM' ORDER BY m.id DESC LIMIT 1) AS preview
                FROM conversations c
                ORDER BY c.updated_at DESC, c.id DESC
                """
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "is_auto_title": bool(r["is_auto_title"]),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "message_count": r["message_count"] or 0,
                    "preview": r["preview"] or "Sin mensajes todavía",
                }
                for r in rows
            ]

    def get_conversation(self, conv_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, title, is_auto_title, created_at, updated_at FROM conversations WHERE id = ?",
                (conv_id,),
            ).fetchone()
            if not row:
                return None
            msg_rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                (conv_id,),
            ).fetchall()
            return {
                "id": row["id"],
                "title": row["title"],
                "is_auto_title": bool(row["is_auto_title"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "messages": [self._row_to_message(m) for m in msg_rows],
            }

    def get_messages(self, conv_id: int) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                (conv_id,),
            ).fetchall()
            return [self._row_to_message(r) for r in rows]

    def create_conversation(
        self, title: Optional[str] = None, is_auto_title: Optional[bool] = None
    ) -> Dict[str, Any]:
        now_iso = self._now_iso()
        now_hm = datetime.now().strftime("%H:%M:%S")
        clean_title = (title or "").strip()

        with self._lock, self._connect() as conn:
            if not clean_title:
                count_row = conn.execute("SELECT COUNT(*) AS cnt FROM conversations").fetchone()
                next_num = (count_row["cnt"] if count_row else 0) + 1
                clean_title = f"Conversación #{next_num}"
                auto_flag = 1 if is_auto_title is None else int(bool(is_auto_title))
            else:
                auto_flag = int(bool(is_auto_title)) if is_auto_title is not None else 0

            cur = conn.execute(
                "INSERT INTO conversations (title, is_auto_title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (clean_title, auto_flag, now_iso, now_iso),
            )
            conv_id = int(cur.lastrowid)

            conn.execute(
                """
                INSERT INTO messages (conversation_id, sender, sender_label, text, timestamp, sign_ids, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (conv_id, "SYSTEM", "SignBridge v4.0 LSC", DEFAULT_WELCOME_TEXT, now_hm, "[]", now_iso),
            )

        return self.get_conversation(conv_id)  # type: ignore[return-value]

    def rename_conversation(self, conv_id: int, title: str) -> Optional[Dict[str, Any]]:
        clean_title = title.strip()
        if not clean_title:
            return None
        now_iso = self._now_iso()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE conversations SET title = ?, is_auto_title = 0, updated_at = ? WHERE id = ?",
                (clean_title, now_iso, conv_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get_conversation(conv_id)

    def delete_conversation(self, conv_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            return cur.rowcount > 0

    def clear_conversation_messages(self, conv_id: int) -> bool:
        now_iso = self._now_iso()
        now_hm = datetime.now().strftime("%H:%M:%S")
        with self._lock, self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conv_id,)).fetchone()
            if not exists:
                return False
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            conn.execute(
                """
                INSERT INTO messages (conversation_id, sender, sender_label, text, timestamp, sign_ids, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (conv_id, "SYSTEM", "SignBridge v4.0 LSC", DEFAULT_WELCOME_TEXT, now_hm, "[]", now_iso),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now_iso, conv_id))
            return True

    def add_message(
        self,
        conv_id: int,
        sender: str,
        sender_label: str,
        text: str,
        timestamp: Optional[str] = None,
        sign_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        clean_text = text.strip()
        if not clean_text:
            return None

        now_iso = self._now_iso()
        ts = timestamp or datetime.now().strftime("%H:%M:%S")
        signs_json = json.dumps(sign_ids or [], ensure_ascii=False)

        with self._lock, self._connect() as conn:
            conv = conn.execute(
                "SELECT id, is_auto_title FROM conversations WHERE id = ?",
                (conv_id,),
            ).fetchone()
            if not conv:
                return None

            cur = conn.execute(
                """
                INSERT INTO messages (conversation_id, sender, sender_label, text, timestamp, sign_ids, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (conv_id, sender, sender_label, clean_text, ts, signs_json, now_iso),
            )
            msg_id = int(cur.lastrowid)

            # Si el título era automático, usar el primer mensaje real como título resumido
            if conv["is_auto_title"] and sender in ("DEAF", "HEARING"):
                auto_title = clean_text[:42] + ("..." if len(clean_text) > 42 else "")
                conn.execute(
                    "UPDATE conversations SET title = ?, is_auto_title = 0, updated_at = ? WHERE id = ?",
                    (auto_title, now_iso, conv_id),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now_iso, conv_id),
                )

            row = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
            return self._row_to_message(row)

    def update_message(self, msg_id: int, text: str) -> Optional[Dict[str, Any]]:
        clean_text = text.strip()
        if not clean_text:
            return None
        now_iso = self._now_iso()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT conversation_id FROM messages WHERE id = ?", (msg_id,)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE messages SET text = ? WHERE id = ?", (clean_text, msg_id))
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now_iso, row["conversation_id"]),
            )
            updated = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
            return self._row_to_message(updated)

    def delete_message(self, msg_id: int) -> Optional[int]:
        now_iso = self._now_iso()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT conversation_id FROM messages WHERE id = ?", (msg_id,)).fetchone()
            if not row:
                return None
            conv_id = int(row["conversation_id"])
            conn.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now_iso, conv_id))
            return conv_id

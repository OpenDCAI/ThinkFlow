from __future__ import annotations

import json
import hashlib
import re
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from workflow_engine.utils import get_project_root


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", value.strip()).strip("-")
    return normalized[:80] or uuid.uuid4().hex[:12]


def _row(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    return dict(row) if row is not None else None


class ResearchRepository:
    """Local single-user storage for the Codex research workspace."""

    GLOBAL_SPACE_ID = "space_global_research_assistant"

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or (get_project_root() / "outputs" / "research_person")
        self.db_path = self.root / "research.sqlite3"
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._recover_interrupted_conversations()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _init_db(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS spaces (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            codex_thread_id TEXT,
            active_paper_id TEXT,
            scope TEXT NOT NULL DEFAULT 'space',
            status TEXT NOT NULL DEFAULT 'idle',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_conversations_space ON conversations(space_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            turn_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            event_type TEXT NOT NULL DEFAULT 'message',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
        CREATE TABLE IF NOT EXISTS conversation_resources (
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            position INTEGER NOT NULL DEFAULT 0,
            attached_at TEXT NOT NULL,
            PRIMARY KEY(conversation_id, paper_id)
        );
        CREATE INDEX IF NOT EXISTS idx_conversation_resources_paper
            ON conversation_resources(paper_id, conversation_id);
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            resource_type TEXT NOT NULL DEFAULT 'paper',
            title TEXT NOT NULL,
            original_name TEXT,
            stored_path TEXT,
            source_url TEXT,
            availability TEXT NOT NULL DEFAULT 'local_pdf',
            status TEXT NOT NULL DEFAULT 'ready',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_papers_space ON papers(space_id, updated_at DESC);
        -- A resource is stored once globally.  Spaces own only this relation,
        -- while papers.space_id remains as a backwards-compatible primary
        -- space hint for existing callers and databases.
        CREATE TABLE IF NOT EXISTS space_resources (
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            resource_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            position INTEGER NOT NULL DEFAULT 0,
            attached_at TEXT NOT NULL,
            PRIMARY KEY(space_id, resource_id)
        );
        CREATE INDEX IF NOT EXISTS idx_space_resources_resource
            ON space_resources(resource_id, space_id);
        CREATE INDEX IF NOT EXISTS idx_space_resources_space
            ON space_resources(space_id, position, attached_at);
        CREATE TABLE IF NOT EXISTS paper_notes (
            paper_id TEXT PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
            short_summary TEXT NOT NULL DEFAULT '',
            qa_summary TEXT NOT NULL DEFAULT '',
            open_questions TEXT NOT NULL DEFAULT '',
            key_takeaways TEXT NOT NULL DEFAULT '',
            personal_notes TEXT NOT NULL DEFAULT '',
            source_message_ids_json TEXT NOT NULL DEFAULT '[]',
            generated_at TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS wiki_pages (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags_json TEXT NOT NULL DEFAULT '[]',
            source_conversation_id TEXT,
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(space_id, slug)
        );
        CREATE INDEX IF NOT EXISTS idx_wiki_space ON wiki_pages(space_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS wiki_revisions (
            id TEXT PRIMARY KEY,
            page_id TEXT NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
            revision INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ideas (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            problem TEXT NOT NULL DEFAULT '',
            hypothesis TEXT NOT NULL DEFAULT '',
            method TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '',
            risks TEXT NOT NULL DEFAULT '',
            next_steps TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            tags_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ideas_space ON ideas(space_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            conversation_id TEXT,
            kind TEXT NOT NULL,
            provider TEXT NOT NULL,
            status TEXT NOT NULL,
            progress REAL NOT NULL DEFAULT 0,
            input_json TEXT NOT NULL DEFAULT '{}',
            output_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_space ON jobs(space_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            conversation_id TEXT,
            action TEXT NOT NULL,
            idempotency_key TEXT,
            request_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(action, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS pending_actions (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            tool_name TEXT NOT NULL,
            summary TEXT NOT NULL,
            arguments_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            confirmed_at TEXT,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pending_actions_conversation
            ON pending_actions(conversation_id, created_at DESC);
        """
        with self._lock, self._connect() as connection:
            connection.executescript(schema)

    def _recover_interrupted_conversations(self) -> None:
        """A running turn cannot survive the owning backend process."""
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE conversations SET status = 'idle', updated_at = ? WHERE status = 'running'",
                (_now(),),
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
            }
            if "active_paper_id" not in columns:
                connection.execute("ALTER TABLE conversations ADD COLUMN active_paper_id TEXT")
            if "scope" not in columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN scope TEXT NOT NULL DEFAULT 'space'"
                )
            space_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(spaces)").fetchall()
            }
            if "scope" not in space_columns:
                connection.execute(
                    "ALTER TABLE spaces ADD COLUMN scope TEXT NOT NULL DEFAULT 'user'"
                )
            paper_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(papers)").fetchall()
            }
            if "resource_type" not in paper_columns:
                connection.execute(
                    "ALTER TABLE papers ADD COLUMN resource_type TEXT NOT NULL DEFAULT 'paper'"
                )
            connection.execute(
                """INSERT OR IGNORE INTO conversation_resources
                   (conversation_id, paper_id, position, attached_at)
                   SELECT conversations.id, conversations.active_paper_id, 0,
                          conversations.updated_at
                   FROM conversations JOIN papers ON papers.id = conversations.active_paper_id
                   WHERE conversations.active_paper_id IS NOT NULL"""
            )
            # Databases created before global resources used papers.space_id as
            # the only association.  Seed the new relation exactly once.
            connection.execute(
                """INSERT OR IGNORE INTO space_resources
                   (space_id, resource_id, position, attached_at)
                   SELECT space_id, id, 0, created_at FROM papers"""
            )
            connection.execute(
                """UPDATE pending_actions SET status = 'pending', updated_at = ?
                   WHERE status = 'executing'""",
                (_now(),),
            )
        self.ensure_global_space()

    def space_dir(self, space_id: str) -> Path:
        path = self.root / "spaces" / space_id
        for child in ("papers", "wiki", "ideas", "threads", "artifacts", "skills"):
            (path / child).mkdir(parents=True, exist_ok=True)
        return path

    def thread_dir(self, space_id: str, conversation_id: str) -> Path:
        path = self.space_dir(space_id) / "threads" / conversation_id
        path.mkdir(parents=True, exist_ok=True)
        readme = path / "README.md"
        if not readme.exists():
            readme.write_text(
                "# Research conversation workspace\n\n"
                "Shared papers are in `../../papers`, Wiki pages in `../../wiki`, "
                "Ideas in `../../ideas`, and generated artifacts in `../../artifacts`.\n",
                encoding="utf-8",
            )
        return path

    def _fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            return [dict(item) for item in connection.execute(sql, tuple(params)).fetchall()]

    def _fetchone(self, sql: str, params: Iterable[Any] = ()) -> Optional[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            return _row(connection.execute(sql, tuple(params)).fetchone())

    def list_spaces(self) -> list[dict[str, Any]]:
        return self._fetchall(
            """SELECT spaces.*,
                      (SELECT COUNT(*) FROM space_resources
                       WHERE space_resources.space_id = spaces.id) AS resource_count,
                      (SELECT COUNT(*) FROM conversations
                       WHERE conversations.space_id = spaces.id
                         AND conversations.scope != 'system') AS conversation_count
               FROM spaces WHERE spaces.scope != 'system' ORDER BY spaces.updated_at DESC"""
        )

    def get_space(self, space_id: str) -> Optional[dict[str, Any]]:
        return self._fetchone("SELECT * FROM spaces WHERE id = ?", (space_id,))

    def create_space(
        self, title: str, description: str = "", *, scope: str = "user"
    ) -> dict[str, Any]:
        space_id, now = _id("space"), _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO spaces(id, title, description, scope, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (space_id, title.strip(), description.strip(), scope, now, now),
            )
        self.space_dir(space_id)
        return self.get_space(space_id) or {}

    def ensure_global_space(self) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO spaces
                   (id, title, description, scope, created_at, updated_at)
                   VALUES (?, ?, ?, 'system', ?, ?)""",
                (
                    self.GLOBAL_SPACE_ID,
                    "全局研究助理",
                    "不绑定单个研究空间的研究资料编排入口",
                    now,
                    now,
                ),
            )
        self.space_dir(self.GLOBAL_SPACE_ID)
        return self.get_space(self.GLOBAL_SPACE_ID) or {}

    def delete_space(self, space_id: str) -> bool:
        with self._lock, self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM spaces WHERE id = ?", (space_id,)).fetchone()
            if not exists:
                return False
            # A resource may be linked to more than one space.  Move the
            # legacy primary-space hint before deleting this space so the
            # global resource and its other links survive.
            owned = connection.execute(
                "SELECT id FROM papers WHERE space_id = ?", (space_id,)
            ).fetchall()
            for row in owned:
                replacement = connection.execute(
                    """SELECT space_id FROM space_resources
                       WHERE resource_id = ? AND space_id != ?
                       ORDER BY position, attached_at LIMIT 1""",
                    (row["id"], space_id),
                ).fetchone()
                if replacement:
                    connection.execute(
                        "UPDATE papers SET space_id = ? WHERE id = ?",
                        (replacement["space_id"], row["id"]),
                    )
            deleted = connection.execute("DELETE FROM spaces WHERE id = ?", (space_id,)).rowcount > 0
        if deleted:
            shutil.rmtree(self.root / "spaces" / space_id, ignore_errors=True)
        return deleted

    def list_conversations(
        self,
        space_id: str,
        resource_id: Optional[str] = None,
        *,
        scopes: Optional[Iterable[str]] = None,
    ) -> list[dict[str, Any]]:
        scope_values = list(scopes or ("space", "paper", "idea", "global"))
        scope_marks = ",".join("?" for _ in scope_values)
        if resource_id:
            rows = self._fetchall(
                f"""SELECT DISTINCT conversations.* FROM conversations
                    JOIN conversation_resources
                      ON conversation_resources.conversation_id = conversations.id
                    WHERE conversations.space_id = ?
                      AND conversation_resources.paper_id = ?
                      AND conversations.scope IN ({scope_marks})
                    ORDER BY conversations.updated_at DESC""",
                (space_id, resource_id, *scope_values),
            )
        else:
            rows = self._fetchall(
                f"""SELECT * FROM conversations WHERE space_id = ?
                    AND scope IN ({scope_marks}) ORDER BY updated_at DESC""",
                (space_id, *scope_values),
            )
        return [self._decorate_conversation(row) for row in rows]

    def list_global_conversations(self) -> list[dict[str, Any]]:
        self.ensure_global_space()
        return self.list_conversations(self.GLOBAL_SPACE_ID, scopes=("global",))

    def _decorate_conversation(self, conversation: dict[str, Any]) -> dict[str, Any]:
        resource_rows = self._fetchall(
            """SELECT paper_id FROM conversation_resources WHERE conversation_id = ?
               ORDER BY position, attached_at""",
            (conversation["id"],),
        )
        conversation["paper_ids"] = [row["paper_id"] for row in resource_rows]
        conversation["resource_count"] = len(resource_rows)
        if not conversation.get("active_paper_id") and resource_rows:
            conversation["active_paper_id"] = resource_rows[0]["paper_id"]
        return conversation

    def get_conversation(self, conversation_id: str) -> Optional[dict[str, Any]]:
        conversation = self._fetchone("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        return self._decorate_conversation(conversation) if conversation else None

    def create_conversation(
        self,
        space_id: str,
        title: str = "新对话",
        *,
        scope: str = "space",
        paper_ids: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        conversation_id, now = _id("chat"), _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO conversations(id, space_id, title, scope, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (conversation_id, space_id, title.strip() or "新对话", scope, now, now),
            )
            connection.execute("UPDATE spaces SET updated_at = ? WHERE id = ?", (now, space_id))
        self.thread_dir(space_id, conversation_id)
        if paper_ids:
            self.set_conversation_resources(conversation_id, paper_ids)
        return self.get_conversation(conversation_id) or {}

    def create_global_conversation(self, title: str = "全局研究对话") -> dict[str, Any]:
        self.ensure_global_space()
        return self.create_conversation(self.GLOBAL_SPACE_ID, title, scope="global")

    def delete_conversation(self, conversation_id: str) -> bool:
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return False
        with self._lock, self._connect() as connection:
            deleted = connection.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            ).rowcount > 0
        if deleted:
            shutil.rmtree(
                self.root / "spaces" / conversation["space_id"] / "threads" / conversation_id,
                ignore_errors=True,
            )
        return deleted

    def set_conversation_runtime(
        self,
        conversation_id: str,
        *,
        codex_thread_id: Optional[str] = None,
        status: Optional[str] = None,
        title: Optional[str] = None,
    ) -> None:
        updates: list[str] = ["updated_at = ?"]
        values: list[Any] = [_now()]
        for field, value in (
            ("codex_thread_id", codex_thread_id),
            ("status", status),
            ("title", title),
        ):
            if value is not None:
                updates.append(f"{field} = ?")
                values.append(value)
        values.append(conversation_id)
        with self._lock, self._connect() as connection:
            connection.execute(f"UPDATE conversations SET {', '.join(updates)} WHERE id = ?", values)

    def bind_conversation_paper(
        self, conversation_id: str, paper_id: Optional[str]
    ) -> Optional[dict[str, Any]]:
        return self.set_conversation_resources(
            conversation_id, [paper_id] if paper_id else []
        )

    def list_conversation_resources(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """SELECT papers.* FROM papers JOIN conversation_resources
                 ON conversation_resources.paper_id = papers.id
               WHERE conversation_resources.conversation_id = ?
               ORDER BY conversation_resources.position, conversation_resources.attached_at""",
            (conversation_id,),
        )
        for item in rows:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return rows

    def set_conversation_resources(
        self, conversation_id: str, paper_ids: list[str]
    ) -> Optional[dict[str, Any]]:
        unique_ids = list(dict.fromkeys(paper_id for paper_id in paper_ids if paper_id))
        now = _now()
        with self._lock, self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if not exists:
                return None
            connection.execute(
                "DELETE FROM conversation_resources WHERE conversation_id = ?",
                (conversation_id,),
            )
            for position, paper_id in enumerate(unique_ids):
                connection.execute(
                    """INSERT INTO conversation_resources
                       (conversation_id, paper_id, position, attached_at)
                       VALUES (?, ?, ?, ?)""",
                    (conversation_id, paper_id, position, now),
                )
            connection.execute(
                "UPDATE conversations SET active_paper_id = ?, updated_at = ? WHERE id = ?",
                (unique_ids[0] if unique_ids else None, now, conversation_id),
            )
        return self.get_conversation(conversation_id)

    def attach_conversation_resources(
        self, conversation_id: str, paper_ids: list[str]
    ) -> Optional[dict[str, Any]]:
        current = [paper["id"] for paper in self.list_conversation_resources(conversation_id)]
        return self.set_conversation_resources(conversation_id, [*current, *paper_ids])

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid",
            (conversation_id,),
        )
        for item in rows:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return rows

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        turn_id: Optional[str] = None,
        event_type: str = "message",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        message_id, now = _id("msg"), _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO messages
                   (id, conversation_id, turn_id, role, content, event_type, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (message_id, conversation_id, turn_id, role, content, event_type,
                 json.dumps(metadata or {}, ensure_ascii=False), now),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
            )
        return self._fetchone("SELECT * FROM messages WHERE id = ?", (message_id,)) or {}

    def prepare_message_regeneration(
        self, conversation_id: str, message_id: str
    ) -> dict[str, Any]:
        """Remove one user/answer branch while retaining enough state to restore it."""
        with self._lock, self._connect() as connection:
            conversation = connection.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if not conversation:
                raise LookupError("Conversation not found")
            if conversation["status"] == "running":
                raise RuntimeError("Conversation has an active Codex turn")
            target = connection.execute(
                """SELECT rowid AS message_rowid, * FROM messages
                   WHERE id = ? AND conversation_id = ?""",
                (message_id, conversation_id),
            ).fetchone()
            if not target:
                raise LookupError("Message not found")
            if target["role"] != "assistant" and target["event_type"] != "error":
                raise ValueError("Only a Codex answer or failed turn can be replayed")
            user = connection.execute(
                """SELECT rowid AS message_rowid, * FROM messages
                   WHERE conversation_id = ? AND role = 'user' AND rowid < ?
                   ORDER BY rowid DESC LIMIT 1""",
                (conversation_id, target["message_rowid"]),
            ).fetchone()
            if not user:
                raise ValueError("The selected answer has no preceding user question")
            history_rows = connection.execute(
                """SELECT rowid AS message_rowid, * FROM messages
                   WHERE conversation_id = ? AND rowid < ? ORDER BY rowid""",
                (conversation_id, user["message_rowid"]),
            ).fetchall()
            removed_rows = connection.execute(
                """SELECT rowid AS message_rowid, * FROM messages
                   WHERE conversation_id = ? AND rowid >= ? ORDER BY rowid""",
                (conversation_id, user["message_rowid"]),
            ).fetchall()
            connection.execute(
                "DELETE FROM messages WHERE conversation_id = ? AND rowid >= ?",
                (conversation_id, user["message_rowid"]),
            )
            now = _now()
            connection.execute(
                """UPDATE conversations
                   SET codex_thread_id = NULL, status = 'idle', updated_at = ?
                   WHERE id = ?""",
                (now, conversation_id),
            )

        def decode(row: sqlite3.Row) -> dict[str, Any]:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            return item

        return {
            "conversation_id": conversation_id,
            "prompt": user["content"],
            "history": [decode(row) for row in history_rows],
            "removed": [dict(row) for row in removed_rows],
            "anchor_rowid": int(user["message_rowid"]) - 1,
            "original_thread_id": conversation["codex_thread_id"],
            "original_status": conversation["status"],
            "original_updated_at": conversation["updated_at"],
        }

    def restore_message_regeneration(self, snapshot: dict[str, Any]) -> None:
        """Restore a branch when a replacement Codex turn did not complete."""
        conversation_id = str(snapshot["conversation_id"])
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM messages WHERE conversation_id = ? AND rowid > ?",
                (conversation_id, int(snapshot["anchor_rowid"])),
            )
            for row in snapshot["removed"]:
                connection.execute(
                    """INSERT INTO messages
                       (id, conversation_id, turn_id, role, content, event_type,
                        metadata_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["id"], row["conversation_id"], row["turn_id"], row["role"],
                        row["content"], row["event_type"], row["metadata_json"],
                        row["created_at"],
                    ),
                )
            connection.execute(
                """UPDATE conversations
                   SET codex_thread_id = ?, status = ?, updated_at = ? WHERE id = ?""",
                (
                    snapshot["original_thread_id"], snapshot["original_status"],
                    snapshot["original_updated_at"], conversation_id,
                ),
            )

    @staticmethod
    def _decorate_action(action: dict[str, Any]) -> dict[str, Any]:
        action["arguments"] = json.loads(action.pop("arguments_json") or "{}")
        action["result"] = json.loads(action.pop("result_json") or "{}")
        return action

    def create_pending_action(
        self,
        conversation_id: str,
        tool_name: str,
        summary: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        action_id, now = _id("action"), _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO pending_actions
                   (id, conversation_id, tool_name, summary, arguments_json,
                    status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    action_id,
                    conversation_id,
                    tool_name,
                    summary,
                    json.dumps(arguments, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_pending_action(action_id) or {}

    def get_pending_action(self, action_id: str) -> Optional[dict[str, Any]]:
        action = self._fetchone("SELECT * FROM pending_actions WHERE id = ?", (action_id,))
        return self._decorate_action(action) if action else None

    def list_pending_actions(
        self,
        conversation_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        if status:
            rows = self._fetchall(
                """SELECT * FROM pending_actions
                   WHERE conversation_id = ? AND status = ?
                   ORDER BY created_at DESC, rowid DESC LIMIT ?""",
                (conversation_id, status, safe_limit),
            )
        else:
            rows = self._fetchall(
                """SELECT * FROM pending_actions WHERE conversation_id = ?
                   ORDER BY created_at DESC, rowid DESC LIMIT ?""",
                (conversation_id, safe_limit),
            )
        return [self._decorate_action(row) for row in rows]

    def claim_pending_action(self, action_id: str) -> Optional[dict[str, Any]]:
        now = _now()
        with self._lock, self._connect() as connection:
            changed = connection.execute(
                """UPDATE pending_actions
                   SET status = 'executing', confirmed_at = ?, updated_at = ?, error = NULL
                   WHERE id = ? AND status = 'pending'""",
                (now, now, action_id),
            ).rowcount
        return self.get_pending_action(action_id) if changed else None

    def finish_pending_action(
        self,
        action_id: str,
        *,
        status: str,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError(f"Unsupported action status: {status}")
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE pending_actions
                   SET status = ?, result_json = ?, error = ?, updated_at = ?, completed_at = ?
                   WHERE id = ?""",
                (
                    status,
                    json.dumps(result or {}, ensure_ascii=False),
                    error,
                    now,
                    now,
                    action_id,
                ),
            )
        return self.get_pending_action(action_id)

    def cancel_pending_action(self, action_id: str) -> Optional[dict[str, Any]]:
        now = _now()
        with self._lock, self._connect() as connection:
            changed = connection.execute(
                """UPDATE pending_actions
                   SET status = 'cancelled', updated_at = ?, completed_at = ?
                   WHERE id = ? AND status = 'pending'""",
                (now, now, action_id),
            ).rowcount
        return self.get_pending_action(action_id) if changed else None

    def record_audit(
        self,
        *,
        conversation_id: Optional[str],
        action: str,
        request: dict[str, Any],
        result: dict[str, Any],
        status: str,
        space_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        audit_id, now = _id("audit"), _now()
        target_space_id = space_id or self.GLOBAL_SPACE_ID
        self.ensure_global_space()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO audit_log
                   (id, space_id, conversation_id, action, idempotency_key,
                    request_json, result_json, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    audit_id,
                    target_space_id,
                    conversation_id,
                    action,
                    idempotency_key,
                    json.dumps(request, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    status,
                    now,
                ),
            )
        row = self._fetchone("SELECT * FROM audit_log WHERE id = ?", (audit_id,)) or {}
        if row:
            row["request"] = json.loads(row.pop("request_json") or "{}")
            row["result"] = json.loads(row.pop("result_json") or "{}")
        return row

    @staticmethod
    def _resource_metadata(item: dict[str, Any]) -> dict[str, Any]:
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return item

    def _decorate_resource(self, item: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not item:
            return None
        self._resource_metadata(item)
        space_rows = self._fetchall(
            """SELECT space_id FROM space_resources
               WHERE resource_id = ? ORDER BY position, attached_at""",
            (item["id"],),
        )
        # Old rows can be read safely even if a process has not run the
        # migration yet.  _init_db/_recover normally guarantee this relation.
        item["space_ids"] = [row["space_id"] for row in space_rows]
        if not item["space_ids"] and item.get("space_id"):
            item["space_ids"] = [item["space_id"]]
        item["resource_id"] = item["id"]
        return item

    def list_resources(self, *, resource_type: Optional[str] = None) -> list[dict[str, Any]]:
        if resource_type:
            rows = self._fetchall(
                "SELECT * FROM papers WHERE resource_type = ? ORDER BY updated_at DESC",
                (resource_type,),
            )
        else:
            rows = self._fetchall("SELECT * FROM papers ORDER BY updated_at DESC")
        return [self._decorate_resource(row) for row in rows if row]

    def list_resource_spaces(self, resource_id: str) -> list[dict[str, Any]]:
        return self._fetchall(
            """SELECT spaces.* FROM spaces
               JOIN space_resources ON space_resources.space_id = spaces.id
               WHERE space_resources.resource_id = ?
               ORDER BY space_resources.position, space_resources.attached_at""",
            (resource_id,),
        )

    def resource_in_space(self, resource_id: str, space_id: str) -> bool:
        row = self._fetchone(
            "SELECT 1 AS present FROM space_resources WHERE resource_id = ? AND space_id = ?",
            (resource_id, space_id),
        )
        if row:
            return True
        # Compatibility for a legacy row encountered before migration.
        return bool(
            self._fetchone(
                "SELECT 1 AS present FROM papers WHERE id = ? AND space_id = ?",
                (resource_id, space_id),
            )
        )

    def link_resource_to_space(
        self, resource_id: str, space_id: str, *, position: Optional[int] = None
    ) -> Optional[dict[str, Any]]:
        if not self._fetchone("SELECT 1 AS present FROM papers WHERE id = ?", (resource_id,)):
            return None
        if not self._fetchone("SELECT 1 AS present FROM spaces WHERE id = ?", (space_id,)):
            return None
        now = _now()
        with self._lock, self._connect() as connection:
            if position is None:
                max_position = connection.execute(
                    "SELECT COALESCE(MAX(position), -1) FROM space_resources WHERE space_id = ?",
                    (space_id,),
                ).fetchone()[0]
                position = int(max_position) + 1
            connection.execute(
                """INSERT OR IGNORE INTO space_resources
                   (space_id, resource_id, position, attached_at)
                   VALUES (?, ?, ?, ?)""",
                (space_id, resource_id, position, now),
            )
            connection.execute("UPDATE spaces SET updated_at = ? WHERE id = ?", (now, space_id))
        return self.get_paper(resource_id)

    def unlink_resource_from_space(self, resource_id: str, space_id: str) -> bool:
        with self._lock, self._connect() as connection:
            deleted = connection.execute(
                "DELETE FROM space_resources WHERE resource_id = ? AND space_id = ?",
                (resource_id, space_id),
            ).rowcount > 0
            if deleted:
                # Keep the compatibility space_id pointing at a remaining
                # link whenever the primary space was removed.
                paper = connection.execute(
                    "SELECT space_id FROM papers WHERE id = ?", (resource_id,)
                ).fetchone()
                if paper and paper["space_id"] == space_id:
                    replacement = connection.execute(
                        """SELECT space_id FROM space_resources
                           WHERE resource_id = ? ORDER BY position, attached_at LIMIT 1""",
                        (resource_id,),
                    ).fetchone()
                    if replacement:
                        connection.execute(
                            "UPDATE papers SET space_id = ? WHERE id = ?",
                            (replacement["space_id"], resource_id),
                        )
        return deleted

    def list_papers(self, space_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """SELECT papers.* FROM papers
               JOIN space_resources ON space_resources.resource_id = papers.id
               WHERE space_resources.space_id = ?
               ORDER BY papers.updated_at DESC, space_resources.position""",
            (space_id,),
        )
        # If this is a pre-migration database, include the legacy owner row.
        if not rows:
            rows = self._fetchall(
                "SELECT * FROM papers WHERE space_id = ? ORDER BY updated_at DESC", (space_id,)
            )
        return [self._decorate_resource(row) for row in rows if row]

    def get_paper(self, paper_id: str) -> Optional[dict[str, Any]]:
        paper = self._fetchone("SELECT * FROM papers WHERE id = ?", (paper_id,))
        return self._decorate_resource(paper)

    def update_paper_metadata(
        self,
        paper_id: str,
        metadata: dict[str, Any],
        *,
        status: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        now = _now()
        with self._lock, self._connect() as connection:
            if status is None:
                connection.execute(
                    "UPDATE papers SET metadata_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(metadata, ensure_ascii=False), now, paper_id),
                )
            else:
                connection.execute(
                    "UPDATE papers SET metadata_json = ?, status = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(metadata, ensure_ascii=False), status, now, paper_id),
                )
        return self.get_paper(paper_id)

    def add_paper(
        self,
        space_id: str,
        *,
        title: str,
        original_name: Optional[str] = None,
        stored_path: Optional[str] = None,
        source_url: Optional[str] = None,
        resource_type: str = "paper",
        availability: str = "local_pdf",
        status: str = "ready",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        normalized_metadata = dict(metadata or {})
        if stored_path and "content_sha256" not in normalized_metadata:
            try:
                digest = hashlib.sha256()
                with Path(stored_path).open("rb") as resource_file:
                    for chunk in iter(lambda: resource_file.read(1024 * 1024), b""):
                        digest.update(chunk)
                normalized_metadata["content_sha256"] = digest.hexdigest()
            except (OSError, ValueError):
                # Metadata-only and transient paths should not prevent import.
                pass
        # Prefer stable identifiers over title matching.  Title-only imports
        # intentionally remain separate because preprints and similarly named
        # papers are common in a research library.
        identifiers: list[tuple[str, str]] = []
        for key in ("arxiv_id", "arxiv", "doi", "canonical_url", "content_sha256"):
            value = normalized_metadata.get(key)
            if value:
                identifiers.append((key, str(value).strip().lower()))
        if source_url:
            identifiers.append(("source_url", source_url.strip().rstrip("/").lower()))
        existing_id: Optional[str] = None
        if identifiers:
            with self._lock, self._connect() as connection:
                rows = connection.execute("SELECT id, source_url, metadata_json FROM papers").fetchall()
            for row in rows:
                existing_metadata = json.loads(row["metadata_json"] or "{}")
                existing_values = {
                    key: str(existing_metadata.get(key)).strip().lower()
                    for key, _ in identifiers
                    if existing_metadata.get(key)
                }
                if row["source_url"]:
                    existing_values["source_url"] = row["source_url"].strip().rstrip("/").lower()
                if any(existing_values.get(key) == value for key, value in identifiers):
                    existing_id = row["id"]
                    break
        if existing_id:
            current = self.get_paper(existing_id) or {}
            merged_metadata = dict(current.get("metadata") or {})
            merged_metadata.update({key: value for key, value in normalized_metadata.items() if value not in (None, "")})
            # Do not overwrite an existing local file with a metadata-only
            # import.  Conversely, a later PDF import can fill a missing path.
            updates: list[str] = ["metadata_json = ?", "updated_at = ?"]
            values: list[Any] = [json.dumps(merged_metadata, ensure_ascii=False), _now()]
            if stored_path and not current.get("stored_path"):
                updates.append("stored_path = ?")
                values.append(stored_path)
            if original_name and not current.get("original_name"):
                updates.append("original_name = ?")
                values.append(original_name)
            if source_url and not current.get("source_url"):
                updates.append("source_url = ?")
                values.append(source_url)
            values.append(existing_id)
            with self._lock, self._connect() as connection:
                connection.execute(f"UPDATE papers SET {', '.join(updates)} WHERE id = ?", values)
            self.link_resource_to_space(existing_id, space_id)
            return self.get_paper(existing_id) or current

        paper_id, now = _id("paper"), _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO papers
                   (id, space_id, resource_type, title, original_name, stored_path, source_url, availability,
                    status, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (paper_id, space_id, resource_type, title, original_name, stored_path, source_url, availability,
                 status, json.dumps(normalized_metadata, ensure_ascii=False), now, now),
            )
            connection.execute(
                """INSERT OR IGNORE INTO space_resources
                   (space_id, resource_id, position, attached_at)
                   VALUES (?, ?, 0, ?)""",
                (space_id, paper_id, now),
            )
        return self.get_paper(paper_id) or {}

    def get_paper_note(self, paper_id: str) -> Optional[dict[str, Any]]:
        note = self._fetchone("SELECT * FROM paper_notes WHERE paper_id = ?", (paper_id,))
        if note:
            note["source_message_ids"] = json.loads(
                note.pop("source_message_ids_json") or "[]"
            )
        return note

    def save_paper_note(
        self,
        paper_id: str,
        *,
        short_summary: str,
        qa_summary: str = "",
        open_questions: str = "",
        key_takeaways: str = "",
        personal_notes: str = "",
        source_message_ids: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        now = _now()
        existing = self.get_paper_note(paper_id)
        revision = int(existing.get("revision", 0)) + 1 if existing else 1
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO paper_notes
                   (paper_id, short_summary, qa_summary, open_questions, key_takeaways,
                    personal_notes, source_message_ids_json, generated_at, revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(paper_id) DO UPDATE SET
                     short_summary=excluded.short_summary,
                     qa_summary=excluded.qa_summary,
                     open_questions=excluded.open_questions,
                     key_takeaways=excluded.key_takeaways,
                     personal_notes=excluded.personal_notes,
                     source_message_ids_json=excluded.source_message_ids_json,
                     generated_at=excluded.generated_at,
                     revision=excluded.revision""",
                (
                    paper_id,
                    short_summary,
                    qa_summary,
                    open_questions,
                    key_takeaways,
                    personal_notes,
                    json.dumps(source_message_ids or [], ensure_ascii=False),
                    now,
                    revision,
                ),
            )
        return self.get_paper_note(paper_id) or {}

    def list_paper_messages(self, paper_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """SELECT messages.* FROM messages
               JOIN conversation_resources
                 ON conversation_resources.conversation_id = messages.conversation_id
               WHERE conversation_resources.paper_id = ?
               ORDER BY messages.created_at""",
            (paper_id,),
        )
        for item in rows:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return rows

    def list_wiki(self, space_id: str, query: str = "") -> list[dict[str, Any]]:
        if query.strip():
            pattern = f"%{query.strip()}%"
            rows = self._fetchall(
                """SELECT * FROM wiki_pages WHERE space_id = ?
                   AND (title LIKE ? OR content LIKE ? OR tags_json LIKE ?) ORDER BY updated_at DESC""",
                (space_id, pattern, pattern, pattern),
            )
        else:
            rows = self._fetchall(
                "SELECT * FROM wiki_pages WHERE space_id = ? ORDER BY updated_at DESC", (space_id,)
            )
        for item in rows:
            item["tags"] = json.loads(item.pop("tags_json") or "[]")
        return rows

    def save_wiki(
        self,
        space_id: str,
        *,
        title: str,
        content: str,
        tags: Optional[list[str]] = None,
        page_id: Optional[str] = None,
        source_conversation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        now = _now()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        with self._lock, self._connect() as connection:
            existing = connection.execute("SELECT * FROM wiki_pages WHERE id = ?", (page_id,)).fetchone() if page_id else None
            if existing:
                connection.execute(
                    """INSERT INTO wiki_revisions(id, page_id, revision, title, content, tags_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (_id("revision"), page_id, existing["revision"], existing["title"],
                     existing["content"], existing["tags_json"], now),
                )
                revision = int(existing["revision"]) + 1
                connection.execute(
                    """UPDATE wiki_pages SET title = ?, content = ?, tags_json = ?, revision = ?,
                       source_conversation_id = COALESCE(?, source_conversation_id), updated_at = ? WHERE id = ?""",
                    (title.strip(), content, tags_json, revision, source_conversation_id, now, page_id),
                )
            else:
                page_id = _id("wiki")
                slug = _slug(title)
                suffix = 1
                while connection.execute(
                    "SELECT 1 FROM wiki_pages WHERE space_id = ? AND slug = ?", (space_id, slug)
                ).fetchone():
                    suffix += 1
                    slug = f"{_slug(title)}-{suffix}"
                connection.execute(
                    """INSERT INTO wiki_pages
                       (id, space_id, slug, title, content, tags_json, source_conversation_id,
                        created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (page_id, space_id, slug, title.strip(), content, tags_json,
                     source_conversation_id, now, now),
                )
        page = self._fetchone("SELECT * FROM wiki_pages WHERE id = ?", (page_id,)) or {}
        if page:
            wiki_path = self.space_dir(space_id) / "wiki" / f"{page['slug']}.md"
            frontmatter = "---\n" + f"id: {page_id}\ntitle: {title.strip()}\n" + "tags:\n"
            frontmatter += "".join(f"  - {tag}\n" for tag in (tags or [])) + "---\n\n"
            wiki_path.write_text(frontmatter + content.rstrip() + "\n", encoding="utf-8")
            page["tags"] = json.loads(page.pop("tags_json") or "[]")
        return page

    def delete_wiki(self, page_id: str) -> bool:
        page = self._fetchone("SELECT * FROM wiki_pages WHERE id = ?", (page_id,))
        if not page:
            return False
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM wiki_pages WHERE id = ?", (page_id,))
        (self.space_dir(page["space_id"]) / "wiki" / f"{page['slug']}.md").unlink(missing_ok=True)
        return True

    def list_ideas(self, space_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM ideas WHERE space_id = ? ORDER BY updated_at DESC", (space_id,))
        for item in rows:
            item["tags"] = json.loads(item.pop("tags_json") or "[]")
        return rows

    def save_idea(self, space_id: str, payload: dict[str, Any], idea_id: Optional[str] = None) -> dict[str, Any]:
        now = _now()
        fields = ("title", "problem", "hypothesis", "method", "evidence", "risks", "next_steps", "status")
        values = {field: str(payload.get(field) or ("draft" if field == "status" else "")) for field in fields}
        tags_json = json.dumps(payload.get("tags") or [], ensure_ascii=False)
        with self._lock, self._connect() as connection:
            existing = connection.execute("SELECT 1 FROM ideas WHERE id = ?", (idea_id,)).fetchone() if idea_id else None
            if existing:
                connection.execute(
                    """UPDATE ideas SET title=?, problem=?, hypothesis=?, method=?, evidence=?, risks=?,
                       next_steps=?, status=?, tags_json=?, updated_at=? WHERE id=?""",
                    tuple(values[field] for field in fields) + (tags_json, now, idea_id),
                )
            else:
                idea_id = _id("idea")
                connection.execute(
                    """INSERT INTO ideas(id, space_id, title, problem, hypothesis, method, evidence,
                       risks, next_steps, status, tags_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (idea_id, space_id) + tuple(values[field] for field in fields) + (tags_json, now, now),
                )
        idea = self._fetchone("SELECT * FROM ideas WHERE id = ?", (idea_id,)) or {}
        if idea:
            idea["tags"] = json.loads(idea.pop("tags_json") or "[]")
            body = (
                f"# {idea['title']}\n\n- 状态：{idea['status']}\n- 标签：{', '.join(idea['tags'])}\n\n"
                f"## 研究问题\n\n{idea['problem']}\n\n## 假设\n\n{idea['hypothesis']}\n\n"
                f"## 方法\n\n{idea['method']}\n\n## 证据\n\n{idea['evidence']}\n\n"
                f"## 风险\n\n{idea['risks']}\n\n## 下一步\n\n{idea['next_steps']}\n"
            )
            (self.space_dir(space_id) / "ideas" / f"{idea_id}.md").write_text(body, encoding="utf-8")
        return idea

    def list_jobs(self, space_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM jobs WHERE space_id = ? ORDER BY updated_at DESC", (space_id,))
        for item in rows:
            item["input"] = json.loads(item.pop("input_json") or "{}")
            item["output"] = json.loads(item.pop("output_json") or "{}")
        return rows

    def create_job(
        self,
        space_id: str,
        *,
        kind: str,
        provider: str,
        input_data: dict[str, Any],
        conversation_id: Optional[str] = None,
        status: str = "waiting_provider",
    ) -> dict[str, Any]:
        job_id, now = _id("job"), _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO jobs(id, space_id, conversation_id, kind, provider, status,
                   input_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, space_id, conversation_id, kind, provider, status,
                 json.dumps(input_data, ensure_ascii=False), now, now),
            )
        job = self._fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,)) or {}
        if job:
            job["input"] = json.loads(job.pop("input_json") or "{}")
            job["output"] = json.loads(job.pop("output_json") or "{}")
        return job

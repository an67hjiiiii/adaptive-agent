"""Durable storage for normal Product conversations.

The repository intentionally owns persistence only.  It does not know about
orchestration, providers, or Pilot artifacts.  JSON remains the local fallback
when DATABASE_URL is absent; a configured PostgreSQL database never silently
falls back to a local file.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.core.context_files import ContextFileError, normalize_context_sources


CONVERSATION_ID_RE = re.compile(r"chat_[A-Za-z0-9_-]+$")


class ConversationStorageError(RuntimeError):
    """Safe configuration or availability error for conversation storage."""


class ConversationRepository(Protocol):
    def read(self, conversation_id: str) -> dict[str, Any] | None: ...
    def write(self, data: dict[str, Any]) -> None: ...
    def list(self, *, limit: int, query: str = "") -> list[dict[str, Any]]: ...
    def delete(self, conversation_id: str) -> bool: ...


def validate_conversation_id(conversation_id: str) -> str:
    if not isinstance(conversation_id, str) or not CONVERSATION_ID_RE.fullmatch(conversation_id):
        raise ValueError("Invalid conversation id")
    return conversation_id


def _safe_sources(value: Any) -> list[dict[str, Any]]:
    """Persist only the normalised attachment identity, never file bytes or paths."""

    try:
        return normalize_context_sources(value if isinstance(value, list) else [])
    except ContextFileError:
        return []


def _epoch(value: Any) -> int:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    return int(time.time())


def _timestamp(value: Any) -> datetime:
    return datetime.fromtimestamp(_epoch(value), tz=timezone.utc)


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return deepcopy(default)
    return deepcopy(value) if value is not None else deepcopy(default)


def _message_metadata(message: dict[str, Any]) -> dict[str, Any]:
    """Whitelist stable UI metadata; attachment fields are sanitised separately."""

    metadata: dict[str, Any] = {}
    for key in (
        "status", "stop_reason", "provider", "model", "mode", "requested_mode",
        "processing_mode", "metrics", "error",
    ):
        if key in message:
            metadata[key] = deepcopy(message[key])
    for key in ("sources", "context_sources", "attachments", "files"):
        if key in message:
            metadata[key] = _safe_sources(message[key])
    return metadata


def _conversation_message(message: dict[str, Any], *, conversation_id: str, fallback_timestamp: int) -> dict[str, Any]:
    clean = {
        "conversation_id": conversation_id,
        "role": str(message.get("role") or "assistant"),
        "content": str(message.get("content") or ""),
        "run_id": message.get("run_id") if isinstance(message.get("run_id"), str) else None,
        "created_at": _epoch(message.get("created_at", fallback_timestamp)),
    }
    clean.update(_message_metadata(message))
    return clean


def _conversation_record(data: dict[str, Any]) -> dict[str, Any]:
    conversation_id = validate_conversation_id(data.get("conversation_id", ""))
    created_at = _epoch(data.get("created_at"))
    return {
        "conversation_id": conversation_id,
        "title": str(data.get("title") or "Cuộc trò chuyện")[:100],
        "created_at": created_at,
        "updated_at": _epoch(data.get("updated_at", created_at)),
        "provider": data.get("provider"),
        "model": data.get("model"),
        "processing_mode": data.get("processing_mode"),
        "status": data.get("status"),
        "last_error": data.get("last_error"),
        # Existing normal-chat semantics use this bounded text for follow-ups.
        "context": str(data.get("context") or "")[:100_000],
        "context_sources": _safe_sources(data.get("context_sources")),
        "run_ids": [item for item in data.get("run_ids", []) if isinstance(item, str)],
        "messages": [
            _conversation_message(item, conversation_id=conversation_id, fallback_timestamp=created_at)
            for item in data.get("messages", []) if isinstance(item, dict)
        ],
    }


class JsonConversationRepository:
    """Existing local development fallback, intentionally kept format-compatible."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, conversation_id: str) -> Path:
        return self.directory / f"{validate_conversation_id(conversation_id)}.json"

    def read(self, conversation_id: str) -> dict[str, Any] | None:
        path = self._path(conversation_id)
        if not path.exists():
            return None
        return _conversation_record(json.loads(path.read_text(encoding="utf-8")))

    def write(self, data: dict[str, Any]) -> None:
        record = _conversation_record(data)
        path = self._path(record["conversation_id"])
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def list(self, *, limit: int, query: str = "") -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        rows: list[dict[str, Any]] = []
        paths = sorted(self.directory.glob("chat_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                messages = data.get("messages", [])
                last_user = next((item.get("content", "") for item in reversed(messages)
                                  if item.get("role") == "user"), "")
                if needle and needle not in f"{data.get('title', '')} {last_user}".casefold():
                    continue
                rows.append({
                    "conversation_id": data.get("conversation_id"),
                    "title": data.get("title") or "Cuộc trò chuyện",
                    "updated_at": data.get("updated_at"),
                    "provider": data.get("provider"),
                    "model": data.get("model"),
                    "mode": data.get("processing_mode"),
                    "status": data.get("status"),
                    "message_count": len(messages),
                    "turn_count": sum(1 for item in messages if item.get("role") == "user"),
                    "run_count": len(data.get("run_ids", [])),
                    "last_preview": last_user[:120],
                })
            except (OSError, json.JSONDecodeError):
                continue
            if len(rows) >= limit:
                break
        return rows

    def delete(self, conversation_id: str) -> bool:
        path = self._path(conversation_id)
        if not path.exists():
            return False
        path.unlink()
        return True


class PostgresConversationRepository:
    """Small synchronous psycopg repository for the existing synchronous persistence path."""

    def __init__(self, database_url: str):
        self._database_url = database_url
        try:
            from psycopg import connect
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - exercised through configuration test doubles
            raise ConversationStorageError(
                "DATABASE_URL is configured but PostgreSQL conversation storage is unavailable."
            ) from exc
        self._connect = connect
        self._dict_row = dict_row
        self._initialize_schema()

    def _connection(self):
        try:
            return self._connect(self._database_url, connect_timeout=5)
        except Exception as exc:
            raise ConversationStorageError(
                "DATABASE_URL is configured but PostgreSQL conversation storage could not initialize."
            ) from exc

    def _initialize_schema(self) -> None:
        statements = (
            """CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                provider TEXT,
                model TEXT,
                processing_mode TEXT,
                status TEXT,
                last_error TEXT,
                context_text TEXT NOT NULL DEFAULT '',
                context_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
                run_ids JSONB NOT NULL DEFAULT '[]'::jsonb
            )""",
            """CREATE TABLE IF NOT EXISTS conversation_messages (
                message_id BIGSERIAL PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                run_id TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                UNIQUE(conversation_id, position)
            )""",
            "CREATE INDEX IF NOT EXISTS conversations_updated_at_idx ON conversations (updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS conversation_messages_order_idx ON conversation_messages (conversation_id, position)",
        )
        with self._connection() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    def read(self, conversation_id: str) -> dict[str, Any] | None:
        conversation_id = validate_conversation_id(conversation_id)
        try:
            with self._connection() as connection:
                with connection.cursor(row_factory=self._dict_row) as cursor:
                    cursor.execute("SELECT * FROM conversations WHERE conversation_id = %s", (conversation_id,))
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    cursor.execute(
                        "SELECT position, role, content, run_id, created_at, metadata "
                        "FROM conversation_messages WHERE conversation_id = %s ORDER BY position ASC",
                        (conversation_id,),
                    )
                    messages = []
                    for message_row in cursor.fetchall():
                        message = {
                            "conversation_id": conversation_id,
                            "role": message_row["role"],
                            "content": message_row["content"],
                            "run_id": message_row["run_id"],
                            "created_at": _epoch(message_row["created_at"]),
                        }
                        message.update(_json_value(message_row["metadata"], {}))
                        messages.append(message)
                    return {
                        "conversation_id": conversation_id,
                        "title": row["title"],
                        "created_at": _epoch(row["created_at"]),
                        "updated_at": _epoch(row["updated_at"]),
                        "provider": row["provider"],
                        "model": row["model"],
                        "processing_mode": row["processing_mode"],
                        "status": row["status"],
                        "last_error": row["last_error"],
                        "context": row["context_text"],
                        "context_sources": _safe_sources(_json_value(row["context_sources"], [])),
                        "run_ids": _json_value(row["run_ids"], []),
                        "messages": messages,
                    }
        except ConversationStorageError:
            raise
        except Exception as exc:
            raise ConversationStorageError("PostgreSQL conversation storage is unavailable.") from exc

    def write(self, data: dict[str, Any]) -> None:
        record = _conversation_record(data)
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO conversations (
                            conversation_id, title, created_at, updated_at, provider, model,
                            processing_mode, status, last_error, context_text, context_sources, run_ids
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        ON CONFLICT (conversation_id) DO UPDATE SET
                            title = EXCLUDED.title, updated_at = EXCLUDED.updated_at,
                            provider = EXCLUDED.provider, model = EXCLUDED.model,
                            processing_mode = EXCLUDED.processing_mode, status = EXCLUDED.status,
                            last_error = EXCLUDED.last_error, context_text = EXCLUDED.context_text,
                            context_sources = EXCLUDED.context_sources, run_ids = EXCLUDED.run_ids""",
                        (
                            record["conversation_id"], record["title"], _timestamp(record["created_at"]),
                            _timestamp(record["updated_at"]), record["provider"], record["model"],
                            record["processing_mode"], record["status"], record["last_error"], record["context"],
                            json.dumps(record["context_sources"]), json.dumps(record["run_ids"]),
                        ),
                    )
                    cursor.execute("DELETE FROM conversation_messages WHERE conversation_id = %s", (record["conversation_id"],))
                    for position, message in enumerate(record["messages"]):
                        cursor.execute(
                            """INSERT INTO conversation_messages (
                                conversation_id, position, role, content, run_id, created_at, metadata
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)""",
                            (
                                record["conversation_id"], position, str(message.get("role") or "assistant"),
                                str(message.get("content") or ""), message.get("run_id"),
                                _timestamp(message.get("created_at", record["updated_at"])),
                                json.dumps(_message_metadata(message)),
                            ),
                        )
        except ConversationStorageError:
            raise
        except Exception as exc:
            raise ConversationStorageError("PostgreSQL conversation storage is unavailable.") from exc

    def list(self, *, limit: int, query: str = "") -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        params: list[Any] = []
        where = ""
        if query.strip():
            pattern = f"%{query.strip()}%"
            where = """WHERE c.title ILIKE %s OR EXISTS (
                SELECT 1 FROM conversation_messages search_message
                WHERE search_message.conversation_id = c.conversation_id
                  AND search_message.role = 'user' AND search_message.content ILIKE %s
            )"""
            params.extend((pattern, pattern))
        params.append(limit)
        try:
            with self._connection() as connection:
                with connection.cursor(row_factory=self._dict_row) as cursor:
                    cursor.execute(
                        f"""SELECT c.conversation_id, c.title, c.updated_at, c.provider, c.model,
                            c.processing_mode AS mode, c.status,
                            (SELECT COUNT(*) FROM conversation_messages all_messages
                             WHERE all_messages.conversation_id = c.conversation_id) AS message_count,
                            (SELECT COUNT(*) FROM conversation_messages user_messages
                             WHERE user_messages.conversation_id = c.conversation_id AND user_messages.role = 'user') AS turn_count,
                            jsonb_array_length(c.run_ids) AS run_count,
                            COALESCE((SELECT latest.content FROM conversation_messages latest
                             WHERE latest.conversation_id = c.conversation_id AND latest.role = 'user'
                             ORDER BY latest.position DESC LIMIT 1), '') AS last_preview
                        FROM conversations c {where} ORDER BY c.updated_at DESC LIMIT %s""",
                        params,
                    )
                    return [
                        {**row, "updated_at": _epoch(row["updated_at"]), "last_preview": row["last_preview"][:120]}
                        for row in cursor.fetchall()
                    ]
        except ConversationStorageError:
            raise
        except Exception as exc:
            raise ConversationStorageError("PostgreSQL conversation storage is unavailable.") from exc

    def delete(self, conversation_id: str) -> bool:
        conversation_id = validate_conversation_id(conversation_id)
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM conversations WHERE conversation_id = %s", (conversation_id,))
                    return cursor.rowcount > 0
        except ConversationStorageError:
            raise
        except Exception as exc:
            raise ConversationStorageError("PostgreSQL conversation storage is unavailable.") from exc


def repository_from_environment(*, database_url: str | None, json_directory: Path) -> ConversationRepository:
    """Select one storage backend once at application startup."""

    if database_url and database_url.strip():
        return PostgresConversationRepository(database_url.strip())
    return JsonConversationRepository(json_directory)

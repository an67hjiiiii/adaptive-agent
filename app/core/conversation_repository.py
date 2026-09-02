"""Durable storage for normal Product conversations.

The repository intentionally owns persistence only.  It does not know about
orchestration, providers, or Pilot artifacts.  JSON remains the local fallback
when DATABASE_URL is absent; a configured PostgreSQL database never silently
falls back to a local file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.core.context_files import (
    ContextFileError,
    MAX_CONTEXT_FILES,
    normalize_context_sources,
    prepare_context_file,
)


LOGGER = logging.getLogger(__name__)


CONVERSATION_ID_RE = re.compile(r"chat_[A-Za-z0-9_-]+$")
PROJECT_ID_RE = re.compile(r"project_[A-Za-z0-9_-]+$")


class ConversationStorageError(RuntimeError):
    """Safe configuration or availability error for conversation storage."""


class ConversationRepository(Protocol):
    def read(self, conversation_id: str) -> dict[str, Any] | None: ...
    def write(self, data: dict[str, Any]) -> None: ...
    def append(
        self,
        data: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        preserve_historical_context: bool = False,
    ) -> None: ...
    def list(self, *, limit: int, query: str = "") -> list[dict[str, Any]]: ...
    def delete(self, conversation_id: str) -> bool: ...
    def get_project_workspace(self, conversation_id: str, *, include_content: bool = False) -> dict[str, Any] | None: ...
    def save_project_workspace(self, conversation_id: str, workspace: dict[str, Any]) -> dict[str, Any]: ...
    def detach_project_workspace(self, conversation_id: str) -> bool: ...


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


def _safe_workspace_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 100 or "/" in name or "\\" in name or any(ord(char) < 32 for char in name):
        raise ValueError("Invalid project workspace name")
    return name


def _workspace_record(value: Any, *, conversation_id: str) -> dict[str, Any]:
    """Normalize persisted project text through the existing source validator."""

    if not isinstance(value, dict):
        raise ValueError("Invalid project workspace")
    files = value.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_CONTEXT_FILES:
        raise ValueError("Invalid project workspace files")
    project_id = str(value.get("project_id") or f"project_{uuid.uuid4().hex[:12]}")
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError("Invalid project id")
    now = _epoch(value.get("updated_at"))
    created_at = _epoch(value.get("created_at", now))
    normalized_files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("Invalid project file")
        try:
            prepared = prepare_context_file(
                filename=item.get("filename"),
                relative_path=item.get("relative_path"),
                content=item.get("content"),
            )
        except ContextFileError as exc:
            raise ValueError(exc.message) from exc
        source = prepared["source"]
        relative_path = source.get("relative_path")
        if not relative_path or relative_path in seen_paths:
            raise ValueError("Project files require unique relative paths")
        seen_paths.add(relative_path)
        text = prepared["text"]
        normalized_files.append({
            "relative_path": relative_path,
            "filename": source["filename"],
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "byte_count": len(text.encode("utf-8")),
            "source": source,
            "content": text,
        })
    normalized_files.sort(key=lambda item: item["relative_path"])
    project_hash = hashlib.sha256(json.dumps(
        [(item["relative_path"], item["content_hash"]) for item in normalized_files],
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    return {
        "project_id": project_id,
        "conversation_id": validate_conversation_id(conversation_id),
        "name": _safe_workspace_name(value.get("name")),
        "created_at": created_at,
        "updated_at": now,
        "project_hash": project_hash,
        "file_count": len(normalized_files),
        "files": normalized_files,
    }


def _workspace_public(workspace: dict[str, Any] | None) -> dict[str, Any] | None:
    if not workspace:
        return None
    return {
        key: deepcopy(workspace.get(key))
        for key in ("project_id", "conversation_id", "name", "created_at", "updated_at", "project_hash", "file_count")
    } | {
        "files": [{
            "relative_path": item["relative_path"],
            "filename": item["filename"],
            "content_hash": item["content_hash"],
            "byte_count": item["byte_count"],
            "source": deepcopy(item["source"]),
        } for item in workspace.get("files", [])],
    }


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
    record = {
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
    if data.get("project_workspace"):
        record["project_workspace"] = _workspace_record(
            data["project_workspace"], conversation_id=conversation_id,
        )
    return record


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

    def append(
        self,
        data: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        preserve_historical_context: bool = False,
    ) -> None:
        # JSON is the local fallback and has no row-level append primitive. Its
        # existing atomic file replacement remains the compatible behavior.
        self.write(data)

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

    def get_project_workspace(self, conversation_id: str, *, include_content: bool = False) -> dict[str, Any] | None:
        record = self.read(conversation_id)
        workspace = record.get("project_workspace") if record else None
        if not workspace:
            return None
        return deepcopy(workspace) if include_content else _workspace_public(workspace)

    def save_project_workspace(self, conversation_id: str, workspace: dict[str, Any]) -> dict[str, Any]:
        conversation_id = validate_conversation_id(conversation_id)
        existing = self.read(conversation_id)
        now = int(time.time())
        record = existing or {
            "conversation_id": conversation_id,
            "title": _safe_workspace_name(workspace.get("name")),
            "created_at": now,
            "updated_at": now,
            "messages": [],
            "run_ids": [],
        }
        candidate = dict(workspace)
        if record.get("project_workspace"):
            candidate.setdefault("project_id", record["project_workspace"].get("project_id"))
            candidate.setdefault("created_at", record["project_workspace"].get("created_at"))
        candidate["updated_at"] = now
        record["updated_at"] = now
        record["project_workspace"] = _workspace_record(candidate, conversation_id=conversation_id)
        self.write(record)
        return _workspace_public(record["project_workspace"])

    def detach_project_workspace(self, conversation_id: str) -> bool:
        record = self.read(conversation_id)
        if not record or not record.get("project_workspace"):
            return False
        record.pop("project_workspace", None)
        record["updated_at"] = int(time.time())
        self.write(record)
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
        self._connection_handle = None
        self._connection_lock = threading.RLock()
        self._initialize_schema()

    @staticmethod
    def _closed(connection: Any) -> bool:
        value = getattr(connection, "closed", False)
        if callable(value):
            value = value()
        return isinstance(value, (bool, int)) and bool(value)

    @contextmanager
    def _connection(self):
        lock = getattr(self, "_connection_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._connection_lock = lock
        with lock:
            connection = getattr(self, "_connection_handle", None)
            if connection is None or self._closed(connection):
                try:
                    connection = self._connect(self._database_url, connect_timeout=5)
                except Exception as exc:
                    raise ConversationStorageError(
                        "DATABASE_URL is configured but PostgreSQL conversation storage could not initialize."
                    ) from exc
                self._connection_handle = connection
            try:
                yield connection
                commit = getattr(connection, "commit", None)
                if callable(commit):
                    commit()
            except Exception:
                rollback = getattr(connection, "rollback", None)
                if callable(rollback):
                    try:
                        rollback()
                    except Exception:
                        pass
                self._connection_handle = None
                close = getattr(connection, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
                raise

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
            """CREATE TABLE IF NOT EXISTS project_workspaces (
                project_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                project_hash TEXT NOT NULL,
                file_count INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS project_files (
                project_id TEXT NOT NULL REFERENCES project_workspaces(project_id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                relative_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                byte_count INTEGER NOT NULL,
                source_metadata JSONB NOT NULL,
                content_text TEXT NOT NULL,
                PRIMARY KEY(project_id, position),
                UNIQUE(project_id, relative_path)
            )""",
            "CREATE INDEX IF NOT EXISTS project_workspaces_conversation_idx ON project_workspaces (conversation_id)",
            "CREATE INDEX IF NOT EXISTS project_files_order_idx ON project_files (project_id, position)",
        )
        with self._connection() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    def read(self, conversation_id: str) -> dict[str, Any] | None:
        conversation_id = validate_conversation_id(conversation_id)
        started = time.perf_counter()
        sql_calls = 0
        conversation_query_ms = None
        message_query_ms = None
        try:
            with self._connection() as connection:
                with connection.cursor(row_factory=self._dict_row) as cursor:
                    query_started = time.perf_counter()
                    cursor.execute("SELECT * FROM conversations WHERE conversation_id = %s", (conversation_id,))
                    sql_calls += 1
                    conversation_query_ms = round((time.perf_counter() - query_started) * 1000)
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    query_started = time.perf_counter()
                    cursor.execute(
                        "SELECT position, role, content, run_id, created_at, metadata "
                        "FROM conversation_messages WHERE conversation_id = %s ORDER BY position ASC",
                        (conversation_id,),
                    )
                    sql_calls += 1
                    message_query_ms = round((time.perf_counter() - query_started) * 1000)
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
        finally:
            LOGGER.info(
                "conversation_read_timing %s",
                {
                    "conversation_query_ms": conversation_query_ms,
                    "message_query_ms": message_query_ms,
                    "sql_calls": sql_calls,
                    "total_ms": round((time.perf_counter() - started) * 1000),
                },
            )

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

    def append(
        self,
        data: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        preserve_historical_context: bool = False,
    ) -> None:
        """Append new turn rows without rewriting the existing transcript.

        The caller supplies the already-loaded conversation and only the new
        message rows. Metadata and message inserts share one short transaction;
        the provider is never awaited while this transaction is open.
        """

        record = _conversation_record(data)
        cleaned_messages = [
            _conversation_message(
                message,
                conversation_id=record["conversation_id"],
                fallback_timestamp=record["updated_at"],
            )
            for message in messages
            if isinstance(message, dict)
        ]
        started = time.perf_counter()
        sql_calls = 0
        context_update = "" if preserve_historical_context else (
            "context_text = EXCLUDED.context_text, "
            "context_sources = EXCLUDED.context_sources, "
        )
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""INSERT INTO conversations (
                            conversation_id, title, created_at, updated_at, provider, model,
                            processing_mode, status, last_error, context_text, context_sources, run_ids
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        ON CONFLICT (conversation_id) DO UPDATE SET
                            title = EXCLUDED.title, updated_at = EXCLUDED.updated_at,
                            provider = EXCLUDED.provider, model = EXCLUDED.model,
                            processing_mode = EXCLUDED.processing_mode, status = EXCLUDED.status,
                            last_error = EXCLUDED.last_error, {context_update}
                            run_ids = EXCLUDED.run_ids""",
                        (
                            record["conversation_id"], record["title"], _timestamp(record["created_at"]),
                            _timestamp(record["updated_at"]), record["provider"], record["model"],
                            record["processing_mode"], record["status"], record["last_error"], record["context"],
                            json.dumps(record["context_sources"]), json.dumps(record["run_ids"]),
                        ),
                    )
                    sql_calls += 1
                    if cleaned_messages:
                        cursor.execute(
                            "SELECT COALESCE(MAX(position) + 1, 0) "
                            "FROM conversation_messages WHERE conversation_id = %s",
                            (record["conversation_id"],),
                        )
                        sql_calls += 1
                        position_row = cursor.fetchone()
                        if isinstance(position_row, dict):
                            position = int(next(iter(position_row.values())) or 0)
                        else:
                            position = int((position_row or (0,))[0] or 0)
                        for offset, message in enumerate(cleaned_messages):
                            cursor.execute(
                                """INSERT INTO conversation_messages (
                                    conversation_id, position, role, content, run_id, created_at, metadata
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)""",
                                (
                                    record["conversation_id"], position + offset,
                                    str(message.get("role") or "assistant"),
                                    str(message.get("content") or ""), message.get("run_id"),
                                    _timestamp(message.get("created_at", record["updated_at"])),
                                    json.dumps(_message_metadata(message)),
                                ),
                            )
                            sql_calls += 1
        except ConversationStorageError:
            raise
        except Exception as exc:
            raise ConversationStorageError("PostgreSQL conversation storage is unavailable.") from exc
        finally:
            LOGGER.info(
                "conversation_append_timing %s",
                {
                    "sql_calls": sql_calls,
                    "message_count": len(cleaned_messages),
                    "total_ms": round((time.perf_counter() - started) * 1000),
                },
            )

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
        started = time.perf_counter()
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
        finally:
            LOGGER.info(
                "conversation_list_timing %s",
                {"sql_calls": 1, "total_ms": round((time.perf_counter() - started) * 1000)},
            )

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

    def get_project_workspace(self, conversation_id: str, *, include_content: bool = False) -> dict[str, Any] | None:
        conversation_id = validate_conversation_id(conversation_id)
        fields = "position, relative_path, filename, content_hash, byte_count, source_metadata"
        if include_content:
            fields += ", content_text"
        try:
            with self._connection() as connection:
                with connection.cursor(row_factory=self._dict_row) as cursor:
                    cursor.execute(
                        "SELECT project_id, conversation_id, name, project_hash, file_count, created_at, updated_at "
                        "FROM project_workspaces WHERE conversation_id = %s",
                        (conversation_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    cursor.execute(
                        f"SELECT {fields} FROM project_files WHERE project_id = %s ORDER BY position ASC",
                        (row["project_id"],),
                    )
                    files = []
                    for file_row in cursor.fetchall():
                        source = _safe_sources([_json_value(file_row["source_metadata"], {})])
                        item = {
                            "relative_path": file_row["relative_path"],
                            "filename": file_row["filename"],
                            "content_hash": file_row["content_hash"],
                            "byte_count": file_row["byte_count"],
                            "source": source[0] if source else {"filename": file_row["filename"], "relative_path": file_row["relative_path"]},
                        }
                        if include_content:
                            item["content"] = file_row["content_text"]
                        files.append(item)
                    workspace = {
                        "project_id": row["project_id"], "conversation_id": row["conversation_id"],
                        "name": row["name"], "project_hash": row["project_hash"], "file_count": row["file_count"],
                        "created_at": _epoch(row["created_at"]), "updated_at": _epoch(row["updated_at"]), "files": files,
                    }
                    return workspace if include_content else _workspace_public(workspace)
        except ConversationStorageError:
            raise
        except Exception as exc:
            raise ConversationStorageError("PostgreSQL project workspace storage is unavailable.") from exc

    def save_project_workspace(self, conversation_id: str, workspace: dict[str, Any]) -> dict[str, Any]:
        conversation_id = validate_conversation_id(conversation_id)
        candidate = _workspace_record(workspace, conversation_id=conversation_id)
        now = _timestamp(candidate["updated_at"])
        try:
            with self._connection() as connection:
                with connection.cursor(row_factory=self._dict_row) as cursor:
                    cursor.execute(
                        """INSERT INTO conversations (
                            conversation_id, title, created_at, updated_at, context_text, context_sources, run_ids
                        ) VALUES (%s, %s, %s, %s, '', '[]'::jsonb, '[]'::jsonb)
                        ON CONFLICT (conversation_id) DO NOTHING""",
                        (conversation_id, candidate["name"], now, now),
                    )
                    cursor.execute(
                        """INSERT INTO project_workspaces (
                            project_id, conversation_id, name, project_hash, file_count, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (conversation_id) DO UPDATE SET
                            name = EXCLUDED.name, project_hash = EXCLUDED.project_hash,
                            file_count = EXCLUDED.file_count, updated_at = EXCLUDED.updated_at
                        RETURNING project_id, created_at""",
                        (
                            candidate["project_id"], conversation_id, candidate["name"], candidate["project_hash"],
                            candidate["file_count"], _timestamp(candidate["created_at"]), now,
                        ),
                    )
                    row = cursor.fetchone()
                    project_id = row["project_id"] if isinstance(row, dict) else row[0]
                    created_at = row["created_at"] if isinstance(row, dict) else row[1]
                    cursor.execute("DELETE FROM project_files WHERE project_id = %s", (project_id,))
                    for position, item in enumerate(candidate["files"]):
                        cursor.execute(
                            """INSERT INTO project_files (
                                project_id, position, relative_path, filename, content_hash, byte_count, source_metadata, content_text
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)""",
                            (
                                project_id, position, item["relative_path"], item["filename"], item["content_hash"],
                                item["byte_count"], json.dumps(item["source"]), item["content"],
                            ),
                        )
                    candidate["project_id"] = project_id
                    candidate["created_at"] = _epoch(created_at)
                    return _workspace_public(candidate)
        except ConversationStorageError:
            raise
        except Exception as exc:
            raise ConversationStorageError("PostgreSQL project workspace storage is unavailable.") from exc

    def detach_project_workspace(self, conversation_id: str) -> bool:
        conversation_id = validate_conversation_id(conversation_id)
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM project_workspaces WHERE conversation_id = %s", (conversation_id,))
                    return cursor.rowcount > 0
        except ConversationStorageError:
            raise
        except Exception as exc:
            raise ConversationStorageError("PostgreSQL project workspace storage is unavailable.") from exc


def repository_from_environment(*, database_url: str | None, json_directory: Path) -> ConversationRepository:
    """Select one storage backend once at application startup."""

    if database_url and database_url.strip():
        return PostgresConversationRepository(database_url.strip())
    return JsonConversationRepository(json_directory)

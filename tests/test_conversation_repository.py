from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import conversation_repository as repository_module
from app.core.conversation_repository import (
    ConversationStorageError,
    JsonConversationRepository,
    PostgresConversationRepository,
    repository_from_environment,
)


class _RecordingCursor:
    def __init__(self, *, rowcount: int = 1):
        self.statements: list[tuple[str, object]] = []
        self.rowcount = rowcount

    def execute(self, statement, parameters=None):
        self.statements.append((" ".join(statement.split()), parameters))

    def fetchone(self):
        return (0,)

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _RecordingConnection:
    def __init__(self, *, rowcount: int = 1):
        self.cursor_instance = _RecordingCursor(rowcount=rowcount)
        self.commit_count = 0

    def cursor(self, **_):
        return self.cursor_instance

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ConversationRepositoryTests(unittest.TestCase):
    @staticmethod
    def _record(conversation_id: str = "chat_repo_one"):
        return {
            "conversation_id": conversation_id,
            "title": "Repository title",
            "created_at": 10,
            "updated_at": 20,
            "provider": "groq",
            "model": "openai/gpt-oss-120b",
            "processing_mode": "DIRECT",
            "status": "failed",
            "last_error": "safe failure",
            "context": "bounded restart context",
            "context_sources": [{
                "filename": "notes.md", "source_id": "ctx_0123456789abcdef",
                "format": "md", "parser": "utf-8-text-v1", "char_count": 7,
            }],
            "run_ids": ["run_one"],
            "messages": [
                {
                    "role": "user", "content": "First", "run_id": "run_one", "created_at": 10,
                    "context_sources": [{"filename": "notes.md", "source_id": "ctx_0123456789abcdef", "path": "C:\\private\\notes.md"}],
                },
                {
                    "role": "assistant", "content": "Failed answer", "run_id": "run_one", "created_at": 11,
                    "status": "failed", "provider": "groq", "model": "openai/gpt-oss-120b",
                    "mode": "DIRECT", "metrics": {"logical_calls": 1},
                },
            ],
        }

    def test_json_create_reload_order_and_failed_turn_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConversationRepository(Path(temp_dir))
            record = self._record()
            repository.write(record)
            reopened = JsonConversationRepository(Path(temp_dir)).read("chat_repo_one")
        self.assertEqual([item["content"] for item in reopened["messages"]], ["First", "Failed answer"])
        self.assertEqual(reopened["messages"][1]["status"], "failed")
        self.assertEqual(reopened["provider"], "groq")
        self.assertEqual(reopened["model"], "openai/gpt-oss-120b")
        self.assertEqual(reopened["processing_mode"], "DIRECT")
        self.assertEqual(reopened["context"], "bounded restart context")

    def test_json_list_search_delete_and_safe_attachment_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConversationRepository(Path(temp_dir))
            first = self._record("chat_repo_first")
            second = self._record("chat_repo_second")
            second["title"] = "Other"
            second["messages"][0]["content"] = "Different question"
            repository.write(first)
            repository.write(second)
            rows = repository.list(limit=10, query="repository")
            self.assertEqual([row["conversation_id"] for row in rows], ["chat_repo_first"])
            raw = json.loads((Path(temp_dir) / "chat_repo_first.json").read_text(encoding="utf-8"))
            source = raw["messages"][0]["context_sources"][0]
            self.assertEqual(source["filename"], "notes.md")
            self.assertNotIn("path", source)
            self.assertTrue(repository.delete("chat_repo_first"))
            self.assertIsNone(repository.read("chat_repo_first"))
            self.assertFalse(repository.delete("chat_repo_first"))

    def test_relative_path_roundtrip_and_legacy_source_compatibility(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConversationRepository(Path(temp_dir))
            record = self._record("chat_repo_paths")
            project_source = {
                "filename": "routes.py",
                "relative_path": "api/routes.py",
                "source_id": "ctx_0123456789abcdef",
                "format": "py",
                "parser": "utf-8-text-v1",
            }
            record["context_sources"] = [project_source]
            record["messages"][0]["context_sources"] = [project_source]
            repository.write(record)
            reopened = repository.read("chat_repo_paths")
            self.assertEqual(reopened["context_sources"][0]["relative_path"], "api/routes.py")
            self.assertEqual(reopened["messages"][0]["context_sources"][0]["relative_path"], "api/routes.py")

            legacy = self._record("chat_repo_legacy")
            legacy["context_sources"] = [{"filename": "notes.txt", "source_id": "ctx_0123456789abcdef"}]
            repository.write(legacy)
            self.assertEqual(repository.read("chat_repo_legacy")["context_sources"][0]["filename"], "notes.txt")
            self.assertNotIn("relative_path", repository.read("chat_repo_legacy")["context_sources"][0])

            unsafe = self._record("chat_repo_unsafe")
            unsafe["context_sources"] = [{"filename": "routes.py", "relative_path": "C:\\Users\\private\\routes.py"}]
            repository.write(unsafe)
            self.assertEqual(repository.read("chat_repo_unsafe")["context_sources"], [])

    def test_storage_selection_is_json_without_database_and_postgres_with_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            self.assertIsInstance(
                repository_from_environment(database_url=None, json_directory=directory),
                JsonConversationRepository,
            )
            expected = object()
            with patch.object(repository_module, "PostgresConversationRepository", return_value=expected) as factory:
                selected = repository_from_environment(
                    database_url="postgresql://configured-but-not-printed", json_directory=directory,
                )
        self.assertIs(selected, expected)
        factory.assert_called_once()

    def test_configured_database_failure_never_falls_back_to_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                repository_module,
                "PostgresConversationRepository",
                side_effect=ConversationStorageError("safe database startup failure"),
            ):
                with self.assertRaises(ConversationStorageError):
                    repository_from_environment(
                        database_url="postgresql://configured-but-not-printed",
                        json_directory=Path(temp_dir),
                    )

    def test_database_selection_does_not_import_or_modify_legacy_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            legacy = directory / "chat_legacy.json"
            legacy.write_text('{"conversation_id":"chat_legacy","messages":[]}', encoding="utf-8")
            before = legacy.read_bytes()
            with patch.object(repository_module, "PostgresConversationRepository", return_value=object()):
                repository_from_environment(
                    database_url="postgresql://configured-but-not-printed", json_directory=directory,
                )
            self.assertEqual(legacy.read_bytes(), before)

    def test_postgres_schema_has_cascade_and_required_indexes_without_live_database(self):
        connection = _RecordingConnection()
        repository = PostgresConversationRepository.__new__(PostgresConversationRepository)
        repository._database_url = "postgresql://test"
        repository._connect = lambda *_args, **_kwargs: connection
        repository._initialize_schema()
        ddl = "\n".join(statement for statement, _ in connection.cursor_instance.statements)
        self.assertIn("ON DELETE CASCADE", ddl)
        self.assertIn("conversations_updated_at_idx", ddl)
        self.assertIn("conversation_messages_order_idx", ddl)

    def test_postgres_delete_targets_parent_and_relies_on_cascade_without_live_database(self):
        connection = _RecordingConnection(rowcount=1)
        repository = PostgresConversationRepository.__new__(PostgresConversationRepository)
        repository._database_url = "postgresql://test"
        repository._connect = lambda *_args, **_kwargs: connection
        self.assertTrue(repository.delete("chat_repo_delete"))
        statement, parameters = connection.cursor_instance.statements[-1]
        self.assertEqual(statement, "DELETE FROM conversations WHERE conversation_id = %s")
        self.assertEqual(parameters, ("chat_repo_delete",))

    def test_postgres_append_reuses_connection_and_does_not_rewrite_history(self):
        connection = _RecordingConnection()
        connect_calls = []
        repository = PostgresConversationRepository.__new__(PostgresConversationRepository)
        repository._database_url = "postgresql://test"
        repository._connect = lambda *_args, **_kwargs: connect_calls.append(True) or connection
        record = self._record("chat_repo_append")
        new_message = {"role": "user", "content": "Next", "run_id": "run_two", "created_at": 30}

        repository.append({**record, "messages": record["messages"] + [new_message], "run_ids": ["run_one", "run_two"]}, messages=[new_message])
        repository.append({**record, "messages": record["messages"] + [new_message], "run_ids": ["run_one", "run_two"]}, messages=[])

        statements = [statement for statement, _ in connection.cursor_instance.statements]
        self.assertEqual(len(connect_calls), 1)
        self.assertNotIn("DELETE FROM conversation_messages", "\n".join(statements))
        self.assertGreaterEqual(connection.commit_count, 2)

    def test_repository_module_is_product_storage_only(self):
        source = Path(repository_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("runs/pilot", source)
        self.assertNotIn("app.core.pilot", source)


if __name__ == "__main__":
    unittest.main()

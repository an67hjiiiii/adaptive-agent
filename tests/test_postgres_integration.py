from __future__ import annotations

import os
import time
import unittest
import uuid

from app.core.conversation_repository import PostgresConversationRepository


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


@unittest.skipUnless(DATABASE_URL, "DATABASE_URL is required for the PostgreSQL integration test")
class PostgresConversationRepositoryIntegrationTests(unittest.TestCase):
    """Exercise the real schema and a fresh repository instance in CI."""

    @classmethod
    def setUpClass(cls):
        cls.repository = PostgresConversationRepository(DATABASE_URL)

    def _message_count(self, conversation_id: str) -> int:
        import psycopg

        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM conversation_messages WHERE conversation_id = %s",
                    (conversation_id,),
                )
                return int(cursor.fetchone()[0])

    def _workspace_count(self, conversation_id: str) -> tuple[int, int]:
        import psycopg

        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT project_id FROM project_workspaces WHERE conversation_id = %s", (conversation_id,))
                row = cursor.fetchone()
                if row is None:
                    return (0, 0)
                cursor.execute("SELECT COUNT(*) FROM project_files WHERE project_id = %s", (row[0],))
                return (1, int(cursor.fetchone()[0]))

    def test_roundtrip_reopens_with_metadata_and_cascades_messages(self):
        conversation_id = f"chat_ci_pg_{uuid.uuid4().hex}"
        source = {
            "filename": "routes.py",
            "relative_path": "api/routes.py",
            "source_id": "ctx_0123456789abcdef",
            "format": "py",
            "parser": "utf-8-text-v1",
            "char_count": 13,
            "byte_count": 13,
            "line_count": 1,
        }
        now = int(time.time())
        record = {
            "conversation_id": conversation_id,
            "title": "CI PostgreSQL roundtrip",
            "created_at": now,
            "updated_at": now + 1,
            "provider": "fake",
            "model": "fake-research-v2",
            "processing_mode": "DIRECT",
            "status": "completed",
            "context": "route context",
            "context_sources": [source],
            "run_ids": ["run_ci_pg"],
            "messages": [
                {
                    "role": "user",
                    "content": "Where is the route?",
                    "run_id": "run_ci_pg",
                    "created_at": now,
                    "context_sources": [source],
                },
                {
                    "role": "assistant",
                    "content": "It is in api/routes.py.",
                    "run_id": "run_ci_pg",
                    "created_at": now + 1,
                    "status": "completed",
                    "provider": "fake",
                    "model": "fake-research-v2",
                    "mode": "DIRECT",
                },
            ],
        }

        try:
            self.repository.write(record)
            reopened = PostgresConversationRepository(DATABASE_URL)
            loaded = reopened.read(conversation_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["conversation_id"], conversation_id)
            self.assertEqual(loaded["provider"], "fake")
            self.assertEqual(loaded["model"], "fake-research-v2")
            self.assertEqual(loaded["processing_mode"], "DIRECT")
            self.assertEqual(loaded["status"], "completed")
            self.assertEqual(
                [message["content"] for message in loaded["messages"]],
                ["Where is the route?", "It is in api/routes.py."],
            )
            self.assertEqual(
                loaded["context_sources"][0]["relative_path"],
                "api/routes.py",
            )
            self.assertEqual(
                loaded["messages"][0]["context_sources"][0]["relative_path"],
                "api/routes.py",
            )
            self.assertEqual(self._message_count(conversation_id), 2)

            self.assertTrue(reopened.delete(conversation_id))
            self.assertIsNone(reopened.read(conversation_id))
            self.assertEqual(self._message_count(conversation_id), 0)
            self.assertFalse(reopened.delete(conversation_id))
        finally:
            # Keep cleanup scoped to this test's unique conversation ID.
            self.repository.delete(conversation_id)

    def test_workspace_roundtrip_is_metadata_only_until_project_retrieval_and_cascades(self):
        conversation_id = f"chat_ci_workspace_{uuid.uuid4().hex}"
        workspace = {
            "name": "ci-project",
            "files": [
                {"filename": "routes.py", "relative_path": "api/routes.py", "content": "def result_route(): return app"},
                {"filename": "routes.py", "relative_path": "admin/routes.py", "content": "def admin_route(): return admin"},
            ],
        }
        try:
            saved = self.repository.save_project_workspace(conversation_id, workspace)
            public = PostgresConversationRepository(DATABASE_URL).get_project_workspace(conversation_id)
            loaded = self.repository.get_project_workspace(conversation_id, include_content=True)
            self.assertEqual(saved["file_count"], 2)
            self.assertEqual([item["relative_path"] for item in public["files"]], ["admin/routes.py", "api/routes.py"])
            self.assertTrue(all("content" not in item for item in public["files"]))
            self.assertEqual(loaded["files"][1]["content"], "def result_route(): return app")
            self.assertEqual(self._workspace_count(conversation_id), (1, 2))
            self.assertTrue(self.repository.delete(conversation_id))
            self.assertEqual(self._workspace_count(conversation_id), (0, 0))
        finally:
            self.repository.delete(conversation_id)


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

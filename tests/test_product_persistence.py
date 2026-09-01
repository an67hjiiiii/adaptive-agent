from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main_module


class ProductConversationPersistenceTests(unittest.TestCase):
    """Focused local-storage contract tests; no provider APIs are used."""

    def setUp(self):
        self.client = TestClient(main_module.app)

    @staticmethod
    def _conversation(conversation_id: str, title: str, *, run_ids=None):
        return {
            "conversation_id": conversation_id,
            "title": title,
            "created_at": 1,
            "updated_at": 2,
            "provider": "fake",
            "model": "fake-research-v2",
            "status": "completed",
            "messages": [
                {
                    "conversation_id": conversation_id,
                    "role": "user",
                    "content": f"Question for {title}",
                    "created_at": 1,
                    "run_id": (run_ids or [None])[0],
                },
                {
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "content": f"Answer for {title}",
                    "created_at": 2,
                    "run_id": (run_ids or [None])[0],
                    "status": "completed",
                    "mode": "DIRECT",
                    "metrics": {},
                },
            ],
            "run_ids": list(run_ids or []),
        }

    def test_create_store_message_and_reopen_preserves_identity_and_fields(self):
        async def fake_execute_once(**kwargs):
            data = {
                "run_id": "run_product_1",
                "provider": "fake",
                "model": "fake-research-v2",
                "answer": "Stored answer",
                "status": "completed",
                "stop_reason": "STOP_SUFFICIENT",
                "metrics": {"logical_calls": 1},
            }
            await kwargs["emit"]({
                "type": "final",
                "answer": data["answer"],
                "status": data["status"],
                "stop_reason": data["stop_reason"],
                "metrics": data["metrics"],
                "run_id": data["run_id"],
                "conversation_id": kwargs["conversation_id"],
                "provider": data["provider"],
                "model": data["model"],
            })
            return data

        with tempfile.TemporaryDirectory() as temp_dir:
            runs = Path(temp_dir)
            conversations = runs / "conversations"
            conversations.mkdir()
            with (
                patch.object(main_module, "RUNS", runs),
                patch.object(main_module, "CONVERSATIONS", conversations),
                patch.object(main_module, "execute_once", new=fake_execute_once),
            ):
                response = self.client.post(
                    "/api/chat/stream",
                    json={"message": "Persist this", "context": "local reference", "provider": "fake"},
                )
                self.assertEqual(response.status_code, 200)
                events = [json.loads(line) for line in response.text.splitlines() if line]
                final = next(event for event in events if event["type"] == "final")
                conversation_id = final["conversation_id"]
                stored_path = conversations / f"{conversation_id}.json"
                self.assertTrue(stored_path.exists())
                stored = json.loads(stored_path.read_text(encoding="utf-8"))

                self.assertEqual(stored["conversation_id"], conversation_id)
                self.assertEqual(stored["title"], "Persist this")
                self.assertIsInstance(stored["created_at"], int)
                self.assertIsInstance(stored["updated_at"], int)
                self.assertEqual(stored["run_ids"], ["run_product_1"])
                self.assertEqual([item["role"] for item in stored["messages"]], ["user", "assistant"])
                self.assertTrue(all(item["conversation_id"] == conversation_id for item in stored["messages"]))
                self.assertTrue(all(isinstance(item["created_at"], int) for item in stored["messages"]))

                # API reload uses the backend record and keeps the same ID.
                first_open = self.client.get(f"/api/conversations/{conversation_id}").json()
                second_open = self.client.get(f"/api/conversations/{conversation_id}").json()
                self.assertEqual(first_open["conversation_id"], conversation_id)
                self.assertEqual(second_open["messages"], first_open["messages"])
                listed_after_create = self.client.get("/api/conversations?limit=10").json()["conversations"]
                self.assertEqual([item["conversation_id"] for item in listed_after_create], [conversation_id])

            # A fresh repository/process view can reopen the same on-disk record.
            with patch.object(main_module, "CONVERSATIONS", conversations):
                reopened = main_module.read_conversation(conversation_id)
            self.assertEqual(reopened["conversation_id"], conversation_id)
            self.assertEqual(reopened["messages"][1]["content"], "Stored answer")

    def test_list_rename_search_delete_and_unrelated_run_survival(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runs = Path(temp_dir)
            conversations = runs / "conversations"
            conversations.mkdir()
            first_id = "chat_product_first"
            second_id = "chat_product_second"
            first = self._conversation(first_id, "Original title", run_ids=["run_product"])
            second = self._conversation(second_id, "Another title")
            with patch.object(main_module, "RUNS", runs), patch.object(main_module, "CONVERSATIONS", conversations):
                main_module.write_conversation(first)
                main_module.write_conversation(second)
                (runs / "run_product.json").write_text("{}", encoding="utf-8")
                unrelated = runs / "run_unrelated_research.json"
                unrelated.write_text("{}", encoding="utf-8")

                listed = self.client.get("/api/conversations?limit=10")
                self.assertEqual(listed.status_code, 200)
                listed_ids = {row["conversation_id"] for row in listed.json()["conversations"]}
                self.assertEqual(listed_ids, {first_id, second_id})

                renamed = self.client.patch(
                    f"/api/conversations/{first_id}",
                    json={"title": "Renamed product conversation"},
                )
                self.assertEqual(renamed.status_code, 200)
                self.assertEqual(renamed.json()["conversation_id"], first_id)
                self.assertEqual(renamed.json()["title"], "Renamed product conversation")

                refreshed = self.client.get("/api/conversations?limit=10").json()["conversations"]
                row = next(item for item in refreshed if item["conversation_id"] == first_id)
                self.assertEqual(row["title"], "Renamed product conversation")
                self.assertNotIn("Original title", {item["title"] for item in refreshed})
                # This mirrors the UI's client-side search over loaded metadata.
                matches = [
                    item for item in refreshed
                    if "renamed product" in f"{item['title']} {item['last_preview']}".casefold()
                ]
                self.assertEqual([item["conversation_id"] for item in matches], [first_id])

                deleted = self.client.delete(f"/api/conversations/{first_id}")
                self.assertEqual(deleted.status_code, 200)
                self.assertEqual(
                    self.client.get("/api/conversations?limit=10").json()["conversations"],
                    [item for item in refreshed if item["conversation_id"] != first_id],
                )
                self.assertEqual(self.client.get(f"/api/conversations/{first_id}").status_code, 404)
                self.assertFalse((conversations / f"{first_id}.json").exists())
                self.assertFalse((runs / "run_product.json").exists())
                self.assertTrue(unrelated.exists())

    def test_blank_rename_is_rejected_without_corrupting_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            conversations = Path(temp_dir) / "conversations"
            conversations.mkdir()
            conversation_id = "chat_blank_title"
            with patch.object(main_module, "CONVERSATIONS", conversations):
                main_module.write_conversation(self._conversation(conversation_id, "Keep this title"))
                response = self.client.patch(
                    f"/api/conversations/{conversation_id}",
                    json={"title": "   "},
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(main_module.read_conversation(conversation_id)["title"], "Keep this title")


if __name__ == "__main__":
    unittest.main()

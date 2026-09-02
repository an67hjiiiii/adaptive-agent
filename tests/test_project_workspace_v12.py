from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.main as main_module
from app.core.conversation_repository import JsonConversationRepository
from app.core.rag import frozen_snapshot
from fastapi.testclient import TestClient


def workspace_files():
    return [
        {"filename": "routes.py", "relative_path": "api/routes.py", "content": "def result_route(): return app"},
        {"filename": "routes.py", "relative_path": "admin/routes.py", "content": "def admin_route(): return admin"},
        {"filename": "main.py", "relative_path": "app/main.py", "content": "from api.routes import result_route"},
    ]


class ProjectWorkspaceJsonTests(unittest.TestCase):
    def test_workspace_roundtrip_metadata_is_lightweight_and_content_is_retrievable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConversationRepository(Path(temp_dir))
            saved = repository.save_project_workspace("chat_workspace_one", {"name": "demo-project", "files": workspace_files()})
            public = repository.get_project_workspace("chat_workspace_one")
            loaded = repository.get_project_workspace("chat_workspace_one", include_content=True)
        self.assertEqual(saved["file_count"], 3)
        self.assertEqual([item["relative_path"] for item in public["files"]], ["admin/routes.py", "api/routes.py", "app/main.py"])
        self.assertTrue(all("content" not in item for item in public["files"]))
        self.assertEqual(loaded["files"][1]["content"], "def result_route(): return app")

    def test_workspace_isolation_detach_and_unsafe_path_rejection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConversationRepository(Path(temp_dir))
            repository.save_project_workspace("chat_workspace_a", {"name": "project-a", "files": workspace_files()})
            self.assertIsNone(repository.get_project_workspace("chat_workspace_b"))
            self.assertTrue(repository.detach_project_workspace("chat_workspace_a"))
            self.assertIsNone(repository.get_project_workspace("chat_workspace_a"))
            with self.assertRaises(ValueError):
                repository.save_project_workspace("chat_workspace_bad", {"name": "bad", "files": [
                    {"filename": "routes.py", "relative_path": "C:\\private\\routes.py", "content": "x"},
                ]})

    def test_twenty_file_limit_and_legacy_conversation_compatibility(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConversationRepository(Path(temp_dir))
            files = [{"filename": f"file_{index}.py", "relative_path": f"src/file_{index}.py", "content": "pass"} for index in range(20)]
            self.assertEqual(repository.save_project_workspace("chat_workspace_twenty", {"name": "twenty", "files": files})["file_count"], 20)
            with self.assertRaises(ValueError):
                repository.save_project_workspace("chat_workspace_many", {"name": "many", "files": files + [{"filename": "extra.py", "relative_path": "src/extra.py", "content": "pass"}]})
            repository.write({"conversation_id": "chat_workspace_legacy", "title": "legacy", "created_at": 1, "messages": [], "run_ids": []})
            self.assertIsNone(repository.get_project_workspace("chat_workspace_legacy"))


class ProjectWorkspaceRuntimeContractTests(unittest.TestCase):
    def test_relevance_gate_keeps_greetings_general_chat_and_auto_separate(self):
        self.assertFalse(main_module.project_relevance_gate("hi", []))
        self.assertFalse(main_module.project_relevance_gate("nói tiếng Việt đi", []))
        self.assertFalse(main_module.project_relevance_gate("2 + 2", []))
        self.assertTrue(main_module.project_relevance_gate("entry point nằm ở file nào?", []))
        self.assertTrue(main_module.project_relevance_gate("route đó gọi gì?", [{"content": "project route api/routes.py"}]))

    def test_project_context_uses_path_aware_rag_and_records_selected_paths(self):
        workspace = {
            "files": [
                {"relative_path": "api/routes.py", "source": {"filename": "routes.py", "relative_path": "api/routes.py"}, "content": "def result_route(): return app"},
                {"relative_path": "admin/routes.py", "source": {"filename": "routes.py", "relative_path": "admin/routes.py"}, "content": "def admin_route(): return admin"},
            ]
        }
        snapshot, meta = frozen_snapshot("route result ở đâu", main_module.workspace_context(workspace))
        selected = main_module.workspace_selected_sources(workspace, meta)
        self.assertIn("[PROJECT STRUCTURE]", snapshot)
        self.assertIn("api/routes.py", [item["relative_path"] for item in selected])
        self.assertNotIn("content", main_module.workspace_selected_sources(workspace, meta)[0])


class ProjectWorkspaceChatIsolationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def test_only_relevant_turns_receive_workspace_context(self):
        captured = []

        async def fake_execute_once(**kwargs):
            captured.append(kwargs)
            data = {
                "run_id": f"run_workspace_{len(captured)}", "provider": "fake", "model": "fake-research-v2",
                "answer": "offline", "status": "completed", "stop_reason": "STOP_SUFFICIENT", "metrics": {},
                "processing_mode": kwargs["mode"], "events": [],
            }
            await kwargs["emit"]({
                "type": "final", "answer": data["answer"], "status": data["status"],
                "stop_reason": data["stop_reason"], "metrics": data["metrics"], "run_id": data["run_id"],
                "conversation_id": kwargs["conversation_id"], "provider": "fake", "model": "fake-research-v2",
                "processing_mode": kwargs["mode"],
            })
            return data

        with tempfile.TemporaryDirectory() as temp_dir:
            conversations = Path(temp_dir) / "conversations"
            conversations.mkdir()
            with (
                patch.object(main_module, "CONVERSATIONS", conversations),
                patch.object(main_module, "execute_once", new=fake_execute_once),
            ):
                main_module.conversation_repository().save_project_workspace(
                    "chat_workspace_chat", {"name": "demo", "files": workspace_files()},
                )
                for message in ("hi", "entry point nằm ở file nào?"):
                    response = self.client.post("/api/chat/stream", json={
                        "message": message, "provider": "fake", "conversation_id": "chat_workspace_chat",
                        "context_active": False,
                    })
                    self.assertEqual(response.status_code, 200)
        self.assertNotIn("[PROJECT STRUCTURE]", captured[0]["frozen_context"])
        self.assertIn("[PROJECT STRUCTURE]", captured[1]["frozen_context"])
        self.assertEqual(captured[1]["mode"], "adaptive-auto")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

import app.main as main_module
from app.core.conversation_repository import JsonConversationRepository
from app.core.rag import frozen_snapshot
from app.core.orchestrator import Orchestrator
from app.core.types import Budget, RunState
from app.providers.fake import FakeProvider
from fastapi.testclient import TestClient


def workspace_files():
    return [
        {"filename": "routes.py", "relative_path": "api/routes.py", "content": "def result_route(): return app"},
        {"filename": "routes.py", "relative_path": "admin/routes.py", "content": "def admin_route(): return admin"},
        {"filename": "main.py", "relative_path": "app/main.py", "content": "from api.routes import result_route"},
    ]


def web_dev_files():
    return [
        {"filename": "README.md", "relative_path": "README.md", "content": "web-dev-basics"},
        {"filename": "app.py", "relative_path": "app.py", "content": "from flask import Flask"},
        {"filename": "requirements.txt", "relative_path": "requirements.txt", "content": "flask"},
        {"filename": "index.html", "relative_path": "templates/index.html", "content": "<main>home</main>"},
        {"filename": "result.html", "relative_path": "templates/result.html", "content": "<main>result</main>"},
        {"filename": "style.css", "relative_path": "static/css/style.css", "content": "body {}"},
        {"filename": "script.js", "relative_path": "static/js/script.js", "content": "console.log('ok')"},
    ]


def long_project_history():
    history = []
    for index in range(8):
        history.extend([
            {"role": "user", "content": f"Project route {index} nằm ở file nào? " + "x" * 500},
            {"role": "assistant", "content": f"Project answer {index}: " + "y" * 1200},
        ])
    return history


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

    def test_web_dev_basics_seven_file_workspace_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConversationRepository(Path(temp_dir))
            saved = repository.save_project_workspace(
                "chat_workspace_web_dev", {"name": "web-dev-basics", "files": web_dev_files()},
            )
            loaded = repository.get_project_workspace("chat_workspace_web_dev")
        self.assertEqual(saved["file_count"], 7)
        self.assertEqual(saved["project_hash"], loaded["project_hash"])
        self.assertEqual(
            [item["relative_path"] for item in loaded["files"]],
            sorted(item["relative_path"] for item in web_dev_files()),
        )


class ProjectWorkspaceRuntimeContractTests(unittest.TestCase):
    def test_relevance_gate_keeps_greetings_general_chat_and_auto_separate(self):
        self.assertFalse(main_module.project_relevance_gate("hi", []))
        self.assertFalse(main_module.project_relevance_gate("nói tiếng Việt đi", []))
        self.assertFalse(main_module.project_relevance_gate("2 + 2", []))
        self.assertTrue(main_module.project_relevance_gate("entry point nằm ở file nào?", []))
        self.assertTrue(main_module.project_relevance_gate("route đó gọi gì?", [{"content": "project route api/routes.py"}]))

    def test_product_history_resets_greeting_but_keeps_explicit_language_preference(self):
        history = long_project_history()
        self.assertEqual(main_module.product_history_for_turn("hi", history), [])
        vietnamese = [{"role": "user", "content": "nói tiếng Việt đi"}, *history]
        selected = main_module.product_history_for_turn("hi", vietnamese)
        rendered = main_module.format_history(selected, max_chars=main_module._PRODUCT_HISTORY_MAX_CHARS)
        self.assertIn("nói tiếng Việt đi", rendered)
        self.assertNotIn("Project answer", rendered)
        self.assertLessEqual(len(rendered), main_module._PRODUCT_HISTORY_MAX_CHARS)
        self.assertFalse(main_module.project_relevance_gate("hi", selected))

    def test_product_history_uses_only_minimal_followup_context(self):
        history = long_project_history() + [
            {"role": "user", "content": "Route /result hoạt động thế nào?"},
            {"role": "assistant", "content": "Route /result render templates/result.html."},
        ]
        self_contained = main_module.product_history_for_turn("Project này dùng công nghệ gì?", history)
        self.assertNotIn("Project answer", main_module.format_history(self_contained))
        followup = main_module.product_history_for_turn("route đó render file nào?", history)
        rendered = main_module.format_history(followup, max_chars=main_module._PRODUCT_HISTORY_MAX_CHARS)
        self.assertIn("Route /result", rendered)
        self.assertNotIn("Project answer 7", rendered)
        self.assertLessEqual(len(rendered), main_module._PRODUCT_HISTORY_MAX_CHARS)
        self.assertTrue(main_module.project_relevance_gate("route đó render file nào?", followup))
        generic = main_module.product_history_for_turn("giải thích rõ hơn phần trên", history)
        self.assertIn("Route /result", main_module.format_history(generic))

    def test_product_auto_greeting_uses_direct_solver_and_verifier_without_analyzer(self):
        async def execute():
            async def emit(_event):
                return None
            state = RunState(strategy="adaptive", provider="fake", model="fake-research-v2", task="hi", context="")
            orchestrator = Orchestrator(FakeProvider(), emit, budget=Budget(), product_auto=True)
            await orchestrator.run(state)
            return state
        state = asyncio.run(execute())
        route = next(event for event in state.events if event["title"] == "AUTO route selected")
        self.assertEqual(route["meta"]["mode"], "DIRECT")
        self.assertFalse(any(event.get("title") == "Analyzer" for event in state.events))
        self.assertEqual(state.stop_reason, "STOP_SUFFICIENT")

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
                "sources": kwargs["retrieval_meta"].get("attached_sources", []),
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

    def test_workspace_sources_are_assistant_evidence_not_user_attachments(self):
        captured = []

        async def fake_execute_once(**kwargs):
            captured.append(kwargs)
            return {
                "run_id": f"run_source_{len(captured)}", "provider": "fake", "model": "fake-research-v2",
                "answer": "offline", "status": "completed", "stop_reason": "STOP_SUFFICIENT", "metrics": {},
                "processing_mode": kwargs["mode"], "events": [],
                "sources": kwargs["retrieval_meta"].get("attached_sources", []),
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            conversations = Path(temp_dir) / "conversations"
            conversations.mkdir()
            draft_source = {"filename": "note.md", "relative_path": "note.md", "source_id": "ctx_1234567890abcdef"}
            with (
                patch.object(main_module, "CONVERSATIONS", conversations),
                patch.object(main_module, "execute_once", new=fake_execute_once),
            ):
                main_module.conversation_repository().save_project_workspace(
                    "chat_workspace_sources", {"name": "demo", "files": workspace_files()},
                )
                first = self.client.post("/api/chat/stream", json={
                    "message": "ghi nhớ tệp này", "provider": "fake", "conversation_id": "chat_workspace_sources",
                    "context": "draft note", "context_sources": [draft_source],
                })
                self.assertEqual(first.status_code, 200)
                second = self.client.post("/api/chat/stream", json={
                    "message": "entry point nằm ở file nào?", "provider": "fake", "conversation_id": "chat_workspace_sources",
                    "context_active": False,
                })
                self.assertEqual(second.status_code, 200)
                conversation = self.client.get("/api/conversations/chat_workspace_sources").json()
        users = [item for item in conversation["messages"] if item["role"] == "user"]
        assistants = [item for item in conversation["messages"] if item["role"] == "assistant"]
        self.assertEqual(users[0]["context_sources"][0]["filename"], draft_source["filename"])
        self.assertEqual(users[0]["context_sources"][0]["relative_path"], draft_source["relative_path"])
        self.assertEqual(users[1]["context_sources"], [])
        self.assertIn("api/routes.py", [item.get("relative_path") for item in assistants[1]["sources"]])
        self.assertIn("[PROJECT STRUCTURE]", captured[1]["frozen_context"])


if __name__ == "__main__":
    unittest.main()

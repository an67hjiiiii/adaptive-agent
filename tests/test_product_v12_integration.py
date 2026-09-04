from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main_module


def workspace_files():
    return [
        {"filename": "README.md", "relative_path": "README.md", "content": "web-dev-basics Flask project."},
        {"filename": "main.py", "relative_path": "app/main.py", "content": "def main(): return create_app()"},
        {"filename": "requirements.txt", "relative_path": "requirements.txt", "content": "flask"},
    ]


def events(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def capture_executor(calls):
    async def execute(**kwargs):
        calls.append(kwargs)
        scope = kwargs["grounding_scope"]
        task = kwargs["message"].casefold()
        answer = (
            "INSUFFICIENT SOURCE EVIDENCE"
            if scope == "SOURCE_REQUIRED" and "database" in task
            else "GENERAL ANSWER" if scope == "GENERAL" else "SOURCE ANSWER"
        )
        sources = kwargs["retrieval_meta"].get("attached_sources", [])
        result = {
            "run_id": f"run_v12_integration_{len(calls)}", "provider": "fake", "model": "fake-research-v2",
            "answer": answer, "status": "completed", "stop_reason": "STOP_SUFFICIENT", "metrics": {},
            "processing_mode": kwargs["mode"], "events": [], "sources": sources,
        }
        await kwargs["emit"]({
            "type": "final", "answer": answer, "status": result["status"], "stop_reason": result["stop_reason"],
            "metrics": {}, "run_id": result["run_id"], "conversation_id": kwargs["conversation_id"],
            "provider": "fake", "model": "fake-research-v2", "processing_mode": kwargs["mode"],
            "sources": sources,
        })
        return result
    return execute


class ProductV12IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def _sandbox(self, calls):
        temp_dir = tempfile.TemporaryDirectory()
        runs = Path(temp_dir.name) / "runs"
        conversations = runs / "conversations"
        conversations.mkdir(parents=True)
        return temp_dir, (
            patch.object(main_module, "RUNS", runs),
            patch.object(main_module, "CONVERSATIONS", conversations),
            patch.object(main_module, "execute_once", new=capture_executor(calls)),
        )

    def _chat(self, message, conversation_id=None, **extra):
        payload = {"message": message, "provider": "fake", **extra}
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        response = self.client.post("/api/chat/stream", json=payload)
        self.assertEqual(response.status_code, 200)
        return next(event for event in events(response) if event["type"] == "final")

    def test_general_without_project_has_general_scope_and_no_source_abstention(self):
        calls = []
        temp_dir, patches = self._sandbox(calls)
        try:
            with patches[0], patches[1], patches[2]:
                self.assertEqual(
                    self.client.post("/api/chat/stream", json={"message": "   ", "provider": "fake"}).status_code,
                    422,
                )
                final = self._chat("aeon mall đà nẵng mới mở ở đâu")
        finally:
            temp_dir.cleanup()
        self.assertEqual(calls[0]["grounding_scope"], "GENERAL")
        self.assertEqual(final["answer"], "GENERAL ANSWER")
        self.assertNotIn("[PROJECT STRUCTURE]", calls[0]["frozen_context"])

    def test_active_project_survives_general_then_project_and_missing_evidence(self):
        calls = []
        conversation_id = "chat_v12_lifecycle"
        temp_dir, patches = self._sandbox(calls)
        try:
            with patches[0], patches[1], patches[2]:
                main_module.conversation_repository().save_project_workspace(
                    conversation_id, {"name": "web-dev-basics", "files": workspace_files()},
                )
                general = self._chat("thời tiết hôm nay thế nào?", conversation_id, context_active=False)
                self.assertIsNotNone(main_module.get_project_workspace(conversation_id))
                project = self._chat("Entry point của project này nằm ở đâu?", conversation_id, context_active=False)
                missing = self._chat(
                    "Database của project này dùng MySQL hay PostgreSQL?", conversation_id, context_active=False,
                )
        finally:
            temp_dir.cleanup()
        self.assertEqual(general["answer"], "GENERAL ANSWER")
        self.assertEqual(project["answer"], "SOURCE ANSWER")
        self.assertEqual(missing["answer"], "INSUFFICIENT SOURCE EVIDENCE")
        self.assertEqual([call["grounding_scope"] for call in calls], ["GENERAL", "SOURCE_REQUIRED", "SOURCE_REQUIRED"])
        self.assertNotIn("[PROJECT STRUCTURE]", calls[0]["frozen_context"])
        self.assertIn("[PROJECT STRUCTURE]", calls[1]["frozen_context"])
        self.assertIn("app/main.py", calls[1]["retrieval_meta"]["project_workspace"]["selected_relative_paths"])

    def test_explicit_source_detach_new_chat_and_normal_attachment_are_isolated(self):
        calls = []
        conversation_id = "chat_v12_detach"
        temp_dir, patches = self._sandbox(calls)
        try:
            with patches[0], patches[1], patches[2]:
                main_module.conversation_repository().save_project_workspace(
                    conversation_id, {"name": "web-dev-basics", "files": workspace_files()},
                )
                explicit = self._chat("Dựa vào README.md, project này làm gì?", conversation_id, context_active=False)
                self.assertEqual(explicit["answer"], "SOURCE ANSWER")
                self.assertEqual(self.client.delete(f"/api/conversations/{conversation_id}/project-workspace").status_code, 200)
                detached = self._chat("Entry point của project này nằm ở đâu?", conversation_id, context_active=False)
                prepared = self.client.post("/api/context/prepare", json={"filename": "notes.txt", "content": "A local note."})
                self.assertEqual(prepared.status_code, 200)
                new_chat = self._chat(
                    "Dựa vào notes.txt, hãy tóm tắt.",
                    context=prepared.json()["text"], context_active=True,
                    context_sources=[prepared.json()["source"]],
                )
        finally:
            temp_dir.cleanup()
        self.assertEqual(detached["answer"], "SOURCE ANSWER")
        self.assertNotIn("project_workspace", calls[1]["retrieval_meta"])
        self.assertEqual(calls[2]["grounding_scope"], "SOURCE_REQUIRED")
        self.assertNotIn("project_workspace", calls[2]["retrieval_meta"])
        self.assertEqual(calls[2]["retrieval_meta"]["attached_sources"][0]["filename"], "notes.txt")
        self.assertTrue(new_chat["conversation_id"] != conversation_id)

    def test_active_project_ui_uses_v39_indicator_and_new_chat_reset_contract(self):
        root = Path(main_module.__file__).resolve().parent / "static"
        html = (root / "index.html").read_text(encoding="utf-8")
        js = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn('styles.css?v=39', html)
        self.assertIn('app.js?v=39', html)
        indicator = js.split("function renderProjectWorkspaceIndicator", 1)[1].split("function sourceIsExternal", 1)[0]
        new_chat = js.split("function newConversation", 1)[1].split("function setContextOpen", 1)[0]
        self.assertIn("Đang dùng", indicator)
        self.assertIn("projectWorkspace=null", new_chat)


if __name__ == "__main__":
    unittest.main()

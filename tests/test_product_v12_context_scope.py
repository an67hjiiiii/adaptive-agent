from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main_module
from app.core.types import ProviderResult, Usage


def workspace_files():
    return [
        {"filename": "README.md", "relative_path": "README.md", "content": "web-dev-basics Flask project."},
        {"filename": "main.py", "relative_path": "app/main.py", "content": "def main(): return create_app()"},
        {"filename": "requirements.txt", "relative_path": "requirements.txt", "content": "flask"},
    ]


def stream_events(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def capture_executor(calls):
    async def execute(**kwargs):
        calls.append(kwargs)
        sources = kwargs["retrieval_meta"].get("attached_sources", [])
        result = {
            "run_id": f"run_scope_{len(calls)}", "provider": "fake", "model": "fake-research-v2",
            "answer": "offline scope result", "status": "completed", "stop_reason": "STOP_SUFFICIENT",
            "metrics": {}, "processing_mode": kwargs["mode"], "events": [], "sources": sources,
        }
        await kwargs["emit"]({
            "type": "final", "answer": result["answer"], "status": result["status"],
            "stop_reason": result["stop_reason"], "metrics": result["metrics"], "run_id": result["run_id"],
            "conversation_id": kwargs["conversation_id"], "provider": result["provider"],
            "model": result["model"], "processing_mode": result["processing_mode"], "sources": sources,
        })
        return result
    return execute


class ScopeAwareFakeProvider:
    name = "fake"
    model = "fake-research-v2"

    def __init__(self):
        self.calls = []

    async def generate(self, *, system, user):
        self.calls.append({"system": system, "user": user})
        if "Runtime Verifier" in system:
            text = json.dumps({"status": "PASS", "issues": [], "rationale": "bounded test"})
        elif "normal model knowledge" in system:
            text = "GENERAL ANSWER"
        elif "database" in user.lower():
            text = "INSUFFICIENT SOURCE EVIDENCE"
        else:
            text = "SOURCE ANSWER"
        return ProviderResult(text=text, usage=Usage(1, 1), model=self.model)


class ProductV12ContextScopeTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def _with_workspace(self, conversation_id, calls):
        temp_dir = tempfile.TemporaryDirectory()
        conversations = Path(temp_dir.name) / "conversations"
        conversations.mkdir()
        patches = (
            patch.object(main_module, "CONVERSATIONS", conversations),
            patch.object(main_module, "execute_once", new=capture_executor(calls)),
        )
        return temp_dir, conversations, patches

    def test_no_active_project_general_chat_is_not_source_required(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            conversations = Path(temp_dir) / "conversations"
            conversations.mkdir()
            with (
                patch.object(main_module, "CONVERSATIONS", conversations),
                patch.object(main_module, "execute_once", new=capture_executor(calls)),
            ):
                response = self.client.post("/api/chat/stream", json={
                    "message": "aeon mall đà nẵng mới mở ở đâu", "provider": "fake",
                })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls[0]["grounding_scope"], "GENERAL")
        self.assertEqual(calls[0]["retrieval_meta"]["context_scope"], "GENERAL")

    def test_active_project_unrelated_general_chat_bypasses_workspace(self):
        calls = []
        temp_dir, _conversations, patches = self._with_workspace("chat_scope_general", calls)
        try:
            with patches[0], patches[1]:
                main_module.conversation_repository().save_project_workspace(
                    "chat_scope_general", {"name": "web-dev-basics", "files": workspace_files()},
                )
                response = self.client.post("/api/chat/stream", json={
                    "message": "aeon mall đà nẵng mới mở ở đâu", "provider": "fake",
                    "conversation_id": "chat_scope_general", "context_active": False,
                })
        finally:
            temp_dir.cleanup()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls[0]["grounding_scope"], "GENERAL")
        self.assertNotIn("[PROJECT STRUCTURE]", calls[0]["frozen_context"])
        self.assertNotIn("project_workspace", calls[0]["retrieval_meta"])

    def test_project_question_and_missing_evidence_remain_source_required(self):
        calls = []
        temp_dir, _conversations, patches = self._with_workspace("chat_scope_project", calls)
        try:
            with patches[0], patches[1]:
                main_module.conversation_repository().save_project_workspace(
                    "chat_scope_project", {"name": "web-dev-basics", "files": workspace_files()},
                )
                for message in (
                    "Entry point của project này nằm đâu?",
                    "Database của project này dùng MySQL hay PostgreSQL?",
                ):
                    response = self.client.post("/api/chat/stream", json={
                        "message": message, "provider": "fake", "conversation_id": "chat_scope_project",
                        "context_active": False,
                    })
                    self.assertEqual(response.status_code, 200)
        finally:
            temp_dir.cleanup()
        self.assertEqual([call["grounding_scope"] for call in calls], ["SOURCE_REQUIRED", "SOURCE_REQUIRED"])
        self.assertTrue(all("[PROJECT STRUCTURE]" in call["frozen_context"] for call in calls))
        self.assertIn("app/main.py", calls[0]["retrieval_meta"]["project_workspace"]["selected_relative_paths"])

    def test_explicit_source_request_is_required_and_general_turn_keeps_project(self):
        calls = []
        temp_dir, _conversations, patches = self._with_workspace("chat_scope_followup", calls)
        try:
            with patches[0], patches[1]:
                main_module.conversation_repository().save_project_workspace(
                    "chat_scope_followup", {"name": "web-dev-basics", "files": workspace_files()},
                )
                for message in (
                    "Dựa vào README, project này dùng framework gì?",
                    "thời tiết hôm nay thế nào?",
                    "Entry point của project này nằm đâu?",
                    "cái này hoạt động sao?",
                ):
                    response = self.client.post("/api/chat/stream", json={
                        "message": message, "provider": "fake", "conversation_id": "chat_scope_followup",
                        "context_active": False,
                    })
                    self.assertEqual(response.status_code, 200)
        finally:
            temp_dir.cleanup()
        self.assertEqual(
            [call["grounding_scope"] for call in calls],
            ["SOURCE_REQUIRED", "GENERAL", "SOURCE_REQUIRED", "SOURCE_REQUIRED"],
        )
        self.assertNotIn("[PROJECT STRUCTURE]", calls[1]["frozen_context"])
        self.assertIn("[PROJECT STRUCTURE]", calls[2]["frozen_context"])
        self.assertIn("[PROJECT STRUCTURE]", calls[3]["frozen_context"])

    def test_general_scope_changes_prompt_policy_without_extra_classifier_call(self):
        provider = ScopeAwareFakeProvider()

        async def emit(_event):
            return None

        async def run(scope, task, context=""):
            with patch.object(main_module, "get_provider", return_value=provider):
                return await main_module.execute_once(
                    strategy="adaptive", provider_name="fake", model_name="fake-research-v2", mode="direct",
                    message=task, frozen_context=context, retrieval_meta={"context_scope": scope}, history=[],
                    emit=emit, grounding_scope=scope,
                )

        general = asyncio.run(run("GENERAL", "aeon mall đà nẵng mới mở ở đâu"))
        source_required = asyncio.run(run(
            "SOURCE_REQUIRED", "Database của project này dùng MySQL hay PostgreSQL?",
            "SOURCE: app/main.py\ndef main(): return create_app()",
        ))
        self.assertEqual(general["answer"], "GENERAL ANSWER")
        self.assertEqual(source_required["answer"], "INSUFFICIENT SOURCE EVIDENCE")
        self.assertEqual(len(provider.calls), 4)  # direct solver + verifier for each run only
        self.assertIn("normal model knowledge", provider.calls[0]["system"])
        self.assertIn("only the frozen reference context", provider.calls[2]["system"])


if __name__ == "__main__":
    unittest.main()

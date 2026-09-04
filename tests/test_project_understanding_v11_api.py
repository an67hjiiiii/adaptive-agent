from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main_module


def stream_events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def capture_executor(calls: list[dict]):
    async def fake_execute_once(**kwargs):
        calls.append(kwargs)
        sources = kwargs["retrieval_meta"].get("attached_sources", [])
        run_id = f"run_v11_c_{len(calls)}"
        result = {
            "run_id": run_id,
            "strategy": "adaptive",
            "provider": "fake",
            "model": "fake-research-v2",
            "processing_mode": kwargs["mode"],
            "answer": "offline wiring result",
            "status": "completed",
            "stop_reason": "STOP_SUFFICIENT",
            "metrics": {},
            "events": [],
            "sources": sources,
        }
        await kwargs["emit"]({
            "type": "final",
            "answer": result["answer"],
            "status": result["status"],
            "stop_reason": result["stop_reason"],
            "metrics": result["metrics"],
            "run_id": run_id,
            "conversation_id": kwargs["conversation_id"],
            "provider": result["provider"],
            "model": result["model"],
            "processing_mode": result["processing_mode"],
            "sources": sources,
        })
        return result

    return fake_execute_once


class ProjectContextApiWiringTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def test_nested_project_context_is_canonicalized_by_rag_and_preserves_sources(self):
        calls: list[dict] = []
        project_files = []
        for filename, relative_path, content in (
            ("routes.py", "api/routes.py", "def customer_route(): return customer_service()"),
            ("routes.py", "admin/routes.py", "def admin_route(): return admin_service()"),
        ):
            prepared = self.client.post(
                "/api/context/prepare",
                json={"filename": filename, "relative_path": relative_path, "content": content},
            )
            self.assertEqual(prepared.status_code, 200)
            payload = prepared.json()
            project_files.append({
                "filename": payload["source"]["filename"],
                "relative_path": payload["source"]["relative_path"],
                "content": payload["text"],
            })

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "runs"
            conversation_dir = run_dir / "conversations"
            conversation_dir.mkdir(parents=True)
            with (
                patch.object(main_module, "RUNS", run_dir),
                patch.object(main_module, "CONVERSATIONS", conversation_dir),
                patch.object(main_module, "execute_once", new=capture_executor(calls)),
            ):
                saved = self.client.post(
                    "/api/conversations/project-workspace",
                    json={"name": "demo", "files": project_files},
                )
                self.assertEqual(saved.status_code, 200)
                conversation_id = saved.json()["conversation_id"]
                workspace = main_module.get_project_workspace(conversation_id, include_content=True)
                raw_handoff = main_module.workspace_context(workspace)
                self.assertTrue(raw_handoff.startswith("[PROJECT STRUCTURE]\n\n\n[RETRIEVED CONTEXT]\n\n"))

                response = self.client.post(
                    "/api/chat/stream",
                    json={
                        "message": "customer route nằm file nào?",
                        "provider": "fake",
                        "conversation_id": conversation_id,
                        "context_active": False,
                    },
                )
                self.assertEqual(response.status_code, 200)

        self.assertEqual(len(calls), 1)
        handoff = calls[0]
        self.assertIn("[PROJECT STRUCTURE]\nadmin/routes.py\napi/routes.py", handoff["frozen_context"])
        self.assertNotIn("C:\\", handoff["frozen_context"])
        self.assertNotIn("/home/", handoff["frozen_context"])
        self.assertEqual(handoff["retrieval_meta"]["retrieval_settings_version"], "RAG-LEXICAL-V1@1.2")
        selected_paths = handoff["retrieval_meta"]["project_workspace"]["selected_relative_paths"]
        self.assertIn("api/routes.py", selected_paths)
        final = next(event for event in stream_events(response) if event["type"] == "final")
        self.assertIn("api/routes.py", [source.get("relative_path") for source in final["sources"]])

    def test_flat_prepared_source_keeps_the_normal_attachment_contract(self):
        prepared_response = self.client.post(
            "/api/context/prepare",
            json={"filename": "notes.txt", "content": "ordinary flat attachment"},
        )
        self.assertEqual(prepared_response.status_code, 200)
        prepared = prepared_response.json()
        calls: list[dict] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "runs"
            conversation_dir = run_dir / "conversations"
            conversation_dir.mkdir(parents=True)
            with (
                patch.object(main_module, "RUNS", run_dir),
                patch.object(main_module, "CONVERSATIONS", conversation_dir),
                patch.object(main_module, "execute_once", new=capture_executor(calls)),
            ):
                response = self.client.post(
                    "/api/chat/stream",
                    json={
                        "message": "Summarize the attached note.",
                        "context": f"===== notes.txt =====\n{prepared['text']}",
                        "context_active": True,
                        "context_sources": [prepared["source"]],
                        "provider": "fake",
                    },
                )
                self.assertEqual(response.status_code, 200)

        self.assertEqual(len(calls), 1)
        handoff = calls[0]
        self.assertIn("ordinary flat attachment", handoff["frozen_context"])
        self.assertNotIn("[PROJECT STRUCTURE]", handoff["frozen_context"])
        source = handoff["retrieval_meta"]["attached_sources"][0]
        self.assertEqual(source["filename"], "notes.txt")
        self.assertNotIn("relative_path", source)

    def test_source_metadata_without_prepared_context_is_rejected_before_execution(self):
        calls: list[dict] = []
        source = {
            "filename": "routes.py",
            "relative_path": "api/routes.py",
            "source_id": "ctx_0123456789abcdef",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "runs"
            conversation_dir = run_dir / "conversations"
            conversation_dir.mkdir(parents=True)
            with (
                patch.object(main_module, "RUNS", run_dir),
                patch.object(main_module, "CONVERSATIONS", conversation_dir),
                patch.object(main_module, "execute_once", new=capture_executor(calls)),
            ):
                response = self.client.post(
                    "/api/chat/stream",
                    json={
                        "message": "Use the project route.",
                        "context": "",
                        "context_active": True,
                        "context_sources": [source],
                        "provider": "fake",
                    },
                )

                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"]["code"], "INVALID_CONTEXT_REFERENCE")
                self.assertEqual(calls, [])
                self.assertEqual(list(run_dir.glob("run_*.json")), [])
                self.assertEqual(list(conversation_dir.glob("chat_*.json")), [])

    def test_chat_without_context_remains_on_the_normal_product_path(self):
        calls: list[dict] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "runs"
            conversation_dir = run_dir / "conversations"
            conversation_dir.mkdir(parents=True)
            with (
                patch.object(main_module, "RUNS", run_dir),
                patch.object(main_module, "CONVERSATIONS", conversation_dir),
                patch.object(main_module, "execute_once", new=capture_executor(calls)),
            ):
                response = self.client.post(
                    "/api/chat/stream",
                    json={"message": "hello", "provider": "fake"},
                )
                self.assertEqual(response.status_code, 200)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["retrieval_meta"].get("attached_sources"), None)
        self.assertEqual(calls[0]["retrieval_meta"]["method"], "none")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main_module
from app.core.context_files import SUPPORTED_CONTEXT_EXTENSIONS


class ProductQATests(unittest.TestCase):
    """Independent non-live Product V1 checks; no Pilot or live provider calls."""

    def setUp(self):
        self.client = TestClient(main_module.app)

    @staticmethod
    def _events(response):
        return [json.loads(line) for line in response.text.splitlines() if line.strip()]

    @staticmethod
    def _storage(temp_dir):
        runs = Path(temp_dir)
        conversations = runs / "conversations"
        conversations.mkdir()
        return runs, conversations

    def test_fake_chat_contract_persists_conversation_and_frozen_provenance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runs, conversations = self._storage(temp_dir)
            with patch.object(main_module, "RUNS", runs), patch.object(main_module, "CONVERSATIONS", conversations):
                response = self.client.post(
                    "/api/chat/stream",
                    json={
                        "message": "Theo tài liệu, access token hết hạn sau bao lâu?",
                        "context": "Access token expires after 60 minutes.",
                        "provider": "fake",
                    },
                )
                self.assertEqual(response.status_code, 200)
                events = self._events(response)
                final = next(event for event in events if event["type"] == "final")
                self.assertEqual(final["status"], "completed")
                self.assertEqual(final["stop_reason"], "STOP_SUFFICIENT")
                self.assertEqual(final["provider"], "fake")
                self.assertEqual(final["model"], "fake-research-v2")
                self.assertIn("60 phút", final["answer"])
                self.assertRegex(final["conversation_id"], r"^chat_[A-Za-z0-9_-]+$")
                self.assertTrue(any(event.get("event", {}).get("title") == "AUTO route selected" for event in events))
                metrics = next(event["metrics"] for event in events if event["type"] == "metrics")
                self.assertEqual(metrics["e2e_boundary_version"], "E2E-MEASURE-V2")

                run_id = final["run_id"]
                conversation_id = final["conversation_id"]
                raw = json.loads((runs / f"{run_id}.json").read_text(encoding="utf-8"))
                opened = self.client.get(f"/api/conversations/{conversation_id}")
                self.assertEqual(opened.status_code, 200)
                conversation = opened.json()
                self.assertEqual(conversation["conversation_id"], conversation_id)
                self.assertEqual(len(conversation["messages"]), 2)
                self.assertEqual(len(conversation["turns"]), 1)
                self.assertEqual(raw["conversation_id"], conversation_id)
                self.assertEqual(raw["strategy"], "adaptive")
                self.assertTrue(raw["source_document_ids"])
                self.assertTrue(raw["source_document_ids"][0].startswith("doc_"))
                self.assertEqual(raw["metrics"]["e2e_boundary_version"], "E2E-MEASURE-V2")
                self.assertNotIn("Traceback", response.text)

    def test_product_modes_normalize_without_changing_model(self):
        seen = []

        async def fake_execute_once(**kwargs):
            seen.append((kwargs["mode"], kwargs["model_name"], kwargs["strategy"]))
            data = {
                "run_id": f"run_mode_{len(seen)}",
                "provider": "fake",
                "model": "fake-research-v2",
                "answer": "mode answer",
                "status": "completed",
                "stop_reason": "STOP_SUFFICIENT",
                "metrics": {},
                "processing_mode": kwargs["mode"],
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
            _, conversations = self._storage(temp_dir)
            with (
                patch.object(main_module, "CONVERSATIONS", conversations),
                patch.object(main_module, "execute_once", new=fake_execute_once),
            ):
                for mode in ("auto", "direct", "parallel", "planned"):
                    response = self.client.post(
                        "/api/chat/stream",
                        json={
                            "message": f"mode {mode}",
                            "provider": "fake",
                            "model": "fake-research-v2",
                            "mode": mode,
                        },
                    )
                    self.assertEqual(response.status_code, 200)

        self.assertEqual([item[0] for item in seen], ["adaptive-auto", "DIRECT", "PARALLEL", "PLANNED"])
        self.assertEqual({item[1] for item in seen}, {"fake-research-v2"})
        self.assertEqual({item[2] for item in seen}, {"adaptive"})

    def _assert_fake_mode(self, requested, message, expected_processing_mode, event_title, expected_route):
        with tempfile.TemporaryDirectory() as temp_dir:
            runs, conversations = self._storage(temp_dir)
            with patch.object(main_module, "RUNS", runs), patch.object(main_module, "CONVERSATIONS", conversations):
                response = self.client.post(
                    "/api/chat/stream",
                    json={
                        "message": message,
                        "context": "Authentication and pagination reference.",
                        "provider": "fake",
                        "model": "fake-research-v2",
                        "mode": requested,
                    },
                )
                self.assertEqual(response.status_code, 200, requested)
                events = self._events(response)
                final = next(event for event in events if event["type"] == "final")
                self.assertEqual(final["status"], "completed", requested)
                route_events = [
                    event for event in events
                    if event["type"] == "trace" and event["event"].get("title") == event_title
                ]
                self.assertTrue(route_events, f"No {event_title} event for {requested}")
                route = route_events[0]["event"]["meta"]["mode"]
                self.assertEqual(route, expected_route)
                raw = json.loads((runs / f"{final['run_id']}.json").read_text(encoding="utf-8"))
                self.assertEqual(raw["processing_mode"], expected_processing_mode)
                self.assertEqual(raw["model"], "fake-research-v2")

    def test_fake_chat_executes_auto_and_parallel_product_modes(self):
        self._assert_fake_mode("auto", "simple task", "adaptive-auto", "AUTO route selected", "DIRECT")
        self._assert_fake_mode(
            "parallel",
            "Analyze authentication, pagination and error handling.",
            "PARALLEL",
            "Product mode selected",
            "PARALLEL",
        )

    def test_forced_direct_mode_executes_successfully(self):
        self._assert_fake_mode("direct", "simple task", "DIRECT", "Product mode selected", "DIRECT")

    def test_forced_planned_mode_executes_successfully(self):
        self._assert_fake_mode(
            "planned",
            "Analyze authentication and pagination; từ đó lập thứ tự.",
            "PLANNED",
            "Product mode selected",
            "PLANNED",
        )

    def test_openai_catalog_and_invalid_product_selections_are_safe(self):
        config = self.client.get("/api/config")
        self.assertEqual(config.status_code, 200)
        data = config.json()
        self.assertEqual(
            data["context_file_extensions"],
            ["txt", "md", "py", "js", "ts", "json", "html", "css", "csv"],
        )
        openai_ids = [item["id"] for item in data["model_options"]["openai"]]
        self.assertEqual(openai_ids, ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"])
        self.assertEqual(data["models"]["openai"], "gpt-5.6-luna")
        self.assertEqual(data["chat_strategy"], "adaptive-auto")
        self.assertEqual(
            [item["id"] for item in data["mode_options"]],
            ["adaptive-auto", "DIRECT", "PARALLEL", "PLANNED"],
        )

        invalid_provider = self.client.post(
            "/api/chat/stream",
            json={"message": "hello", "provider": "not-a-provider"},
        )
        self.assertEqual(invalid_provider.status_code, 422)
        self.assertNotIn("Traceback", invalid_provider.text)

        with tempfile.TemporaryDirectory() as temp_dir:
            _, conversations = self._storage(temp_dir)
            with patch.object(main_module, "CONVERSATIONS", conversations):
                invalid_model = self.client.post(
                    "/api/chat/stream",
                    json={"message": "hello", "provider": "fake", "model": "gpt-5.6-luna"},
                )
            self.assertEqual(invalid_model.status_code, 200)
            events = self._events(invalid_model)
            fatal = next(event for event in events if event["type"] == "fatal")
            self.assertIn("Unsupported model selection", fatal["error"])
            self.assertNotIn("Traceback", invalid_model.text)

    def test_context_prepare_formats_parser_errors_and_source_identity(self):
        for suffix in sorted(SUPPORTED_CONTEXT_EXTENSIONS):
            extension = suffix.removeprefix(".")
            response = self.client.post(
                "/api/context/prepare",
                json={"filename": f"reference{suffix}", "content": "token expiry: 60 minutes"},
            )
            self.assertEqual(response.status_code, 200, extension)
            prepared = response.json()
            self.assertEqual(prepared["status"], "ready")
            self.assertEqual(prepared["source"]["format"], extension)
            self.assertRegex(prepared["source"]["source_id"], r"^ctx_[0-9a-f]{16}$")

        unsupported = self.client.post(
            "/api/context/prepare",
            json={"filename": "reference.pdf", "content": "content"},
        )
        self.assertEqual(unsupported.status_code, 415)
        self.assertEqual(unsupported.json()["detail"]["code"], "UNSUPPORTED_FORMAT")

        parser_error = self.client.post(
            "/api/context/prepare",
            json={"filename": "reference.json", "content": "valid\u0000invalid"},
        )
        self.assertEqual(parser_error.status_code, 422)
        self.assertEqual(parser_error.json()["detail"]["code"], "PARSER_FAILED")

        decode_error = self.client.post(
            "/api/context/prepare",
            json={
                "filename": "reference.txt",
                "content_base64": base64.b64encode(b"\xff\xfe").decode("ascii"),
            },
        )
        self.assertEqual(decode_error.status_code, 422)
        self.assertEqual(decode_error.json()["detail"]["code"], "DECODE_FAILED")

        path_error = self.client.post(
            "/api/context/prepare",
            json={"filename": "..\\secret.txt", "content": "content"},
        )
        self.assertEqual(path_error.status_code, 400)
        self.assertEqual(path_error.json()["detail"]["code"], "INVALID_FILENAME")

        first = self.client.post(
            "/api/context/prepare",
            json={"filename": "same.txt", "content": "same content"},
        ).json()
        retry = self.client.post(
            "/api/context/prepare",
            json={"filename": "same.txt", "content": "same content"},
        ).json()
        self.assertEqual(retry["text"], first["text"])
        self.assertEqual(retry["source"], first["source"])

        html = (Path(main_module.__file__).resolve().parent / "static" / "index.html").read_text(encoding="utf-8")
        js = (Path(main_module.__file__).resolve().parent / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/context/prepare"', js)
        self.assertIn("contextSourcesForRequest", js)
        self.assertIn("cfg.context_file_extensions", js)
        self.assertNotIn("SUPPORTED_CONTEXT_EXTENSIONS", js)
        self.assertNotIn("legacy API contract", html)
        compare_line = next(
            line for line in js.splitlines() if 'fetch("/api/compare/stream"' in line
        )
        self.assertIn("context_sources:contextSourcesForRequest()", compare_line)
        self.assertIn("activeContextFile=file", js)
        self.assertIn("processContextFile(activeContextFile)", js)
        self.assertIn('$("#context").value="";clearContextFile()', js)

        with tempfile.TemporaryDirectory() as temp_dir:
            runs, conversations = self._storage(temp_dir)
            source = first["source"]
            with patch.object(main_module, "RUNS", runs), patch.object(main_module, "CONVERSATIONS", conversations):
                response = self.client.post(
                    "/api/chat/stream",
                    json={
                        "message": "What is the token expiry?",
                        "context": first["text"],
                        "context_sources": [source],
                        "provider": "fake",
                    },
                )
                self.assertEqual(response.status_code, 200)
                final = next(event for event in self._events(response) if event["type"] == "final")
                raw = json.loads((runs / f"{final['run_id']}.json").read_text(encoding="utf-8"))
                self.assertEqual(final["sources"][0]["source_id"], source["source_id"])
                self.assertEqual(raw["sources"][0]["filename"], "same.txt")
                self.assertEqual(raw["retrieval_meta"]["attached_sources"][0]["parser"], "utf-8-text-v1")
                self.assertIn(first["text"], raw["context"])

    def test_compare_preserves_context_source_identity(self):
        source = self.client.post(
            "/api/context/prepare",
            json={"filename": "compare.txt", "content": "token expiry: 60 minutes"},
        ).json()["source"]
        with tempfile.TemporaryDirectory() as temp_dir:
            runs, conversations = self._storage(temp_dir)
            with patch.object(main_module, "RUNS", runs), patch.object(main_module, "CONVERSATIONS", conversations):
                response = self.client.post(
                    "/api/compare/stream",
                    json={
                        "message": "What is the token expiry?",
                        "context": "token expiry: 60 minutes",
                        "context_sources": [source],
                        "provider": "fake",
                    },
                )
                self.assertEqual(response.status_code, 200)
                results = [
                    event["result"] for event in self._events(response)
                    if event["type"] == "compare_result"
                ]
                self.assertEqual([result["strategy"] for result in results], ["single", "fixed", "static", "adaptive"])
                for result in results:
                    raw = json.loads((runs / f"{result['run_id']}.json").read_text(encoding="utf-8"))
                    self.assertEqual(raw["retrieval_meta"].get("attached_sources"), [source])
                    self.assertEqual(raw["sources"], [source])

    def test_product_controls_have_accessible_names_and_status_announcements(self):
        root = Path(main_module.__file__).resolve().parent / "static"
        html = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="prompt" rows="1" maxlength="12000" aria-label=', html)
        self.assertIn('id="context" maxlength="100000" aria-label=', html)
        self.assertIn('id="toasts" role="status" aria-live="polite" aria-atomic="true"', html)

    def test_provider_failure_is_safe_and_persisted_as_structured_fatal(self):
        async def failing_provider(**_kwargs):
            raise RuntimeError("upstream secret provider-test-secret")

        with tempfile.TemporaryDirectory() as temp_dir:
            runs, conversations = self._storage(temp_dir)
            with (
                patch.object(main_module, "RUNS", runs),
                patch.object(main_module, "CONVERSATIONS", conversations),
                patch.object(main_module, "get_provider", side_effect=failing_provider),
            ):
                response = self.client.post(
                    "/api/chat/stream",
                    json={"message": "provider failure", "provider": "fake"},
                )
                self.assertEqual(response.status_code, 200)
                fatal = next(event for event in self._events(response) if event["type"] == "fatal")
                self.assertEqual(fatal["provider"], "fake")
                self.assertNotIn("provider-test-secret", response.text)
                raw = json.loads((runs / f"{fatal['run_id']}.json").read_text(encoding="utf-8"))
                self.assertEqual(raw["incident"]["origin"], "provider")
                self.assertEqual(raw["incident"]["category"], "PROVIDER_ERROR")
                self.assertNotIn("provider-test-secret", json.dumps(raw))


if __name__ == "__main__":
    unittest.main()

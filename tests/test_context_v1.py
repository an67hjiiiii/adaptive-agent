from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

from app.core.context_files import (  # noqa: E402
    CONTEXT_FILE_PARSER,
    ContextFileError,
    MAX_CONTEXT_FILE_BYTES,
    prepare_context_file,
)
from app.core.rag import frozen_snapshot  # noqa: E402
from app.providers.fake import FakeProvider  # noqa: E402
import app.main as main_module  # noqa: E402


class ContextFilePreparationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def test_supported_text_source_matrix_uses_one_safe_parser(self):
        extensions = ("txt", "md", "py", "js", "ts", "json", "html", "css", "csv")
        for extension in extensions:
            with self.subTest(extension=extension):
                result = prepare_context_file(
                    filename=f"fixture.{extension}",
                    content="entry point /api/project\n",
                )
                self.assertEqual(result["status"], "ready")
                self.assertEqual(result["parser"], CONTEXT_FILE_PARSER)
                self.assertEqual(result["source"]["filename"], f"fixture.{extension}")
                self.assertEqual(result["source"]["format"], extension)
                self.assertEqual(result["text"], "entry point /api/project")

    def test_unsupported_empty_oversized_decode_parser_and_path_fail_closed(self):
        cases = (
            ("UNSUPPORTED_FORMAT", dict(filename="fixture.pdf", content="x")),
            ("EMPTY_FILE", dict(filename="fixture.md", content=" \r\n\t")),
            (
                "FILE_TOO_LARGE",
                dict(
                    filename="fixture.md",
                    content_base64=base64.b64encode(b"x" * (MAX_CONTEXT_FILE_BYTES + 1)).decode(),
                ),
            ),
            ("DECODE_FAILED", dict(filename="fixture.md", content_base64="%%%")),
            ("PARSER_FAILED", dict(filename="fixture.md", content="valid\x00binary")),
            ("INVALID_FILENAME", dict(filename="..\\secret.md", content="x")),
            ("INVALID_FILENAME", dict(filename="CON.txt", content="x")),
            ("INVALID_FILENAME", dict(filename="bad?.md", content="x")),
        )
        for code, kwargs in cases:
            with self.subTest(code=code):
                with self.assertRaises(ContextFileError) as raised:
                    prepare_context_file(**kwargs)
                self.assertEqual(raised.exception.code, code)

    def test_prepare_endpoint_returns_text_and_filename_without_persisting_upload(self):
        response = self.client.post(
            "/api/context/prepare",
            json={
                "filename": "routes.py",
                "content_base64": base64.b64encode(b"GET /api/project").decode(),
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["text"], "GET /api/project")
        self.assertEqual(payload["source"]["filename"], "routes.py")
        self.assertEqual(payload["source"]["parser"], CONTEXT_FILE_PARSER)

    def test_prepare_endpoint_errors_are_safe_and_truthful(self):
        unsupported = self.client.post(
            "/api/context/prepare",
            json={"filename": "../private.pdf", "content": "secret"},
        )
        self.assertEqual(unsupported.status_code, 400)
        self.assertEqual(unsupported.json()["detail"]["code"], "INVALID_FILENAME")
        self.assertNotIn("private.pdf", unsupported.text)

        invalid_utf8 = self.client.post(
            "/api/context/prepare",
            json={"filename": "bad.md", "content_base64": base64.b64encode(b"\xff\xfe").decode()},
        )
        self.assertEqual(invalid_utf8.status_code, 422)
        self.assertEqual(invalid_utf8.json()["detail"]["code"], "DECODE_FAILED")


class ContextProductFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def test_prepared_content_reaches_normal_product_execution_and_source_identity(self):
        prepared = self.client.post(
            "/api/context/prepare",
            json={
                "filename": "routes.py",
                "content": "def register_routes():\n    return {'GET /api/project': summarize_project}",
            },
        ).json()
        context = f"===== {prepared['filename']} =====\n{prepared['text']}"
        seen = {}

        async def fake_execute_once(**kwargs):
            seen.update(kwargs)
            sources = kwargs["retrieval_meta"].get("attached_sources", [])
            data = {
                "run_id": "run_context_v1",
                "strategy": "adaptive",
                "provider": "fake",
                "model": "fake-research-v2",
                "processing_mode": "adaptive-auto",
                "answer": "The route calls summarize_project.",
                "status": "completed",
                "stop_reason": "STOP_SUFFICIENT",
                "metrics": {"logical_calls": 1, "physical_requests": 1},
                "sources": sources,
            }
            await kwargs["emit"]({
                "type": "final",
                "answer": data["answer"],
                "status": data["status"],
                "stop_reason": data["stop_reason"],
                "metrics": data["metrics"],
                "run_id": data["run_id"],
                "provider": data["provider"],
                "model": data["model"],
                "sources": sources,
                "conversation_id": kwargs["conversation_id"],
            })
            return data

        with tempfile.TemporaryDirectory() as temp_dir:
            conversation_dir = Path(temp_dir) / "conversations"
            conversation_dir.mkdir()
            with (
                patch.object(main_module, "RUNS", Path(temp_dir)),
                patch.object(main_module, "CONVERSATIONS", conversation_dir),
                patch.object(main_module, "execute_once", new=fake_execute_once),
            ):
                response = self.client.post(
                    "/api/chat/stream",
                    json={
                        "message": "Which API route calls the service?",
                        "context": context,
                        "context_sources": [prepared["source"]],
                        "provider": "fake",
                    },
                )
                self.assertEqual(response.status_code, 200)
                events = [json.loads(line) for line in response.text.splitlines() if line]
                final = next(event for event in events if event["type"] == "final")
                conversation_id = final["conversation_id"]
                conversation = self.client.get(
                    f"/api/conversations/{conversation_id}"
                ).json()

        self.assertIn("register_routes", seen["frozen_context"])
        self.assertIn("/api/project", seen["frozen_context"])
        self.assertEqual(
            seen["retrieval_meta"]["attached_sources"][0]["filename"],
            "routes.py",
        )
        self.assertEqual(final["sources"][0]["filename"], "routes.py")
        self.assertEqual(conversation["context_sources"][0]["filename"], "routes.py")
        self.assertEqual(conversation["turns"][0]["assistant"]["sources"][0]["filename"], "routes.py")

    def test_real_fake_execution_emits_and_persists_source_identity(self):
        source = {
            "source_id": "ctx_0123456789abcdef",
            "filename": "README.md",
            "format": "md",
            "parser": CONTEXT_FILE_PARSER,
            "char_count": 12,
        }
        events = []

        async def emit(event):
            events.append(event)

        async def run():
            with tempfile.TemporaryDirectory() as temp_dir:
                with (
                    patch.object(main_module, "RUNS", Path(temp_dir)),
                    patch.object(main_module, "get_provider", return_value=FakeProvider()),
                ):
                    return await main_module.execute_once(
                        strategy="adaptive",
                        provider_name="fake",
                        mode="adaptive-auto",
                        message="Summarize the supplied file.",
                        frozen_context="===== README.md =====\nContext demo.",
                        retrieval_meta={"attached_sources": [source]},
                        history=[],
                        emit=emit,
                    )

        result = asyncio.run(run())
        final = next(event for event in events if event["type"] == "final")
        self.assertEqual(final["sources"][0]["filename"], "README.md")
        self.assertEqual(result["sources"][0]["filename"], "README.md")
        self.assertEqual(result["retrieval_meta"]["attached_sources"][0]["filename"], "README.md")

    def test_mini_project_fixture_preserves_all_small_files_for_context_retrieval(self):
        fixture_dir = ROOT / "tests" / "fixtures" / "context_project_v1"
        prepared_files = []
        for path in sorted(path for path in fixture_dir.iterdir() if path.is_file()):
            prepared = prepare_context_file(
                filename=path.name,
                content=path.read_text(encoding="utf-8"),
            )
            prepared_files.append(prepared)
        context = "\n\n--- attached file ---\n\n".join(
            f"===== {item['filename']} =====\n{item['text']}"
            for item in prepared_files
        )
        snapshot, metadata = frozen_snapshot(
            "Find the entry point, API route, service module and summarize the project.",
            context,
        )

        self.assertEqual(len(prepared_files), 5)
        for filename in ("README.md", "app.py", "routes.py", "service.py", "config.py"):
            self.assertIn(filename, snapshot)
        for marker in ("register_routes", "/api/project", "summarize_project", "Context Demo"):
            self.assertIn(marker, snapshot)
        self.assertEqual(metadata["method"], "full-small-context")
        self.assertEqual(metadata["chunks_selected"], metadata["chunks_total"])


class ContextUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    def test_ui_uses_backend_preparation_and_truthful_states(self):
        self.assertIn('id="contextFile" type="file" multiple', self.html)
        self.assertIn('id="contextFileList"', self.html)
        self.assertIn('"/api/context/prepare"', self.js)
        self.assertIn("cfg.context_file_extensions", self.js)
        self.assertNotIn("SUPPORTED_CONTEXT_EXTENSIONS", self.js)
        self.assertNotIn("legacy API contract", self.html)
        for label in ("Đang tải", "Đang xử lý", "Sẵn sàng", "Không hỗ trợ", "Không thể xử lý"):
            self.assertIn(label, self.js)
        self.assertIn("context_sources:contextSourcesForRequest()", self.js)
        self.assertIn("function retryContextFile", self.js)
        self.assertIn("processContextFile(item.file,id)", self.js)
        self.assertIn("contextAttachments.delete(id)", self.js)
        self.assertIn("function renderContextAttachments", self.js)
        self.assertIn("function contextAttachmentPending", self.js)
        self.assertIn("MAX_CONTEXT_FILE_BYTES_V1", self.js)
        self.assertIn("clearContextFile();currentConversationId=id", self.js)
        self.assertIn("persistedContextSources=Array.isArray(conversation.context_sources)", self.js)
        self.assertIn("context-file-row", self.css)

    def test_ui_source_filename_is_escaped_and_rendered_in_product_surfaces(self):
        self.assertIn('sourceBox.className="turn-sources"', self.js)
        self.assertIn('source.filename', self.js)
        self.assertIn('meta.attached_sources', self.js)
        self.assertIn('retrieval.attached_sources', self.js)
        self.assertIn('esc(source)', self.js)
        self.assertIn('role="list"', self.html)


if __name__ == "__main__":
    unittest.main()

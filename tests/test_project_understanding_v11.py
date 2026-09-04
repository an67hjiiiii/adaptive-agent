from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.core.context_files import (
    MAX_CONTEXT_FILES,
    ContextFileError,
    normalize_context_sources,
    prepare_context_file,
)
from app.core.orchestrator import Orchestrator
from app.core.rag import frozen_snapshot
from app.core.conversation_repository import JsonConversationRepository
from app.core.types import Budget
from app.providers.fake import FakeProvider
import app.main as main_module


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "v11_projects"
CASES = ROOT / "tests" / "fixtures" / "v11_evaluation" / "cases.json"


def fixture_files(name: str) -> list[Path]:
    return sorted(
        path
        for path in (FIXTURES / name).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def project_context(name: str) -> str:
    files = fixture_files(name)
    lines = ["[PROJECT STRUCTURE]"]
    lines.extend(path.relative_to(FIXTURES / name).as_posix() for path in files)
    lines.extend(["", "[RETRIEVED CONTEXT]", ""])
    for path in files:
        relative_path = path.relative_to(FIXTURES / name).as_posix()
        lines.extend([f"SOURCE: {relative_path}", path.read_text(encoding="utf-8"), ""])
    return "\n".join(lines).strip()


def prepared_fixture_sources(name: str) -> list[dict]:
    """Use the production preparation contract for every useful fixture file."""
    prepared=[]
    for path in fixture_files(name):
        relative_path=path.relative_to(FIXTURES / name).as_posix()
        result=prepare_context_file(
            filename=path.name,
            relative_path=relative_path,
            content=path.read_text(encoding="utf-8"),
        )
        prepared.append({
            "filename":path.name,
            "relative_path":relative_path,
            "content":result["text"],
            "source":result["source"],
        })
    return sorted(prepared, key=lambda item: item["relative_path"])


class ProjectPathSafetyTests(unittest.TestCase):
    def test_relative_path_is_optional_and_keeps_duplicate_basenames_distinct(self):
        api = prepare_context_file(
            filename="routes.py", relative_path="api/routes.py", content="def user_route(): pass"
        )
        admin = prepare_context_file(
            filename="routes.py", relative_path="admin/routes.py", content="def admin_route(): pass"
        )
        self.assertEqual(api["source"]["relative_path"], "api/routes.py")
        self.assertEqual(admin["source"]["relative_path"], "admin/routes.py")
        self.assertNotEqual(api["source"]["source_id"], admin["source"]["source_id"])
        normalized = normalize_context_sources([api["source"], admin["source"]])
        self.assertEqual([item["relative_path"] for item in normalized], ["api/routes.py", "admin/routes.py"])

    def test_unsafe_relative_paths_fail_closed_and_legacy_filename_still_works(self):
        for path in ("../secret.py", "../../.env", "/var/app/file.py", "C:\\Users\\name\\secret.py", "D:\\secret.py"):
            with self.subTest(path=path):
                with self.assertRaises(ContextFileError) as raised:
                    prepare_context_file(filename="secret.py", relative_path=path, content="x")
                self.assertEqual(raised.exception.code, "INVALID_RELATIVE_PATH")
        legacy = prepare_context_file(filename="README.md", content="legacy source")
        self.assertNotIn("relative_path", legacy["source"])
        self.assertEqual(normalize_context_sources([legacy["source"]])[0]["filename"], "README.md")

    def test_project_limit_accepts_twenty_and_rejects_twenty_one(self):
        self.assertEqual(MAX_CONTEXT_FILES, 20)
        sources = [
            {"filename": f"file_{index}.py", "relative_path": f"src/file_{index}.py"}
            for index in range(20)
        ]
        self.assertEqual(len(normalize_context_sources(sources)), 20)
        self.assertEqual(len(main_module.ChatRequest(message="locate", context_sources=sources).context_sources), 20)
        with self.assertRaises(ContextFileError) as raised:
            normalize_context_sources(sources + [{"filename": "file_20.py", "relative_path": "src/file_20.py"}])
        self.assertEqual(raised.exception.code, "TOO_MANY_FILES")


class ProjectRagTests(unittest.TestCase):
    def test_manifest_is_deterministic_bounded_and_retrieval_keeps_paths(self):
        context = project_context("large")
        first, first_meta = frozen_snapshot("Admin routes nằm ở đâu?", context)
        second, second_meta = frozen_snapshot("Admin routes nằm ở đâu?", context)
        self.assertEqual(first, second)
        self.assertEqual(first_meta["snapshot_id"], second_meta["snapshot_id"])
        self.assertTrue(first.startswith("[PROJECT STRUCTURE]"))
        self.assertIn("[RETRIEVED CONTEXT]", first)
        self.assertIn("SOURCE: admin/routes.py", first)
        self.assertEqual(first_meta["method"], "lexical-overlap-path-v1")
        self.assertLessEqual(first_meta["chunks_selected"], 6)
        self.assertEqual(len(first_meta["source_document_ids"]), 20)
        self.assertTrue(all("relative_path" in item for item in first_meta["source_documents"]))
        self.assertNotIn("C:/", first)

    def test_path_signal_is_modest_against_strong_content(self):
        context = """[PROJECT STRUCTURE]
auth.py
services/session.py

[RETRIEVED CONTEXT]

SOURCE: auth.py
def unrelated_color(): return 'blue'

SOURCE: services/session.py
def auth_middleware(request): return validate_session(request)"""
        snapshot, metadata = frozen_snapshot("auth middleware nằm đâu?", context, top_k=1)
        self.assertIn("SOURCE: services/session.py", snapshot)
        self.assertNotIn("SOURCE: auth.py\ndef unrelated", snapshot)
        self.assertEqual(metadata["selected_chunks"][0]["source_path"], "services/session.py")


class ProjectFixtureAndProductIsolationTests(unittest.TestCase):
    def test_original_fixture_counts_and_machine_readable_cases_are_valid(self):
        self.assertEqual(len(fixture_files("small")), 5)
        self.assertEqual(len(fixture_files("medium")), 10)
        self.assertEqual(len(fixture_files("large")), 20)
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        self.assertEqual(cases["version"], "PROJECT-UNDERSTANDING-V1.1")
        self.assertEqual(set(cases["manual_scoring"]), {"PASS", "PARTIAL", "FAIL"})
        self.assertEqual({case["category"] for case in cases["cases"]}, {"STRUCTURE", "LOCATE", "RELATION", "TRACE", "SUMMARY"})
        for case in cases["cases"]:
            available = {path.relative_to(FIXTURES / case["fixture"]).as_posix() for path in fixture_files(case["fixture"])}
            self.assertTrue(set(case["expected_relevant_files"]) <= available, case["id"])

    def test_twenty_file_entry_question_stays_direct(self):
        async def emit(_event):
            return None

        orchestrator = Orchestrator(FakeProvider(), emit, budget=Budget())
        self.assertEqual(orchestrator.product_auto_fast_path("Entry point nằm đâu?")[0], "DIRECT")
        analysis = {"aspects": [{"name": "entry", "goal": "locate entry point"}], "dependencies": [], "parallelizable_groups": [], "verification_demand": "low"}
        self.assertEqual(orchestrator.choose_product_mode(analysis, "Entry point nằm đâu?")[0], "DIRECT")

    def test_s_m_l_fixture_ingestion_keeps_only_safe_relative_source_identity(self):
        for fixture_name, expected_count in (("small", 5), ("medium", 10), ("large", 20)):
            with self.subTest(fixture=fixture_name):
                sources=prepared_fixture_sources(fixture_name)
                self.assertEqual(len(sources), expected_count)
                relative_paths=[item["relative_path"] for item in sources]
                self.assertEqual(relative_paths, sorted(relative_paths))
                self.assertTrue(any("/" in path for path in relative_paths))
                for item in sources:
                    source=item["source"]
                    self.assertEqual(source["relative_path"], item["relative_path"])
                    self.assertNotIn("..", source["relative_path"].split("/"))
                    self.assertFalse(source["relative_path"].startswith(("/", "C:", "D:")))

    def test_workspace_to_rag_handoff_is_deterministic_and_keeps_known_paths(self):
        expected={
            "small": ("entry_point", "app/main.py"),
            "medium": ("fetch_user", "services/user_service.py"),
            "large": ("entry_point", "app/main.py"),
        }
        for fixture_name, (query, source_path) in expected.items():
            with self.subTest(fixture=fixture_name):
                workspace={"files": prepared_fixture_sources(fixture_name)}
                handoff=main_module.workspace_context(workspace)
                first, first_meta=frozen_snapshot(query, handoff)
                second, second_meta=frozen_snapshot(query, handoff)
                self.assertEqual(first, second)
                self.assertEqual(first_meta["snapshot_hash"], second_meta["snapshot_hash"])
                self.assertTrue(first.startswith("[PROJECT STRUCTURE]\n"))
                self.assertIn("[RETRIEVED CONTEXT]", first)
                self.assertIn(source_path, [chunk["source_path"] for chunk in first_meta["selected_chunks"]])
                self.assertIn(f"SOURCE: {source_path}", first)
                self.assertNotIn("C:\\Users\\", first)
                self.assertNotIn("/home/", first)

    def test_noise_segment_contract_and_workspace_isolation_are_explicit(self):
        noise={".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "coverage", ".next"}
        self.assertFalse(any(part in noise for part in "src/build_helper.py".split("/")))
        self.assertTrue(any(part in noise for part in "build/output.js".split("/")))
        with tempfile.TemporaryDirectory() as temp_dir:
            repository=JsonConversationRepository(Path(temp_dir))
            repository.save_project_workspace("chat_fixture_a", {"name":"small", "files":prepared_fixture_sources("small")})
            self.assertIsNone(repository.get_project_workspace("chat_fixture_b"))
            self.assertEqual(repository.get_project_workspace("chat_fixture_a")["file_count"], 5)


class ProjectUiContractTests(unittest.TestCase):
    def test_folder_picker_menu_and_folder_safety_contract_are_present(self):
        html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="contextFolder" type="file" webkitdirectory directory multiple', html)
        self.assertIn("Chọn thư mục dự án", html)
        self.assertIn("Chọn tệp", html)
        self.assertIn("MAX_PROJECT_FILES = 20", js)
        self.assertIn("Hỗ trợ tối đa 20 tệp mã nguồn trong một dự án.", js)
        self.assertIn("PROJECT_NOISE_DIRECTORIES", js)
        folder_filter = js.split("function supportedProjectFiles", 1)[1].split("async function importProjectFolder", 1)[0]
        self.assertIn("cfg?.context_file_extensions", folder_filter)
        self.assertNotIn("new Set((extensions||[])", folder_filter)
        self.assertIn("relative_path:item.relativePath", js)
        self.assertIn("[PROJECT STRUCTURE]", js)
        self.assertIn("SOURCE: ${safeContextFilename", js)
        self.assertIn("clearDraftAttachments()", js)
        self.assertIn(".attachment-menu", css)
        self.assertIn("styles.css?v=38", html)
        self.assertIn("app.js?v=38", html)


if __name__ == "__main__":
    unittest.main()

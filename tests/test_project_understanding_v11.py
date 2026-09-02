from __future__ import annotations

import json
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
from app.core.types import Budget
from app.providers.fake import FakeProvider
import app.main as main_module


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "v11_projects"
CASES = ROOT / "tests" / "fixtures" / "v11_evaluation" / "cases.json"


def fixture_files(name: str) -> list[Path]:
    return sorted(path for path in (FIXTURES / name).rglob("*") if path.is_file())


def project_context(name: str) -> str:
    files = fixture_files(name)
    lines = ["[PROJECT STRUCTURE]"]
    lines.extend(path.relative_to(FIXTURES / name).as_posix() for path in files)
    lines.extend(["", "[RETRIEVED CONTEXT]", ""])
    for path in files:
        relative_path = path.relative_to(FIXTURES / name).as_posix()
        lines.extend([f"SOURCE: {relative_path}", path.read_text(encoding="utf-8"), ""])
    return "\n".join(lines).strip()


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


class ProjectUiContractTests(unittest.TestCase):
    def test_folder_picker_menu_and_folder_safety_contract_are_present(self):
        html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="contextFolder" type="file" webkitdirectory directory multiple', html)
        self.assertIn("Chọn thư mục dự án", html)
        self.assertIn("Chọn tệp", html)
        self.assertIn("MAX_PROJECT_FILES_V11 = 20", js)
        self.assertIn("V1.1 hỗ trợ tối đa 20 tệp mã nguồn trong một dự án.", js)
        self.assertIn("PROJECT_NOISE_V11", js)
        self.assertIn("relative_path:item.relativePath", js)
        self.assertIn("[PROJECT STRUCTURE]", js)
        self.assertIn("SOURCE: ${safeContextFilename", js)
        self.assertIn("clearDraftAttachments()", js)
        self.assertIn(".attachment-menu", css)
        self.assertIn("styles.css?v=34", html)
        self.assertIn("app.js?v=34", html)


if __name__ == "__main__":
    unittest.main()

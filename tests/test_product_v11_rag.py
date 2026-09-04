from __future__ import annotations

import unittest

from app.core.rag import frozen_snapshot


def project_context(files: list[tuple[str, str]], manifest: list[str] | None = None) -> str:
    paths = manifest if manifest is not None else [path for path, _content in files]
    lines = ["[PROJECT STRUCTURE]", *paths, "", "[RETRIEVED CONTEXT]", ""]
    for path, content in files:
        lines.extend([f"SOURCE: {path}", content, ""])
    return "\n".join(lines).strip()


class ProductV11RagTests(unittest.TestCase):
    def test_project_manifest_is_sorted_safe_and_snapshot_is_deterministic(self):
        files = [
            ("zeta.txt", "A final note."),
            ("api/routes.py", "from services.user_service import fetch_user"),
            ("app.py", "The entry point calls the user route."),
            ("api/helpers.py", "def helper(): return True"),
        ]
        context = project_context(
            files,
            manifest=[
                "zeta.txt",
                r"C:\Users\Viet Anh\project\app.py",
                "app.py",
                "api/routes.py",
                "api/helpers.py",
            ],
        )

        first, first_meta = frozen_snapshot("user route", context, top_k=2)
        second, second_meta = frozen_snapshot("user route", context, top_k=2)

        self.assertEqual(first, second)
        self.assertEqual(first_meta["snapshot_id"], second_meta["snapshot_id"])
        structure = first.split("\n\n[RETRIEVED CONTEXT]\n\n", 1)[0]
        self.assertEqual(
            structure.splitlines()[1:],
            ["api/helpers.py", "api/routes.py", "app.py", "zeta.txt"],
        )
        self.assertNotIn("C:/Users", first)
        self.assertNotIn("C:\\Users", first)

    def test_nested_relative_identity_survives_selection_and_duplicate_basenames(self):
        context = project_context(
            [
                ("admin/routes.py", "def admin_route(): return 'admin'"),
                ("api/routes.py", "def user_route(): return 'user'"),
            ]
        )

        snapshot, metadata = frozen_snapshot("user route", context, top_k=1)

        self.assertEqual(metadata["selected_chunks"][0]["source_path"], "api/routes.py")
        self.assertIn("SOURCE: api/routes.py", snapshot)
        self.assertNotIn("SOURCE: routes.py", snapshot)
        self.assertEqual(
            {item["relative_path"] for item in metadata["source_documents"]},
            {"admin/routes.py", "api/routes.py"},
        )

    def test_unsafe_source_identity_is_dropped_instead_of_emitted(self):
        context = project_context(
            [
                ("api/routes.py", "def user_route(): return 'user'"),
                (r"C:\Users\Viet Anh\project\secret.py", "secret = True"),
            ]
        )

        snapshot, metadata = frozen_snapshot("user route", context, top_k=2)

        self.assertIn("SOURCE: api/routes.py", snapshot)
        self.assertNotIn("C:/Users", snapshot)
        self.assertNotIn("C:\\Users", snapshot)
        self.assertEqual(
            {item["relative_path"] for item in metadata["source_documents"]},
            {"api/routes.py"},
        )

    def test_relevant_text_beats_a_path_only_hint(self):
        context = project_context(
            [
                ("src/middleware/auth.py", "def unrelated_color(): return 'blue'"),
                (
                    "docs/guide.md",
                    "Authentication middleware validates each request before routing.",
                ),
            ]
        )

        _snapshot, metadata = frozen_snapshot("auth middleware", context, top_k=1)

        self.assertEqual(metadata["selected_chunks"][0]["source_path"], "docs/guide.md")

    def test_flat_source_keeps_legacy_simple_rag_shape(self):
        source = "A single uploaded file describes the health endpoint."

        snapshot, metadata = frozen_snapshot("health endpoint", source)

        self.assertEqual(snapshot, source)
        self.assertEqual(metadata["method"], "full-small-context")
        self.assertNotIn("relative_path", metadata["source_documents"][0])
        self.assertNotIn("[PROJECT STRUCTURE]", snapshot)

    def test_project_snapshot_is_bounded_and_does_not_duplicate_all_file_contents(self):
        files = [
            (f"src/module_{index}.py", f"def function_{index}(): return 'value-{index}'")
            for index in range(8)
        ]
        context = project_context(files)

        snapshot, metadata = frozen_snapshot("function_3", context, top_k=2, max_chars=900)

        self.assertLessEqual(len(snapshot), 900)
        self.assertLessEqual(metadata["chunks_selected"], 2)
        self.assertLessEqual(snapshot.count("SOURCE: "), 2)
        self.assertIn("src/module_3.py", snapshot)

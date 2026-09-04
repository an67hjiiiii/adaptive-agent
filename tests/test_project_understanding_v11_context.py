from __future__ import annotations

import unittest

from app.core.context_files import (
    CONTEXT_FILE_PARSER,
    MAX_CONTEXT_FILE_BYTES,
    MAX_CONTEXT_FILES,
    ContextFileError,
    normalize_context_sources,
    prepare_context_file,
)


class ProjectIngestionContextTests(unittest.TestCase):
    def test_nested_relative_path_is_normalized_and_source_identity_is_preserved(self):
        prepared = prepare_context_file(
            filename="routes.py",
            relative_path=r"api\admin/routes.py",
            content="def admin_route(): pass",
        )

        self.assertEqual(prepared["status"], "ready")
        self.assertEqual(prepared["parser"], CONTEXT_FILE_PARSER)
        self.assertEqual(prepared["source"]["filename"], "routes.py")
        self.assertEqual(prepared["source"]["relative_path"], "api/admin/routes.py")
        self.assertNotIn("C:/", prepared["source"]["relative_path"])
        self.assertNotIn("..", prepared["source"]["relative_path"].split("/"))

    def test_filename_only_attachment_remains_backward_compatible(self):
        prepared = prepare_context_file(filename="README.md", content="legacy source")

        self.assertEqual(prepared["source"]["filename"], "README.md")
        self.assertNotIn("relative_path", prepared["source"])
        self.assertEqual(prepared["text"], "legacy source")

    def test_unsafe_relative_paths_and_unsupported_formats_fail_closed(self):
        for path in ("../secret.py", r"..\secret.py", "/home/user/secret.py", r"C:\Users\name\secret.py"):
            with self.subTest(path=path):
                with self.assertRaises(ContextFileError) as raised:
                    prepare_context_file(filename="secret.py", relative_path=path, content="x")
                self.assertEqual(raised.exception.code, "INVALID_RELATIVE_PATH")

        with self.assertRaises(ContextFileError) as raised:
            prepare_context_file(filename="archive.pdf", content="x")
        self.assertEqual(raised.exception.code, "UNSUPPORTED_FORMAT")

    def test_file_and_source_count_boundaries_are_explicit(self):
        accepted = prepare_context_file(
            filename="limit.txt",
            content="x" * MAX_CONTEXT_FILE_BYTES,
        )
        self.assertEqual(accepted["status"], "ready")
        self.assertEqual(accepted["source"]["byte_count"], MAX_CONTEXT_FILE_BYTES)

        with self.assertRaises(ContextFileError) as oversized:
            prepare_context_file(filename="over.txt", content="x" * (MAX_CONTEXT_FILE_BYTES + 1))
        self.assertEqual(oversized.exception.code, "FILE_TOO_LARGE")

        sources = [
            {"filename": "routes.py", "relative_path": f"service_{index}/routes.py"}
            for index in range(MAX_CONTEXT_FILES)
        ]
        self.assertEqual(len(normalize_context_sources(sources)), MAX_CONTEXT_FILES)
        with self.assertRaises(ContextFileError) as too_many:
            normalize_context_sources(sources + [{"filename": "extra.py", "relative_path": "extra.py"}])
        self.assertEqual(too_many.exception.code, "TOO_MANY_FILES")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from app.core.context_files import ContextFileError, MAX_CONTEXT_FILE_BYTES, prepare_context_file


class ContextBoundaryP0Tests(unittest.TestCase):
    def test_file_size_boundary_accepts_limit_and_rejects_over_limit(self):
        self.assertEqual(MAX_CONTEXT_FILE_BYTES, 100_000)
        for size in (99_999, 100_000):
            with self.subTest(size=size):
                prepared = prepare_context_file(filename="boundary.txt", content="x" * size)

                self.assertEqual(prepared["status"], "ready")
                self.assertEqual(prepared["source"]["byte_count"], size)
                self.assertEqual(len(prepared["text"].encode("utf-8")), size)

        with self.assertRaises(ContextFileError) as raised:
            prepare_context_file(
                filename="boundary.txt",
                content="x" * 100_001,
            )
        self.assertEqual(raised.exception.code, "FILE_TOO_LARGE")


if __name__ == "__main__":
    unittest.main()

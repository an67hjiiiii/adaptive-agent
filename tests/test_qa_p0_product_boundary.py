from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main_module


class ProductBoundaryP0Tests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def test_blank_prompt_is_rejected_before_provider_call_or_persistence(self):
        async def fail_if_called(**_kwargs):
            self.fail("blank prompt must not reach execution")

        with tempfile.TemporaryDirectory() as temp_dir:
            runs = Path(temp_dir)
            conversations = runs / "conversations"
            conversations.mkdir()
            with (
                patch.object(main_module, "RUNS", runs),
                patch.object(main_module, "CONVERSATIONS", conversations),
                patch.object(main_module, "execute_once", new=fail_if_called),
            ):
                for message in ("", " ", "   ", "\n", "\t"):
                    with self.subTest(repr=repr(message)):
                        response = self.client.post(
                            "/api/chat/stream",
                            json={"message": message, "provider": "fake"},
                        )
                        self.assertEqual(response.status_code, 422)
                        self.assertNotIn("Traceback", response.text)

            self.assertEqual(list(runs.glob("run_*.json")), [])
            self.assertEqual(list(conversations.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()

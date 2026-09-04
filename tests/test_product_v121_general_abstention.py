from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main_module
from app.core.types import ProviderResult, Usage


NO_SOURCE_ABSTENTION = "I don't have any source information available to answer that question."


def workspace_files():
    return [
        {"filename": "README.md", "relative_path": "README.md", "content": "web-dev-basics uses Flask."},
        {"filename": "app.py", "relative_path": "app.py", "content": "app = Flask(__name__)\n# entry point"},
    ]


def events(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


class EnvelopeSensitiveFakeProvider:
    """Models the observed false abstention only when GENERAL sees an empty envelope."""

    name = "fake"
    model = "fake-research-v2"

    def __init__(self):
        self.calls = []

    async def generate(self, *, system, user):
        self.calls.append({"system": system, "user": user})
        reference = user.partition("FROZEN REFERENCE CONTEXT:")[2].strip()
        if "Structural Analyzer" in system:
            text = json.dumps({
                "aspects": [{"name": "answer", "goal": "answer the question"}], "dependencies": [],
                "parallelizable_groups": [], "verification_demand": "low", "verification_reasons": [],
                "rationale": "single question",
            })
        elif "Runtime Verifier" in system:
            text = json.dumps({"status": "PASS", "issues": [], "rationale": "candidate is usable"})
        elif "database" in user.casefold():
            text = "INSUFFICIENT SOURCE EVIDENCE"
        elif reference == "No external reference context was supplied.":
            text = NO_SOURCE_ABSTENTION
        elif "README.md" in reference or "app.py" in reference:
            text = "SOURCE ANSWER"
        else:
            text = "NORMAL GENERAL ANSWER"
        return ProviderResult(text=text, usage=Usage(1, 1), model=self.model)


class ProductV121GeneralAbstentionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def _chat(self, message, *, conversation_id=None, workspace=False):
        provider = EnvelopeSensitiveFakeProvider()
        with tempfile.TemporaryDirectory() as temp_dir:
            runs = Path(temp_dir) / "runs"
            conversations = runs / "conversations"
            conversations.mkdir(parents=True)
            with (
                patch.object(main_module, "RUNS", runs),
                patch.object(main_module, "CONVERSATIONS", conversations),
                patch.object(main_module, "get_provider", return_value=provider),
            ):
                if workspace:
                    main_module.conversation_repository().save_project_workspace(
                        conversation_id, {"name": "web-dev-basics", "files": workspace_files()},
                    )
                payload = {"message": message, "provider": "fake", "mode": "adaptive-auto"}
                if conversation_id:
                    payload.update({"conversation_id": conversation_id, "context_active": False})
                response = self.client.post("/api/chat/stream", json=payload)
                self.assertEqual(response.status_code, 200)
                final = next(event for event in events(response) if event["type"] == "final")
                active = main_module.get_project_workspace(conversation_id) if conversation_id else None
        return final, provider, active

    def test_general_no_project_preserves_normal_final_without_context_envelope(self):
        final, provider, _active = self._chat("aeon mall đà nẵng mới mở ở đâu")
        self.assertEqual(final["answer"], "NORMAL GENERAL ANSWER")
        self.assertEqual(len(provider.calls), 3)  # Analyzer → Solver → Verifier, not a scope classifier.
        self.assertTrue(all("FROZEN REFERENCE CONTEXT:" not in call["user"] for call in provider.calls))

    def test_general_with_active_project_preserves_answer_and_workspace(self):
        final, provider, active = self._chat(
            "aeon mall đà nẵng mới mở ở đâu", conversation_id="chat_v121_general", workspace=True,
        )
        self.assertEqual(final["answer"], "NORMAL GENERAL ANSWER")
        self.assertIsNotNone(active)
        self.assertTrue(all("FROZEN REFERENCE CONTEXT:" not in call["user"] for call in provider.calls))

    def test_source_required_evidence_and_missing_evidence_keep_distinct_finals(self):
        entry, entry_provider, _active = self._chat(
            "Entry point của project này nằm ở đâu?", conversation_id="chat_v121_entry", workspace=True,
        )
        database, database_provider, _active = self._chat(
            "Database của project này dùng MySQL hay PostgreSQL?", conversation_id="chat_v121_database", workspace=True,
        )
        self.assertEqual(entry["answer"], "SOURCE ANSWER")
        self.assertEqual(database["answer"], "INSUFFICIENT SOURCE EVIDENCE")
        self.assertTrue(any("FROZEN REFERENCE CONTEXT:" in call["user"] for call in entry_provider.calls))
        self.assertTrue(any("FROZEN REFERENCE CONTEXT:" in call["user"] for call in database_provider.calls))

    def test_explicit_source_request_remains_source_required(self):
        final, provider, _active = self._chat(
            "Dựa vào README.md, project này làm gì?", conversation_id="chat_v121_readme", workspace=True,
        )
        self.assertEqual(final["answer"], "SOURCE ANSWER")
        self.assertTrue(any("FROZEN REFERENCE CONTEXT:" in call["user"] for call in provider.calls))


if __name__ == "__main__":
    unittest.main()

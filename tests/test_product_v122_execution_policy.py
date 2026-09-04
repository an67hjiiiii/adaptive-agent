from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main_module
from app.core.types import ProviderResult, Usage


def workspace_files():
    return [
        {"filename": "README.md", "relative_path": "README.md", "content": "Flask application."},
        {"filename": "app.py", "relative_path": "app.py", "content": "app = Flask(__name__)\n# entry point"},
    ]


def stream_events(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


class PolicyFakeProvider:
    name = "fake"
    model = "fake-research-v2"

    async def generate(self, *, system, user):
        if "Structural Analyzer" in system:
            text = json.dumps({
                "aspects": [{"name": "answer", "goal": "answer the question"}],
                "dependencies": [], "parallelizable_groups": [],
                "verification_demand": "low", "verification_reasons": [],
                "rationale": "single bounded task",
            })
        elif "Runtime Verifier" in system:
            text = json.dumps({"status": "PASS", "issues": [], "rationale": "usable"})
        elif "database" in user.casefold():
            text = "INSUFFICIENT SOURCE EVIDENCE"
        elif "normal model knowledge" in system:
            text = "NORMAL GENERAL ANSWER"
        else:
            text = "SOURCE ANSWER"
        return ProviderResult(text=text, usage=Usage(1, 1), model=self.model)


class ProductV122ExecutionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def _chat(self, message, *, conversation_id=None, workspace=False):
        provider = PolicyFakeProvider()
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
                        conversation_id, {"name": "web-basics", "files": workspace_files()},
                    )
                payload = {"message": message, "provider": "fake", "mode": "adaptive-auto"}
                if conversation_id:
                    payload.update({"conversation_id": conversation_id, "context_active": False})
                response = self.client.post("/api/chat/stream", json=payload)
                self.assertEqual(response.status_code, 200)
                final = next(event for event in stream_events(response) if event["type"] == "final")
                evidence = json.loads((runs / f"{final['run_id']}.json").read_text(encoding="utf-8"))
        return final, evidence

    @staticmethod
    def _policy(evidence):
        return evidence["metrics"]["execution_policy"]

    def test_general_without_project_is_optional_and_skipped(self):
        final, evidence = self._chat("Aeon Mall Đà Nẵng mới mở ở đâu?")
        policy = self._policy(evidence)
        self.assertEqual(final["answer"], "NORMAL GENERAL ANSWER")
        self.assertEqual(
            (policy["scope"], policy["evidence_policy"], policy["retrieval_state"]),
            ("GENERAL", "OPTIONAL", "SKIPPED"),
        )
        self.assertFalse(policy["active_project"])
        self.assertEqual((evidence["metrics"]["logical_calls"], evidence["metrics"]["physical_requests"]), (3, 3))

    def test_general_with_active_project_still_skips_retrieval(self):
        _final, evidence = self._chat(
            "Aeon Mall Đà Nẵng mới mở ở đâu?", conversation_id="chat_v122_general", workspace=True,
        )
        policy = self._policy(evidence)
        self.assertEqual((policy["scope"], policy["retrieval_state"]), ("GENERAL", "SKIPPED"))
        self.assertTrue(policy["active_project"])
        self.assertNotIn("project_workspace", evidence["retrieval_meta"])

    def test_project_question_with_evidence_is_required_hit(self):
        final, evidence = self._chat(
            "Entry point của project này nằm ở đâu?", conversation_id="chat_v122_hit", workspace=True,
        )
        policy = self._policy(evidence)
        self.assertEqual(final["answer"], "SOURCE ANSWER")
        self.assertEqual(
            (policy["scope"], policy["evidence_policy"], policy["retrieval_state"]),
            ("PROJECT_GROUNDED", "REQUIRED", "HIT"),
        )

    def test_project_question_without_evidence_is_required_miss_and_abstains(self):
        final, evidence = self._chat(
            "Database của project này dùng MySQL hay PostgreSQL?",
            conversation_id="chat_v122_miss", workspace=True,
        )
        policy = self._policy(evidence)
        self.assertEqual(final["answer"], "INSUFFICIENT SOURCE EVIDENCE")
        self.assertEqual(
            (policy["scope"], policy["evidence_policy"], policy["retrieval_state"]),
            ("PROJECT_GROUNDED", "REQUIRED", "MISS"),
        )

    def test_explicit_source_request_remains_required(self):
        _final, evidence = self._chat(
            "Dựa vào README.md, ứng dụng này dùng framework gì?",
            conversation_id="chat_v122_explicit", workspace=True,
        )
        policy = self._policy(evidence)
        self.assertEqual(policy["scope"], "PROJECT_GROUNDED")
        self.assertEqual(policy["evidence_policy"], "REQUIRED")
        self.assertEqual(policy["retrieval_state"], "HIT")

    def test_route_is_orthogonal_to_scope(self):
        _general_final, general = self._chat("Hôm nay trời thế nào?")
        _project_final, project = self._chat(
            "Entry point của project này nằm ở đâu?", conversation_id="chat_v122_route", workspace=True,
        )
        general_policy = self._policy(general)
        project_policy = self._policy(project)
        self.assertEqual((general_policy["route"], project_policy["route"]), ("DIRECT", "DIRECT"))
        self.assertNotEqual(general_policy["scope"], project_policy["scope"])

    def test_trace_and_persisted_metrics_contain_compact_policy_fields(self):
        final, evidence = self._chat("Bạn là ai?")
        policy_event = next(event for event in evidence["events"] if event["kind"] == "execution_policy")
        self.assertEqual(policy_event["meta"], evidence["metrics"]["execution_policy"])
        self.assertEqual(evidence["retrieval_meta"]["execution_policy"], evidence["metrics"]["execution_policy"])
        self.assertEqual(final["metrics"]["execution_policy"], evidence["metrics"]["execution_policy"])
        self.assertIn("logical_calls", evidence["metrics"])
        self.assertIn("physical_requests", evidence["metrics"])
        self.assertIn("e2e_ms", evidence["metrics"])


if __name__ == "__main__":
    unittest.main()

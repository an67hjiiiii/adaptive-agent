from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.orchestrator import Orchestrator
from app.core.product_config import product_model_catalog
from app.core.types import Budget, ProviderResult, RunState, Usage
from app.providers.base import Provider
import app.main as main_module
from app.core.pilot import (
    DEFAULT_PILOT_MODEL,
    DEFAULT_PILOT_PROVIDER,
    PILOT_GROQ_REQUEST_PARAMETERS,
)


class DeterministicProductProvider(Provider):
    """Offline provider double for product topology tests."""

    name = "fake"

    def __init__(self, *, name: str = "fake", model: str = "fake-research-v2"):
        self.name = name
        self.model = model
        self.calls: list[str] = []

    async def generate(self, *, system: str, user: str) -> ProviderResult:
        if "Structural Analyzer" in system:
            role = "Analyzer"
            value = {
                "aspects": [
                    {"name": "one", "goal": "Solve one"},
                    {"name": "two", "goal": "Solve two"},
                ],
                "dependencies": [],
                "parallelizable_groups": [["one", "two"]],
                "verification_demand": "low",
                "verification_reasons": [],
                "rationale": "offline product test",
            }
            text = json.dumps(value)
        elif "Planner Agent" in system:
            role = "Planner"
            text = json.dumps({"subtasks": [
                {"id": "S1", "goal": "Solve one", "depends_on": []},
                {"id": "S2", "goal": "Solve two", "depends_on": []},
            ]})
        elif "Runtime Verifier" in system:
            role = "Verifier"
            text = json.dumps({"status": "PASS", "issues": [], "rationale": "sufficient"})
        elif "Direct Solver" in system:
            role = "Direct Solver"
            text = "direct answer"
        elif "Worker Agent" in system:
            role = "Worker"
            text = "worker evidence"
        elif "Synthesizer" in system:
            role = "Synthesizer"
            text = "synthesized answer"
        else:
            role = "Unknown"
            text = "ok"
        self.calls.append(role)
        return ProviderResult(
            text=text,
            usage=Usage(10, 5),
            request_id=f"offline-{len(self.calls)}",
            model=self.model,
            usage_metadata_available=True,
        )


class ProductCatalogTests(unittest.TestCase):
    def test_provider_and_model_catalog_is_explicit_and_provider_scoped(self):
        defaults, options = main_module.model_catalog()
        self.assertEqual(set(defaults), {"fake", "gemini", "groq", "openrouter", "openai"})
        self.assertEqual(
            [item["id"] for item in options["openai"]],
            ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"],
        )
        self.assertIn("openai/gpt-oss-120b", {item["id"] for item in options["groq"]})
        self.assertNotIn("gpt-5.6-luna", {item["id"] for item in options["groq"]})

    def test_unknown_environment_model_is_not_inserted_as_custom_choice(self):
        with patch.dict(os.environ, {"OPENAI_MODEL": "not-a-catalog-model"}, clear=False):
            defaults, options = product_model_catalog()
        self.assertEqual(defaults["openai"], "gpt-5.6-luna")
        self.assertNotIn("not-a-catalog-model", {item["id"] for item in options["openai"]})

    def test_openai_luna_terra_sol_validate_to_canonical_ids(self):
        for model in ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"):
            self.assertEqual(main_module.validated_model("openai", model), model)
        with self.assertRaisesRegex(Exception, "Unsupported model selection"):
            main_module.validated_model("openai", "openai/gpt-oss-120b")

    def test_mismatched_product_provider_model_is_rejected_without_provider_call(self):
        with patch.object(main_module, "get_provider") as factory:
            response = TestClient(main_module.app).post(
                "/api/chat/stream",
                json={
                    "message": "offline mismatch",
                    "provider": "groq",
                    "model": "gpt-5.6-luna",
                    "mode": "DIRECT",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Unsupported model selection", response.text)
        factory.assert_not_called()


class ProductModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_modes_force_topology_without_changing_model(self):
        for mode in ("DIRECT", "PARALLEL", "PLANNED"):
            provider = DeterministicProductProvider(model="gpt-5.6-terra")
            emitted = []

            async def emit(event):
                emitted.append(event)

            state = RunState(
                strategy="adaptive",
                provider=provider.name,
                model=provider.model,
                task="product mode task",
                context="frozen context",
                retrieval_meta={"chunks_total": 1, "chunks_selected": 1},
            )
            orchestrator = Orchestrator(
                provider,
                emit,
                budget=Budget(max_retries_per_call=0),
                product_mode=mode,
            )
            orchestrator.choose_mode = lambda _analysis: (_ for _ in ()).throw(
                AssertionError("explicit product mode must not invoke AUTO chooser")
            )
            await orchestrator.run(state)
            decision = next(
                event for event in state.events if event["title"] == "Product mode selected"
            )
            self.assertEqual(decision["meta"]["mode"], mode)
            self.assertEqual(state.model, "gpt-5.6-terra")
            self.assertEqual(state.status, "completed")
            self.assertIn("Verifier", provider.calls)


class ProductEndpointIsolationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def test_product_mode_and_model_reach_executor_without_live_provider(self):
        captured = {}

        async def fake_execute_once(**kwargs):
            captured.update(kwargs)
            data = {
                "run_id": "run_product_mode",
                "strategy": "adaptive",
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "processing_mode": kwargs["mode"],
                "answer": "offline answer",
                "status": "completed",
                "stop_reason": "STOP_SUFFICIENT",
                "metrics": {},
                "events": [{
                    "kind": "decision",
                    "title": "Product mode selected",
                    "detail": kwargs["mode"],
                    "meta": {"mode": kwargs["mode"]},
                }],
            }
            await kwargs["emit"]({
                "type": "final",
                "answer": data["answer"],
                "status": data["status"],
                "stop_reason": data["stop_reason"],
                "run_id": data["run_id"],
                "conversation_id": kwargs["conversation_id"],
                "provider": data["provider"],
                "model": data["model"],
                "processing_mode": kwargs["mode"],
            })
            return data

        with tempfile.TemporaryDirectory() as temp_dir:
            runs = Path(temp_dir)
            conversations = runs / "conversations"
            conversations.mkdir()
            with (
                patch.object(main_module, "RUNS", runs),
                patch.object(main_module, "CONVERSATIONS", conversations),
                patch.object(main_module, "execute_once", new=fake_execute_once),
            ):
                response = self.client.post(
                    "/api/chat/stream",
                    json={
                        "message": "offline selected mode",
                        "provider": "openai",
                        "model": "gpt-5.6-terra",
                        "mode": "PLANNED",
                    },
                )
                self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["mode"], "PLANNED")
        self.assertEqual(captured["model_name"], "gpt-5.6-terra")

    def test_product_selection_does_not_mutate_frozen_pilot_identity(self):
        before = (DEFAULT_PILOT_PROVIDER, DEFAULT_PILOT_MODEL, dict(PILOT_GROQ_REQUEST_PARAMETERS))
        self.assertEqual(main_module.validated_model("openai", "gpt-5.6-sol"), "gpt-5.6-sol")
        self.assertEqual(main_module.validated_processing_mode("PARALLEL"), "PARALLEL")
        after = (DEFAULT_PILOT_PROVIDER, DEFAULT_PILOT_MODEL, dict(PILOT_GROQ_REQUEST_PARAMETERS))
        self.assertEqual(after, before)
        self.assertEqual(after[0], "groq")
        self.assertEqual(after[1], "openai/gpt-oss-120b")

    def test_invalid_mode_is_structured_and_no_traceback_is_returned(self):
        response = self.client.post(
            "/api/chat/stream",
            json={"message": "bad mode", "provider": "fake", "mode": "UNKNOWN"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported processing mode selection", response.text)
        self.assertNotIn("Traceback", response.text)


class ProductUiContractTests(unittest.TestCase):
    def test_mode_picker_and_payload_are_present(self):
        root = Path(main_module.__file__).resolve().parents[1]
        html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
        js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="modeChoices"', html)
        self.assertIn('id="settingsModeSummary"', html)
        for mode in ("adaptive-auto", "DIRECT", "PARALLEL", "PLANNED"):
            self.assertIn(mode, js)
        self.assertIn("mode,conversation_id", js)
        self.assertIn("modeText(requestedMode)", js)


if __name__ == "__main__":
    unittest.main()

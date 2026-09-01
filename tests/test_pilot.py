from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

import app.main as main_module
from app.core.pilot import (
    DEFAULT_PILOT_MODEL,
    DEFAULT_PILOT_PROVIDER,
    PILOT_STRATEGIES,
    PilotLedger,
    build_balanced_order_schedule,
    build_pilot_manifest,
    export_processed_dataset,
    pilot_config_snapshot,
    validate_order_schedule,
)
from app.core.orchestrator import Orchestrator
from app.core.rag import frozen_snapshot
from app.core.types import Budget, RunState, Usage
from app.providers.fake import FakeProvider
from app.providers.compatible import OpenAICompatibleProvider


def task_manifest(count: int = 8) -> dict:
    return {
        "manifest_id": "TASK-MANIFEST-TEST-V1",
        "version": "1.0",
        "benchmark_version": "BENCHMARK-TEST-V1",
        "rubric_version_reference": "RUBRIC-TEST-V1",
        "tasks": [
            {
                "task_id": f"T{index}",
                "task_version": "1.0",
                "task_hash": f"task-hash-{index}",
                "reference_manifest_id": "REF-TEST-V1",
                "reference_manifest_version": "1.0",
                "source_document_ids": [f"doc-{index}"],
                "source_document_hashes": [f"doc-hash-{index}"],
                "task_text": "This must not be copied into the run manifest.",
                "hidden_rubric_contents": "This must not be copied into the run manifest.",
            }
            for index in range(1, count + 1)
        ],
    }


class PilotScheduleTests(unittest.TestCase):
    def test_schedule_is_deterministic_balanced_and_sequential(self):
        units = [f"unit-{index}" for index in range(24)]
        first = build_balanced_order_schedule(
            units,
            preregistration_version="PILOT-R1",
            task_manifest_hash="a" * 64,
            seed="fixed-test-seed",
        )
        second = build_balanced_order_schedule(
            units,
            preregistration_version="PILOT-R1",
            task_manifest_hash="a" * 64,
            seed="fixed-test-seed",
        )
        self.assertEqual(first, second)
        self.assertTrue(validate_order_schedule(first, units))
        self.assertEqual([row["unit_id"] for row in first], units)
        position_counts = [
            sum(row["strategy_order"][position] == strategy for row in first)
            for position in range(4)
            for strategy in PILOT_STRATEGIES
        ]
        self.assertEqual(position_counts, [6] * 16)


class PilotManifestTests(unittest.TestCase):
    def test_benchmark_rubric_and_corpus_identity_chain_is_consistent(self):
        root = Path(__file__).resolve().parents[1]
        benchmark_path = root / "benchmarks" / "pilot" / "pilot_benchmark_v1.json"
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        unsigned = dict(benchmark)
        declared_artifact_hash = unsigned.pop("artifact_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), declared_artifact_hash)
        corpus_path = root / "corpus" / "pilot" / "v1" / "CORPUS_MANIFEST.json"
        self.assertEqual(hashlib.sha256(corpus_path.read_bytes()).hexdigest(), benchmark["corpus_manifest_sha256"])
        rubric = json.loads((root / "evaluation" / "pilot" / "pilot_rubrics_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(rubric["benchmark_id"], benchmark["benchmark_id"])
        self.assertEqual(rubric["benchmark_version"], benchmark["benchmark_version"])
        self.assertEqual(rubric["corpus_version"], benchmark["corpus_version"])
        self.assertEqual(rubric["benchmark_binding"]["manifest_artifact_sha256"], declared_artifact_hash)
        self.assertEqual(len(benchmark["tasks"]), 8)
        self.assertEqual(len(rubric["tasks"]), 8)

    def test_manifest_has_unique_conditions_and_no_task_or_rubric_contents(self):
        manifest = build_pilot_manifest(task_manifest(), require_balanced=True)
        self.assertEqual(manifest["expected_comparison_units"], 24)
        self.assertEqual(manifest["expected_strategy_runs"], 96)
        self.assertEqual(manifest["provider"], DEFAULT_PILOT_PROVIDER)
        self.assertEqual(manifest["model"], DEFAULT_PILOT_MODEL)
        condition_keys = []
        for unit in manifest["units"]:
            self.assertEqual(set(unit["strategy_order"]), set(PILOT_STRATEGIES))
            for condition in unit["conditions"]:
                condition_keys.append((unit["unit_id"], condition["strategy"]))
                self.assertIsNone(condition["run_id"])
                self.assertEqual(condition["status"], "missing_not_run")
                self.assertIn("strategy_config_id", condition)
                self.assertIn("context_snapshot_hash", condition)
                self.assertIn("rubric_version_reference", condition)
        self.assertEqual(len(condition_keys), len(set(condition_keys)))
        serialized = json.dumps(manifest, ensure_ascii=False)
        self.assertNotIn("task_text", serialized)
        self.assertNotIn("hidden_rubric_contents", serialized)
        self.assertEqual(manifest["order_policy"]["balance_status"], "balanced")

    def test_manifest_uses_one_authoritative_benchmark_identity(self):
        root = Path(__file__).resolve().parents[1]
        benchmark = json.loads((root / "benchmarks" / "pilot" / "pilot_benchmark_v1.json").read_text(encoding="utf-8"))
        manifest = build_pilot_manifest(benchmark, repeat_count=1, require_balanced=False)
        self.assertEqual(manifest["benchmark_id"], "pilot_benchmark_v1")
        self.assertEqual(manifest["benchmark_version"], "pilot_benchmark_v1@1.1.0")
        self.assertEqual(manifest["benchmark_provenance_version"], "PILOT-R2")
        for unit in manifest["units"]:
            self.assertEqual(unit["benchmark_id"], manifest["benchmark_id"])
            self.assertEqual(unit["benchmark_version"], manifest["benchmark_version"])
            self.assertEqual(unit["benchmark_provenance_version"], "PILOT-R2")
            for condition in unit["conditions"]:
                self.assertEqual(condition["benchmark_id"], manifest["benchmark_id"])
                self.assertEqual(condition["benchmark_version"], manifest["benchmark_version"])

    def test_authorization_snapshots_and_denominator_rules_are_frozen(self):
        root = Path(__file__).resolve().parents[1]
        limits = (root / "docs" / "PILOT_PROVIDER_LIMITS.md").read_text(encoding="utf-8")
        self.assertIn("GROQ-PILOT-LIMITS-V1", limits)
        self.assertIn("RPM=30", limits)
        self.assertIn("RPD=1000", limits)
        self.assertIn("TPM=8000", limits)
        self.assertIn("TPD=200000", limits)
        self.assertIn("SEPARATE_ITPM_OTPM_NOT_VERIFIED", limits)
        config = json.loads((root / "config" / "pilot" / "PILOT_CONFIG_V1.json").read_text(encoding="utf-8"))
        self.assertEqual(config["benchmark_binding"]["benchmark_id"], "pilot_benchmark_v1")
        self.assertEqual(config["benchmark_binding"]["benchmark_version"], "pilot_benchmark_v1@1.1.0")
        self.assertEqual(config["quality_binding"]["rubric_version"], "PILOT-RUBRIC-V1.0")
        self.assertEqual(config["pacing_policy"]["aggregate_token_ceiling_per_minute"], 8000)
        self.assertEqual(config["denominator_policy"]["case_c_strategy_terminal_without_answer"], "strategy_missingness")
        quality = (root / "docs" / "QUALITY_EVALUATION_PROTOCOL.md").read_text(encoding="utf-8")
        for case in ("A. Valid answer", "B. Provider/infrastructure failure", "C. Strategy terminates without evaluable answer", "D. Corrupted/invalid experimental unit", "E. Manually excluded unit"):
            self.assertIn(case, quality)
        self.assertIn("post-hoc winner-dependent denominator", quality)

    def test_config_freezes_groq_settings_and_verified_price_snapshot(self):
        config = pilot_config_snapshot()
        self.assertEqual(config["provider"], "groq")
        self.assertEqual(config["model"], "openai/gpt-oss-120b")
        self.assertEqual(config["identities"]["fixed_config_id"], "FIXED-TOPOLOGY-V1")
        self.assertEqual(config["identities"]["static_config_id"], "STATIC-PRESETS-V1")
        self.assertEqual(config["identities"]["model_pilot_config_id"], "MODEL-PILOT-V1")
        self.assertEqual(config["identities"]["rag_pilot_config_id"], "RAG-PILOT-V1")
        self.assertEqual(config["identities"]["orch_pilot_config_id"], "ORCH-PILOT-V1")
        self.assertEqual(config["identities"]["fixed_pilot_config_id"], "FIXED-PILOT-V1")
        self.assertEqual(config["identities"]["static_pilot_config_id"], "STATIC-PILOT-V1")
        self.assertEqual(config["identities"]["price_pilot_config_id"], "PRICE-PILOT-V1")
        self.assertEqual(config["generation_settings"]["model_settings_version"], "1.1")
        self.assertEqual(config["generation_settings"]["request_parameters"]["temperature"], 0.6)
        self.assertEqual(config["generation_settings"]["request_parameters"]["max_completion_tokens"], 4096)
        self.assertEqual(config["generation_settings"]["request_parameters"]["reasoning_effort"], "medium")
        self.assertEqual(config["generation_settings"]["parameter_status"]["seed"], "UNUSED_BY_DESIGN")
        self.assertEqual(config["generation_settings"]["parameter_status"]["reasoning_format"], "UNSUPPORTED")
        self.assertEqual(
            config["generation_settings"]["parameter_status"]["parallel_tool_calls"],
            "PROVIDER_DEFAULT_TRUE_NO_TOOLS",
        )
        self.assertEqual(
            config["generation_settings"]["parameter_status"]["citation_options"],
            "PROVIDER_DEFAULT_ENABLED_NO_DOCUMENTS_OR_SEARCH",
        )
        self.assertEqual(
            config["generation_settings"]["parameter_status"]["store"],
            "UNSUPPORTED_BY_GROQ",
        )
        self.assertEqual(config["pricing"]["status"], "VERIFIED")
        self.assertTrue(config["pricing"]["allow_cost_calculation"])
        self.assertEqual(config["pricing"]["pricing_id"], "PRICE-PILOT-V1")
        self.assertEqual(config["pricing"]["pricing_version"], "1.1")
        self.assertEqual(config["pricing"]["currency"], "USD")
        self.assertEqual(config["pricing"]["cached_input_usd_per_million_tokens"], 0.075)
        self.assertEqual(config["pricing"]["reasoning_token_rate"], "Unavailable")
        self.assertNotIn("api_key", json.dumps(config, ensure_ascii=False).lower())
        self.assertEqual(config["benchmark_binding"]["benchmark_id"], "pilot_benchmark_v1")
        self.assertEqual(config["benchmark_binding"]["benchmark_version"], "pilot_benchmark_v1@1.1.0")
        self.assertEqual(config["reference_scope_policy"]["whole_document"], "EXPLICIT_ONLY")
        self.assertEqual(config["provider_limits_snapshot"]["itpm_otpm"], "SEPARATE_ITPM_OTPM_NOT_VERIFIED")
        self.assertEqual(config["pacing_policy"]["aggregate_token_ceiling_per_minute"], 8000)

        root = Path(__file__).resolve().parents[1]
        model_file = json.loads((root / "config" / "pilot" / "MODEL_PILOT_V1.json").read_text(encoding="utf-8"))
        price_file = json.loads((root / "config" / "pilot" / "PRICE_PILOT_V1.json").read_text(encoding="utf-8"))
        self.assertEqual(model_file["config_id"], "MODEL-PILOT-V1")
        self.assertEqual(model_file["config_version"], "1.1")
        self.assertEqual(model_file["request_parameters"], config["generation_settings"]["request_parameters"])
        self.assertEqual(model_file["parameter_status"], config["generation_settings"]["parameter_status"])
        self.assertEqual(price_file["pricing_id"], "PRICE-PILOT-V1")
        self.assertEqual(price_file["pricing_version"], "1.1")
        self.assertEqual(price_file["input_usd_per_million_tokens"], config["pricing"]["input_usd_per_million_tokens"])
        self.assertEqual(price_file["cached_input_usd_per_million_tokens"], config["pricing"]["cached_input_usd_per_million_tokens"])
        self.assertEqual(price_file["output_usd_per_million_tokens"], config["pricing"]["output_usd_per_million_tokens"])


class PilotModelAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_frozen_request_parameters_and_usage_breakdown_are_forwarded(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                prompt_tokens_details=SimpleNamespace(cached_tokens=4),
                completion_tokens_details=SimpleNamespace(reasoning_tokens=7),
            ),
            id="chatcmpl-test",
            model="openai/gpt-oss-120b",
        )
        with patch("app.providers.compatible.AsyncOpenAI") as client_factory:
            client = client_factory.return_value
            client.chat.completions.create = AsyncMock(return_value=response)
            provider = OpenAICompatibleProvider(
                name="groq",
                model="openai/gpt-oss-120b",
                api_key="placeholder",
                base_url="https://api.groq.com/openai/v1",
                generation_settings=pilot_config_snapshot()["generation_settings"],
                timeout_seconds=60,
            )
            result = await provider.generate(system="system", user="user")

        request = client.chat.completions.create.await_args.kwargs
        self.assertEqual(request["temperature"], 0.6)
        self.assertEqual(request["max_completion_tokens"], 4096)
        self.assertEqual(request["top_p"], 1.0)
        self.assertEqual(request["reasoning_effort"], "medium")
        self.assertEqual(request["response_format"], {"type": "text"})
        self.assertFalse(request["extra_body"]["include_reasoning"])
        self.assertFalse(request["stream"])
        self.assertEqual(request["n"], 1)
        self.assertEqual(request["service_tier"], "on_demand")
        self.assertNotIn("seed", request)
        self.assertEqual(result.usage.input_tokens, 10)
        self.assertEqual(result.usage.output_tokens, 20)
        self.assertEqual(result.usage.cached_input_tokens, 4)
        self.assertEqual(result.usage.reasoning_tokens, 7)
        self.assertTrue(result.usage_metadata_available)

    def test_verified_groq_cost_uses_cached_input_rate_when_reported(self):
        state = RunState(
            strategy="single",
            provider="groq",
            model="openai/gpt-oss-120b",
            task="task",
            context="context",
        )
        state.usage_metadata_available = True
        state.usage = Usage(100, 200, cached_input_tokens=40, reasoning_tokens=150)
        metrics = Orchestrator(object(), lambda _event: None, budget=Budget()).metrics(state)
        expected = ((60 * 0.15) + (40 * 0.075) + (200 * 0.60)) / 1_000_000
        self.assertEqual(metrics["cached_input_tokens"], 40)
        self.assertEqual(metrics["reasoning_tokens"], 150)
        self.assertEqual(metrics["calculated_cost_usd"], round(expected, 8))


class PilotLedgerTests(unittest.TestCase):
    def _manifest(self):
        return build_pilot_manifest(
            {
                "manifest_id": "DRY-TASK-V1",
                "version": "1.0",
                "benchmark_version": "DRY-RUN-NOT-BENCHMARK",
                "rubric_version_reference": "NOT_APPLICABLE",
                "tasks": [{"task_id": "dry-1", "task_hash": "dry-hash"}],
            },
            repeat_count=1,
            provider="fake",
            model="fake-research-v2",
            dry_run=True,
        )

    def test_interrupted_attempt_gets_new_run_without_overwriting_old_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PilotLedger(Path(directory), self._manifest())
            started = ledger.begin("dry-1-r1", "single", run_id="run_first")
            self.assertEqual(started["run_id"], "run_first")
            reopened = PilotLedger.open(directory)
            recovered = reopened.recover_interrupted()
            self.assertEqual(len(recovered), 1)
            condition = reopened.condition("dry-1-r1", "single")
            self.assertEqual(condition["status"], "missing_not_run")
            self.assertEqual(condition["attempts"][0]["run_id"], "run_first")
            restarted = reopened.begin("dry-1-r1", "single", run_id="run_second")
            raw_path = Path(directory) / restarted["raw_evidence_path"]
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw = {
                "run_id": "run_second",
                "status": "completed",
                "stop_reason": "STOP_SUFFICIENT",
                "provider": "fake",
                "model": "fake-research-v2",
                "snapshot_id": "snap-test",
                "snapshot_hash": "hash-test",
                "metrics": {
                    "agent_executions": 1,
                    "logical_calls": 1,
                    "physical_requests": 1,
                    "usage_metadata_available": False,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "calculated_cost_usd": None,
                },
            }
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            recorded = reopened.record("dry-1-r1", "single", raw_path=raw_path, raw=raw)
            self.assertEqual(recorded["status"], "observed")
            self.assertEqual([item["run_id"] for item in recorded["attempts"]], ["run_first", "run_second"])
            self.assertTrue(reopened.assert_integrity())
            processed = export_processed_dataset(directory, include_dry_run=True)
            rows = [row for row in processed["rows"] if row["strategy"] == "single"]
            self.assertEqual(len(rows), 1)
            attempt_rows = [row for row in processed["attempt_rows"] if row["strategy"] == "single"]
            self.assertEqual(len(attempt_rows), 2)
            self.assertTrue(rows[0]["canonical_attempt"])
            self.assertEqual(processed["benchmark_id"], "DRY-TASK-V1")
            self.assertEqual(processed["benchmark_version"], "DRY-RUN-NOT-BENCHMARK")
            self.assertEqual(rows[-1]["benchmark_id"], "DRY-TASK-V1")
            self.assertIsNone(rows[-1]["input_tokens"])
            self.assertIsNone(rows[-1]["calculated_cost_usd"])

    def test_terminal_condition_cannot_be_started_again(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PilotLedger(Path(directory), self._manifest())
            started = ledger.begin("dry-1-r1", "single", run_id="run_terminal")
            raw_path = Path(directory) / started["raw_evidence_path"]
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw = {"run_id": "run_terminal", "status": "failed", "stop_reason": "STOP_FAILURE"}
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            ledger.record("dry-1-r1", "single", raw_path=raw_path, raw=raw)
            with self.assertRaisesRegex(RuntimeError, "CONDITION_ALREADY_TERMINAL"):
                ledger.begin("dry-1-r1", "single")

    def test_integrity_detects_orphan_raw_and_reports_reconciliation_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = PilotLedger(root, self._manifest())
            (root / "raw").mkdir(parents=True, exist_ok=True)
            (root / "raw" / "run_orphan.json").write_text(json.dumps({"run_id": "run_orphan", "status": "completed"}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "orphan raw evidence"):
                ledger.assert_integrity()

    def test_whole_unit_rerun_creates_new_unit_attempt_without_erasing_old_conditions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = PilotLedger(root, self._manifest())
            first = ledger.begin("dry-1-r1", "single")
            raw_path = root / first["raw_evidence_path"]
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw = {"run_id": first["run_id"], "status": "failed", "provider_incident": True,
                   "provider_error_category": "RATE_LIMITED", "strategy": "single"}
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            ledger.record("dry-1-r1", "single", raw_path=raw_path, raw=raw)
            ledger.mark_unit_incident("dry-1-r1", category="RATE_LIMITED", reason="test")
            with self.assertRaisesRegex(RuntimeError, "WHOLE_UNIT_RERUN_REQUIRED"):
                ledger.begin("dry-1-r1", "single", retry=True)
            attempt = ledger.begin_unit_attempt("dry-1-r1")
            self.assertTrue(attempt["unit_attempt_id"].startswith("ua_"))
            self.assertEqual(ledger.condition("dry-1-r1", "single")["status"], "missing_not_run")
            self.assertEqual(len(ledger.condition("dry-1-r1", "single")["attempts"]), 1)
            summary = ledger.status_summary()
            self.assertEqual(summary["remaining"], 4)
            self.assertEqual(summary["rerunnable"], 0)


class PilotRuntimeTests(unittest.TestCase):
    def test_fake_dry_run_metadata_and_frozen_snapshot_are_persisted(self):
        snapshot, retrieval_meta = frozen_snapshot("dry infrastructure task", "reference text")

        async def run():
            async def sink(_event):
                return None

            return await main_module.execute_once(
                strategy="single",
                provider_name="fake",
                model_name="fake-research-v2",
                message="dry infrastructure task",
                frozen_context=snapshot,
                retrieval_meta=retrieval_meta,
                history=[],
                emit=sink,
                run_id="run_dry_metadata",
                run_metadata={"dry_run": True, "evidence_class": "DRY_RUN", "unit_id": "dry-1-r1"},
            )

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(main_module, "RUNS", Path(directory)),
                patch.object(main_module, "get_provider", return_value=FakeProvider()),
            ):
                data = asyncio.run(run())
            saved = json.loads((Path(directory) / "run_dry_metadata.json").read_text(encoding="utf-8"))
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["evidence_class"], "DRY_RUN")
        self.assertEqual(saved["pilot"]["unit_id"], "dry-1-r1")
        self.assertEqual(saved["snapshot_id"], retrieval_meta["snapshot_id"])

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import app.main as main_module
from app.core.pilot import PilotLedger, build_pilot_manifest, export_processed_dataset
from app.core.pilot_executor import (
    AsyncRequestPacer,
    PilotExecutor,
    PilotExecutorError,
    _runtime_task_records,
    validate_snapshot_completeness,
)
from app.core.pilot_authorization import (
    AUTHORIZED_PILOT_SCOPE,
    LocalPilotUsageLedger,
    PILOT_PACING_POLICY,
    PilotAuthorizationError,
    build_authorization_record,
    build_live_window,
    build_preflight_binding,
)
from app.providers.fake import FakeProvider


def executor_task_manifest(*, provider: str = "fake", model: str = "fake-research-v2") -> dict:
    return {
        "manifest_id": "EXECUTOR-TASK-V1",
        "version": "1.0",
        "benchmark_version": "EXECUTOR-BENCH-V1",
        "rubric_version_reference": "EXECUTOR-RUBRIC-V1",
        "tasks": [{
            "task_id": "EXEC-T1",
            "task_version": "1.0",
            "task_hash": "executor-task-hash",
            "task_text": "Answer from the supplied reference context.",
            "expected_output_instruction": "Use a compact answer.",
            "context": "Executor reference context.",
            "hidden_rubric_contents": "must never reach the runtime",
        }],
    }


def live_controls(manifest: dict, *, before=None, after=None, authorization_status="AUTHORIZED", window_status="ACTIVE"):
    local_zone = timezone(timedelta(hours=7))
    local_now = datetime.now(local_zone)
    preflight = build_preflight_binding(
        preflight_id="preflight-live-test",
        manifest_id=manifest["manifest_id"],
        provider=manifest["provider"],
        model=manifest["model"],
        model_settings_identity=manifest["model_settings_identity"],
        freeze_identity=manifest["freeze_identity"],
        checked_at=datetime.now(timezone.utc),
    )
    authorization = build_authorization_record(
        authorization_id="authorization-live-test",
        manifest_id=manifest["manifest_id"],
        freeze_candidate_id=manifest["freeze_identity"],
        preflight_id=preflight["preflight_id"],
        window_id="window-live-test",
        timestamp=datetime.now(timezone.utc),
        status=authorization_status,
    )
    window = build_live_window(
        "window-live-test",
        before or (local_now - timedelta(minutes=1)),
        after or (local_now + timedelta(hours=1)),
        status=window_status,
        manifest_id=manifest["manifest_id"],
        freeze_candidate_id=manifest["freeze_identity"],
        authorization_id=authorization["authorization_id"],
    )
    return preflight, authorization, window


def make_executor(directory: str, *, provider: str = "fake", model: str = "fake-research-v2", task=None, phase: str | None = None, preflight=None, authorization=None, live_window=None, local_usage_ledger=None):
    task = task or executor_task_manifest(provider=provider, model=model)
    manifest = build_pilot_manifest(
        task,
        repeat_count=1,
        provider=provider,
        model=model,
        require_balanced=False,
    )
    ledger = PilotLedger(Path(directory), manifest)
    selected_phase = phase or ("PREFLIGHT" if provider != "fake" else "PILOT")
    if provider != "fake" and selected_phase == "PILOT" and preflight is not None and preflight.get("binding_schema_id") is None:
        preflight, generated_authorization, generated_window = live_controls(manifest)
        authorization = authorization or generated_authorization
        live_window = live_window or generated_window
    return PilotExecutor(
        ledger,
        task,
        phase=selected_phase,
        allow_live=provider != "fake",
        source_roots=[Path.cwd()],
        preflight=preflight,
        authorization=authorization,
        live_window=live_window,
        local_usage_ledger=local_usage_ledger,
    ), ledger


class PilotExecutorTests(unittest.TestCase):
    def test_request_pacer_honors_retry_after_before_next_request(self):
        async def exercise():
            pacer = AsyncRequestPacer(requests_per_minute=60000, max_in_flight=1, tokens_per_minute=8000)
            pacer.note_retry_after(0.04)
            started = time.perf_counter()
            release = await pacer.acquire()
            release()
            return time.perf_counter() - started

        self.assertGreaterEqual(asyncio.run(exercise()), 0.03)

    def test_snapshot_completeness_validator_covers_all_eight_benchmark_tasks(self):
        root = Path(__file__).resolve().parents[1]
        benchmark = json.loads((root / "benchmarks" / "pilot" / "pilot_benchmark_v1.json").read_text(encoding="utf-8"))
        reports = validate_snapshot_completeness(benchmark, source_roots=[root])
        self.assertEqual(len(reports), 8)
        self.assertTrue(all(item["required_support_present"] for item in reports))
        self.assertTrue(all(item["snapshot_hash"] and item["snapshot_id"] for item in reports))
        self.assertEqual(reports[-1]["truncated"], False)

    def test_snapshot_completeness_fails_closed_when_global_budget_is_too_small(self):
        root = Path(__file__).resolve().parents[1]
        benchmark = json.loads((root / "benchmarks" / "pilot" / "pilot_benchmark_v1.json").read_text(encoding="utf-8"))
        reports = validate_snapshot_completeness(benchmark, source_roots=[root], top_k=1, max_chars=7000)
        target = next(item for item in reports if item["task_id"] == "PILOT-R2-08")
        self.assertFalse(target["required_support_present"])
        self.assertTrue(target["missing_sections"])

    def test_live_pilot_requires_freeze_and_successful_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = build_pilot_manifest(
                executor_task_manifest(provider="groq", model="openai/gpt-oss-120b"),
                provider="groq",
                model="openai/gpt-oss-120b",
                require_balanced=False,
            )
            ledger = PilotLedger(Path(directory), manifest)
            with self.assertRaisesRegex(PilotExecutorError, "FRESH_PILOT_PREFLIGHT_REQUIRED"):
                PilotExecutor(
                    ledger,
                    executor_task_manifest(provider="groq", model="openai/gpt-oss-120b"),
                    phase="PILOT",
                    allow_live=True,
                    source_roots=[Path.cwd()],
                )

    def test_main_phase_requires_a_separate_main_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, ledger = make_executor(directory)
            with self.assertRaisesRegex(PilotExecutorError, "MAIN_FREEZE_REQUIRED"):
                PilotExecutor(
                    ledger,
                    executor.task_manifest,
                    phase="MAIN",
                    source_roots=[Path.cwd()],
                )

    def test_live_pilot_rejects_stale_or_incomplete_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            task = executor_task_manifest(provider="groq", model="openai/gpt-oss-120b")
            manifest = build_pilot_manifest(
                task,
                provider="groq",
                model="openai/gpt-oss-120b",
                require_balanced=False,
            )
            ledger = PilotLedger(Path(directory), manifest)
            stale = {
                "provider": "groq",
                "model": "openai/gpt-oss-120b",
                "error_category": "SUCCESS",
                "result": "PASS",
                "network_reachable": True,
                "authenticated": True,
                "model_access": True,
                "generation_ok": True,
                "settings_identity": "MODEL-SETTINGS-V1",
                "checked_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            }
            with self.assertRaisesRegex(PilotExecutorError, "FRESH_PILOT_PREFLIGHT_REQUIRED"):
                PilotExecutor(
                    ledger,
                    task,
                    phase="PILOT",
                    allow_live=True,
                    source_roots=[Path.cwd()],
                    preflight=stale,
                )

    def test_live_pilot_requires_authorization_and_rejects_invalid_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            task = executor_task_manifest(provider="groq", model="openai/gpt-oss-120b")
            manifest = build_pilot_manifest(
                task,
                provider="groq",
                model="openai/gpt-oss-120b",
                require_balanced=False,
            )
            preflight, authorization, window = live_controls(manifest)
            with self.assertRaisesRegex(PilotExecutorError, "PILOT_AUTHORIZATION_REQUIRED"):
                PilotExecutor(
                    PilotLedger(Path(directory) / "missing", manifest),
                    task,
                    phase="PILOT",
                    allow_live=True,
                    source_roots=[Path.cwd()],
                    preflight=preflight,
                    live_window=window,
                )
            invalid = copy.deepcopy(authorization)
            invalid["authorized_scope"] = "WRONG_SCOPE"
            with self.assertRaisesRegex(PilotExecutorError, "authorization scope"):
                PilotExecutor(
                    PilotLedger(Path(directory) / "invalid", manifest),
                    task,
                    phase="PILOT",
                    allow_live=True,
                    source_roots=[Path.cwd()],
                    preflight=preflight,
                    authorization=invalid,
                    live_window=window,
                )

    def test_live_pilot_blocks_future_and_expired_windows_and_allows_active_window(self):
        with tempfile.TemporaryDirectory() as directory:
            task = executor_task_manifest(provider="groq", model="openai/gpt-oss-120b")
            manifest = build_pilot_manifest(
                task,
                provider="groq",
                model="openai/gpt-oss-120b",
                require_balanced=False,
            )
            local_now = datetime.now(timezone(timedelta(hours=7)))
            for name, before, after, error in (
                ("future", local_now + timedelta(hours=1), local_now + timedelta(hours=2), "NOT_STARTED"),
                ("expired", local_now - timedelta(hours=2), local_now - timedelta(hours=1), "EXPIRED"),
            ):
                preflight, authorization, window = live_controls(
                    manifest,
                    before=before,
                    after=after,
                )
                with self.assertRaisesRegex(PilotExecutorError, error):
                    PilotExecutor(
                        PilotLedger(Path(directory) / name, manifest),
                        task,
                        phase="PILOT",
                        allow_live=True,
                        source_roots=[Path.cwd()],
                        preflight=preflight,
                        authorization=authorization,
                        live_window=window,
                    )
            preflight, authorization, window = live_controls(manifest)
            executor = PilotExecutor(
                PilotLedger(Path(directory) / "active", manifest),
                task,
                phase="PILOT",
                allow_live=True,
                source_roots=[Path.cwd()],
                preflight=preflight,
                authorization=authorization,
                live_window=window,
            )
            self.assertTrue(executor.live_request_gate.validate())

    def test_live_request_gate_enforces_daily_guards_and_records_attempt_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            task = executor_task_manifest(provider="groq", model="openai/gpt-oss-120b")
            manifest = build_pilot_manifest(
                task,
                provider="groq",
                model="openai/gpt-oss-120b",
                require_balanced=False,
            )
            preflight, authorization, window = live_controls(manifest)

            policy = copy.deepcopy(PILOT_PACING_POLICY)
            policy["reserve_policy"]["rpd_reserve_requests"] = 999
            policy["reserve_policy"]["effective_rpd_ceiling"] = 1
            policy["reserve_policy"]["tpd_reserve_tokens"] = 199990
            policy["reserve_policy"]["effective_tpd_ceiling"] = 10
            rpd_usage = LocalPilotUsageLedger(
                Path(directory) / "rpd.json",
                policy=policy,
                window_id=window["window_id"],
            )
            rpd_usage.record(requests=1, tokens=0)
            rpd_executor = PilotExecutor(
                PilotLedger(Path(directory) / "rpd-ledger", manifest),
                task,
                phase="PILOT",
                allow_live=True,
                source_roots=[Path.cwd()],
                preflight=preflight,
                authorization=authorization,
                live_window=window,
                local_usage_ledger=rpd_usage,
            )
            with self.assertRaisesRegex(PilotExecutorError, "LOCAL_RPD_GUARD"):
                asyncio.run(rpd_executor.live_request_gate.bind(
                    unit_id="EXEC-T1-r1",
                    attempt_id="attempt-rpd",
                    condition_id="EXEC-T1-r1::single",
                )())

            policy["reserve_policy"]["rpd_reserve_requests"] = 990
            policy["reserve_policy"]["effective_rpd_ceiling"] = 10
            policy["reserve_policy"]["tpd_reserve_tokens"] = 199999
            policy["reserve_policy"]["effective_tpd_ceiling"] = 1
            tpd_usage = LocalPilotUsageLedger(
                Path(directory) / "tpd.json",
                policy=policy,
                window_id=window["window_id"],
            )
            tpd_usage.record(requests=0, tokens=1)
            tpd_executor = PilotExecutor(
                PilotLedger(Path(directory) / "tpd-ledger", manifest),
                task,
                phase="PILOT",
                allow_live=True,
                source_roots=[Path.cwd()],
                preflight=preflight,
                authorization=authorization,
                live_window=window,
                local_usage_ledger=tpd_usage,
            )
            with self.assertRaisesRegex(PilotExecutorError, "LOCAL_TPD_GUARD"):
                asyncio.run(tpd_executor.live_request_gate.bind(
                    unit_id="EXEC-T1-r1",
                    attempt_id="attempt-tpd",
                    condition_id="EXEC-T1-r1::single",
                )())

            normal_usage = LocalPilotUsageLedger(
                Path(directory) / "normal.json",
                window_id=window["window_id"],
            )
            normal_executor = PilotExecutor(
                PilotLedger(Path(directory) / "normal-ledger", manifest),
                task,
                phase="PILOT",
                allow_live=True,
                source_roots=[Path.cwd()],
                preflight=preflight,
                authorization=authorization,
                live_window=window,
                local_usage_ledger=normal_usage,
            )
            normal_executor.live_request_gate.pacer = AsyncRequestPacer(
                requests_per_minute=60000,
                max_in_flight=1,
                tokens_per_minute=8000,
            )
            bound = normal_executor.live_request_gate.bind(
                unit_id="EXEC-T1-r1",
                attempt_id="attempt-1",
                condition_id="EXEC-T1-r1::single",
            )
            release = asyncio.run(bound())
            release()
            bound.record_tokens(17)
            snapshot = normal_usage.snapshot()
            self.assertEqual(snapshot["requests_consumed"], 1)
            self.assertEqual(snapshot["tokens_consumed"], 17)
            self.assertEqual(snapshot["unknown_token_observations"], 0)
            self.assertEqual(snapshot["provider_remaining_requests"], "UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING")
            self.assertEqual(snapshot["request_observations"][0]["attempt_id"], "attempt-1")

    def test_export_has_one_canonical_row_and_preserves_attempt_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, ledger = make_executor(directory)
            with patch.object(main_module, "get_provider", return_value=FakeProvider()):
                executor.run(limit=4)
            exported = export_processed_dataset(directory, include_dry_run=False)
            self.assertEqual(exported["row_count"], 4)
            exported = export_processed_dataset(directory, include_dry_run=True)
            self.assertEqual(exported["row_count"], 4)
            self.assertEqual(exported["attempt_row_count"], 4)
            self.assertTrue(all(row["canonical_attempt"] for row in exported["rows"]))
    def test_limit_and_manifest_order_are_sequential(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, ledger = make_executor(directory)
            with patch.object(main_module, "get_provider", return_value=FakeProvider()):
                first = executor.run(limit=2)
                second = executor.run(limit=2)
            self.assertEqual(first["executed_count"], 2)
            self.assertEqual(second["executed_count"], 2)
            expected = ledger.manifest["units"][0]["strategy_order"]
            actual = [item["strategy"] for item in first["results"] + second["results"]]
            self.assertEqual(actual, expected)
            self.assertEqual(ledger.status_summary()["completed_count"], 4)

    def test_completed_condition_is_not_called_or_duplicated_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, ledger = make_executor(directory)
            with patch.object(main_module, "get_provider", return_value=FakeProvider()), patch.object(
                main_module, "execute_once", new=AsyncMock(wraps=main_module.execute_once)
            ) as execute_once:
                executor.run(limit=4)
                restarted = executor.run(limit=4)
                self.assertEqual(execute_once.await_count, 4)
            self.assertEqual(restarted["executed_count"], 0)
            self.assertEqual(len(list((Path(directory) / "raw").glob("run_*.json"))), 4)
            self.assertTrue(ledger.assert_integrity())

    def test_interrupted_run_recovers_and_retries_with_a_new_attempt_id(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, ledger = make_executor(directory)
            old = ledger.begin("EXEC-T1-r1", "single", run_id="run_interrupted")
            self.assertEqual(old["run_state"], "RUNNING")
            with patch.object(main_module, "get_provider", return_value=FakeProvider()):
                result = executor.run(limit=1)
            new_id = result["results"][0]["attempt_id"]
            self.assertNotEqual(new_id, "run_interrupted")
            condition = ledger.condition("EXEC-T1-r1", "single")
            self.assertEqual([item["run_id"] for item in condition["attempts"]], ["run_interrupted", new_id])
            self.assertEqual(condition["status"], "observed")
            self.assertTrue((Path(directory) / condition["raw_evidence_path"]).exists())

    def test_provider_failure_is_persisted_and_retry_keeps_both_attempts(self):
        task = executor_task_manifest()
        with tempfile.TemporaryDirectory() as directory:
            executor, ledger = make_executor(
                directory,
                provider="groq",
                model="openai/gpt-oss-120b",
                task=task,
                phase="PILOT",
                preflight={
                    "provider": "groq",
                    "model": "openai/gpt-oss-120b",
                    "error_category": "SUCCESS",
                    "result": "PASS",
                    "network_reachable": True,
                    "authenticated": True,
                    "model_access": True,
                    "generation_ok": True,
                    "settings_identity": "MODEL-SETTINGS-V1",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            with patch.object(main_module, "get_provider", side_effect=ValueError("GROQ_API_KEY is not configured")):
                first = executor.run(limit=1)
                second = executor.run(limit=1)
            self.assertEqual(second["executed_count"], 0)
            # The rerun uses an in-process Fake double; keep the production
            # gate but replace only its pacer with a deterministic fast clock.
            executor.live_request_gate.pacer = AsyncRequestPacer(
                requests_per_minute=60000,
                max_in_flight=3,
                tokens_per_minute=800000,
            )
            def fake_groq():
                provider = FakeProvider()
                provider.name = "groq"
                provider.model = "openai/gpt-oss-120b"
                return provider
            with patch.object(main_module, "get_provider", side_effect=[fake_groq(), fake_groq(), fake_groq(), fake_groq()]):
                retry = executor.run(limit=4, retry_failed=True)
            self.assertEqual(first["results"][0]["run_state"], "PROVIDER_ERROR")
            self.assertEqual(retry["executed_count"], 4)
            condition = ledger.condition("EXEC-T1-r1", first["results"][0]["strategy"])
            self.assertEqual(len(condition["attempts"]), 2)
            self.assertNotEqual(condition["attempts"][0]["run_id"], condition["attempts"][1]["run_id"])
            old_raw = condition["attempts"][0]["raw_evidence_path"]
            raw = json.loads((Path(directory) / old_raw).read_text(encoding="utf-8"))
            self.assertTrue(raw["provider_incident"])
            self.assertEqual(raw["provider_error_category"], "NOT_CONFIGURED")
            self.assertNotIn("groq_test_secret_value", json.dumps(raw))

    def test_snapshot_is_frozen_for_the_whole_unit_and_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, ledger = make_executor(directory)
            with patch.object(main_module, "get_provider", return_value=FakeProvider()):
                executor.run(limit=4)
            conditions = [ledger.condition("EXEC-T1-r1", strategy) for strategy in ("single", "fixed", "static", "adaptive")]
            self.assertEqual({item["context_snapshot_id"] for item in conditions}, {conditions[0]["context_snapshot_id"]})
            self.assertEqual({item["context_snapshot_hash"] for item in conditions}, {conditions[0]["context_snapshot_hash"]})
            with self.assertRaises(RuntimeError):
                ledger.set_unit_snapshot(
                    "EXEC-T1-r1",
                    snapshot_id="snap_different",
                    snapshot_hash="hash_different",
                )

    def test_prefight_rows_are_excluded_from_default_processed_export(self):
        task = executor_task_manifest()
        with tempfile.TemporaryDirectory() as directory:
            executor, _ledger = make_executor(
                directory,
                task=task,
                phase="PREFLIGHT",
            )
            with patch.object(main_module, "get_provider", return_value=FakeProvider()):
                executor.run(limit=1)
            default_export = export_processed_dataset(directory)
            preflight_export = export_processed_dataset(directory, include_preflight=True)
            self.assertFalse(any(row["phase"] == "PREFLIGHT" for row in default_export["rows"]))
            self.assertEqual(sum(row["phase"] == "PREFLIGHT" for row in preflight_export["rows"]), 1)

    def test_runtime_projection_does_not_send_hidden_rubric_content(self):
        task = executor_task_manifest()
        with tempfile.TemporaryDirectory() as directory:
            executor, _ledger = make_executor(directory, task=task)
            captured: list[dict] = []

            async def fake_execute_once(**kwargs):
                captured.append(kwargs)
                return {
                    "run_id": kwargs["run_id"],
                    "strategy": kwargs["strategy"],
                    "provider": "fake",
                    "model": "fake-research-v2",
                    "status": "completed",
                    "stop_reason": "COMPLETED",
                    "snapshot_id": kwargs["retrieval_meta"]["snapshot_id"],
                    "snapshot_hash": kwargs["retrieval_meta"]["snapshot_hash"],
                    "metrics": {"usage_metadata_available": False},
                }

            with patch.object(main_module, "execute_once", side_effect=fake_execute_once):
                executor.run(limit=1)
            self.assertEqual(len(captured), 1)
            self.assertIn("OUTPUT REQUIREMENT", captured[0]["message"])
            self.assertEqual(
                captured[0]["generation_settings"]["model_settings_id"],
                "MODEL-SETTINGS-V1",
            )
            self.assertNotIn("hidden_rubric_contents", captured[0]["message"])
            self.assertNotIn("must never reach the runtime", captured[0]["message"])
            self.assertNotIn("hidden_rubric_contents", captured[0]["frozen_context"])

    def test_benchmark_scope_includes_declared_sections_and_excludes_undeclared(self):
        root = Path(__file__).resolve().parents[1]
        benchmark = json.loads((root / "benchmarks" / "pilot" / "pilot_benchmark_v1.json").read_text(encoding="utf-8"))
        records = _runtime_task_records(benchmark, source_roots=[root])
        context = records["PILOT-R2-01"]["context"]
        self.assertIn("## Runtime structural signals", context)
        self.assertIn("## Verifier and terminal behavior", context)
        self.assertNotIn("## Comparison strategies", context)
        self.assertNotIn("## Measurement definitions", context)
        self.assertEqual(records["PILOT-R2-01"]["reference_scope"][0]["section_ids"], [
            "runtime-structural-signals",
            "rule-based-adaptive-controller",
            "runtime-roles",
            "verifier-and-terminal-behavior",
        ])

    def test_invalid_declared_section_fails_closed(self):
        root = Path(__file__).resolve().parents[1]
        benchmark = json.loads((root / "benchmarks" / "pilot" / "pilot_benchmark_v1.json").read_text(encoding="utf-8"))
        invalid = copy.deepcopy(benchmark)
        invalid["tasks"][0]["reference_bindings"][0]["section_ids"] = ["does-not-exist"]
        with self.assertRaisesRegex(PilotExecutorError, "invalid section"):
            _runtime_task_records(invalid, source_roots=[root])

    def test_explicit_whole_document_binding_is_the_only_full_document_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = "## Included\nkeep this\n\n## Also included\nwhole document is explicit"
            path = root / "source.md"
            path.write_text(source, encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            task_manifest = {
                "manifest_id": "WHOLE-DOC-TEST",
                "version": "1.0",
                "benchmark_version": "WHOLE-DOC-TEST@1.0.0",
                "corpus_manifest": [{"source_id": "doc", "path": "source.md", "sha256": digest}],
                "tasks": [{
                    "task_id": "WHOLE-1",
                    "task_text": "Use the explicitly permitted document.",
                    "reference_source_ids": ["doc"],
                    "reference_bindings": [{"source_id": "doc", "whole_document": True}],
                }],
            }
            record = _runtime_task_records(task_manifest, source_roots=[root])["WHOLE-1"]
            self.assertIn("## Included", record["context"])
            self.assertIn("## Also included", record["context"])
            self.assertTrue(record["reference_scope"][0]["whole_document"])

    def test_source_id_without_binding_cannot_use_inline_context_as_whole_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "source.md"
            path.write_text("## Source\nfull source", encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            task_manifest = {
                "manifest_id": "IMPLICIT-WHOLE-DOC-TEST",
                "version": "1.0",
                "benchmark_version": "IMPLICIT-WHOLE-DOC-TEST@1.0.0",
                "corpus_manifest": [{"source_id": "doc", "path": "source.md", "sha256": digest}],
                "tasks": [{
                    "task_id": "IMPLICIT-1",
                    "task_text": "This source must not bypass scope enforcement.",
                    "reference_source_ids": ["doc"],
                    "context": "inline context that would otherwise hide the full source",
                }],
            }
            with self.assertRaisesRegex(PilotExecutorError, "no explicit section scope"):
                _runtime_task_records(task_manifest, source_roots=[root])

    def test_scoped_snapshot_is_shared_by_all_four_strategies(self):
        root = Path(__file__).resolve().parents[1]
        benchmark = json.loads((root / "benchmarks" / "pilot" / "pilot_benchmark_v1.json").read_text(encoding="utf-8"))
        manifest = build_pilot_manifest(
            benchmark,
            repeat_count=1,
            provider="fake",
            model="fake-research-v2",
            require_balanced=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            ledger = PilotLedger(Path(directory), manifest)
            executor = PilotExecutor(ledger, benchmark, source_roots=[root])
            with patch.object(main_module, "get_provider", return_value=FakeProvider()):
                executor.run(limit=4)
            conditions = [ledger.condition("PILOT-R2-01-r1", strategy) for strategy in ("single", "fixed", "static", "adaptive")]
            self.assertEqual({item["context_snapshot_id"] for item in conditions}, {conditions[0]["context_snapshot_id"]})
            self.assertEqual({item["context_snapshot_hash"] for item in conditions}, {conditions[0]["context_snapshot_hash"]})
            self.assertEqual(conditions[0]["reference_scope"][0]["section_ids"][0], "runtime-structural-signals")
            exported = export_processed_dataset(directory)
            first_row = next(row for row in exported["rows"] if row["strategy"] == "single")
            self.assertTrue(first_row["reference_scope_hash"])
            self.assertIn("contract-v0.6.3:runtime-structural-signals", first_row["reference_section_ids"])


if __name__ == "__main__":
    unittest.main()

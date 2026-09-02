from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from fastapi.testclient import TestClient

from app.core.graph import validate_plan
from app.core.orchestrator import Orchestrator
from app.core.provider_diagnostics import (
    ERROR_CATEGORIES,
    classify_provider_error,
    run_provider_diagnostic,
)
from app.core.incidents import (
    INCIDENT_TAXONOMY_VERSION,
    RUN_OUTCOME_CATEGORIES,
    safe_provider_incident,
)
from app.core.rag import frozen_snapshot
from app.core.types import Budget, ProviderResult, RunState, Usage
from app.core.conversation_repository import JsonConversationRepository
from app.providers.base import Provider
from app.providers.fake import FakeProvider
import app.main as main_module


def analyzer_payload(*, count=1, dependencies=None, verification="low"):
    aspects = [
        {"name": f"aspect_{index}", "goal": f"Solve aspect {index}"}
        for index in range(1, count + 1)
    ]
    return {
        "aspects": aspects,
        "dependencies": dependencies or [],
        "parallelizable_groups": [[item["name"] for item in aspects]] if count > 1 and not dependencies else [],
        "verification_demand": verification,
        "verification_reasons": ["sensitive"] if verification == "high" else [],
        "rationale": "Structural test rationale.",
    }


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(
        self,
        *,
        analyzer=None,
        plan=None,
        verifier=None,
        worker_delay=0.0,
        timeout_role=None,
        error_role=None,
        invalid_analyzer_once=False,
        usage_metadata_available=None,
        model="gemini-3.7-flash",
    ):
        self.model = model
        self.analyzer = analyzer or analyzer_payload()
        self.plan = plan or {"subtasks": [{"id": "S1", "goal": "Solve", "depends_on": []}]}
        self.verifier = list(verifier or [{"status": "PASS", "issues": [], "rationale": "Sufficient"}])
        self.worker_delay = worker_delay
        self.timeout_role = timeout_role
        self.error_role = error_role
        self.invalid_analyzer_once = invalid_analyzer_once
        self.usage_metadata_available = usage_metadata_available
        self.calls = []
        self.system_prompts = []
        self.active_workers = 0
        self.max_active_workers = 0

    def role(self, system):
        if "Structural Analyzer" in system:
            return "Analyzer"
        if "Planner Agent" in system:
            return "Planner"
        if "Runtime Verifier" in system:
            return "Verifier"
        if "Worker Agent" in system:
            return "Worker"
        if "Synthesizer" in system:
            return "Synthesizer"
        if "Direct Solver" in system:
            return "Direct Solver"
        return "Unknown"

    async def generate(self, *, system: str, user: str) -> ProviderResult:
        role = self.role(system)
        self.calls.append((role, user))
        self.system_prompts.append((role, system))
        if role == self.timeout_role:
            await asyncio.sleep(0.2)
        if role == self.error_role:
            raise RuntimeError(f"{role} provider error")
        if role == "Worker":
            self.active_workers += 1
            self.max_active_workers = max(self.max_active_workers, self.active_workers)
            try:
                await asyncio.sleep(self.worker_delay)
            finally:
                self.active_workers -= 1

        if role == "Analyzer":
            if self.invalid_analyzer_once:
                self.invalid_analyzer_once = False
                text = "{}"
            else:
                text = json.dumps(self.analyzer)
        elif role == "Planner":
            text = json.dumps(self.plan)
        elif role == "Verifier":
            value = self.verifier.pop(0) if len(self.verifier) > 1 else self.verifier[0]
            text = json.dumps(value)
        elif role == "Direct Solver":
            text = "Direct answer"
        elif role == "Worker":
            text = "Worker evidence"
        elif role == "Synthesizer":
            text = "Synthesized answer"
        else:
            text = "OK"
        return ProviderResult(
            text=text,
            usage=Usage(11, 7),
            request_id=f"req_{len(self.calls)}",
            model=self.model,
            usage_metadata_available=self.usage_metadata_available,
        )


async def run_adaptive(provider, budget=None):
    emitted = []

    async def emit(event):
        emitted.append(event)

    state = RunState(
        strategy="adaptive",
        provider=provider.name,
        model=provider.model,
        task="Test task",
        context="Frozen test context",
        retrieval_meta={"method": "test", "chunks_total": 1, "chunks_selected": 1},
    )
    orchestrator = Orchestrator(provider, emit, budget=budget or Budget())
    await orchestrator.run(state)
    return state, orchestrator, emitted


async def run_product_auto(provider, *, task="Test task", context="Frozen test context", budget=None):
    emitted = []

    async def emit(event):
        emitted.append(event)

    state = RunState(
        strategy="adaptive",
        provider=provider.name,
        model=provider.model,
        task=task,
        context=context,
        retrieval_meta={"method": "test", "chunks_total": 20, "chunks_selected": 20},
    )
    orchestrator = Orchestrator(
        provider,
        emit,
        budget=budget or Budget(),
        product_auto=True,
    )
    await orchestrator.run(state)
    return state, orchestrator, emitted


async def run_strategy(strategy, provider, *, task="Test task", budget=None):
    emitted = []

    async def emit(event):
        emitted.append(event)

    state = RunState(
        strategy=strategy,
        provider=provider.name,
        model=provider.model,
        task=task,
        context="Frozen test context",
        retrieval_meta={"method": "test", "chunks_total": 1, "chunks_selected": 1},
    )
    orchestrator = Orchestrator(provider, emit, budget=budget or Budget())
    await orchestrator.run(state)
    return state, orchestrator, emitted


class RuntimeFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_answers_current_task_without_history_or_context_contamination(self):
        provider = FakeProvider()
        result = await provider.generate(
            system="You are the Direct Solver.",
            user=(
                "CURRENT USER TASK:\nHãy chào ngắn gọn.\n\n"
                "RECENT CONVERSATION CONTEXT:\nAccess token hết hạn sau bao lâu?\n\n"
                "FROZEN REFERENCE CONTEXT:\nAuthentication, Pagination và Error Handling."
            ),
        )
        self.assertNotIn("60 phút", result.text)
        self.assertNotIn("Authentication:", result.text)

    async def test_fake_worker_output_does_not_leak_internal_prefix(self):
        provider = FakeProvider()
        result = await provider.generate(
            system="You are a Worker Agent.",
            user=(
                "CURRENT USER TASK:\nTheo tài liệu, access token hết hạn sau bao lâu?\n\n"
                "RECENT CONVERSATION CONTEXT:\n(none)\n\n"
                "FROZEN REFERENCE CONTEXT:\nAccess token hết hạn sau 60 phút."
            ),
        )
        self.assertNotIn("Worker result:", result.text)
        self.assertIn("60 phút", result.text)

    async def test_dependency_welcome_example_routes_planned(self):
        provider = FakeProvider()
        state = RunState(
            strategy="adaptive",
            provider=provider.name,
            model=provider.model,
            task=(
                "Phân tích Authentication, Pagination và Error Handling; từ đó lập trình tự kiểm tra, "
                "sau đó kết luận cách xử lý một request lỗi."
            ),
            context="Authentication. Pagination. Error Handling.",
            retrieval_meta={"method": "test", "chunks_total": 1, "chunks_selected": 1},
        )

        async def emit(_event):
            return None

        await Orchestrator(provider, emit, budget=Budget()).run(state)
        route = next(event["meta"]["mode"] for event in state.events if event["title"] == "AUTO route selected")
        self.assertEqual(route, "PLANNED")
        self.assertTrue(any(event["title"] == "DAG validated" for event in state.events))

    async def test_fake_analyzer_focuses_on_task_not_unrelated_context(self):
        emitted = []

        async def emit(event):
            emitted.append(event)

        provider = FakeProvider()
        state = RunState(
            strategy="adaptive",
            provider=provider.name,
            model=provider.model,
            task="Theo tài liệu, access token hết hạn sau bao lâu?",
            context=(
                "Authentication uses Bearer tokens. Public and confidential clients differ.\n\n"
                "Pagination uses cursors.\n\nError handling includes 401 and 429."
            ),
            retrieval_meta={"method": "test", "chunks_total": 3, "chunks_selected": 3},
        )
        orchestrator = Orchestrator(provider, emit, budget=Budget())
        await orchestrator.run(state)
        route = next(event["meta"]["mode"] for event in state.events if event["title"] == "AUTO route selected")
        self.assertEqual(route, "DIRECT")
        self.assertEqual(orchestrator.budget.escalations, 0)
        self.assertEqual(state.stop_reason, "STOP_SUFFICIENT")

    async def test_structural_analyzer_does_not_receive_hidden_task_labels(self):
        provider = ScriptedProvider()
        await run_adaptive(provider)
        analyzer_system = next(system for role, system in provider.system_prompts if role == "Analyzer")
        for hidden_label in ("T1", "T2", "T3", "T4", "Easy/Medium/Hard", "A/N/V/R"):
            self.assertNotIn(hidden_label, analyzer_system)

    async def test_direct_auto_skips_planner_and_stops_sufficient(self):
        provider = ScriptedProvider()
        state, orchestrator, _ = await run_adaptive(provider)
        roles = [role for role, _ in provider.calls]
        self.assertEqual(roles, ["Analyzer", "Direct Solver", "Verifier"])
        self.assertNotIn("Planner", roles)
        self.assertEqual(state.stop_reason, "STOP_SUFFICIENT")
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.agent_executions, 3)
        self.assertEqual(orchestrator.budget.logical_calls, 3)
        self.assertEqual(orchestrator.budget.physical_requests, 3)
        self.assertGreater(orchestrator.metrics(state)["calculated_cost_usd"], 0)

    async def test_product_auto_route_matrix_uses_task_structure_not_context_size(self):
        provider = ScriptedProvider(analyzer=analyzer_payload(count=3))
        orchestrator = Orchestrator(provider, lambda _event: None, budget=Budget(), product_auto=True)
        direct = [
            "Project này sử dụng những công nghệ chính nào?",
            "Entry point của backend nằm ở file nào?",
            "Hãy liệt kê các file trong context và mô tả ngắn vai trò.",
            "Project có những route nào?",
            "style.css và script.js có vai trò gì?",
            "Tóm tắt project cho developer mới.",
            "Đọc tất cả 20 file và tóm tắt.",
        ]
        for task in direct:
            fast = orchestrator.product_auto_fast_path(task)
            mode = fast[0] if fast else orchestrator.choose_product_mode(provider.analyzer, task)[0]
            self.assertEqual(mode, "DIRECT", task)
        self.assertEqual(
            orchestrator.product_auto_fast_path("Entry point của backend nằm ở file nào?" )[0],
            "DIRECT",
        )
        self.assertEqual(
            orchestrator.choose_product_mode(provider.analyzer,
                                             "Phân tích project này.")[0],
            "DIRECT",
        )
        for task in (
            "Đánh giá riêng frontend, backend và deployment của project.",
            "Phân tích độc lập authentication, database access và error handling.",
            "So sánh ba module độc lập theo chức năng, dependency và rủi ro.",
        ):
            self.assertEqual(orchestrator.choose_product_mode(provider.analyzer, task)[0], "PARALLEL", task)
        for task in (
            "Trace luồng từ form người dùng qua backend cho tới result template.",
            "Tìm nguyên nhân lỗi, xác định nơi phát sinh rồi xác định các bước sửa theo dependency.",
            "Xác định entry point, trace startup sequence rồi giải thích thứ tự khởi tạo.",
        ):
            self.assertEqual(orchestrator.choose_product_mode(provider.analyzer, task)[0], "PLANNED", task)
        huge_context = "\n".join(f"file_{index}.py" for index in range(20))
        state, _, _ = await run_product_auto(
            FakeProvider(),
            task="Hãy liệt kê các file bạn thực sự thấy trong context và mô tả ngắn vai trò.",
            context=huge_context,
        )
        route = next(event["meta"]["mode"] for event in state.events if event["title"] == "AUTO route selected")
        self.assertEqual(route, "DIRECT")
        self.assertFalse(any(event["meta"].get("agent_type") == "Analyzer" for event in state.events))

    async def test_product_auto_fast_path_does_not_change_research_adaptive(self):
        product_state, _, _ = await run_product_auto(
            FakeProvider(),
            task="Project này dùng công nghệ gì?",
            context="app.py\nREADME.md\nrequirements.txt",
        )
        product_roles = [event["meta"].get("agent_type") for event in product_state.events if event["kind"] == "agent_start"]
        self.assertEqual(product_roles, ["Direct Solver", "Verifier"])
        research_state, _, _ = await run_adaptive(ScriptedProvider())
        research_roles = [event["meta"].get("agent_type") for event in research_state.events if event["kind"] == "agent_start"]
        self.assertIn("Analyzer", research_roles)

    async def test_e2e_wall_clock_includes_shared_context_preparation(self):
        provider = ScriptedProvider()
        emitted = []

        async def emit(event):
            emitted.append(event)

        context_prep_ms = 75
        state = RunState(
            strategy="single",
            provider=provider.name,
            model=provider.model,
            task="E2E boundary task",
            context="Frozen context",
            retrieval_meta={"context_prep_ms": context_prep_ms, "chunks_total": 1, "chunks_selected": 1},
            # Callers backdate the state boundary by the shared preparation
            # duration so this strategy is charged for context exactly once.
            started_at=time.perf_counter() - context_prep_ms / 1000,
        )
        orchestrator = Orchestrator(provider, emit, budget=Budget())
        await orchestrator.run(state)
        metrics = orchestrator.metrics(state)
        self.assertEqual(metrics["e2e_boundary_version"], "E2E-MEASURE-V2")
        self.assertEqual(metrics["context_prep_ms"], context_prep_ms)
        self.assertGreaterEqual(metrics["e2e_ms"], context_prep_ms - 1)

    async def test_e2e_wall_clock_includes_provider_delay_and_parallel_critical_path(self):
        provider = ScriptedProvider(analyzer=analyzer_payload(count=3), worker_delay=0.10)
        state, orchestrator, _ = await run_adaptive(provider)
        worker_events = [
            event for event in state.events
            if event["kind"] == "agent_end" and event["meta"].get("agent_type") == "Worker"
        ]
        worker_durations = [event["meta"]["duration_ms"] for event in worker_events]
        metrics = orchestrator.metrics(state)
        self.assertEqual(len(worker_durations), 3)
        self.assertGreaterEqual(metrics["e2e_ms"], max(worker_durations))
        self.assertLess(metrics["e2e_ms"], sum(worker_durations))
        self.assertGreaterEqual(metrics["e2e_ms"], 90)
        self.assertEqual(provider.max_active_workers, 3)

    async def test_e2e_wall_clock_includes_retry_backoff(self):
        provider = ScriptedProvider(invalid_analyzer_once=True)
        budget = Budget(max_retries_per_call=1, retry_base_seconds=0.05, retry_max_seconds=0.05)
        state, orchestrator, _ = await run_adaptive(provider, budget)
        metrics = orchestrator.metrics(state)
        self.assertEqual(metrics["retries"], 1)
        self.assertGreaterEqual(metrics["e2e_ms"], 40)

    async def test_all_strategies_use_the_same_e2e_boundary_contract(self):
        metrics_by_strategy = {}
        for strategy in ("single", "fixed", "static", "adaptive"):
            provider = ScriptedProvider()
            state, orchestrator, _ = await run_strategy(strategy, provider)
            metrics_by_strategy[strategy] = orchestrator.metrics(state)
        self.assertEqual(
            {metrics["e2e_boundary_version"] for metrics in metrics_by_strategy.values()},
            {"E2E-MEASURE-V2"},
        )
        self.assertTrue(all(metrics["e2e_ms"] >= 0 for metrics in metrics_by_strategy.values()))

    async def test_fixed_topology_is_identical_across_task_shapes(self):
        plans = [
            {"subtasks": [{"id": "A", "goal": "Lookup", "depends_on": []}]},
            {"subtasks": [
                {"id": "A", "goal": "First", "depends_on": []},
                {"id": "B", "goal": "Second", "depends_on": ["A"]},
                {"id": "C", "goal": "Third", "depends_on": []},
            ]},
            {"subtasks": [
                {"id": "X", "goal": "One", "depends_on": []},
                {"id": "Y", "goal": "Two", "depends_on": []},
                {"id": "Z", "goal": "Three", "depends_on": []},
            ]},
            {"subtasks": [
                {"id": "P", "goal": "Prerequisite", "depends_on": []},
                {"id": "Q", "goal": "Dependent", "depends_on": ["P"]},
            ]},
        ]
        signatures = []
        identities = []
        for index, plan in enumerate(plans, 1):
            provider = ScriptedProvider(plan=plan)
            state, _, _ = await run_strategy("fixed", provider, task=f"Fixed task {index}")
            roles = [role for role, _ in provider.calls]
            self.assertEqual(roles, ["Planner", "Worker", "Worker", "Worker", "Verifier", "Synthesizer"])
            scheduler = [event for event in state.events if event["kind"] == "scheduler"]
            self.assertEqual([event["meta"]["nodes"] for event in scheduler], [["S1", "S2", "S3"]])
            starts = [event for event in state.events
                      if event["kind"] == "agent_start" and event["meta"].get("agent_type") == "Worker"]
            self.assertEqual([event["meta"]["subtask_id"] for event in starts], ["S1", "S2", "S3"])
            self.assertTrue(all(event["meta"]["dependencies"] == [] for event in starts))
            self.assertFalse(any(event["title"] == "AUTO route selected" for event in state.events))
            self.assertFalse(any(event["title"] == "Targeted escalation" for event in state.events))
            identities.append(state.config_identity)
            signatures.append((tuple(roles), tuple(scheduler[0]["meta"]["nodes"]),
                               tuple(state.config_identity["fixed_topology"]["role_sequence"]),
                               state.config_identity["fixed_topology"]["topology_signature"]))
        self.assertEqual(len(set(signatures)), 1)
        self.assertEqual(len({item["strategy_config_id"] for item in identities}), 1)
        self.assertEqual(len({item["strategy_config_version"] for item in identities}), 1)
        self.assertEqual(identities[0]["strategy_config_id"], "FIXED-TOPOLOGY-V1")
        self.assertEqual(identities[0]["fixed_config_id"], "FIXED-TOPOLOGY-V1")
        self.assertEqual(identities[0]["fixed_topology"]["worker_count"], 3)

    async def test_fixed_verifier_needs_work_is_observational_only(self):
        provider = ScriptedProvider(verifier=[{
            "status": "NEEDS_WORK",
            "issues": [{"type": "missing", "description": "Repair", "target": "R"}],
            "rationale": "Candidate needs review",
        }])
        state, _, _ = await run_strategy("fixed", provider)
        roles = [role for role, _ in provider.calls]
        self.assertEqual(roles.count("Verifier"), 1)
        self.assertNotIn("Worker · T1", [role for role, _ in provider.calls])
        self.assertFalse(any(event["title"] == "Targeted escalation" for event in state.events))
        self.assertFalse(state.config_identity["fixed_topology"]["runtime_escalation"])

    async def test_static_selects_one_versioned_preset_without_adaptive_router(self):
        cases = [
            (analyzer_payload(count=1), "STATIC-DIRECT-V1", ["Analyzer", "Direct Solver", "Verifier"]),
            (analyzer_payload(count=3), "STATIC-PARALLEL-V1",
             ["Analyzer", "Worker", "Worker", "Worker", "Synthesizer", "Verifier"]),
            (analyzer_payload(count=3, dependencies=[
                {"from": "aspect_1", "to": "aspect_2", "reason": "prerequisite"},
            ]), "STATIC-PLANNED-V1",
             ["Analyzer", "Planner", "Worker", "Worker", "Worker", "Synthesizer", "Verifier"]),
        ]
        for index, (analysis, preset_id, expected_roles) in enumerate(cases, 1):
            provider = ScriptedProvider(analyzer=analysis)
            emitted = []

            async def emit(event):
                emitted.append(event)

            state = RunState(
                strategy="static", provider=provider.name, model=provider.model,
                task=f"Static task {index}", context="Frozen test context",
                retrieval_meta={"method": "test", "chunks_total": 1, "chunks_selected": 1},
            )
            orchestrator = Orchestrator(provider, emit, budget=Budget())

            def forbidden_adaptive_router(_):
                raise AssertionError("Static must not invoke Adaptive choose_mode")

            orchestrator.choose_mode = forbidden_adaptive_router
            await orchestrator.run(state)
            self.assertEqual([role for role, _ in provider.calls], expected_roles)
            decisions = [event for event in state.events if event["title"] == "Static route frozen"]
            self.assertEqual(len(decisions), 1)
            self.assertEqual(decisions[0]["meta"]["preset_id"], preset_id)
            self.assertEqual(decisions[0]["meta"]["preset_version"], "1.0")
            self.assertEqual(state.config_identity["selected_preset"], preset_id)
            self.assertEqual(state.config_identity["selected_preset_version"], "1.0")
            self.assertEqual(state.config_identity["static_config_id"], "STATIC-PRESETS-V1")
            self.assertFalse(any(event["title"] == "AUTO route selected" for event in state.events))
            self.assertFalse(any(event["title"] == "Targeted escalation" for event in state.events))

    async def test_static_needs_work_does_not_change_preset_or_escalate(self):
        provider = ScriptedProvider(
            analyzer=analyzer_payload(count=3, dependencies=[
                {"from": "aspect_1", "to": "aspect_2", "reason": "prerequisite"},
            ]),
            verifier=[{
                "status": "NEEDS_WORK",
                "issues": [{"type": "missing", "description": "Fix only", "target": "F1"}],
                "rationale": "Static candidate requires review",
            }],
        )
        state, _, _ = await run_strategy("static", provider)
        self.assertEqual(state.config_identity["selected_preset"], "STATIC-PLANNED-V1")
        self.assertEqual([role for role, _ in provider.calls].count("Verifier"), 1)
        self.assertFalse(any(role == "Worker" and "T1" in text for role, text in provider.calls))
        observed = [event for event in state.events if event["title"] == "Static verifier observed"]
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["meta"]["status"], "NEEDS_WORK")
        self.assertFalse(observed[0]["meta"]["adaptive_escalation_allowed"])
        self.assertFalse(any(event["title"] == "Targeted escalation" for event in state.events))

    async def test_static_preset_identity_is_deterministic_for_same_signals(self):
        selected = []
        for _ in range(2):
            provider = ScriptedProvider(analyzer=analyzer_payload(count=3))
            state, _, _ = await run_strategy("static", provider, task="same static task")
            selected.append((state.config_identity["selected_preset"],
                             state.config_identity["selected_preset_version"],
                             state.config_identity["static_preset"]))
        self.assertEqual(selected[0], selected[1])

    async def test_missing_provider_usage_remains_null_not_zero(self):
        provider = ScriptedProvider(usage_metadata_available=False)
        state, orchestrator, _ = await run_adaptive(provider)
        metrics = orchestrator.metrics(state)
        self.assertFalse(metrics["usage_metadata_available"])
        self.assertIsNone(metrics["input_tokens"])
        self.assertIsNone(metrics["output_tokens"])
        self.assertIsNone(metrics["total_tokens"])
        self.assertIsNone(metrics["calculated_cost_usd"])
        ends = [event for event in state.events if event["kind"] == "agent_end"]
        self.assertTrue(all(event["meta"]["total_tokens"] is None for event in ends))

    async def test_agent_execution_evidence_is_distinct_from_calls_and_bounded(self):
        provider = ScriptedProvider()
        state, _, _ = await run_adaptive(provider)
        starts = [event for event in state.events if event["kind"] == "agent_start"]
        ends = [event for event in state.events if event["kind"] == "agent_end"]
        requests = [event for event in state.events if event["kind"] == "provider_request"]
        self.assertEqual(len(starts), state.agent_executions)
        self.assertEqual(len(starts), 3)
        self.assertEqual(len(requests), 3)
        self.assertEqual({event["meta"]["execution_id"] for event in starts}, {"AE-001", "AE-002", "AE-003"})
        for event in starts:
            meta = event["meta"]
            self.assertIn("assigned_goal", meta)
            self.assertIn("dependencies", meta)
            self.assertIn("start_ms", meta)
            self.assertEqual(meta["status"], "running")
        for event in ends:
            meta = event["meta"]
            self.assertIn("end_ms", meta)
            self.assertIn("duration_ms", meta)
            self.assertIn("total_tokens", meta)
            self.assertLessEqual(len(meta["output_preview"]), 320)
            self.assertEqual(meta["status"], "completed")
        self.assertTrue(all("execution_id" in event["meta"] for event in requests))
        self.assertEqual(state.agent_executions, 3)

    async def test_targeted_escalation_evidence_links_issue_to_repair_worker(self):
        provider = ScriptedProvider(
            verifier=[
                {"status": "NEEDS_WORK", "issues": [{"type": "missing", "description": "Fix A", "target": "A"}], "rationale": "Repair required"},
                {"status": "PASS", "issues": [], "rationale": "Repaired"},
            ]
        )
        state, _, _ = await run_adaptive(provider)
        escalation = next(event for event in state.events if event["title"] == "Targeted escalation")
        self.assertEqual(escalation["meta"]["subtasks"][0]["id"], "T1")
        self.assertEqual(escalation["meta"]["subtasks"][0]["goal"], "A")
        repair = next(event for event in state.events if event["kind"] == "agent_start" and event["meta"].get("subtask_id") == "T1")
        self.assertTrue(repair["meta"]["targeted_repair"])
        self.assertEqual(repair["meta"]["escalation_issue"], "A")
        verification = [event for event in state.events if event["kind"] == "verification"]
        self.assertTrue(verification[0]["meta"]["targeted_repair"] is False)
        self.assertTrue(verification[-1]["meta"]["targeted_repair"] is True)

    async def test_parallel_workers_run_concurrently_without_planner(self):
        provider = ScriptedProvider(analyzer=analyzer_payload(count=3), worker_delay=0.05)
        state, _, _ = await run_adaptive(provider)
        roles = [role for role, _ in provider.calls]
        self.assertNotIn("Planner", roles)
        self.assertEqual(roles.count("Worker"), 3)
        self.assertEqual(provider.max_active_workers, 3)
        scheduler = [event for event in state.events if event["kind"] == "scheduler"]
        self.assertTrue(scheduler[0]["meta"]["parallel"])
        worker_starts = [event["meta"]["start_ms"] for event in state.events
                         if event["kind"] == "agent_start" and event["meta"].get("agent_type") == "Worker"]
        worker_ends = [event["meta"]["end_ms"] for event in state.events
                       if event["kind"] == "agent_end" and event["meta"].get("agent_type") == "Worker"]
        self.assertLess(max(worker_starts), min(worker_ends))
        self.assertEqual(state.stop_reason, "STOP_SUFFICIENT")

    async def test_planned_mode_validates_and_schedules_dependencies(self):
        plan = {
            "subtasks": [
                {"id": "S1", "goal": "First", "depends_on": []},
                {"id": "S2", "goal": "Second", "depends_on": ["S1"]},
                {"id": "S3", "goal": "Independent", "depends_on": []},
            ]
        }
        provider = ScriptedProvider(
            analyzer=analyzer_payload(
                count=3,
                dependencies=[{"from": "aspect_1", "to": "aspect_2", "reason": "prerequisite"}],
            ),
            plan=plan,
        )
        state, _, _ = await run_adaptive(provider)
        roles = [role for role, _ in provider.calls]
        self.assertIn("Planner", roles)
        self.assertTrue(any(event["title"] == "DAG validated" for event in state.events))
        batches = [event["meta"]["nodes"] for event in state.events if event["kind"] == "scheduler"]
        self.assertEqual(batches, [["S1", "S3"], ["S2"]])
        starts = {event["meta"]["subtask_id"]: event["meta"]["start_ms"] for event in state.events
                  if event["kind"] == "agent_start" and event["meta"].get("subtask_id")}
        ends = {event["meta"]["subtask_id"]: event["meta"]["end_ms"] for event in state.events
                if event["kind"] == "agent_end" and event["meta"].get("subtask_id")}
        self.assertLessEqual(ends["S1"], starts["S2"])

    async def test_needs_work_targets_independent_fixes_concurrently(self):
        provider = ScriptedProvider(
            verifier=[
                {
                    "status": "NEEDS_WORK",
                    "issues": [
                        {"type": "missing", "description": "Fix A", "target": "A"},
                        {"type": "conflict", "description": "Fix B", "target": "B"},
                    ],
                    "rationale": "Repair required",
                },
                {"status": "PASS", "issues": [], "rationale": "Repaired"},
            ],
            worker_delay=0.05,
        )
        state, orchestrator, _ = await run_adaptive(provider)
        self.assertEqual(provider.max_active_workers, 2)
        self.assertEqual(orchestrator.budget.escalations, 1)
        self.assertEqual(state.stop_reason, "STOP_SUFFICIENT")
        self.assertTrue(any(event["title"] == "Targeted escalation" for event in state.events))

    async def test_fail_verdict_does_not_escalate(self):
        provider = ScriptedProvider(
            verifier=[{"status": "FAIL", "issues": [{"type": "unsupported"}], "rationale": "Bad"}]
        )
        state, orchestrator, _ = await run_adaptive(provider)
        self.assertEqual(orchestrator.budget.escalations, 0)
        self.assertEqual(state.stop_reason, "STOP_BUDGET_OR_VERIFICATION")

    async def test_structured_output_retry_is_one_logical_call_two_requests(self):
        provider = ScriptedProvider(invalid_analyzer_once=True)
        budget = Budget(max_retries_per_call=1)
        state, orchestrator, _ = await run_adaptive(provider, budget)
        self.assertEqual([role for role, _ in provider.calls].count("Analyzer"), 2)
        self.assertEqual(orchestrator.budget.logical_calls, 3)
        self.assertEqual(orchestrator.budget.physical_requests, 4)
        self.assertEqual(state.agent_executions, 3)
        self.assertEqual(state.usage.total_tokens, 72)
        self.assertTrue(any(event["kind"] == "retry" for event in state.events))

    async def test_timeout_stops_failed_run(self):
        provider = ScriptedProvider(timeout_role="Direct Solver")
        budget = Budget(max_retries_per_call=0, call_timeout_seconds=0.01)
        state, orchestrator, _ = await run_adaptive(provider, budget)
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.stop_reason, "STOP_FAILURE")
        self.assertEqual(orchestrator.budget.physical_requests, 2)

    async def test_verifier_failure_preserves_candidate_as_degraded_final(self):
        provider = ScriptedProvider(error_role="Verifier")
        state, orchestrator, emitted = await run_adaptive(provider)
        self.assertEqual(state.status, "degraded")
        self.assertEqual(state.stop_reason, "STOP_VERIFICATION_UNAVAILABLE")
        self.assertEqual(state.answer, "Direct answer")
        final = next(event for event in emitted if event["type"] == "final")
        self.assertEqual(final["answer"], "Direct answer")
        self.assertEqual(final["status"], "degraded")
        self.assertEqual(final["provider"], "scripted")
        self.assertEqual(final["model"], provider.model)

    async def test_logical_budget_stops_before_solver(self):
        provider = ScriptedProvider()
        budget = Budget(max_logical_calls=1, max_retries_per_call=0)
        state, _, _ = await run_adaptive(provider, budget)
        self.assertEqual(state.status, "stopped")
        self.assertEqual(state.stop_reason, "STOP_BUDGET_LOGICAL_CALLS")

    async def test_physical_budget_stops_with_explicit_terminal_state(self):
        provider = ScriptedProvider()
        budget = Budget(max_physical_requests=1, max_retries_per_call=0)
        state, orchestrator, _ = await run_adaptive(provider, budget)
        self.assertEqual(state.status, "stopped")
        self.assertEqual(state.stop_reason, "STOP_BUDGET_PHYSICAL_REQUESTS")
        self.assertEqual(orchestrator.budget.physical_requests, 1)


class GraphAndRagTests(unittest.TestCase):
    def test_retry_delay_uses_provider_retry_hint(self):
        request = httpx.Request("POST", "https://provider.invalid/generate")
        response = httpx.Response(
            429,
            request=request,
            json={"error": {"details": [{"retryDelay": "17s"}]}},
        )
        error = httpx.HTTPStatusError("rate limited", request=request, response=response)
        provider = ScriptedProvider()

        async def sink(_):
            return None

        orchestrator = Orchestrator(provider, sink, budget=Budget())
        self.assertEqual(orchestrator._retry_delay(error, 0), 17.0)

    def test_dag_rejects_cycle_and_unknown_dependency(self):
        with self.assertRaisesRegex(ValueError, "Cycle detected"):
            validate_plan([
                {"id": "A", "depends_on": ["B"]},
                {"id": "B", "depends_on": ["A"]},
            ])
        with self.assertRaisesRegex(ValueError, "Unknown dependency"):
            validate_plan([{"id": "A", "depends_on": ["missing"]}])

    def test_frozen_rag_snapshot_is_deterministic_and_selective(self):
        source = "\n\n".join(
            f"Chunk {index}: topic_{index} " + (f"detail_{index} " * 80)
            for index in range(12)
        )
        first, first_meta = frozen_snapshot("Explain topic_9", source, top_k=2, max_chars=1200)
        second, second_meta = frozen_snapshot("Explain topic_9", source, top_k=2, max_chars=1200)
        self.assertEqual(first, second)
        self.assertEqual(
            {key: value for key, value in first_meta.items() if key != "created_at"},
            {key: value for key, value in second_meta.items() if key != "created_at"},
        )
        self.assertEqual(first_meta["method"], "lexical-overlap-v1")
        self.assertEqual(first_meta["retrieval_config_id"], "RAG-LEXICAL-V1")
        self.assertIn("topic_9", first)
        self.assertEqual(first_meta["chunks_selected"], 2)
        self.assertTrue(first_meta["snapshot_id"].startswith("snap_"))
        self.assertEqual(first_meta["snapshot_id"], second_meta["snapshot_id"])
        self.assertEqual(first_meta["context_hash"], second_meta["context_hash"])
        self.assertEqual(first_meta["source_document_ids"], second_meta["source_document_ids"])
        self.assertEqual(first_meta["chunk_ids"], second_meta["chunk_ids"])
        self.assertEqual(first_meta["retrieval_settings"]["top_k"], 2)
        self.assertTrue(first_meta["source_documents"][0]["document_id"].startswith("doc_"))
        self.assertIn("created_at", first_meta)

    def test_frozen_rag_records_explicit_truncation(self):
        source = "topic_9 detail " * 300
        snapshot, meta = frozen_snapshot("Explain topic_9", source, top_k=2, max_chars=120)
        self.assertEqual(len(snapshot), 120)
        self.assertTrue(meta["truncation"]["applied"])
        self.assertEqual(meta["truncation"]["reason"], "max_chars")
        self.assertEqual(meta["truncation"]["original_chars"], len(source.strip()))
        self.assertEqual(meta["truncation"]["context_chars"], len(snapshot))
        self.assertGreater(meta["truncation"]["dropped_chars"], 0)


class ProviderDiagnosticTests(unittest.TestCase):
    @staticmethod
    def http_error(status, payload):
        request = httpx.Request("POST", "https://provider.invalid/generate")
        response = httpx.Response(status, request=request, json=payload)
        return httpx.HTTPStatusError("provider response", request=request, response=response)

    def test_error_taxonomy_covers_every_failure_category(self):
        cases = [
            ("NOT_CONFIGURED", ValueError("GEMINI_API_KEY is not configured")),
            ("NETWORK_BLOCKED", PermissionError("Outbound network access is blocked")),
            ("DNS_ERROR", socket.gaierror(-2, "Name or service not known")),
            ("TIMEOUT", TimeoutError("provider timed out")),
            ("AUTHENTICATION_FAILED", self.http_error(401, {"error": {"code": "invalid_api_key"}})),
            ("PERMISSION_DENIED", self.http_error(403, {"error": {"code": "permission_denied"}})),
            ("MODEL_NOT_FOUND", self.http_error(404, {"error": {"code": "model_not_found"}})),
            ("RATE_LIMITED", self.http_error(429, {"error": {"code": "rate_limit_exceeded"}})),
            ("QUOTA_EXHAUSTED", self.http_error(429, {"error": {"code": "insufficient_quota"}})),
            ("CREDIT_EXHAUSTED", self.http_error(400, {"error": {"code": "credit_balance_exhausted"}})),
            ("PROVIDER_ERROR", self.http_error(500, {"error": {"code": "internal_error"}})),
        ]
        seen = set()
        for expected, error in cases:
            with self.subTest(category=expected):
                category, safe_message = classify_provider_error(error)
                self.assertEqual(category, expected)
                self.assertTrue(safe_message)
                self.assertNotIn("provider.invalid", safe_message)
                seen.add(category)
        self.assertEqual(seen, set(ERROR_CATEGORIES) - {"SUCCESS"})

    def test_wrapped_sdk_connection_error_is_network_blocked(self):
        # OpenAI-compatible SDKs wrap httpx transport failures in an
        # APIConnectionError.  Classification must inspect the exception
        # chain instead of turning a blocked connection into PROVIDER_ERROR.
        wrapped = RuntimeError("Connection error.")
        wrapped.__cause__ = httpx.ConnectError("All connection attempts failed")
        category, safe_message = classify_provider_error(wrapped)
        self.assertEqual(category, "NETWORK_BLOCKED")
        self.assertEqual(safe_message, "Outbound network access is blocked; run the smoke command on a network-enabled machine.")

    def test_raw_provider_incident_is_structured_without_body_or_sensitive_headers(self):
        request = httpx.Request("POST", "https://provider.invalid/generate")
        response = httpx.Response(
            429,
            request=request,
            headers={
                "retry-after": "12",
                "x-ratelimit-limit-requests": "30",
                "authorization": "Bearer should-never-be-copied",
                "x-secret-body": "not allowed",
                "x-request-id": "req-safe-123",
            },
            json={"error": {"code": "rate_limit_exceeded", "body_secret": "do-not-persist"}},
        )
        error = httpx.HTTPStatusError("provider response body_secret=do-not-persist", request=request, response=response)
        record = safe_provider_incident(
            error,
            provider="groq",
            model="openai/gpt-oss-120b",
            attempt=2,
            retry=1,
        )
        self.assertEqual(record["taxonomy_version"], INCIDENT_TAXONOMY_VERSION)
        self.assertEqual(record["category"], "RATE_LIMITED")
        self.assertEqual(record["http_status"], 429)
        self.assertEqual(record["retry_after_seconds"], 12.0)
        self.assertEqual(record["request_id"], "req-safe-123")
        encoded = json.dumps(record, ensure_ascii=False)
        self.assertNotIn("body_secret", encoded)
        self.assertNotIn("authorization", encoded.lower())
        self.assertNotIn("do-not-persist", encoded)
        self.assertNotIn("should-never-be-copied", encoded)

    def test_run_outcome_taxonomy_has_strategy_and_infrastructure_categories(self):
        self.assertIn("SUCCESS", RUN_OUTCOME_CATEGORIES)
        self.assertIn("STRATEGY_TERMINAL_FAILURE", RUN_OUTCOME_CATEGORIES)
        self.assertIn("EXPERIMENT_INFRASTRUCTURE_ERROR", RUN_OUTCOME_CATEGORIES)
        self.assertIn("INTERRUPTED_OR_STALE", RUN_OUTCOME_CATEGORIES)

    def test_fake_provider_returns_normalized_success(self):
        async def run():
            return await run_provider_diagnostic(
                provider_name="fake",
                configured=True,
                model="fake-research-v2",
                provider_factory=main_module.get_provider,
                timeout_seconds=2,
            )

        diagnostic = asyncio.run(run())
        self.assertEqual(set(diagnostic), {
            "provider", "configured", "network_reachable", "authenticated", "model_access",
            "generation_ok", "usage_metadata_available", "latency_ms", "error_category", "safe_message",
        })
        self.assertEqual(diagnostic["provider"], "fake")
        self.assertTrue(diagnostic["configured"])
        self.assertTrue(diagnostic["generation_ok"])
        self.assertTrue(diagnostic["usage_metadata_available"])
        self.assertEqual(diagnostic["error_category"], "SUCCESS")

    def test_unconfigured_provider_does_not_call_factory(self):
        calls = []

        def factory(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("unconfigured provider must not be constructed")

        async def run():
            return await run_provider_diagnostic(
                provider_name="groq",
                configured=False,
                model=None,
                provider_factory=factory,
                timeout_seconds=2,
            )

        diagnostic = asyncio.run(run())
        self.assertEqual(diagnostic["error_category"], "NOT_CONFIGURED")
        self.assertFalse(diagnostic["configured"])
        self.assertFalse(diagnostic["generation_ok"])
        self.assertEqual(calls, [])


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def test_chat_always_dispatches_adaptive_and_hides_baseline_choice(self):
        seen = []

        async def fake_execute_once(**kwargs):
            seen.append(kwargs["strategy"])
            await kwargs["emit"]({
                "type": "final",
                "answer": "ok",
                "status": "completed",
                "stop_reason": "STOP_SUFFICIENT",
                "metrics": {},
                "run_id": "run_test",
            })
            return {}

        with tempfile.TemporaryDirectory() as temp_dir:
            conversation_dir = Path(temp_dir) / "conversations"
            conversation_dir.mkdir()
            with (
                patch.object(main_module, "CONVERSATIONS", conversation_dir),
                patch.object(main_module, "execute_once", new=fake_execute_once),
            ):
                response = self.client.post(
                    "/api/chat/stream",
                    # An untrusted client must not be able to turn normal chat
                    # into a research-baseline run.
                    json={
                        "message": "hello",
                        "context": "reference",
                        "provider": "fake",
                        "strategy": "single",
                    },
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen, ["adaptive"])
        frontend = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Chọn provider, model và chế độ xử lý riêng cho từng lượt chat", frontend)
        self.assertNotIn('id="strategy"', frontend)

    def test_compare_strategy_names_remain_distinct_in_execution(self):
        provider = ScriptedProvider()

        async def sink(_):
            return None

        async def run_all():
            results = []
            for strategy in ("single", "fixed", "static", "adaptive"):
                results.append(await main_module.execute_once(
                    strategy=strategy,
                    provider_name="fake",
                    message="strategy identity task",
                    frozen_context="Frozen context",
                    retrieval_meta={"method": "test", "chunks_total": 1, "chunks_selected": 1},
                    history=[],
                    emit=sink,
                ))
            return results

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(main_module, "RUNS", Path(temp_dir)),
                patch.object(main_module, "get_provider", return_value=provider),
            ):
                results = asyncio.run(run_all())
        self.assertEqual(
            [result["strategy"] for result in results],
            ["single", "fixed", "static", "adaptive"],
        )
        self.assertEqual(
            {result["strategy"] for result in results},
            {"single", "fixed", "static", "adaptive"},
        )

    def test_compare_is_sequential_and_reuses_one_snapshot(self):
        calls = []
        active = 0
        max_active = 0

        async def fake_execute_once(**kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            calls.append((kwargs["strategy"], kwargs["frozen_context"], kwargs["retrieval_meta"],
                          kwargs["model_name"], kwargs["budget_config"], kwargs["comparison_meta"]))
            await asyncio.sleep(0.01)
            active -= 1
            return {
                "run_id": f"run_{kwargs['strategy']}",
                "status": "completed",
                "stop_reason": "COMPLETED",
                "answer": f"Answer for {kwargs['strategy']}",
                "metrics": {"agent_executions": 1, "logical_calls": 1, "physical_requests": 1,
                             "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                             "e2e_ms": 1, "calculated_cost_usd": 0,
                             "usage_metadata_available": False},
                "snapshot_id": kwargs["retrieval_meta"]["snapshot_id"],
                "snapshot_hash": kwargs["retrieval_meta"]["snapshot_hash"],
                "context_hash": kwargs["retrieval_meta"]["context_hash"],
            }

        with patch.object(main_module, "execute_once", new=fake_execute_once):
            response = self.client.post(
                "/api/compare/stream",
                json={"message": "topic 8", "context": "topic 8 reference", "provider": "fake"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item[0] for item in calls], ["single", "fixed", "static", "adaptive"])
        self.assertEqual(max_active, 1)
        self.assertEqual(len({item[1] for item in calls}), 1)
        self.assertEqual(len({json.dumps(item[2], sort_keys=True) for item in calls}), 1)
        self.assertEqual(len({item[2]["snapshot_id"] for item in calls}), 1)
        self.assertEqual(len({item[2]["context_hash"] for item in calls}), 1)
        self.assertTrue(calls[0][2]["chunk_ids"] == calls[-1][2]["chunk_ids"])
        self.assertEqual(len({item[3] for item in calls}), 1)
        self.assertEqual(len({json.dumps(item[4], sort_keys=True) for item in calls}), 1)
        self.assertEqual([item[5]["order"] for item in calls], [1, 2, 3, 4])
        self.assertEqual(len({item[5]["comparison_id"] for item in calls}), 1)
        events = [json.loads(line) for line in response.text.splitlines() if line]
        results = [event["result"] for event in events if event["type"] == "compare_result"]
        self.assertEqual(len(results), 4)
        self.assertEqual([item["answer"] for item in results], [f"Answer for {strategy}" for strategy in ("single", "fixed", "static", "adaptive")])
        self.assertTrue(all(item["quality_evaluation"] == "Not evaluated" for item in results))
        self.assertTrue(all(item["metrics"]["input_tokens"] is None for item in results))
        self.assertTrue(all(item["metrics"]["calculated_cost_usd"] is None for item in results))
        self.assertEqual(len({item["snapshot_id"] for item in results}), 1)
        self.assertEqual(len({item["snapshot_hash"] for item in results}), 1)
        self.assertEqual(len({item["context_hash"] for item in results}), 1)
        final = next(event for event in events if event["type"] == "compare_final")
        self.assertEqual(final["snapshot_id"], results[0]["snapshot_id"])
        self.assertEqual(final["snapshot_hash"], results[0]["snapshot_hash"])
        self.assertEqual(final["context_hash"], results[0]["context_hash"])

    def test_compare_failure_persists_four_distinct_raw_runs(self):
        async def failing_execute_once(**kwargs):
            raise RuntimeError("provider construction failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(main_module, "RUNS", Path(temp_dir)),
                patch.object(main_module, "execute_once", new=failing_execute_once),
            ):
                response = self.client.post(
                    "/api/compare/stream",
                    json={"message": "failure compare", "context": "same reference", "provider": "fake"},
                )
            self.assertEqual(response.status_code, 200)
            events = [json.loads(line) for line in response.text.splitlines() if line]
            results = [event["result"] for event in events if event["type"] == "compare_result"]
            self.assertEqual([item["strategy"] for item in results], ["single", "fixed", "static", "adaptive"])
            self.assertEqual(len({item["run_id"] for item in results}), 4)
            self.assertTrue(all(item["status"] == "failed" for item in results))
            self.assertTrue(all(item["answer"] is None for item in results))
            self.assertTrue(all(item["metrics"]["input_tokens"] is None for item in results))
            self.assertTrue(all(item["metrics"]["output_tokens"] is None for item in results))
            self.assertTrue(all(item["metrics"]["total_tokens"] is None for item in results))
            self.assertTrue(all(item["metrics"]["calculated_cost_usd"] is None for item in results))
            self.assertEqual(len({item["snapshot_hash"] for item in results}), 1)
            for item in results:
                raw_path = Path(temp_dir) / f"{item['run_id']}.json"
                self.assertTrue(raw_path.exists())
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                self.assertEqual(raw["strategy"], item["strategy"])
                self.assertEqual(raw["status"], "failed")
                self.assertEqual(raw["snapshot_hash"], results[0]["snapshot_hash"])
                self.assertEqual(raw["comparison"]["comparison_id"], item["comparison"]["comparison_id"])
                self.assertEqual(raw["strategy_config_id"], item["strategy_config_id"])
                self.assertEqual(raw["strategy_config_version"], "1.0")
                self.assertEqual(raw["config_identity"]["strategy_config_id"], item["strategy_config_id"])

    def test_config_and_frontend_do_not_expose_configured_secrets(self):
        response = self.client.get("/api/config")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["chat_strategy"], "adaptive-auto")
        self.assertNotIn("keys", payload)
        root = Path(main_module.__file__).resolve().parents[1]
        frontend = "\n".join(
            (root / "app" / "static" / name).read_text(encoding="utf-8")
            for name in ("index.html", "app.js")
        )
        secrets = [os.getenv("GEMINI_API_KEY", ""), os.getenv("OPENAI_API_KEY", "")]
        if any(secret and secret in response.text for secret in secrets):
            self.fail("A configured provider secret was returned by /api/config")
        if any(secret and secret in frontend for secret in secrets):
            self.fail("A configured provider secret was found in frontend assets")
        ignore_lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".env", [line.strip() for line in ignore_lines])

    def test_config_exposes_safe_model_choices_and_rejects_unknown_model(self):
        payload = self.client.get("/api/config").json()
        gemini_ids = [item["id"] for item in payload["model_options"]["gemini"]]
        self.assertIn("gemini-3.7-flash", gemini_ids)
        self.assertIn("gemini-3.5-flash-lite", gemini_ids)
        response = self.client.post(
            "/api/chat/stream",
            json={"message": "hello", "provider": "fake", "model": "provider/unknown"},
        )
        self.assertIn("Unsupported model selection", response.text)

    def test_provider_diagnostic_endpoint_has_normalized_schema(self):
        response = self.client.post(
            "/api/provider/diagnostic",
            json={"provider": "fake", "model": "fake-research-v2"},
        )
        self.assertEqual(response.status_code, 200)
        diagnostic = response.json()
        self.assertEqual(set(diagnostic), {
            "provider", "configured", "network_reachable", "authenticated", "model_access",
            "generation_ok", "usage_metadata_available", "latency_ms", "error_category", "safe_message",
        })
        self.assertEqual(diagnostic["error_category"], "SUCCESS")
        self.assertTrue(diagnostic["generation_ok"])

    def test_provider_diagnostic_missing_key_is_truthful_and_safe(self):
        with (
            patch.object(main_module, "provider_configured", return_value=False),
            patch.object(main_module, "write_provider_status") as write_status,
            patch.object(main_module, "get_provider") as factory,
        ):
            response = self.client.post(
                "/api/provider/test",
                json={"provider": "groq", "model": "openai/gpt-oss-20b"},
            )
        self.assertEqual(response.status_code, 200)
        diagnostic = response.json()
        self.assertEqual(diagnostic["error_category"], "NOT_CONFIGURED")
        self.assertFalse(diagnostic["configured"])
        factory.assert_not_called()
        write_status.assert_called_once()

    def test_provider_diagnostic_maps_credit_exhaustion_without_raw_error(self):
        request = httpx.Request("POST", "https://provider.invalid/generate")
        response_body = {"error": {"code": "credit_balance_exhausted", "message": "provider-test-secret"}}
        response = httpx.Response(400, request=request, json=response_body)
        provider_error = httpx.HTTPStatusError("credit balance exhausted provider-test-secret", request=request, response=response)
        with (
            patch.object(main_module, "provider_configured", return_value=True),
            patch.object(main_module, "validated_model", return_value="gpt-5.6-luna"),
            patch.object(main_module, "get_provider", side_effect=provider_error),
            patch.object(main_module, "write_provider_status"),
        ):
            result = self.client.post(
                "/api/provider/test",
                json={"provider": "openai", "model": "gpt-5.6-luna"},
            )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["error_category"], "CREDIT_EXHAUSTED")
        self.assertNotIn("provider-test-secret", result.text)

    def test_local_ui_contract_disables_stale_browser_cache(self):
        health = self.client.get("/api/health")
        config = self.client.get("/api/config")
        home = self.client.get("/")
        script = self.client.get("/static/app.js")
        style = self.client.get("/static/styles.css")
        self.assertEqual(health.json()["version"], main_module.APP_VERSION)
        self.assertEqual(config.json()["app_version"], main_module.APP_VERSION)
        for response in (health, config, home, script, style):
            self.assertEqual(response.headers.get("cache-control"), "no-store, max-age=0")
            self.assertEqual(response.headers.get("pragma"), "no-cache")
        self.assertEqual(
            config.json()["context_file_extensions"],
            ["txt", "md", "py", "js", "ts", "json", "html", "css", "csv"],
        )
        self.assertIn('id="contextFile" type="file" multiple', home.text)
        self.assertNotIn("legacy API contract", home.text)
        self.assertIn('id="contextProvenance"', home.text)

    def test_two_turns_persist_under_one_conversation(self):
        seen_histories = []

        async def fake_execute_once(**kwargs):
            seen_histories.append(list(kwargs["history"]))
            data = {
                "run_id": f"run_turn_{len(seen_histories)}",
                "strategy": "adaptive",
                "provider": "fake",
                "model": "fake-research-v2",
                "answer": f"answer {len(seen_histories)}",
                "status": "completed",
                "stop_reason": "STOP_SUFFICIENT",
                "metrics": {"logical_calls": 3, "physical_requests": 3},
            }
            await kwargs["emit"]({
                "type": "final",
                "answer": data["answer"],
                "status": data["status"],
                "stop_reason": data["stop_reason"],
                "metrics": data["metrics"],
                "run_id": data["run_id"],
                "conversation_id": kwargs["conversation_id"],
                "provider": data["provider"],
                "model": data["model"],
            })
            return data

        with tempfile.TemporaryDirectory() as temp_dir:
            conversation_dir = Path(temp_dir) / "conversations"
            conversation_dir.mkdir()
            with (
                patch.object(main_module, "RUNS", Path(temp_dir)),
                patch.object(main_module, "CONVERSATIONS", conversation_dir),
                patch.object(main_module, "execute_once", new=fake_execute_once),
            ):
                first = self.client.post(
                    "/api/chat/stream",
                    json={"message": "first", "context": "reference", "provider": "fake"},
                )
                match = next(
                    json.loads(line) for line in first.text.splitlines()
                    if line and json.loads(line).get("type") == "final"
                )
                conversation_id = match["conversation_id"]
                second = self.client.post(
                    "/api/chat/stream",
                    json={
                        "message": "follow up",
                        "provider": "fake",
                        "conversation_id": conversation_id,
                        "history": [{"role": "user", "content": "untrusted replacement"}],
                    },
                )
                self.assertEqual(second.status_code, 200)
                stored = self.client.get(f"/api/conversations/{conversation_id}").json()
        self.assertEqual(len(stored["messages"]), 4)
        self.assertEqual(len(stored["run_ids"]), 2)
        self.assertEqual(stored["context"], "reference")
        self.assertEqual(seen_histories[0], [])
        self.assertEqual([item["content"] for item in seen_histories[1]], ["first", "answer 1"])

    def test_product_chat_reads_once_then_uses_bounded_append(self):
        class CountingRepository:
            def __init__(self):
                self.read_calls = 0
                self.append_calls = 0

            def read(self, _conversation_id):
                self.read_calls += 1
                return None

            def append(self, _data, *, messages, preserve_historical_context=False):
                self.append_calls += 1
                self.last_message_count = len(messages)
                self.last_preserve = preserve_historical_context

            def write(self, _data):
                raise AssertionError("normal chat must not use full repository write")

            def list(self, *, limit, query=""):
                return []

            def delete(self, _conversation_id):
                return False

        repository = CountingRepository()

        async def fake_execute_once(**kwargs):
            run_id = "run_bounded_append"
            await kwargs["emit"]({
                "type": "final", "answer": "ok", "status": "completed",
                "stop_reason": "STOP_SUFFICIENT", "metrics": {}, "run_id": run_id,
                "conversation_id": kwargs["conversation_id"], "provider": "fake",
                "model": "fake-research-v2",
            })
            return {
                "run_id": run_id, "strategy": "adaptive", "provider": "fake",
                "model": "fake-research-v2", "processing_mode": "adaptive-auto",
                "answer": "ok", "status": "completed", "stop_reason": "STOP_SUFFICIENT",
                "metrics": {}, "sources": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(main_module, "RUNS", Path(temp_dir)),
                patch.object(main_module, "conversation_repository", return_value=repository),
                patch.object(main_module, "execute_once", new=fake_execute_once),
            ):
                response = self.client.post(
                    "/api/chat/stream",
                    json={"message": "hi", "provider": "fake"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(repository.read_calls, 1)
        self.assertEqual(repository.append_calls, 1)
        self.assertEqual(repository.last_message_count, 2)

    def test_reloaded_historical_context_is_not_active_for_unrelated_turn(self):
        calls = []
        source = {
            "filename": "api_reference.txt",
            "source_id": "ctx_0123456789abcdef",
            "format": "txt",
            "parser": "utf-8-text-v1",
            "char_count": 24,
            "line_count": 1,
        }
        historical_context = "SECRET_API_REFERENCE_MARKER"

        async def fake_execute_once(**kwargs):
            calls.append({
                "message": kwargs["message"],
                "context": kwargs["frozen_context"],
                "retrieval_meta": kwargs["retrieval_meta"],
            })
            run_id = f"run_context_{len(calls)}"
            data = {
                "run_id": run_id,
                "strategy": "adaptive",
                "provider": "fake",
                "model": "fake-research-v2",
                "processing_mode": "adaptive-auto",
                "answer": "hello",
                "status": "completed",
                "stop_reason": "STOP_SUFFICIENT",
                "metrics": {},
                "sources": [],
            }
            await kwargs["emit"]({
                "type": "final", "answer": data["answer"], "status": data["status"],
                "stop_reason": data["stop_reason"], "metrics": data["metrics"],
                "run_id": run_id, "conversation_id": kwargs["conversation_id"],
                "provider": data["provider"], "model": data["model"],
            })
            return data

        def historical_record(conversation_id):
            return {
                "conversation_id": conversation_id,
                "title": "Historical reference",
                "created_at": 1,
                "updated_at": 2,
                "provider": "fake",
                "model": "fake-research-v2",
                "processing_mode": "adaptive-auto",
                "status": "completed",
                "context": historical_context,
                "context_sources": [source],
                "run_ids": ["run_old"],
                "messages": [
                    {"role": "user", "content": "summarize the file", "run_id": "run_old",
                     "created_at": 1, "context_sources": [source]},
                    {"role": "assistant", "content": "old answer", "run_id": "run_old",
                     "created_at": 2, "sources": [source]},
                ],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            conversation_dir = root / "conversations"
            conversation_dir.mkdir()
            repository = JsonConversationRepository(conversation_dir)
            existing_id = "chat_historical_context"
            no_file_id = "chat_no_file_context"
            repository.write(historical_record(existing_id))
            repository.write({
                "conversation_id": no_file_id, "title": "No files", "created_at": 1,
                "updated_at": 2, "provider": "fake", "model": "fake-research-v2",
                "processing_mode": "adaptive-auto", "status": "completed", "context": "",
                "context_sources": [], "run_ids": [], "messages": [],
            })
            with (
                patch.object(main_module, "RUNS", root),
                patch.object(main_module, "CONVERSATIONS", conversation_dir),
                patch.object(main_module, "execute_once", new=fake_execute_once),
            ):
                # Case A: a new conversation has no active reference context.
                new_response = self.client.post(
                    "/api/chat/stream",
                    json={"message": "hi", "provider": "fake", "context": "",
                          "context_sources": [], "context_active": False},
                )
                self.assertEqual(new_response.status_code, 200)
                # Case B: a reloaded conversation that never used files stays empty.
                no_file_response = self.client.post(
                    "/api/chat/stream",
                    json={"message": "hi", "provider": "fake", "conversation_id": no_file_id,
                          "context": "", "context_sources": [], "context_active": False},
                )
                self.assertEqual(no_file_response.status_code, 200)
                # Case C: reload preserves history, but the new unrelated turn is context-free.
                reloaded = self.client.get(f"/api/conversations/{existing_id}")
                self.assertEqual(reloaded.status_code, 200)
                self.assertEqual(reloaded.json()["context_sources"][0]["filename"], source["filename"])
                old_response = self.client.post(
                    "/api/chat/stream",
                    json={"message": "hi", "provider": "fake", "conversation_id": existing_id,
                          "context": "", "context_sources": [], "context_active": False},
                )
                self.assertEqual(old_response.status_code, 200)
                # Case E: a new conversation cannot inherit the prior project's context.
                isolated_response = self.client.post(
                    "/api/chat/stream",
                    json={"message": "hi", "provider": "fake", "context": "",
                          "context_sources": [], "context_active": False},
                )
                self.assertEqual(isolated_response.status_code, 200)
                stored = self.client.get(f"/api/conversations/{existing_id}").json()

        self.assertEqual(len(calls), 4)
        self.assertTrue(all(item["context"] == "No external reference context was supplied." for item in calls))
        self.assertTrue(all(historical_context not in item["context"] for item in calls))
        self.assertEqual(stored["context"], historical_context)
        self.assertEqual(stored["context_sources"][0]["relative_path"] if "relative_path" in stored["context_sources"][0] else stored["context_sources"][0]["filename"], source["filename"])
        self.assertEqual(stored["messages"][0]["context_sources"][0]["filename"], source["filename"])
        self.assertEqual(stored["messages"][-2]["content"], "hi")
        self.assertEqual(stored["messages"][-2].get("context_sources"), [])

    def test_explicit_context_remains_available_after_historical_reload(self):
        calls = []
        source = {
            "filename": "api_reference.txt", "source_id": "ctx_0123456789abcdef",
            "format": "txt", "parser": "utf-8-text-v1", "char_count": 24,
        }
        historical_context = "EXPLICIT_API_FOLLOWUP_MARKER"

        async def fake_execute_once(**kwargs):
            calls.append((kwargs["frozen_context"], kwargs["retrieval_meta"].get("attached_sources", [])))
            run_id = "run_explicit_context"
            await kwargs["emit"]({"type": "final", "answer": "auth", "status": "completed",
                                    "stop_reason": "STOP_SUFFICIENT", "metrics": {}, "run_id": run_id,
                                    "conversation_id": kwargs["conversation_id"], "provider": "fake",
                                    "model": "fake-research-v2"})
            return {"run_id": run_id, "provider": "fake", "model": "fake-research-v2",
                    "processing_mode": "adaptive-auto", "answer": "auth", "status": "completed",
                    "stop_reason": "STOP_SUFFICIENT", "metrics": {}, "sources": [source]}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            conversation_dir = root / "conversations"
            conversation_dir.mkdir()
            JsonConversationRepository(conversation_dir).write({
                "conversation_id": "chat_explicit_context", "title": "Reference", "created_at": 1,
                "updated_at": 2, "provider": "fake", "model": "fake-research-v2",
                "processing_mode": "adaptive-auto", "status": "completed", "context": historical_context,
                "context_sources": [source], "run_ids": [], "messages": [],
            })
            with (
                patch.object(main_module, "RUNS", root),
                patch.object(main_module, "CONVERSATIONS", conversation_dir),
                patch.object(main_module, "execute_once", new=fake_execute_once),
            ):
                response = self.client.post(
                    "/api/chat/stream",
                    json={"message": "API auth dùng gì?", "provider": "fake",
                          "conversation_id": "chat_explicit_context", "context": historical_context,
                          "context_sources": [source], "context_active": True},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(calls), 1)
        self.assertIn(historical_context, calls[0][0])
        self.assertEqual(calls[0][1][0]["filename"], source["filename"])

    def test_reload_context_lifecycle_does_not_rehydrate_the_composer(self):
        js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("context_active:activeContext", js)
        self.assertIn("function activeContextForRequest()", js)
        self.assertIn("/* Persisted context is historical metadata; reload never activates it in the draft. */", js)
        self.assertNotIn('if(typeof conversation.context==="string")$("#context").value=conversation.context', js)

    def test_product_hot_path_does_not_wait_for_optional_evidence_or_sidebar_refresh(self):
        js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        switch = js.split("async function loadConversation(id)", 1)[1].split("async function loadRunInspector", 1)[0]
        self.assertNotIn("await loadRunInspector", switch)
        self.assertNotIn("await loadConversations", switch)
        self.assertIn("resetInspector(\"idle\")", switch)
        self.assertIn("conversation_switch_timing", switch)
        chat = js.split("async function runChat", 1)[1].split("async function testProvider", 1)[0]
        self.assertNotIn("await loadConversations", chat)
        self.assertIn("updateConversationSidebar", chat)

    def test_product_chat_uses_bounded_repository_append_and_timing_identity(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        repository = (ROOT / "app" / "core" / "conversation_repository.py").read_text(encoding="utf-8")
        for field in (
            "request_received_ms", "conversation_load_ms", "user_message_persist_ms",
            "routing_ms", "provider_start_ms", "provider_first_response_ms",
            "assistant_persist_ms", "total_ms",
        ):
            self.assertIn(field, source)
        self.assertIn("existing=existing", source)
        self.assertIn("def append(", repository)
        self.assertIn("conversation_append_timing", repository)
        postgres_append = repository.split("class PostgresConversationRepository", 1)[1].split("def append(", 1)[1].split("def list(", 1)[0]
        self.assertNotIn('DELETE FROM conversation_messages WHERE conversation_id = %s', postgres_append)

    def test_fatal_stream_has_conversation_metadata_and_persists_failed_turn(self):
        async def failing_execute_once(**kwargs):
            raise ValueError("provider unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            conversation_dir = Path(temp_dir) / "conversations"
            conversation_dir.mkdir()
            with (
                patch.object(main_module, "RUNS", Path(temp_dir)),
                patch.object(main_module, "CONVERSATIONS", conversation_dir),
                patch.object(main_module, "execute_once", new=failing_execute_once),
            ):
                response = self.client.post(
                    "/api/chat/stream",
                    json={"message": "first attempt", "context": "reference", "provider": "fake"},
                )
                events = [json.loads(line) for line in response.text.splitlines() if line]
                fatal = next(event for event in events if event["type"] == "fatal")
                conversation = self.client.get(
                    f"/api/conversations/{fatal['conversation_id']}"
                ).json()
                evidence_path = Path(temp_dir) / f"{fatal['run_id']}.json"
                self.assertTrue(evidence_path.exists())
                evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fatal["provider"], "fake")
        self.assertEqual(fatal["model"], None)
        self.assertTrue(fatal["run_id"].startswith("run_"))
        self.assertEqual(conversation["run_ids"], [fatal["run_id"]])
        self.assertEqual(len(conversation["messages"]), 2)
        self.assertEqual(conversation["messages"][1]["status"], "failed")
        self.assertEqual(evidence["status"], "failed")
        self.assertEqual(evidence["stop_reason"], "STOP_FAILURE")

    def test_execute_once_saves_json_evidence(self):
        provider = ScriptedProvider()
        snapshot, retrieval_meta = frozen_snapshot(
            "Simple evidence task",
            "Evidence topic one.\n\nEvidence topic two.",
        )

        async def sink(_):
            return None

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(main_module, "RUNS", Path(temp_dir)),
                patch.object(main_module, "get_provider", return_value=provider),
            ):
                data = asyncio.run(main_module.execute_once(
                    strategy="adaptive",
                    provider_name="fake",
                    message="Simple evidence task",
                    frozen_context=snapshot,
                    retrieval_meta=retrieval_meta,
                    history=[],
                    emit=sink,
                ))
            evidence_path = Path(temp_dir) / f"{data['run_id']}.json"
            self.assertTrue(evidence_path.exists())
            saved = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["metrics"]["logical_calls"], 3)
            self.assertEqual(saved["metrics"]["physical_requests"], 3)
            self.assertEqual(saved["stop_reason"], "STOP_SUFFICIENT")
            self.assertEqual(saved["snapshot_id"], retrieval_meta["snapshot_id"])
            self.assertEqual(saved["context_hash"], retrieval_meta["context_hash"])
            self.assertEqual(saved["source_document_ids"], retrieval_meta["source_document_ids"])
            self.assertEqual(saved["chunk_ids"], retrieval_meta["chunk_ids"])
            self.assertIn("created_at", saved["retrieval_meta"])
            self.assertIn("truncation", saved["retrieval_meta"])
            self.assertIn("selected_chunks", saved["retrieval_meta"])
            self.assertTrue(any(event["kind"] == "rag" for event in saved["events"]))

    def test_strategy_config_identity_is_persisted_for_fixed_and_static(self):
        async def sink(_):
            return None

        fixed_identities = []
        static_identity = None
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(main_module, "RUNS", Path(temp_dir)),
                patch.object(main_module, "get_provider", side_effect=lambda *_args, **_kwargs: ScriptedProvider(
                    analyzer=analyzer_payload(count=3),
                    plan={"subtasks": [
                        {"id": "A", "goal": "one", "depends_on": []},
                        {"id": "B", "goal": "two", "depends_on": ["A"]},
                    ]},
                )),
            ):
                for index in range(2):
                    data = asyncio.run(main_module.execute_once(
                        strategy="fixed", provider_name="fake", message=f"fixed {index}",
                        frozen_context="Frozen context", retrieval_meta={"method": "test"},
                        history=[], emit=sink,
                    ))
                    fixed_identities.append(data["config_identity"])
                    saved = json.loads((Path(temp_dir) / f"{data['run_id']}.json").read_text(encoding="utf-8"))
                    self.assertEqual(saved["strategy_config_id"], "FIXED-TOPOLOGY-V1")
                    self.assertEqual(saved["strategy_config_version"], "1.0")
                    self.assertEqual(saved["config_identity"]["fixed_topology"]["worker_count"], 3)
                static = asyncio.run(main_module.execute_once(
                    strategy="static", provider_name="fake", message="static identity",
                    frozen_context="Frozen context", retrieval_meta={"method": "test"},
                    history=[], emit=sink,
                ))
                static_identity = static["config_identity"]
                saved_static = json.loads((Path(temp_dir) / f"{static['run_id']}.json").read_text(encoding="utf-8"))
                self.assertEqual(saved_static["strategy_config_id"], "STATIC-PRESETS-V1")
                self.assertEqual(saved_static["strategy_config_version"], "1.0")
        self.assertEqual(fixed_identities[0], fixed_identities[1])
        self.assertEqual(static_identity["static_config_id"], "STATIC-PRESETS-V1")
        self.assertTrue(static_identity["selected_preset"].startswith("STATIC-"))
        self.assertEqual(static_identity["selected_preset_version"], "1.0")

    def test_stopped_run_is_saved_as_raw_evidence(self):
        provider = ScriptedProvider()

        async def sink(_):
            return None

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(main_module, "RUNS", Path(temp_dir)),
                patch.object(main_module, "get_provider", return_value=provider),
                patch.object(
                    main_module,
                    "make_budget",
                    return_value=Budget(max_logical_calls=1, max_retries_per_call=0),
                ),
            ):
                data = asyncio.run(main_module.execute_once(
                    strategy="adaptive",
                    provider_name="fake",
                    message="stopped evidence task",
                    frozen_context="Frozen context",
                    retrieval_meta={"method": "test", "chunks_total": 1, "chunks_selected": 1},
                    history=[],
                    emit=sink,
                ))
            evidence_path = Path(temp_dir) / f"{data['run_id']}.json"
            self.assertTrue(evidence_path.exists())
            saved = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "stopped")
        self.assertEqual(saved["stop_reason"], "STOP_BUDGET_LOGICAL_CALLS")
        self.assertTrue(saved["events"])


class V06RegressionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def test_config_lists_dev_providers_without_exposing_keys(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "groq_placeholder", "OPENROUTER_API_KEY": "openrouter_placeholder"}, clear=False):
            response = self.client.get("/api/config")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("groq", data["models"])
            self.assertIn("openrouter", data["models"])
            raw = response.text
            self.assertNotIn("groq_placeholder", raw)
            self.assertNotIn("openrouter_placeholder", raw)

    def test_conversation_api_returns_grouped_turns_and_supports_rename_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            conversations = Path(temp_dir) / "conversations"
            conversations.mkdir()
            runs = Path(temp_dir)
            cid = "chat_grouped_test"
            conversation = {
                "conversation_id": cid,
                "title": "Old title",
                "created_at": 1,
                "updated_at": 2,
                "provider": "fake",
                "model": "fake-research-v2",
                "messages": [
                    {"role": "user", "content": "Question", "created_at": 1, "run_id": "run_grouped"},
                    {"role": "assistant", "content": "Answer", "created_at": 2, "run_id": "run_grouped", "mode": "DIRECT", "metrics": {"logical_calls": 3}},
                ],
                "run_ids": ["run_grouped"],
            }
            (conversations / f"{cid}.json").write_text(json.dumps(conversation), encoding="utf-8")
            (runs / "run_grouped.json").write_text("{}", encoding="utf-8")
            with patch.object(main_module, "RUNS", runs), patch.object(main_module, "CONVERSATIONS", conversations):
                got = self.client.get(f"/api/conversations/{cid}")
                self.assertEqual(got.status_code, 200)
                turns = got.json()["turns"]
                self.assertEqual(len(turns), 1)
                self.assertEqual(turns[0]["user"]["content"], "Question")
                self.assertEqual(turns[0]["assistant"]["mode"], "DIRECT")

                renamed = self.client.patch(f"/api/conversations/{cid}", json={"title": "New title"})
                self.assertEqual(renamed.status_code, 200)
                self.assertEqual(main_module.read_conversation(cid)["title"], "New title")

                deleted = self.client.delete(f"/api/conversations/{cid}")
                self.assertEqual(deleted.status_code, 200)
                self.assertFalse((conversations / f"{cid}.json").exists())
                self.assertFalse((runs / "run_grouped.json").exists())

    def test_gemini_interaction_step_parser(self):
        from app.providers.gemini_provider import GeminiProvider
        data = {"steps": [{"type": "thought", "signature": "x"}, {"type": "model_output", "content": [{"type": "text", "text": "OK"}]}]}
        self.assertEqual(GeminiProvider._output_text(data), "OK")

    def test_provider_status_is_invalidated_when_key_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_file = Path(temp_dir) / "provider_status.json"
            with patch.object(main_module, "PROVIDER_STATUS", status_file):
                with patch.dict(os.environ, {"GROQ_API_KEY": "groq_key_one"}, clear=False):
                    main_module.write_provider_status("groq", "ready", "openai/gpt-oss-120b")
                    self.assertEqual(main_module.read_provider_status()["groq"]["status"], "ready")
                with patch.dict(os.environ, {"GROQ_API_KEY": "groq_key_two"}, clear=False):
                    self.assertEqual(main_module.read_provider_status()["groq"]["status"], "unknown")

    def test_provider_status_is_invalidated_when_model_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_file = Path(temp_dir) / "provider_status.json"
            with patch.object(main_module, "PROVIDER_STATUS", status_file):
                with patch.dict(os.environ, {"OPENAI_API_KEY": "openai_model_placeholder", "OPENAI_MODEL": "gpt-5.6-luna"}, clear=False):
                    main_module.write_provider_status("openai", "ready", "gpt-5.6-luna")
                    self.assertEqual(main_module.read_provider_status()["openai"]["status"], "ready")
                with patch.dict(os.environ, {"OPENAI_API_KEY": "openai_model_placeholder", "OPENAI_MODEL": "gpt-5.6-terra"}, clear=False):
                    self.assertEqual(main_module.read_provider_status()["openai"]["status"], "unknown")

    def test_openai_compatible_provider_disables_hidden_sdk_retries(self):
        source = (ROOT / "app" / "providers" / "compatible.py").read_text(encoding="utf-8")
        openai_source = (ROOT / "app" / "providers" / "openai_provider.py").read_text(encoding="utf-8")
        self.assertIn("max_retries=0", source)
        self.assertIn("max_retries=0", openai_source)


class FrontendV6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
        cls.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    def test_transcript_groups_turn_and_keeps_execution_progressive(self):
        self.assertIn("function makeTurnCard", self.js)
        self.assertIn("messages.appendChild(card)", self.js)
        self.assertIn("trace.appendChild(d)", self.js)
        self.assertNotIn("messages.appendChild(d)", self.js)
        self.assertIn('run.className="run-pill"', self.js)
        self.assertIn("Chi tiết xử lý", self.js)
        self.assertIn('summary.className="run-summary-line"', self.js)
        self.assertIn("m.total_tokens", self.js)
        self.assertIn('class="context-provenance"', self.html)
        self.assertIn('styles.css?v=36', self.html)
        self.assertIn('app.js?v=36', self.html)

    def test_compare_headers_and_result_cells_have_exact_metric_mapping(self):
        head = self.html.split('<table class="compare-table"><thead><tr>', 1)[1].split("</tr>", 1)[0]
        row = self.js.split('insertAdjacentHTML("beforeend",`<tr>', 1)[1].split("</tr>`", 1)[0]
        self.assertEqual(head.count("<th>"), 14)
        self.assertEqual(row.count("<td"), 14)
        expected = (
            "metric(m.input_tokens)", "metric(m.output_tokens)", "metric(m.total_tokens)",
            "fmtLatency(m.e2e_ms)", "cost(m.calculated_cost_usd)",
            "UI_TEXT.labels.notEvaluated", "${evidence}",
        )
        positions = [row.index(value) for value in expected]
        self.assertEqual(positions, sorted(positions))

    def test_locked_sidebar_search_and_adaptive_mode_contract(self):
        self.assertIn('id="searchChat"', self.html)
        self.assertIn('id="searchInput"', self.html)
        self.assertIn("function renderSearchResults", self.js)
        self.assertIn("function mapUiModeToChatStrategy", self.js)
        self.assertIn('if(raw==="auto")return "adaptive-auto";', self.js)
        self.assertIn('direct:"DIRECT"', self.js)
        self.assertIn("Tự động để Adaptive Agent tự chọn cách xử lý phù hợp.", self.html)
        self.assertIn(".threads{display:flex;flex:1 1 auto", self.css)

    def test_failed_turn_has_friendly_error_hierarchy(self):
        self.assertIn("function friendlyRunError", self.js)
        self.assertIn("Không thể chạy với mô hình này", self.js)
        self.assertIn("Không thể kết nối tới server local", self.js)
        self.assertIn('body.classList.toggle("error-answer",meta.status==="failed")', self.js)

    def test_upstream_html_errors_are_replaced_before_markdown(self):
        helper = self.js.split("const UPSTREAM_ERROR_MESSAGES", 1)[1].split("function cap", 1)[0]
        script = "const UPSTREAM_ERROR_MESSAGES" + helper + r'''
const cases = [
  ["html502", "<!DOCTYPE html><html><head><title>502</title></head><body>Bad Gateway</body></html>", 502, "text/html; charset=utf-8", "Máy chủ tạm thời không phản hồi"],
  ["html503", "<html><head><title>503</title></head><body>Service Unavailable</body></html>", 503, "text/html", "Dịch vụ hiện tạm thời không khả dụng"],
  ["html504", "<html><body>504 Gateway Timeout</body></html>", 504, "", "Yêu cầu mất quá nhiều thời gian phản hồi"],
  ["stack", "Traceback (most recent call last):\\n  File \\\"/srv/app/main.py\\\", line 42, in handle\\nRuntimeError: upstream failed", null, "text/plain", "Không thể kết nối tới dịch vụ"],
  ["structured", JSON.stringify({detail: "Unsupported model selection"}), 400, "application/json", "Unsupported model selection"],
  ["plain", "Provider rate limit reached; wait before retrying.", null, "text/plain", "Provider rate limit reached; wait before retrying."],
];
for (const [name, body, status, contentType, expected] of cases) {
  const actual = safeErrorDetail(body, status, contentType);
  if (!actual.includes(expected) || actual.includes("<!DOCTYPE") || actual.includes("<html")) {
    throw new Error(`${name}: ${actual}`);
  }
}
const friendly = friendlyRunError(cases[0][1], "groq", "model", 502, "text/html");
if (!friendly.includes("Máy chủ tạm thời không phản hồi") || friendly.includes("<html")) throw new Error(friendly);
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_readable_type_and_collapsible_responsive_layout_contract(self):
        self.assertIn(".answer-body{max-width:920px", self.css)
        self.assertIn("font-size:15.5px;line-height:1.68", self.css)
        self.assertIn(".question-text{max-width:min(80%,760px)", self.css)
        self.assertIn("font-size:14px;line-height:1.55", self.css)
        self.assertIn(".thread-meta{", self.css)
        self.assertIn(".app{height:100vh;display:flex;grid-template-columns:none", self.css)
        self.assertIn(".app.ins-collapsed .inspector{width:0;flex-basis:0;visibility:hidden;opacity:0;pointer-events:none}", self.css)
        self.assertIn("overflow-x:hidden", self.css)
        self.assertIn("@media(max-width:900px)", self.css)
        self.assertIn(".inspector{position:fixed;right:0", self.css)
        self.assertIn("@media(prefers-reduced-motion:reduce)", self.css)

    def test_panel_state_and_accessible_controls_are_persisted(self):
        self.assertIn('localStorage.setItem("adaptive.sideCollapsed"', self.js)
        self.assertIn('localStorage.setItem("adaptive.insCollapsed"', self.js)
        self.assertIn('localStorage.setItem("adaptive.mobileInspectorOpen"', self.js)
        self.assertIn('localStorage.setItem(INSPECTOR_TAB_KEY,name)', self.js)
        self.assertIn("function updatePanelButtons", self.js)
        self.assertIn('window.addEventListener("resize",()=>{updatePanelButtons()', self.js)
        self.assertIn('aria-controls="sidebar"', self.html)
        self.assertIn('aria-controls="inspector"', self.html)
        self.assertIn('class="app ins-collapsed"', self.html)
        self.assertIn('aria-expanded="false"', self.html)

    def test_v62_chat_first_visual_debt_is_mechanically_reduced(self):
        self.assertIn('class="advanced-menu"', self.html)
        self.assertIn('id="compareBtn"', self.html)
        self.assertIn('id="exportBtn"', self.html)
        self.assertIn(".turn-card{max-width:1040px", self.css)
        self.assertIn("border-radius:0;background:transparent", self.css)
        self.assertIn(".metric-list>div{display:flex", self.css)
        self.assertNotIn("metric-grid", self.html)
        self.assertNotIn("--r-lg", self.css)
        self.assertIn("Approved Adaptive Agent context-review integration v20", self.css)
        self.assertIn(".inspector-close{display:grid", self.css)

    def test_v62_accessible_drawers_tabs_and_raw_actions_are_present(self):
        self.assertIn('aria-controls="contextDrawer"', self.html)
        self.assertIn('role="dialog" aria-modal="true"', self.html)
        self.assertIn('id="inspectorClose"', self.html)
        self.assertIn('id="panelScrim"', self.html)
        self.assertIn('id="rawCopyBtn"', self.html)
        self.assertIn('id="rawDownloadBtn"', self.html)
        self.assertIn('event.key==="ArrowLeft"', self.js)
        self.assertIn('event.key==="Escape"', self.js)
        self.assertIn("function setContextOpen", self.js)

    def test_v62_metrics_keep_provider_fields_separate_and_unavailable(self):
        for element_id in ("mAgents", "mCalls", "mRequests", "mInputTokens", "mOutputTokens", "mTokens", "mRetries", "mEsc", "mCost"):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('m.input_tokens==null?"Unavailable"', self.js)
        self.assertIn('m.output_tokens==null?"Unavailable"', self.js)
        self.assertIn('m.retries==null?"Unavailable"', self.js)

    def test_execution_inspector_exposes_required_evidence_views(self):
        for tab in ("overview", "graph", "agents", "metrics", "raw", "context"):
            self.assertIn(f'data-tab="{tab}"', self.html)
            self.assertIn(f'id="tab-{tab}"', self.html)
        self.assertIn('id="overviewContent"', self.html)
        self.assertIn('id="executionGraph"', self.html)
        self.assertIn('id="agentList"', self.html)
        self.assertIn('role="tablist"', self.html)
        for tab in ("overview", "graph", "agents", "metrics", "raw", "context"):
            self.assertIn(f'aria-controls="tab-{tab}"', self.html)
            self.assertIn(f'aria-labelledby="ins-tab-{tab}"', self.html)
        self.assertIn("function evidenceModel", self.js)
        self.assertIn("function buildGraph", self.js)
        self.assertIn("function renderEvidencePanels", self.js)
        self.assertIn("graphArrow", self.js)
        self.assertIn("Ready-set scheduler", self.js)

    def test_approved_context_review_surfaces_use_real_evidence(self):
        for element_id in (
            "quickDetailBody", "quickTimeline", "openEvidence", "executionEvidence",
            "evidenceMount", "quickCompareGrid", "openComparisonReport",
            "comparisonReport", "comparisonMatrixBody", "comparisonAnswers",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('class="icon-sprite"', self.html)
        self.assertIn("function renderQuickDetails", self.js)
        self.assertIn("function renderComparisonSurfaces", self.js)
        self.assertIn("function mountEvidenceWorkspace", self.js)
        self.assertIn('compareResults.set(String(result.strategy||"").toLowerCase(),result)', self.js)
        self.assertIn('JSON.stringify(safeFrontendEvidence(run.run_id?run:{}),null,2)', self.js)
        self.assertNotIn("2.4s", self.html + self.js)
        self.assertNotIn("$0.012", self.html + self.js)

    def test_v20_history_and_model_picker_match_the_approved_interaction(self):
        self.assertIn('id="chatTitle" hidden', self.html)
        self.assertIn('rel="icon" href="data:image/svg+xml,', self.html)
        self.assertIn('id="providerChoices"', self.html)
        self.assertIn('id="modelChoices"', self.html)
        self.assertIn('role="listbox"', self.html)
        self.assertIn('function renderModelPicker', self.js)
        self.assertIn('function positionModelMenu', self.js)
        self.assertIn('svgIcon("chat","small")', self.js)
        self.assertNotIn('active?"chat":"history"', self.js)
        self.assertIn('position:fixed;left:auto;top:auto;bottom:auto', self.css)
        self.assertIn('.thread-card{height:37px;min-height:37px', self.css)
        self.assertIn('.thread-preview,.thread-meta{display:none!important}', self.css)
        self.assertIn('function closeConversationMenus', self.js)

    def test_execution_metadata_contract_is_instrumented_without_prompts(self):
        orchestrator = (ROOT / "app" / "core" / "orchestrator.py").read_text(encoding="utf-8")
        for field in ("execution_id", "assigned_goal", "dependencies", "start_ms", "end_ms", "duration_ms", "output_preview"):
            self.assertIn(field, orchestrator)
        self.assertIn('"subtasks":repair_subtasks', orchestrator)
        self.assertIn('"targeted_repair":targeted_repair', orchestrator)
        self.assertNotIn('"system":system', orchestrator)

    def test_compare_ui_exposes_full_resource_metrics_without_quality_score(self):
        for heading in (
            "Agent Executions", "Logical Calls", "Physical Requests", "Input Tokens",
            "Output Tokens", "Total Tokens", "E2E Latency", "Calculated Cost", "Quality",
        ):
            self.assertIn(heading, self.html)
        self.assertIn("Chưa đánh giá", self.html)
        self.assertIn("Unavailable", self.js)
        self.assertIn('m.total_tokens==null?"Unavailable"', self.js)
        self.assertIn("compare-evidence", self.js)
        self.assertIn("Frozen Context Snapshot", self.js)
        self.assertIn("Chưa đánh giá", self.js)
        self.assertNotIn("overall QLC", self.html + self.js)

    def test_vietnamese_ui_localization_keeps_runtime_identifiers_intact(self):
        for label in (
            "Cuộc trò chuyện mới", "Nhà cung cấp", "Mô hình",
            "Chi tiết thực thi", "Tổng quan", "Sơ đồ", "Các Agent", "Chỉ số",
            "Dữ liệu gốc", "Ngữ cảnh đã đóng băng",
            "Tự động", "Đã đủ yêu cầu", "Cần bổ sung", "Không đạt", "Không có dữ liệu",
        ):
            self.assertIn(label, self.html + self.js)
        self.assertIn("const UI_TEXT", self.js)
        self.assertIn("function modeText", self.js)
        self.assertIn("function statusText", self.js)
        for internal_value in ("DIRECT", "PARALLEL", "PLANNED", "PASS", "FAIL", "NEEDS_WORK"):
            self.assertIn(internal_value, self.js)
        self.assertIn("safeFrontendEvidence", self.js)

    def test_ui_polish_keeps_normal_mode_copy_short_and_menu_upright(self):
        for label in ('DIRECT: "Trực tiếp"', 'PARALLEL: "Song song"', 'PLANNED: "Theo kế hoạch"'):
            self.assertIn(label, self.js)
        self.assertNotIn("Trực tiếp (DIRECT)", self.js)
        self.assertNotIn("Song song (PARALLEL)", self.js)
        self.assertNotIn("Theo kế hoạch (PLANNED)", self.js)
        self.assertIn('mode-choice${item.id===mode', self.js)
        self.assertNotIn('mode-choice${item.id===mode?" selected":""}" role="radio" aria-checked="${item.id===mode}" data-mode="${esc(item.id)}"><span><b>${esc(item.label)}</b><small>', self.js)
        self.assertNotIn('#inspectorToggle[aria-expanded="false"]{transform:rotate(180deg)}', self.css)
        self.assertIn('.advanced-menu,.advanced-menu>summary,.advanced-menu .advanced-popover{direction:ltr;writing-mode:horizontal-tb;transform:none}', self.css)

    def test_v102_icon_system_and_model_trigger_are_compact_and_real_svg(self):
        self.assertEqual(self.html.count('id="i-chevron"'), 1)
        self.assertIn('class="ui-icon model-chevron"', self.html)
        self.assertIn('<use href="#i-chevron"></use>', self.html)
        self.assertNotIn('id="modeName"', self.html)
        self.assertNotIn('⌄', self.html)
        self.assertEqual(self.js.count('$("#modelName").textContent'), 1)
        self.assertNotIn('id="serverStatus"', self.html)
        self.assertNotIn('class="online"', self.html)
        self.assertNotIn('serverStatus', self.js)
        self.assertIn('.ui-icon{width:18px;height:18px', self.css)
        self.assertIn('.ui-icon.small{width:16px;height:16px}', self.css)
        self.assertIn('#modelMenuButton[aria-expanded="true"] .model-chevron{transform:rotate(180deg)}', self.css)
        self.assertNotIn('#modelMenuButton[aria-expanded="true"]{transform:', self.css)

    def test_locked_ui_uses_real_conversation_and_file_capabilities(self):
        self.assertIn('fetch("/api/conversations?limit=60")', self.js)
        self.assertIn("item.conversation_id", self.js)
        self.assertIn("currentConversationId===c.conversation_id", self.js)
        self.assertNotIn("SUPPORTED_CONTEXT_EXTENSIONS", self.js)
        self.assertIn("cfg.context_file_extensions", self.js)
        self.assertIn("activeContextFile", self.js)
        self.assertIn("processContextFile(activeContextFile)", self.js)
        self.assertNotIn("rename extension", self.js.lower())
        self.assertIn('id="renameDialog"', self.html)
        self.assertIn('method:"PATCH"', self.js)
        self.assertNotIn('prompt("Tên cuộc trò chuyện"', self.js)

    def test_locked_ui_keeps_unavailable_metrics_and_safe_raw_evidence(self):
        self.assertIn('m.input_tokens==null?"Unavailable"', self.js)
        self.assertIn('m.output_tokens==null?"Unavailable"', self.js)
        self.assertIn('m.total_tokens==null?"Unavailable"', self.js)
        self.assertIn('m.calculated_cost_usd==null?unavailableText()', self.js)
        self.assertIn("function safeFrontendEvidence", self.js)
        self.assertIn("hidden[_-]?rubric", self.js)
        self.assertIn("JSON.stringify(safeFrontendEvidence(run)", self.js)

    def test_locked_ui_failed_turn_has_real_bounded_retry(self):
        self.assertIn('retry.className="mini-action retry-turn"', self.js)
        self.assertIn('card.querySelector(".question-text")', self.js)
        self.assertIn("if(!original||busy)return", self.js)
        self.assertIn("promptEl.value=original;autoSize();runChat()", self.js)

    def test_locked_ui_progressive_surfaces_do_not_add_fake_product_modules(self):
        for element_id in ("settingsOverlay", "helpPopover", "sharePopover", "inspectorResizer", "compareResizer"):
            self.assertIn(f'id="{element_id}"', self.html)
        for forbidden in (">Dashboard<", ">Pilot<", ">Benchmark<", ">Research<", ">Agents<", ">Graph<", ">Metrics<", ">Logs<"):
            self.assertNotIn(forbidden, self.html)
        self.assertNotIn("GPT-4", self.html + self.js)
        self.assertNotIn("Claude", self.html + self.js)



if __name__ == "__main__":
    unittest.main()

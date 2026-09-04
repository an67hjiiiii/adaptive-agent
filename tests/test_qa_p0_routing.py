from __future__ import annotations

import unittest

from app.core.orchestrator import Orchestrator
from app.core.types import Budget, RunState
from app.providers.fake import FakeProvider


class CoreP0RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_arithmetic_records_direct_route_and_skips_other_topologies(self):
        emitted = []

        async def emit(event):
            emitted.append(event)

        provider = FakeProvider()
        state = RunState(
            strategy="adaptive",
            provider=provider.name,
            model=provider.model,
            task="What is 2 + 2?",
            context="No external reference context was supplied.",
            retrieval_meta={"method": "none", "chunks_total": 0, "chunks_selected": 0},
        )
        orchestrator = Orchestrator(
            provider,
            emit,
            budget=Budget(max_retries_per_call=0),
            product_auto=True,
        )

        await orchestrator.run(state)

        decision = next(event for event in state.events if event["kind"] == "decision")
        self.assertEqual(decision["meta"]["mode"], "DIRECT")
        self.assertEqual(decision["meta"]["source"], "product-auto-fast-path")
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.stop_reason, "STOP_SUFFICIENT")

        started_roles = [
            event["title"] for event in state.events if event["kind"] == "agent_start"
        ]
        self.assertEqual(started_roles, ["Direct Solver", "Runtime Verifier"])
        for forbidden_role in ("Analyzer", "Planner", "Worker", "Synthesizer"):
            self.assertNotIn(forbidden_role, started_roles)

        trace_decisions = [
            item for item in emitted
            if item.get("type") == "trace" and item["event"]["kind"] == "decision"
        ]
        self.assertEqual(len(trace_decisions), 1)
        self.assertEqual(trace_decisions[0]["event"]["meta"]["mode"], "DIRECT")

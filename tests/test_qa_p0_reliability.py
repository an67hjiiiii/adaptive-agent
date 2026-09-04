from __future__ import annotations

import asyncio
import time
import unittest

from app.core.orchestrator import Orchestrator
from app.core.types import Budget, ProviderResult, RunState, Usage
from app.providers.base import Provider


class TimeoutThenSuccessProvider(Provider):
    name = "fake"
    model = "fake-research-v2"

    def __init__(self):
        self.calls = []
        self.cancelled = False

    async def generate(self, *, system: str, user: str) -> ProviderResult:
        role = "Direct Solver" if "Direct Solver" in system else "Unknown"
        self.calls.append(role)
        if len(self.calls) == 1:
            try:
                await asyncio.sleep(0.20)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return ProviderResult(
            text="follow-up answer",
            usage=Usage(8, 4),
            request_id=f"fake-{len(self.calls)}",
            model=self.model,
            usage_metadata_available=True,
        )


def make_state(task: str, *, chat_history: str = "") -> RunState:
    return RunState(
        strategy="single",
        provider="fake",
        model="fake-research-v2",
        task=task,
        context="No external reference context was supplied.",
        chat_history=chat_history,
        retrieval_meta={"method": "none", "chunks_total": 0, "chunks_selected": 0},
    )


class CoreP0ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_is_bounded_safe_and_follow_up_run_remains_usable(self):
        provider = TimeoutThenSuccessProvider()
        budget = Budget(max_retries_per_call=0, call_timeout_seconds=0.02)

        async def emit(_event):
            return None

        first = make_state("first request")
        orchestrator = Orchestrator(provider, emit, budget=budget)
        started = time.perf_counter()
        await asyncio.wait_for(orchestrator.run(first), timeout=0.50)
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.50)
        self.assertTrue(provider.cancelled)
        self.assertEqual(first.status, "failed")
        self.assertEqual(first.stop_reason, "STOP_FAILURE")
        self.assertEqual(first.outcome_category, "TIMEOUT")
        self.assertEqual(first.error, "Provider request timed out; check network latency and retry.")
        self.assertNotIn("0.20", first.error)
        self.assertEqual(first.incident_records[-1]["provider_error_category"], "TIMEOUT")

        follow_up = make_state(
            "follow-up request",
            chat_history="Previous request stopped safely after a provider timeout.",
        )
        await asyncio.wait_for(orchestrator.run(follow_up), timeout=0.50)

        self.assertEqual(provider.calls, ["Direct Solver", "Direct Solver"])
        self.assertEqual(follow_up.status, "completed")
        self.assertEqual(follow_up.stop_reason, "COMPLETED")
        self.assertEqual(follow_up.answer, "follow-up answer")
        self.assertFalse(follow_up.incident_records)

from __future__ import annotations

import math
import unittest

from app.core.orchestrator import Orchestrator
from app.core.types import Budget, RunState
from app.providers.fake import FakeProvider


def percentile(samples: list[int], fraction: float) -> int:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]


class CoreP0PerformanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_direct_fake_runs_report_local_p50_and_p95(self):
        samples = []
        for _ in range(10):
            provider = FakeProvider()

            async def emit(_event):
                return None

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

            self.assertEqual(state.status, "completed")
            decision = next(event for event in state.events if event["kind"] == "decision")
            self.assertEqual(decision["meta"]["mode"], "DIRECT")
            samples.append(orchestrator.metrics(state)["e2e_ms"])

        p50 = percentile(samples, 0.50)
        p95 = percentile(samples, 0.95)
        self.assertEqual(len(samples), 10)
        self.assertTrue(all(sample >= 0 for sample in samples))
        self.assertGreaterEqual(p50, 0)
        self.assertGreaterEqual(p95, p50)
        print(f"PERF-001 local Fake DIRECT baseline: n=10 p50_ms={p50} p95_ms={p95}")

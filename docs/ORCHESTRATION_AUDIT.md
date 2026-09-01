# Adaptive orchestration correctness audit (T6 + V6.3 baseline closure)

Audited: 2026-08-30 against the extracted V5 source, the local FastAPI
instance, the Fake provider smoke matrix, and the unit/API regression suite.
This document records implementation evidence; it does not define a new
research algorithm.

## Scope and status

`IMPLEMENTED` means the production path contains the named operation and a
mechanical test exercises it. `UNVERIFIED` is used only for evidence that needs
an outbound live provider or browser observation. `FAKE` identifies the
intentional offline provider/test double, not a claim about the controller.

The T6 runtime correction removed internal task labels from the Structural
Analyzer system prompt. V6.3 adds only the requested baseline closure: a
versioned Fixed topology, explicit Static presets, and persisted configuration
identity. Adaptive routing, scheduling, verification, budget, retry, timeout,
and stop policy remain unchanged.

The local `FakeProvider` (`app/providers/fake.py`) is intentionally `FAKE`: it
returns deterministic keyword-based responses so orchestration can be tested
without network or quota. `ScriptedProvider` in `tests/test_runtime.py` is also
a test double. Real provider adapters call the same `Provider.generate` seam,
but live Gemini/OpenAI generation is **UNVERIFIED** in this environment.

## Runtime evidence fixtures

The following local HTTP runs were made against `http://127.0.0.1:8000` with
`provider=fake`; run JSON is in `runs/` and contains the event evidence used by
the inspector:

| Run | Route | Evidence | Terminal |
| --- | --- | --- | --- |
| `run_edc9bcd7f98c` | DIRECT | 3 Agent Executions / 3 logical calls / 3 physical requests | `STOP_SUFFICIENT` |
| `run_a20639ab677f` | PARALLEL | ready-set `S1 + S2 + S3`, 6 / 6 / 6 | `STOP_SUFFICIENT` |
| `run_cc78671c903a` | PLANNED | ready-sets `S1 + S3`, then `S2`, 7 / 7 / 7 | `STOP_SUFFICIENT` |
| `run_0fc1d1282dbd` | PLANNED | conflict-sensitive task, one targeted escalation, 10 / 10 / 10 | `STOP_SUFFICIENT` |

The `/api/chat/stream` path calls `execute_once(strategy="adaptive", ...)`,
and the persisted run keeps the same event list sent over NDJSON. The smoke
command below independently reproduces the four route cases:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_matrix.py --provider fake
```

Result on this audit: **4/4 PASS** (DIRECT, PARALLEL, PLANNED, and targeted
escalation).

## Component-by-component evidence

### 1. Structural analysis

**IMPLEMENTED AT:** `app/core/orchestrator.py:10-22` (`ANALYZER_SYS`),
`Orchestrator.analyze` (`:135-152`), and `_call` (`:76-121`).

**INPUT:** `RunState.task` and the immutable frozen context through
`Orchestrator.prompt`; recent chat history is labeled separately. The Analyzer
prompt is limited to the declared structural schema and observable signals; it
does not contain internal T1/T2/T3/T4 labels or Easy/Medium/Hard/A/N/V/R labels.

**OUTPUT:** Provider-generated, parsed JSON containing `aspects`,
`dependencies`, `parallelizable_groups`, `verification_demand`,
`verification_reasons`, and `rationale`. Validation rejects missing or invalid
fields before routing.

**CALLED BY:** `app/main.py:282` (`execute_once`) → `Orchestrator.run` →
`run_adaptive` → `analyze`.

**TEST:** `RuntimeFlowTests.test_fake_analyzer_focuses_on_task_not_unrelated_context`,
`RuntimeFlowTests.test_structural_analyzer_does_not_receive_hidden_task_labels`,
and the direct/parallel/planned flow tests.

**RUNTIME EVIDENCE:** Each adaptive run records `agent_start`/`provider_request`/
`agent_end` for `Analyzer` and an `analysis` event with all six structural
fields. The hidden-label test captures the actual system prompt passed to the
provider and asserts those labels are absent. V6.1 live Groq runs verify real
Analyzer calls; formal answer-quality evaluation remains **UNVERIFIED**.
Fake/Scripted generation is the declared offline `FAKE` path.

### 2. Initial rule-based routing

**IMPLEMENTED AT:** `Orchestrator.choose_mode` (`app/core/orchestrator.py:154-163`).

**INPUT:** Validated Analyzer `aspects`, `dependencies`,
`parallelizable_groups`, and `verification_demand`.

**OUTPUT:** Exactly `PLANNED` when dependencies or high verification demand are
present; otherwise `PARALLEL` for multiple aspects with a useful group;
otherwise `DIRECT`, with a human-readable reason.

**CALLED BY:** `run_adaptive` immediately after `analyze`; the chosen mode is
emitted as `AUTO route selected`.

**TEST:** `test_direct_auto_skips_planner_and_stops_sufficient`,
`test_parallel_workers_run_concurrently_without_planner`, and
`test_planned_mode_validates_and_schedules_dependencies`.

**RUNTIME EVIDENCE:** The four smoke runs above produced DIRECT, PARALLEL,
PLANNED, and PLANNED respectively. The route event metadata contains only the
observable signals/reason (`mode`, `why`), not a hidden difficulty score.

### 3. Agent selection

**IMPLEMENTED AT:** `Orchestrator.select_agents` (`:165-173`) and the
`agent_selection` event in `run_adaptive` (`:256-259`).

**INPUT:** Analyzer aspect count and the selected mode.

**OUTPUT:** Bounded role counts for `direct_solver`, `planner`, `workers`,
`verifier`, and `synthesizer`; worker count is capped by `Budget.max_workers`.

**CALLED BY:** `run_adaptive` after `choose_mode`, before any solver/planner call.

**TEST:** Direct, parallel, planned, and execution-metadata tests assert the
selected calls and separate role/count evidence.

**RUNTIME EVIDENCE:** Every adaptive run has an `agent_selection` event and the
run metrics expose the resulting `agent_executions` count. The inspector reads
this event; the Orchestrator itself remains a controller, not an extra LLM
execution.

### 4. Task decomposition

**IMPLEMENTED AT:** `Orchestrator.parallel_subtasks` (`:175-185`) and
`Orchestrator.plan` (`:187-199`).

**INPUT:** Analyzer aspects for PARALLEL, or the original task/frozen context
for the Planner Agent in PLANNED mode.

**OUTPUT:** Bounded subtask records `{id, goal, depends_on}`. PARALLEL creates
one independent subtask per bounded aspect; PLANNED accepts the Planner's
provider-generated decomposition and validates it.

**CALLED BY:** `run_adaptive` calls `parallel_subtasks` only on PARALLEL and
`plan` only on PLANNED. `run_fixed`/`run_static` use their own baseline paths.

**TEST:** `test_parallel_workers_run_concurrently_without_planner` and
`test_planned_mode_validates_and_schedules_dependencies`; direct route asserts
Planner is skipped.

**RUNTIME EVIDENCE:** PARALLEL run evidence contains a `Parallel plan from
structural aspects` event; PLANNED evidence contains `Planner` execution and a
`DAG validated` event with the subtask list. No decomposition is claimed for a
DIRECT route.

### 5. DAG construction

**IMPLEMENTED AT:** Planner JSON construction in `Orchestrator.plan` (`:187-199`)
and deterministic independent-node construction in `parallel_subtasks` (`:175-185`).

**INPUT:** Structural task signals and, for PLANNED, the Planner Agent's JSON.

**OUTPUT:** An ordered list of subtask nodes and dependency edges. There is no
separate graph object; the list is the runtime DAG representation.

**CALLED BY:** `run_adaptive` → `plan`/`parallel_subtasks` → `execute_dag`.

**TEST:** `test_planned_mode_validates_and_schedules_dependencies` checks the
three-node DAG and its two ready-set batches; `test_dag_rejects_cycle_and_unknown_dependency`
checks invalid topology rejection.

**RUNTIME EVIDENCE:** `DAG validated` metadata persists `subtasks`; the local
PLANNED run records `S1 + S3` followed by dependent `S2`.

### 6. DAG validation

**IMPLEMENTED AT:** `app/core/graph.py:4-29` (`validate_plan`), called from
`Orchestrator.plan`'s transform and again at `execute_dag` entry.

**INPUT:** Subtask IDs and each `depends_on` list.

**OUTPUT:** `True` for a valid acyclic plan; explicit `ValueError` for duplicate
IDs, unknown dependencies, self-loops, or cycles.

**CALLED BY:** Planner response validation and every DAG execution path.

**TEST:** `GraphAndRagTests.test_dag_rejects_cycle_and_unknown_dependency` and
the planned-flow DAG assertion.

**RUNTIME EVIDENCE:** Valid runs emit `DAG validated` with “Kahn cycle check
passed”; invalid plans stop before workers can run. This is a real validation
pass, not a decorative graph check.

### 7. Kahn/ready-set scheduling

**IMPLEMENTED AT:** `app/core/graph.py:31-36` (`ready_nodes`) and
`Orchestrator.execute_dag` (`app/core/orchestrator.py:208-220`).

**INPUT:** Validated subtasks plus the `done` set.

**OUTPUT:** All currently runnable nodes in source order. The scheduler records
each ready set and marks the batch complete only after its workers return.

**CALLED BY:** `execute_dag`'s `while len(done) < len(subtasks)` loop.

**TEST:** `test_planned_mode_validates_and_schedules_dependencies` asserts exact
batches `[["S1", "S3"], ["S2"]]` and asserts `S1` ends before `S2` starts.

**RUNTIME EVIDENCE:** The PLANNED run's scheduler events show `S1 + S3`, then
`S2`; the `scheduler` metadata includes algorithm `Kahn-style ready set`,
`nodes`, and `parallel`.

### 8. Concurrent Worker execution

**IMPLEMENTED AT:** `Orchestrator.execute_dag` (`:208-220`) uses
`asyncio.gather(*(self.worker(...) for s in batch))`; targeted repairs use the
same primitive in `run_adaptive` (`:302-304`).

**INPUT:** One ready-set batch of independent subtasks (or targeted repair
subtasks).

**OUTPUT:** Worker results collected in batch order and stored by subtask ID.

**CALLED BY:** PARALLEL and PLANNED adaptive routes, plus bounded escalation.

**TEST:** `test_parallel_workers_run_concurrently_without_planner` uses delayed
workers, asserts `max_active_workers == 3`, and asserts the recorded worker
intervals overlap (`max(start_ms) < min(end_ms)`). The NEEDS_WORK test asserts
two repair workers overlap.

**RUNTIME EVIDENCE:** PARALLEL run evidence has one `parallel=true` ready-set
with `S1/S2/S3`; Agent Execution metadata has overlapping relative intervals.
This is actual asyncio concurrency, not a serial loop labeled “parallel”.

### 9. Runtime Verifier

**IMPLEMENTED AT:** `Orchestrator.verify` (`app/core/orchestrator.py:229-246`).

**INPUT:** Original task, frozen context, candidate answer, and a targeted-repair
marker only for re-verification.

**OUTPUT:** Provider-generated JSON normalized to exactly `PASS`, `NEEDS_WORK`, or
`FAIL`, with `issues` and `rationale`.

**CALLED BY:** `run_adaptive` after the direct/worker/synthesized candidate and
again after a targeted repair; `run_fixed` keeps its verifier observational.

**TEST:** `test_direct_auto_skips_planner_and_stops_sufficient`,
`test_needs_work_targets_independent_fixes_concurrently`,
`test_fail_verdict_does_not_escalate`, and verifier-unavailable degradation test.

**RUNTIME EVIDENCE:** Runs persist `verification` events with status, issues,
rationale, and `targeted_repair`; successful smoke runs end in a verifier PASS.
V6.1 Groq runs also ended in verifier PASS with usage metadata; Fake/Scripted
responses remain the intentional offline `FAKE` test path.

### 10. Targeted escalation

**IMPLEMENTED AT:** `Orchestrator.run_adaptive` (`:289-321`).

**INPUT:** A `NEEDS_WORK` verifier result and its issue list, subject to
`Budget.allow_escalation()`.

**OUTPUT:** At most one bounded escalation round by default; one repair subtask
per selected issue, followed by synthesis and targeted re-verification. Repair
workers receive the issue text as `escalation_issue`.

**CALLED BY:** Only the adaptive route after the first verifier returns
`NEEDS_WORK`; `PASS` and `FAIL` bypass escalation.

**TEST:** `test_targeted_escalation_evidence_links_issue_to_repair_worker`,
`test_needs_work_targets_independent_fixes_concurrently`, and
`test_fail_verdict_does_not_escalate`.

**RUNTIME EVIDENCE:** `run_0fc1d1282dbd` records one escalation and ends
`STOP_SUFFICIENT`. Its evidence links verifier issue → `T1` repair goal →
targeted Worker → re-verifier PASS; no unrelated full-pipeline rerun occurs.

### 11. Early stopping

**IMPLEMENTED AT:** `run_adaptive` PASS branches (`:285-287` and `:319-321`).

**INPUT:** Verifier status after the candidate, or after targeted repair.

**OUTPUT:** `state.stop_reason = STOP_SUFFICIENT`, a stop event, and no further
adaptive Agent call.

**CALLED BY:** The adaptive verifier gate.

**TEST:** `test_direct_auto_skips_planner_and_stops_sufficient` and targeted
escalation test assert the terminal reason and completed status.

**RUNTIME EVIDENCE:** DIRECT/PARALLEL/PLANNED smoke runs all persist a verifier
PASS followed by a stop event and `STOP_SUFFICIENT` final event.

### 12. Budget constraint

**IMPLEMENTED AT:** `app/core/types.py:22-63` (`Budget`), configured by
`app/main.py:95-103` (`make_budget`), enforced in `_call` and escalation.

**INPUT:** Logical-call, physical-request, worker, retry, escalation, and timeout
limits (environment overrides are read server-side).

**OUTPUT:** Counters and explicit `RuntimeError` terminal states such as
`STOP_BUDGET_LOGICAL_CALLS` and `STOP_BUDGET_PHYSICAL_REQUESTS`; escalation is
allowed only when all required call/request headroom remains.

**CALLED BY:** Every provider call starts a logical budget unit and records a
physical request; `run_adaptive` checks escalation headroom.

**TEST:** `test_logical_budget_stops_before_solver`,
`test_physical_budget_stops_with_explicit_terminal_state`, and the bounded
escalation tests.

**RUNTIME EVIDENCE:** Stopped run evidence remains JSON with status `stopped`,
the explicit budget stop reason, and the counters at the boundary. Normal runs
expose all three counters in `metrics`.

### 13. Timeout

**IMPLEMENTED AT:** `Orchestrator._call` (`:99-121`) wraps each
`provider.generate` call in `asyncio.wait_for`; the timeout is supplied by
`Budget.call_timeout_seconds`.

**INPUT:** One provider request and the configured per-call timeout.

**OUTPUT:** A timeout exception is redacted and propagated to `run`, which emits
an explicit failed terminal (`STOP_FAILURE`) unless a verifier-preservation path
handles the failure.

**CALLED BY:** Every Analyzer, Planner, Worker, Synthesizer, Solver, and Verifier
execution through `_call`.

**TEST:** `RuntimeFlowTests.test_timeout_stops_failed_run` uses a 10 ms timeout
and asserts failure plus two physical requests boundary accounting.

**RUNTIME EVIDENCE:** The stopped/failed run JSON contains the terminal state;
per-agent events contain start/error metadata. No unbounded provider await exists
on the production call path.

### 14. Retry

**IMPLEMENTED AT:** `_call` retry loop (`app/core/orchestrator.py:88-121`) and
`_retry_delay` (`:54-73`).

**INPUT:** A provider/transform exception, retry limit, and optional provider
retry hint (`Retry-After`/`retryDelay`).

**OUTPUT:** One logical call with bounded retry attempts; each attempt increments
physical requests and emits a `retry` event. Exhaustion emits `agent_error`.

**CALLED BY:** All role executions through `_call`.

**TEST:** `test_structured_output_retry_is_one_logical_call_two_requests` asserts
one Analyzer logical execution, two Analyzer provider calls, total `3` logical /
`4` physical, and a retry event. `test_retry_delay_uses_provider_retry_hint`
checks provider delay extraction.

**RUNTIME EVIDENCE:** Run events contain `retry` with `next_attempt` and
`physical_request`; metrics keep logical and physical totals separate.

### 15. Stop states

**IMPLEMENTED AT:** `Orchestrator.run` (`app/core/orchestrator.py:349-375`) and
adaptive stop branches.

**INPUT:** Successful candidate/verdict, budget/timeout/runtime exceptions, or
verifier availability.

**OUTPUT:** `completed` + `STOP_SUFFICIENT`/`COMPLETED`, `stopped` + explicit
policy/budget reason, `failed` + `STOP_FAILURE`, or `degraded` +
`STOP_VERIFICATION_UNAVAILABLE` with a preserved candidate.

**CALLED BY:** The outer run wrapper for every strategy; `app/main.py:292-301`
persists the final state and events.

**TEST:** Direct PASS, logical/physical budget, timeout, verifier-unavailable,
FAIL-no-escalation, failed-stream, and stopped-run evidence tests.

**RUNTIME EVIDENCE:** `runs/*.json` retains completed, degraded, failed, and
stopped records; the API final event repeats status, stop reason, metrics, and
run ID. Raw evidence is not replaced by an aggregate.

### 16. Instrumentation

**IMPLEMENTED AT:** `_call` (`:76-121`), `RunState.event` and usage accounting
(`app/core/types.py:65-91`), `Orchestrator.metrics` (`orchestrator.py:377-389`),
and `execute_once` persistence (`app/main.py:282-301`).

**INPUT:** Every role call, provider attempt/result, timestamps, usage metadata,
request ID, route/scheduler/verifier events, and final state.

**OUTPUT:** Safe `agent_start`/`provider_request`/`agent_end`/`agent_error` and
control events; `execution_id`, logical call number, physical request count,
role, goal, dependencies, start/end/duration, provider/model, token usage,
status, bounded output preview, run metrics, and JSON evidence. Prompts and
secrets are not persisted in Agent metadata.

**CALLED BY:** `_call` for each bounded runtime execution; `_event` for routing,
DAG, scheduler, verifier, escalation, and stop transitions; `execute_once`
saves the complete `RunState`.

**TEST:** `test_agent_execution_evidence_is_distinct_from_calls_and_bounded`,
`test_targeted_escalation_evidence_links_issue_to_repair_worker`,
`test_execute_once_saves_json_evidence`, and the T5 inspector contract tests.

**RUNTIME EVIDENCE:** The local HTTP PARALLEL run contains `AE-001` onward,
separate logical/physical counters, provider request IDs, usage, timing, and
bounded previews. A metadata-key scan found no `system`, `user`, `prompt`, or
key fields. `metrics.e2e_ms` is calculated from the run's monotonic wall clock;
worker durations are not summed.

## V6.3 baseline contract audit

### Fixed BEFORE

`run_fixed` called `plan` for every task, padded/truncated the provider plan to
three nodes, and passed provider-selected dependencies to `execute_dag`. The
Worker count happened to be three, but role/dependency topology was not a
versioned cross-task fixture; a verifier result was observational only.

### Fixed AFTER

`FIXED-TOPOLOGY-V1` freezes Planner presence, three independent S1/S2/S3 Worker
slots, ready-set concurrency, observational Verifier, Synthesizer, retry,
timeout, and budget identity. Planner output is mapped to goal text only. The
run emits `Fixed topology frozen` plus a fixed topology signature, and no
Adaptive route or targeted escalation is called. Regression evidence covers
four materially different task/plan shapes with one identical signature.

### Static BEFORE

`run_static` analyzed once and selected a mode, but its Worker count and planned
dependencies came directly from task-specific Analyzer/Planner output; no
versioned preset identity was persisted, and a stronger freeze could not be
audited across runs.

### Static AFTER

`STATIC-PRESETS-V1` defines versioned DIRECT, PARALLEL, and PLANNED presets with
role sequence, Worker count, dependency/concurrency policy, Verifier and
Synthesizer presence, and `runtime_escalation=false`. `choose_static_preset`
runs once after the Structural Analyzer; selected preset identity/version is
persisted. Planner goal text is mapped into fixed slots, and a Verifier
`NEEDS_WORK` is recorded as observational evidence without adding workers or
switching presets. Tests patch Adaptive `choose_mode` to prove Static does not
invoke that runtime router.

### Configuration identity evidence

Every RunState carries safe `strategy_config_id`/version plus MODEL, MODEL
SETTINGS, RAG, ORCH, PRICE, prompt-version, and budget identities. Fixed raw
runs share `FIXED-TOPOLOGY-V1`; Static raw runs record
`STATIC-PRESETS-V1` and the selected `STATIC-*` preset. Compare still freezes
one snapshot/provider/model/settings and runs Single, Fixed, Static, Adaptive
sequentially.

## Correctness conclusion and known limits

- **Implemented:** all 16 adaptive components above have concrete production
  functions, call sites, tests, and event/metric evidence.
- **Corrected:** Analyzer no longer receives internal task labels; a regression
  test guards this boundary.
- **FAKE by design:** FakeProvider/ScriptedProvider generation. They validate
  orchestration mechanics offline and must not be presented as live LLM quality.
- **UNVERIFIED:** live Gemini/OpenAI provider generation and pixel-level visual
  review. Groq/OpenRouter live generation and DOM/viewport checks are verified;
  no network absence is classified as a provider failure.
- **V6.3 closed:** Fixed and Static baseline topology/preset identity gaps are
  covered by production evidence and regression tests. They remain pilot
  configurations, not a declaration that Main Freeze has occurred.

## Regression gate

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m compileall -q app tests scripts
node --check app/static/app.js
.\.venv\Scripts\python.exe scripts\smoke_matrix.py --provider fake
```

Audit result after the V6.3 closure: **58/58 tests PASS**, compile and JS syntax
checks PASS, `pip check` reports no broken requirements, and the Fake smoke
matrix is **4/4 PASS**.

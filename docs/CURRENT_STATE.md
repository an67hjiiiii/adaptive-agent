# Current state — verified 2026-08-30 (V6.3 / PILOT-FIX-D)

This file records only facts checked against the extracted V5 source, tests, and
the local FastAPI instance. It must be updated when evidence changes. No provider
key values are recorded here.

## Build and runtime identity

- Application version: `0.6.3` (`app/main.py`).
- The Pilot design/preregistration review is documented in
  [`docs/PILOT_PREREGISTRATION.md`](PILOT_PREREGISTRATION.md); this document
  records design decisions and open gates only and does not claim Pilot runs.
- FastAPI serves `/` and `app/static/`; the checked instance is at
  `http://127.0.0.1:8000`.
- `/api/health` and `/api/config` returned HTTP 200 during this audit.
- `/api/config` reports `chat_strategy=adaptive-auto` and safe model choices.
- The extracted archive has no `.git` directory, so a Git diff cannot be
  produced in this copy.

## Verified architecture

- `app/main.py` validates requests, selects provider/model, creates the frozen
  snapshot, streams NDJSON events, persists runs/conversations, and exposes
  health/config/provider-test/diagnostic/compare APIs.
- `app/core/rag.py` performs deterministic, safely normalized lexical chunk
  selection and returns a content-derived snapshot ID/hash, source/chunk
  provenance, retrieval settings, creation time, and explicit truncation
  metadata; an empty source is represented explicitly.
- `app/core/orchestrator.py` validates analyzer/planner/verifier JSON, chooses
  DIRECT/PARALLEL/PLANNED, enforces budgets/retry/timeout, and emits evidence.
- The Structural Analyzer system prompt is limited to the observable task,
  frozen context, and declared structural schema; internal task labels are not
  sent to the Analyzer. It also distinguishes direct factual lookups,
  explicit prerequisites, independent aspects, and conflict/exception signals.
- Each bounded runtime Agent Execution now emits a safe execution ID, logical
  call number, role/goal/dependencies, relative start/end/duration, provider /
  model, request count, usage, status, and bounded output preview. Hidden
  prompts are not included in this instrumentation.
- `app/core/graph.py` rejects duplicate/unknown/self/cyclic dependencies and
  supplies Kahn-style ready sets.
- Independent workers use `asyncio.gather`; the verifier can request bounded,
  targeted repair workers.
- Runs are saved as JSON under `runs/`; conversations are saved under
  `runs/conversations/`. Writes use temporary files and replacement.
- Main chat dispatches Adaptive AUTO. Compare calls `single`, `fixed`, `static`,
  and `adaptive` sequentially with one frozen snapshot; each strategy receives a
  separate copy of the same provenance metadata so one run cannot mutate the
  comparison unit for the next.
- Compare freezes provider/model/budget/retrieval settings for all four runs,
  returns each answer and stop state with Agent/Logical/Physical counts and
  token/latency/cost fields, labels quality `Not evaluated`, keeps unavailable
  usage/cost as `null`, and persists a separate raw JSON record for each result,
  including pre-execution failures.
- The browser UI groups each user/assistant turn, loads the full conversation
  session, supports rename/delete, provider/model selection, context upload,
  inspector metrics, raw evidence, JSON export, and a Frozen Context Snapshot
  panel showing the selected chunk IDs/text and any recorded truncation.
- V6.2 uses a chat-first neutral UI with one restrained accent, readable
  transcript typography, a compact evidence rail, and progressive disclosure.
  Sidebar and inspector state persist, collapsed panels reclaim chat width,
  compare/export remain in an advanced menu, and raw traces never interrupt
  the transcript.
- The V6.2 Inspector defaults closed for a fresh user and retains Overview,
  evidence-driven Graph, expandable Agent Execution cards, separate Metrics,
  and Raw JSON actions. Missing provider usage/cost is rendered `Unavailable`
  rather than a fake zero.
- T5 adds an evidence-driven Execution Inspector with Overview, Graph, Agents,
  Metrics, and Raw views. The SVG graph is built from recorded roles, plan
  subtasks/dependencies, scheduler batches, verifier escalation, and final
  stop evidence; Agent cards never render hidden prompts by default.
- T6 audits all 16 claimed adaptive components against concrete functions,
  call-sites, tests, and runtime events in `docs/ORCHESTRATION_AUDIT.md`;
  the Analyzer hidden-label boundary is mechanically covered.
- V6.3 closes the baseline topology gaps. Fixed uses the versioned
  `FIXED-TOPOLOGY-V1` configuration: Planner goal text is mapped into exactly
  S1/S2/S3 independent Worker slots, followed by its observational Verifier
  and Synthesizer. Planner output cannot add/remove slots, add dependencies,
  or trigger escalation.
- V6.3 Static uses the versioned `STATIC-PRESETS-V1` catalog. One initial
  structural analysis selects `STATIC-DIRECT-V1`, `STATIC-PARALLEL-V1`, or
  `STATIC-PLANNED-V1`; the selected preset and version are persisted and no
  runtime route/preset change or Adaptive escalation is allowed.
- Every persisted run now records safe strategy/model/RAG/orchestrator/price
  configuration identities, prompt versions, budget identity, and (for Static)
  the selected preset identity. Failed pre-execution comparison records carry
  the same identity fields.
- PILOT-R4 adds `app/core/pilot.py` and `scripts/pilot_harness.py` as a thin,
  separate experiment-control layer. It creates a no-secret `PILOT-R4-V1` Run
  Manifest, balanced seeded Latin-square order, unique-run append ledger with
  interrupted-run recovery, and a derived processed export. It does not change
  the meaning or runtime routing of Single, Fixed, Static, or Adaptive.
- PILOT-FIX-D adds `app/core/pilot_executor.py` and bounded
  `validate`/`status`/`run`/`resume` controls. The executor consumes the frozen
  manifest in declared top-level order, defaults to one new condition, stamps
  one shared context snapshot per comparison unit, preserves interrupted and
  failed attempts, and keeps DRY_RUN/PREFLIGHT outside the default Pilot export.
  No 96-condition Pilot block was run in this audit.
- The checked-in Pilot configuration snapshot uses Groq /
  `openai/gpt-oss-120b` as the candidate, preserves the existing identities,
  adds manifest-only aliases `MODEL-PILOT-V1`, `RAG-PILOT-V1`,
  `ORCH-PILOT-V1`, `FIXED-PILOT-V1`, `STATIC-PILOT-V1`, and
  `PRICE-PILOT-V1`, and freezes explicit generation settings in
  `config/pilot/MODEL_PILOT_V1.json`.
- `PRICE-PILOT-V1@1.1` is now a verified Groq snapshot: $0.15 input, $0.075
  cached input, and $0.60 output per 1M tokens in USD. No separate reasoning
  rate is published; unavailable fields remain explicit and are never mapped
  to zero. Calculated cost uses the frozen snapshot and provider-reported cache
  detail when available.

## Providers and current safe status

The catalog contains `fake`, `gemini`, `groq`, `openrouter`, and `openai`.
After the V6.1 server-side configuration, `/api/config` reported:

```text
available: fake=True, gemini=True, groq=True, openrouter=True, openai=True
status:    fake=ready, gemini=unknown, groq=ready, openrouter=ready, openai=unknown
```

`unknown` means a configured provider has no current successful server-side API
test badge; it is not evidence of provider failure. Groq and OpenRouter each
returned `SUCCESS` from a live generation diagnostic. No key value is recorded
or exposed here.

The provider diagnostic schema is shared by the API and
`scripts/provider_probe.py`. It distinguishes configuration, network/DNS,
timeout, authentication, permission, model, rate/quota/credit, and upstream
errors without returning raw provider bodies. A provider/model/key change
invalidates the stored live-check badge; no-key providers remain `missing`.

## Tests verified in this audit

- `python -m unittest discover -s tests -v`: **73/73 PASS**, including the
  V6.3 Fixed cross-task topology, observational verifier, Static preset
  selection/freeze, strategy-identity regressions, PILOT-R4 manifest/ledger/
  export/runtime checks, and seven PILOT-FIX-D executor control checks.
- `python -m compileall -q app tests scripts`: **PASS**.
- `node --check app/static/app.js`: **PASS**.
- `scripts/smoke_matrix.py --provider fake`: **4/4 PASS** — DIRECT,
  PARALLEL, PLANNED, and targeted-escalation cases.
- V6.3 baseline smoke: **PASS** — Fixed T1/T2/T3/T4 retain one topology and
  three Worker slots; Static direct/parallel/planned presets remain selected
  after initial analysis; Static NEEDS_WORK remains observational.
- Compare API smoke: **PASS** — four top-level strategies ran sequentially,
  all consumed one Frozen Context Snapshot, and each raw result persisted its
  own strategy config identity.
- `scripts/runtime_check.py --write-test --timeout 30`: **PASS** — health,
  config, and two-turn/one-conversation persistence.
- `START_WINDOWS.ps1 -NoBrowser`: **PASS** with the project-local `.venv` and
  the checked server URL; a missing-dependency/network branch emits
  `NETWORK_DEPENDENCY_BLOCKED` without selecting another environment.
- T9 API release checks: **PASS** for health/config/static, context-upload
  contract, conversation persistence, rename/delete, Adaptive DIRECT/PARALLEL/
  PLANNED/escalation graphs, Compare 4/4, and raw evidence export.
- `scripts/provider_probe.py`: Fake **PASS**; Groq live diagnostic **PASS**
  (`openai/gpt-oss-120b`, usage metadata available); OpenRouter live diagnostic
  **PASS** (`openrouter/free`, usage metadata available). Gemini and OpenAI were
  not re-probed in V6.1 and remain `unknown` in the badge.
- V6.2 final minimal Groq diagnostic: **PASS** — authenticated, model access and
  generation succeeded; usage metadata was returned. No key was printed.
- PILOT-FIX-C frozen-settings Groq preflight: **PASS** — the exact Pilot
  request parameters were accepted for `openai/gpt-oss-120b`; network,
  authentication, model access, generation and usage metadata all succeeded.
  The response exposed `completion_tokens_details.reasoning_tokens`; no key or
  response text was persisted. See
  [`docs/GROQ_PILOT_PREFLIGHT.md`](GROQ_PILOT_PREFLIGHT.md).
- V6.1 live Groq scenarios (same model for Analyzer, Planner, Workers,
  Synthesizer, Verifier): T1 **DIRECT/STOP_SUFFICIENT** (3 agents, 3 logical,
  3 physical requests); T2 **PARALLEL/STOP_SUFFICIENT** (3 Workers overlap in
  runtime timestamps, 6 agents, 6 logical, 6 physical); T3
  **PLANNED/STOP_SUFFICIENT** (DAG ready sets observed, dependency batch
  ordering); T4 **PLANNED/STOP_SUFFICIENT** with high verification demand.
  All four returned provider usage and calculated cost fields.
- Browser DOM/viewport and screenshot checks observed required controls, no
  horizontal overflow, clean chat grouping, working drawers/transitions, and
  readable Inspector views at 1366x768, 1920x1080, and 900x768. Browser actions
  also verified context file upload, compare 4/4, JSON download, full-session
  restore, panel/tab persistence, and actual DIRECT/PARALLEL/PLANNED/escalation
  evidence graphs.
- PILOT-R4 Fake infrastructure dry-run: **PASS** — one non-benchmark task,
  four strategies in manifest order, four separate raw records tagged
  `DRY_RUN=true`, one shared snapshot ID, and a four-row derived export.
- PILOT-R4 manifest preparation against the supplied quality-reviewed benchmark
  artifact: **PASS mechanically** — 24 units / 96 conditions, six occurrences
  per strategy and ordinal position, source hashes and rubric-version
  references carried as metadata only. The artifact is not by itself
  authorization for live execution.
- PILOT-FIX-D bounded executor control checks: **PASS** — manifest validation,
  sequential limit/order, completed-condition duplicate prevention, stale-run
  recovery with a new attempt ID, provider-error persistence and explicit
  retry, same-snapshot fairness, hidden-rubric projection exclusion, and
  DRY_RUN/PREFLIGHT export separation.
- PILOT-FIX-C rate-limit feasibility: **PARTIAL/CONDITIONAL** — Fake measured
  13 provider calls per comparison unit (312 baseline / 624 one-retry stress;
  the 1,728 per-condition budget ceiling exceeds the published 1K RPD request
  figure); exact Groq organization limits still require an Integration
  Limits-page check and throttled batching.

## Known discrepancies and environment limits

- Fixed and Static contract gaps identified in V6.2 are closed by the
  versioned configurations and regressions above. The Planner still supplies
  task-specific goal text, which is explicitly allowed; it cannot alter the
  Fixed/Static topology or policy.
- A genuinely fresh virtualenv still needs `requirements.txt`; dependency
  installation can be blocked by this environment's outbound network policy.
  `START_WINDOWS.ps1` reports that condition explicitly and never falls back to
  another project's environment.
- Visual browser checks are manual runtime evidence and therefore remain outside
  the automated regression count (the historical V6.3 count was 73; Task H
  current count is 97).

## Task H integration verification (2026-08-31)

The current full regression after the integration controls is **97/97 PASS**.
The same run also passed Python compilation, JavaScript syntax, and dependency
checks. New mechanical coverage includes benchmark/rubric/corpus identity
hashes, E2E wall-clock inclusion of provider/retry/parallel critical-path
delays, explicit `MAIN_FREEZE_REQUIRED` rejection, fresh preflight age/identity
checks, and shared pacing honoring `retry-after`.

Offline Pilot readiness checks are **PASS** for the eight-task snapshot
completeness validator (8/8 required supporting sections present with the
global `RAG-LEXICAL-V1@1.1` settings), canonical manifest validation
(`pm_9eced06dc61e`, 24 units/96 conditions), runtime-safe projection, Fake
four-strategy dry-run, and raw/ledger integrity tests. No Pilot condition was
executed.

The latest bounded Groq PREFLIGHT at `2026-08-31T04:17:19.200315Z` is
`PASS` for network, authentication, model access, generation, usage metadata,
and `MODEL-SETTINGS-V1`. The adapter did not expose current rate-limit headers
on this response; the historical safe header snapshot remains separately
marked. Gemini and OpenAI remain unverified in this environment; Fake remains
offline-successful.

The checkout's project-local `.venv` is a OneDrive reparse-point runtime whose
Python executable returned Access Denied in this sandbox. Regression commands
were run with the configured dependency-complete sibling runtime, while the
startup script still refuses to substitute another environment. This is an
environment limitation, not application-pass evidence.

The final integration gate decision is **NOT_PILOT_READY** despite the green
offline/live smoke checks. At Task H close, two research-side P1 decisions
were still open in the preregistration/QEP handoff: the operational
missingness/incomparable-unit threshold and a concrete, pre-outcome
manual-exclusion/evaluator-capacity record. Task I-A closes those two
research-control decisions below; the candidate still has no embedded
preflight binding, and the latest probe did not expose current account
rate-limit headers. Conservative pacing and the historical limit snapshot are
therefore not a substitute for the remaining integration sign-offs. No Pilot
condition was executed.

## Task I-A operational freeze (2026-08-31)

The two Task H research-control P1s are closed by the evaluation-side freeze:
`QEP-DENOMINATOR-V1` now binds
`PILOT-DIFFERENTIAL-MISSINGNESS-V1` with numeric threshold `0`, and
`PILOT-CASE-E-ADMIN-V1` defines the closed administrative allowlist,
independent approval, and approval-before-unblinding timing. The
`PILOT-EVALUATOR-PACKETS-V1` registry contains 96 stable `PLANNED` records;
E1/E2/ADJ-1 are `UNASSIGNED` and evaluator capacity is `UNCONFIRMED` until
actual staffing is recorded. No Pilot condition was executed or authorized;
the remaining provider, pacing, preflight, and integration gates are
unchanged.

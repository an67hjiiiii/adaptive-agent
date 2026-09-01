# Current state — verified 2026-08-30 (V6.3)

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

- `python -m unittest discover -s tests -v`: **58/58 PASS**, including the
  V6.3 Fixed cross-task topology, observational verifier, Static preset
  selection/freeze, and strategy-identity regressions.
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
  the automated 52-test regression count.

# Pilot execution protocol — PILOT-R4

**Status:** infrastructure prepared; live Pilot execution is not authorized by
this document.

**Purpose:** make the preregistered Pilot reproducible and auditable while
keeping research semantics, benchmark content, and hidden rubric ownership in
their existing workstreams. This protocol is an execution-control contract,
not a new orchestration algorithm and not a quality-evaluation protocol.

## Readiness conclusion

The V6.3 runtime already supplies the bounded orchestration paths and safe raw
run evidence. PILOT-R4 adds the missing control plane in
`app/core/pilot.py` and `scripts/pilot_harness.py`:

- a no-secret, versioned Pilot configuration snapshot;
- a Run Manifest containing comparison units, strategy/config identities,
  provider/model/settings, snapshot placeholders, canonical benchmark/rubric references,
  pricing identity, execution order, run IDs, and condition status;
- deterministic benchmark reference-scope resolution that fails closed on an
  invalid section and shares one scoped Frozen Context Snapshot across all four
  strategy conditions;
- a deterministic balanced Latin-square order schedule;
- an append-oriented condition ledger that reserves unique run IDs, preserves
  failed/stopped attempts, and recovers interrupted reservations without
  overwriting raw evidence;
- a bounded `PilotExecutor` that consumes the frozen schedule, runs top-level
  conditions sequentially through the existing `execute_once` path, and resumes
  only uncompleted conditions;
- a derived tidy dataset exporter that reads raw evidence and retains
  unavailable usage/cost as `null`.

No benchmark task text, expected facts, rubric contents, or evaluator labels are
created by this work. The authoritative Pilot benchmark identity is
`pilot_benchmark_v1@1.1.0`; `PILOT-R2` is retained only as the benchmark
workstream/provenance label. A supplied task manifest is represented by ID,
version, hash, source IDs/hashes, declared section scope, and a rubric-version
reference only.

## Frozen identities and candidate provider

The versioned identities are inherited from the existing runtime constants; the
Pilot layer does not introduce a second provider/configuration registry.

| Concern | Identity | Version |
| --- | --- | --- |
| Pilot execution control | `PILOT-EXECUTION-INFRA-V1` | `1.0` |
| Run Manifest | `PILOT-R4-V1` | `1.0` |
| Pilot benchmark | `pilot_benchmark_v1` | `1.1.0` |
| Benchmark provenance label | `PILOT-R2` | workstream label only |
| Model catalog runtime anchor | `MODEL-CATALOG-V1` | `1.0` |
| Model Pilot snapshot alias | `MODEL-PILOT-V1` | `1.1` |
| Model settings | `MODEL-SETTINGS-V1` | `1.1` |
| Retrieval runtime anchor | `RAG-LEXICAL-V1` | `1.0` |
| RAG Pilot snapshot alias | `RAG-PILOT-V1` | `1.0` |
| Adaptive runtime anchor | `ORCH-ADAPTIVE-AUTO-V1` | `1.0` |
| Orchestrator Pilot snapshot alias | `ORCH-PILOT-V1` | `1.0` |
| Single | `SINGLE-DIRECT-V1` | `1.0` |
| Fixed runtime anchor | `FIXED-TOPOLOGY-V1` | `1.0` |
| Fixed Pilot snapshot alias | `FIXED-PILOT-V1` | `1.0` |
| Static runtime anchor | `STATIC-PRESETS-V1` | `1.0` |
| Static Pilot snapshot alias | `STATIC-PILOT-V1` | `1.0` |
| Pricing runtime anchor | `PRICE-TABLE-V1` | `1.1` |
| Pricing Pilot snapshot alias | `PRICE-PILOT-V1` | `1.1` |

The Pilot aliases are persisted alongside their runtime anchors so integration
can identify the frozen block without introducing another source of values.
The live Pilot candidate is the already recorded configuration:

```text
provider = groq
model    = openai/gpt-oss-120b
```

The Pilot adapter sends the model, system/user messages, and the explicit
request controls in `config/pilot/MODEL_PILOT_V1.json`. The frozen candidate is:

| Request control | Frozen value | Evidence/status |
| --- | --- | --- |
| `temperature` | `0.6` | Explicit; within Groq's documented reasoning range |
| `max_completion_tokens` | `4096` | Explicit; bounded below the model's `65536` maximum |
| `top_p` | `1.0` | Explicit documented default; temperature is the only diversity control |
| `reasoning_effort` | `medium` | Explicit; supported by GPT-OSS 120B and documented default |
| `include_reasoning` | `false` | Explicit through `extra_body`; keeps reasoning out of answer text |
| `response_format` | `{"type":"text"}` | Explicit |
| `stream` | `false` | Explicit |
| `n` | `1` | Explicit; Groq currently supports only one choice |
| `service_tier` | `on_demand` | Explicit; avoids implicit tier selection |
| `seed` | not sent | `UNUSED_BY_DESIGN`; repeats remain independent |
| `reasoning_format` | not sent | `UNSUPPORTED` for GPT-OSS; use `include_reasoning` instead |
| `stop` | not sent | `PROVIDER_DEFAULT_NULL` |

Tool-calling controls (`tools`, `tool_choice`, `parallel_tool_calls`), stream
options, `user`, `store`, search/document controls, and citation behavior are
explicitly marked unused, not applicable, or provider-default in the model
snapshot. Unsupported penalties/logprobs and deprecated `max_tokens` are not
sent.

Provider-level SDK retries are explicitly `0`; the orchestrator owns one retry
per logical call with a `1.0`-second base, `30.0`-second maximum backoff and a
`60.0`-second call timeout. The adapter client timeout is also `60.0` seconds.
The Pilot budget remains 12 logical calls, 18 physical requests, 3 workers and
1 escalation per condition.

Credentials never enter the configuration snapshot, manifest, ledger, raw
metadata, logs, or frontend.

## Pricing rule

`config/pilot/PRICE_PILOT_V1.json` is a verified snapshot as of
`2026-08-30T13:49:38Z`:

- input: `$0.15` per 1M tokens;
- cached input: `$0.075` per 1M tokens when a cache hit is reported;
- output: `$0.60` per 1M tokens;
- currency: USD;
- separate reasoning-token rate: **Unavailable** (no separate rate is
  published; `completion_tokens_details.reasoning_tokens` is retained as a
  usage breakdown and the reported `completion_tokens` total uses the output
  rate).

The authoritative [Groq model page](https://console.groq.com/docs/model/openai/gpt-oss-120b)
and [prompt-caching documentation](https://console.groq.com/docs/prompt-caching)
are recorded in the snapshot. Calculated API Cost uses this frozen table,
applying the cached input rate only to provider-reported cached tokens and never
substituting zero for an unavailable rate or usage field.

## Run Manifest contract

The JSON shape is implemented by `build_pilot_manifest` and documented by
`config/pilot/PILOT_RUN_MANIFEST_SCHEMA_V1.json`. A live manifest is created
from the separate benchmark task manifest and contains 8 tasks × 3 repeats =
24 comparison units and 96 strategy conditions. It does not copy task text or
rubric contents.

Each unit contains:

- `unit_id`, `task_id`, `repeat_index`/`repeat_id`;
- task/reference manifest version and hashes, canonical benchmark ID/version,
  provenance label, and rubric version reference;
- source document IDs/hashes, resolved `reference_scope`, and a scope hash;
- `order_seed`, Latin-square row, complete `strategy_order`, and per-strategy
  `execution_order`;
- four conditions, each with `strategy`, `strategy_config_id`/version,
  provider, model, model-settings identity, pricing version, snapshot ID/hash
  placeholders, `run_id`, raw-evidence path, and status.

The runtime receives only the task and Frozen Context Snapshot. Hidden rubric
contents are never runtime inputs.

## Reference scope enforcement

For every benchmark task, the execution path is:

```text
benchmark task
  -> reference_bindings (source_id + section_ids)
  -> frozen CORPUS_MANIFEST.json section catalog and line ranges
  -> scoped source text (only declared sections)
  -> one Frozen Context Snapshot per comparison unit
  -> the same snapshot for Single, Fixed, Static, and Adaptive
```

`tasks[].reference_bindings` is authoritative; legacy heading/line anchors are
traceability only. Each declared `section_id` must resolve to a catalog entry
whose 1-based inclusive `line_range` is inside the hashed source file. Missing,
duplicate, malformed, or out-of-range sections fail closed before a condition
can run. The executor never falls back to the full source merely because its
hash is valid. A whole document is allowed only with an explicit
`whole_document=true` binding; source IDs without a binding cannot fall back to
inline context as an implicit whole-document path. Snapshot metadata records
source IDs, full-source hashes, resolved section IDs/scope hash, context
snapshot ID/hash, and chunk provenance; the scope and snapshot are ledger-
checked for all four strategies.

## Order control

The live schedule uses these four Latin-square rows:

```text
Single,   Fixed,    Static,   Adaptive
Fixed,    Static,   Adaptive, Single
Static,   Adaptive, Single,   Fixed
Adaptive, Single,   Fixed,    Static
```

For 24 units, six units are assigned to each row. A seeded Fisher–Yates step
shuffles the unit assignment and the expanded row labels. Each unit also
records a seed derived as:

```text
SHA-256(preregistration_version | task_manifest_hash | unit_id)
```

`validate_order_schedule` checks exact strategy coverage, unique units, the
execution-order map, and six occurrences of each strategy at every ordinal
position. Top-level conditions are executed sequentially. Internal independent
Workers may remain concurrent, and their durations are not summed into E2E
latency.

The existing `/api/compare/stream` endpoint remains a UI/demo endpoint with
its fixed order. It is not the live Pilot harness. The Pilot harness must use a
validated manifest schedule instead.

## Raw evidence and ledger safety

`PilotLedger` stores `manifest.json` and `ledger.json` under one Pilot output
directory and raw run JSON under its `raw/` child. Before execution, `begin`
reserves a new unique `run_id` and writes the reservation. A completed
(`observed`) condition cannot be started again. Failed, stopped, provider-error,
and invalidated conditions can be retried only with explicit opt-in; each retry
gets a new attempt/run ID. `record` requires the matching raw file and records a
terminal status without modifying that raw file.

Allowed condition statuses are:

```text
observed | missing_not_run | failed | stopped | provider_incident | invalidated
```

If a process stops while a condition is `running`, `recover_interrupted`
first reconciles a matching completed/failed/stopped raw file if one exists.
Otherwise it records an interrupted attempt as `missing_not_run`, clears only
the active reservation, and requires a new run ID for any later attempt. The
old run ID/path remains in the attempt history. This prevents duplicate
completed conditions, raw overwrite, loss of failures, and config-version
mixing.

The ledger also exposes the compact operator states `PENDING`, `RUNNING`,
`COMPLETED`, `FAILED`, `STOPPED`, and `PROVIDER_ERROR`; the protocol statuses
above remain the persisted missing-data vocabulary.

Every raw runtime record continues to retain the existing event evidence and
summary metrics:

```text
Agent Executions
Logical Model Calls
Physical Provider Requests
input/output/total tokens
cached input tokens when reported
reasoning tokens when reported
E2E latency
retries and escalations
stop reason/status
provider/model and config identities
Frozen Context snapshot/hash/chunk provenance
calculated cost when usage and a verified price are available
```

Provider incidents are represented by normalized category/safe message only;
raw provider bodies and credentials are excluded.

## Provider limits and pacing gate

The account snapshot is frozen in [`docs/PILOT_PROVIDER_LIMITS.md`](PILOT_PROVIDER_LIMITS.md):
organization `RPM=30`, `RPD=1000`, combined `TPM=8000`, `TPD=200000`, and no
project override. Separate ITPM/OTPM values are
`SEPARATE_ITPM_OTPM_NOT_VERIFIED`; execution uses the combined TPM ceiling and
never invents a split. The historical `phase=PREFLIGHT` response observed the
safe `x-ratelimit-limit-requests=1000` and `x-ratelimit-limit-tokens=8000`
headers; the latest integration probe succeeded but did not expose current
account-limit headers through the adapter, so the historical safe header
snapshot remains the recorded account-header evidence.

Measured Fake call shape is `Single=1`, `Fixed=6`, `Static=3`,
`Adaptive=3` per comparison unit: 312 physical requests for the 24-unit
no-retry baseline, 624 under one retry per observed call, and a hard 1,728
per-condition budget ceiling. The hard ceiling is above RPD and Fake does not
model GPT-OSS reasoning tokens. Integration therefore paces aggregate requests
at no more than 20/minute until fresh headers support another rate, keeps at
most three in-flight workers, honors `retry-after`, and pauses/splits when
remaining quota cannot cover the planned attempt budget. Rate-limited attempts
are operational missingness/provider incidents, not quality failures.

## Pacing and authorization mechanism (PILOT-FIX-I-B)

The machine-readable mechanism is versioned in
`config/pilot/PILOT_PACING_POLICY_V1.json` and is surfaced by
`pilot_config_snapshot()` as `pacing_policy`. Its canonical policy identity is
`GROQ-PILOT-PACING-V1@1.0`: at most 20 requests/minute, three in-flight
requests, combined TPM 8,000, RPD 1,000, and TPD 200,000. A local ten-percent
daily headroom retains effective local guards of RPD 900 and TPD 180,000; the
headroom is a safety policy, not a claim about a second provider quota. The
legacy executor aliases (`max_in_flight_workers`,
`aggregate_token_ceiling_per_minute`, and the conservative RPM field) remain
in the snapshot for compatibility.

`app/core/pilot_authorization.py` provides the no-provider-call mechanism:

- `LocalPilotUsageLedger` records only this execution's requests, known token
  observations, local date, and live-window ID. Provider-wide remaining quota
  is always `UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING`; an absent or unexposed
  rate-limit header is `UNAVAILABLE`, never zero. The local RPD/TPD guard fails
  closed when known usage would cross the effective safety ceiling.
- Retry-After accepts seconds or an HTTP date. A valid hint is honored; a
  missing/invalid hint is represented explicitly and lets the bounded
  exponential-backoff policy remain in charge. Rate-limit incidents are
  recorded as provider operational missingness, not answer-quality failures.
- `PILOT_PREFLIGHT_BINDING_V1` requires exactly one successful `PREFLIGHT`
  result bound to the manifest ID and matching provider, model, model-settings
  identity, freeze/config identity, and a fresh timezone-aware timestamp.
  Mismatch or staleness fails closed. I-B does not run a new Groq preflight;
  I-C owns the final live preflight.
- `PILOT_AUTHORIZATION_V1` is a pure record schema. It uses role
  `PROJECT_OWNER` and scope `AUTHORIZE_PILOT_EXECUTION`, and carries the
  manifest, freeze/candidate, preflight, window, timestamp, and status IDs.
  Creating or validating this record has no executor/provider side effect and
  does not issue the final authorization decision.
- `PILOT_LIVE_WINDOW_V1` requires an actual future `not_before`/`not_after`
  pair, an explicit project/owner timezone, a maximum duration (four hours by
  default), the authorization scope, and a lifecycle status. No expiring
  window is hardcoded into the repository; Integration supplies the real future
  window at final authorization time and must not reinterpret owner wall-clock
  input as UTC.

These schemas and validators close the technical gate only. They do not alter
benchmark, rubric, corpus, strategy, orchestration, RAG, or quality semantics,
and they do not authorize or execute any of the 96 research conditions.

## Derived export

`export_processed_dataset` reads the ledger and raw JSON and writes
`processed/dataset.json`. By default it includes only `phase=PILOT` rows; the
`--include-dry-run` and `--include-preflight` switches are explicit engineering
exports. `rows` contains one deterministic canonical attempt per condition,
while `attempt_rows` preserves every recorded attempt (including superseded or
interrupted attempts) and unrun assignments. Raw events, task text, context
text, and hidden rubric material are not rewritten into the processed table.
Missing usage and unverified pricing remain `null`; the export does not impute
or clean raw evidence.

## Commands

Prepare a live manifest after the benchmark workstream supplies its separate
versioned task manifest:

```powershell
.\.venv\Scripts\python.exe scripts\pilot_harness.py prepare `
  --task-manifest path\to\task_manifest.json `
  --output runs\pilot\pilot_manifest.json
```

The command validates the 4-way balanced order when the supplied manifest has
24 comparison units. It does not call a provider.

Validate a manifest and its optional source-task binding:

```powershell
.\.venv\Scripts\python.exe scripts\pilot_harness.py validate `
  runs\pilot\pilot_manifest.json `
  --task-manifest path\to\task_manifest.json
```

Create/open a ledger and execute only the next bounded conditions. The executor
uses the manifest's unit/strategy order; it never delegates top-level runs in
parallel:

```powershell
.\.venv\Scripts\python.exe scripts\pilot_harness.py run `
  runs\pilot\pilot-ledger `
  --manifest runs\pilot\pilot_manifest.json `
  --task-manifest path\to\task_manifest.json `
  --phase PILOT --limit 1 --allow-live
```

`--limit` counts new condition attempts, not model calls. The default is one.
`--allow-live` is required for any non-Fake provider. A failed/stopped
strategy-only condition may be retried explicitly; a provider/infrastructure
incident pauses its entire comparison unit and `--retry-failed` must request
all four strategies, creating a new `unit_attempt_id`. Completed evidence is
never retried or overwritten.

Inspect and resume an existing ledger:

```powershell
.\.venv\Scripts\python.exe scripts\pilot_harness.py status runs\pilot\pilot-ledger
.\.venv\Scripts\python.exe scripts\pilot_harness.py resume `
  runs\pilot\pilot-ledger `
  --task-manifest path\to\task_manifest.json `
  --phase PILOT --limit 1 --allow-live
```

Run the minimal offline infrastructure smoke (one non-benchmark task × four
strategies × one repeat):

```powershell
.\.venv\Scripts\python.exe scripts\pilot_harness.py dry-run
```

The smoke writes into `runs/pilot/dry-run/`, tags every raw record
`dry_run=true` and `evidence_class=DRY_RUN`, and reports `research_evidence:
false`. It uses Fake only; its answers, tokens, latency, and cost are not Pilot
observations.

Recover an interrupted ledger without rerunning conditions:

```powershell
.\.venv\Scripts\python.exe scripts\pilot_harness.py recover runs\pilot\<manifest-dir>
```

Derive the processed dataset:

```powershell
.\.venv\Scripts\python.exe scripts\pilot_harness.py export runs\pilot\<manifest-dir>
```

Dry-run and preflight rows stay out of this default export. They can be
inspected explicitly with `--include-dry-run` or `--include-preflight`.

There is intentionally no default command for 96 live runs. The executor's
default is one condition, and live execution still requires reviewed task/rubric
artifacts, the recorded frozen-settings Groq preflight, and account-limit
confirmation. The bounded provider preflight command is:

```powershell
.\.venv\Scripts\python.exe scripts\provider_probe.py groq `
  --model openai/gpt-oss-120b --pilot-settings --timeout 90
```

It emits only normalized status, safe settings identity, request-field names,
latency and usage-field names; it never emits the API key or response text.

## Dry-run and regression evidence

The focused Pilot tests cover manifest uniqueness and hidden-content omission,
Latin-square determinism/balance, explicit model settings, verified pricing and
cached-cost accounting, Fake separation, failed and stopped raw persistence,
same-snapshot provenance, and resume safety. Existing runtime tests remain the regression gate for
the Adaptive, Fixed, Static, RAG, provider, and UI contracts.

The dry-run is explicitly engineering evidence only:

```text
DRY_RUN = true
research evidence = NO
```

The same separation applies to the live-provider smoke: it must use
`phase=PREFLIGHT`, `dry_run=false`, `research_evidence=false`, and at most one
condition. Only a reviewed execution with `phase=PILOT` and `dry_run=false` is
eligible for the Pilot processed dataset.

## Critical review and handoff

### P0

- **Benchmark/evaluator handoff:** the supplied
  `benchmarks/pilot/pilot_benchmark_v1.json` is now marked
  `QUALITY_REVIEWED` for `pilot_benchmark_v1@1.1.0`, with the rubric/protocol
  binding recorded by the quality workstream. `PILOT-R2` remains provenance
  only; manifests, rubric, raw evidence, and exports use the canonical
  benchmark ID/version. This turn still does not authorize or run the 96-cell
  Pilot block; integration must perform the final account/integration gate.
- **Reference scope:** all benchmark `reference_bindings.section_ids` now
  resolve against the frozen corpus catalog; invalid sections fail closed and
  only an explicit whole-document binding can request a full source.
- **Account-specific limits and readiness:** `GROQ-PILOT-LIMITS-V1` records
  `RPM=30`, `RPD=1000`, combined `TPM=8000`, `TPD=200000`, and project override
  `NONE`. Separate ITPM/OTPM numbers remain
  `SEPARATE_ITPM_OTPM_NOT_VERIFIED`; execution conservatively uses combined TPM.
  The historical and latest bounded Groq preflights are `PASS` for the frozen
  settings; the latest safe result is recorded in
  `docs/GROQ_PILOT_PREFLIGHT.md` and does not authorize a Pilot by itself.

### P1

- Run `prepare` with the actual eight-task manifest and verify 24 units, six
  occurrences per strategy/ordinal, and all source/rubric version references.
- Run `validate`, then a Fake `run --limit 1`/`resume --limit 1` control check
  against a copied test manifest before opening any live provider call.
- The frozen-settings preflight is recorded in `docs/GROQ_PILOT_PREFLIGHT.md`;
  integration must re-check the current account limit headers immediately
  before execution and retain any `retry-after` observations. The executor
  accepts a live preflight only when its provider/model/settings and success
  flags match and `checked_at` is within the 15-minute freshness window.
- Apply the frozen `docs/QUALITY_EVALUATION_PROTOCOL.md` denominator table:
  `E1` reviews all packets, `E2` reviews the deterministic 24-packet overlap
  plus exceptions, `ADJ-1` handles unresolved disagreements, and Cases B–E
  remain missingness/integrity records rather than quality failures.
- Enforce the pacing policy (combined TPM 8000, conservative 20 RPM until
  fresh headers, at most three in-flight workers, and split/pause on remaining
  quota) before execution.
- Review a live-manifest dry execution for snapshot/config/count/usage/latency/
  stop/incident fields before authorizing any block.

### P2

- Add provider queue/health observations and position-stratified latency
  summaries to the integration report.
- Independently audit source provenance, generated raw-file paths, manifest
  hashes, and secret scanning before the Pilot decision gate.

### P3

- Add approved whole-unit rerun linkage and evaluator package integration after
  the benchmark workstream delivers its artifacts.
- Add cross-provider sensitivity blocks only after the primary Groq block is
  stable and separately versioned.

## Handoff to integration

Integration owns reviewing/accepting the supplied benchmark/task manifest,
validating/consuming the frozen rubric reference and provider preflight, then
consuming the prepared manifest in its recorded order. It must not substitute
providers,
mutate raw evidence, add hidden labels to runtime prompts, or interpret the
Fake dry-run as research evidence. The existing `/api/compare/stream` fixed
order must not be used for the live Pilot unless the preregistration is amended
and re-reviewed.

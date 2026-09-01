# TASK E — PRE-PILOT MEASUREMENT & EVIDENCE AUDIT

Audit date: 2026-08-31 (Asia/Saigon)

## Status

**PARTIAL — PILOT_NOT_READY_FOR_SCIENTIFIC_SCORING**

No P0 invalidation was found. The runtime persists the exact final context
and reuses one snapshot across strategies, so the experiment is auditable at
the input level. Four P1 fixes are still required before latency or quality
comparisons are treated as pilot evidence:

1. required reference coverage is not fail-closed;
2. the stored E2E metric does not implement the preregistered boundary;
3. raw run evidence is not a safe structured provider-error record; and
4. model/strategy failures are not reliably separated from provider and
   infrastructure incidents.

The provider diagnostic endpoint itself is materially stronger than the raw
run-evidence path. Its taxonomy and secret-safe response behavior are
**PASS / ALREADY_SATISFIED** for this audit.

## Evidence basis and limits

I inspected the governing contract, current-state and orchestration audit,
pilot protocols, runtime code, providers, ledger, benchmark bindings and
tests. I also ran:

- .\.venv\Scripts\python.exe -m unittest discover -s tests -v
  — **80/80 PASS**, 20.120 seconds.
- A read-only benchmark snapshot probe using the actual runtime task
  projection and frozen_snapshot.
- A temporary timing probe with delayed provider construction and delayed
  persistence.
- A temporary simulated non-Fake 429 failure probe. The probe used a
  synthetic body marker and did not contact a live provider.

No live provider request was made and no implementation behavior was changed.
The existing docs/TEST_MATRIX.md and docs/CURRENT_STATE.md test-count
references are older than the current 80-test result; that documentation
drift is recorded as P2 below.

## A. Frozen Context Snapshot audit

### Actual construction path

The Pilot runtime projects the allowed task message, output instruction and
scoped reference text in app/core/pilot_executor.py:

- _runtime_task_records and _scoped_source_text construct the runtime-safe
  source projection and exclude rubric/expected-fact material.
- _snapshot_for_unit calls frozen_snapshot once per unit before the strategy
  loop.
- _execute_condition passes the same snapshot string and copied metadata to
  each strategy.
- PilotLedger.set_unit_snapshot persists the snapshot identity for later
  equality checks.

app/core/rag.py:frozen_snapshot normalizes and chunks the source, selects at
most top_k chunks by lexical overlap with a stable original-index tie-break,
assembles them, and applies assembled[:max_chars]. The final context is
returned as context by execute_once and its SHA-256 is stored as context_hash.
The snapshot ID is also built from the post-slice hash. The snapshot version,
RAG configuration, retrieval settings, selected chunk metadata and truncation
counts are persisted (app/core/rag.py:103-228,
app/main.py:410-471).

### Runtime evidence

The actual benchmark probe produced these results (default top_k=6,
max_chars=7000):

| Task | Runtime context | Available / selected chunks | Assembled -> final snapshot | Final truncation |
|---|---:|---:|---:|---|
| R2-04 | 9,898 | 11 / 6 | 7,268 -> 7,000 | yes, 268 chars |
| R2-05 | 9,574 | 8 / 6 | 7,781 -> 7,000 | yes, 781 chars |
| R2-08 | 14,837 | 14 / 6 | 6,803 -> 6,803 | no character slice; 8 chunks omitted by top-k |

R2-01, R2-02, R2-03, R2-06 and R2-07 did not reach the final character
limit in this probe. For R2-04 and R2-05, the final selected chunk is only
partially present in the final context. For R2-08, truncation.applied=false
does not mean full reference coverage: the selected chunk indices were
[0, 5, 6, 8, 10, 12].

The declared reference-binding coverage probe also found omission of required
declared sections from the final prompt. Examples are:

- R2-04: the bound main-chat-flow and conversation-persistence README
  sections were not represented; the bound compare-and-inspector matrix
  section was only partially represented.
- R2-05: the bound runtime-evidence-fixtures audit section and dag-ready-set
  matrix section were not represented, although several DAG implementation
  sections were.
- R2-08: the bound fixed-static matrix section was not represented, even
  though the comparison-strategy contract and correctness conclusion were
  represented.

This check used the benchmark's declared reference_bindings and frozen corpus
section IDs, not hidden rubric text. Line-presence counts are conservative
evidence of omission, not a substitute for semantic fact verification.

### Required determinations

| Question | Determination | Evidence |
|---|---|---|
| Can the context be truncated? | Yes, by top-k selection and final character slicing. | frozen_snapshot, including assembled[:max_chars]. |
| Is the mechanism deterministic? | Yes for the same source, task and settings. | Normalization, stable chunk order/tie-break and versioned settings; deterministic snapshot tests pass. |
| Is the actual context frozen and recorded? | Yes. | Raw context, context_hash, snapshot ID and retrieval metadata are persisted. |
| Is the same context used across strategies? | Yes within a Compare run and each Pilot unit. | One snapshot is made before the strategy loop and passed unchanged; ledger checks identity. |
| Does a strategy receive a different retrieval context? | No evidence of this. | Strategy-specific retrieval is not called; only strategy execution changes. |
| Are omissions identifiable? | Partially. | Selected and available chunk IDs and counts are present; exact dropped ranges/content are not. |
| Is the policy versioned? | Yes. | SNAPSHOT_VERSION, RAG_CONFIG_ID, retrieval settings and Pilot config identity are recorded. |
| Can a required fact/section be removed? | Yes, and declared sections are omitted in the probe. | top-k omission plus final tail slicing; no required-locator coverage assertion exists. |

### Disposition

**P1_FIX_REQUIRED, not P0_INVALIDATING.** The input actually seen by every
strategy is frozen and reproducible, which prevents an untraceable
strategy-fairness failure. However, the benchmark contract binds reference
sections that are not guaranteed to survive retrieval. A completed run can
therefore be internally reproducible while still being scientifically
unevaluable for its declared task.

Smallest safe fix: add a benchmark-level required-reference coverage check
before execution. A unit must either retain every declared required section or
required locator in the final snapshot, or be marked invalidated/not
evaluable before scoring. The check must cover both top-k omission and the
final character slice; increasing max_chars alone does not fix R2-08. Record
the omitted chunk/locator identity and the coverage decision in raw evidence.
Do not silently score a context that failed its declared scope.

Minimum tests:

- an 8-task benchmark regression asserting required section/locator coverage
  or explicit invalidation;
- R2-04/R2-05/R2-08 assertions for available chunks, selected chunks,
  assembled length, final length, and omission decision;
- exact equality of the context string supplied to all four strategies, in
  addition to snapshot ID/hash equality;
- a regression proving context_hash equals sha256(final_context) after the
  final slice.

## B. End-to-end latency audit

### Current measurement

The current run timer is RunState.started_at =
time.perf_counter() in app/core/types.py:78-105. The reported value is
computed in Orchestrator.metrics as the elapsed monotonic wall clock in
app/core/orchestrator.py:617-651. It is not persisted as a start/end pair.

The effective successful-run boundary is:

1. execute_once constructs the provider;
2. RunState is created and the timer starts;
3. orchestration, provider calls, retries, verification, escalation,
   synthesis and final event emission run;
4. the metric is read; then raw persistence occurs.

Important boundary locations are app/main.py:410-471 and
app/core/orchestrator.py:588-651.

### Included and omitted phases

| Phase | Current E2E treatment |
|---|---|
| Request validation / accepted-run boundary | Not represented by an explicit timer envelope. |
| Context preparation and RAG | Omitted: chat snapshots before execute_once; Compare snapshots before strategy_started; Pilot snapshots before ledger.begin. |
| Provider construction | Omitted: construction occurs before RunState. |
| Provider generation | Included after RunState starts. |
| Retry waits / backoff | Included in run wall clock; _call keeps the logical call open across attempts and sleeps. |
| DAG parallel workers | Correctly measured as run wall clock; asyncio.gather does not sum worker durations. |
| Verification, escalation and synthesis | Included when they occur after RunState. |
| Persistence | Omitted on successful runs: save happens after the metric is read. |
| HTTP response/stream delivery | Not represented as a final-ready-to-return timestamp. |

Provider latency is not a separate measurement. Agent duration is measured
around a logical role call and includes transformation, retry attempts and
backoff. Physical request start/end, response status and per-attempt provider
latency are absent. The diagnostic endpoint has its own probe latency, but
that is not the latency of a Pilot run.

Compare has one shared snapshot, but successful results use the RunState
metric while a preconstruction exception uses strategy_started
(app/main.py:646-707). Pilot construction/model/key failures do not pass an
E2E value to save_failed_run_evidence, so those failures can have
e2e_ms=null. These are not one common definition.

A temporary controlled probe delayed provider construction by about 150 ms
and persistence by about 150 ms. It measured approximately 523 ms from
request-side wrapper through save, while stored E2E was approximately 223 ms.
The 523 ms value includes persistence and is therefore not itself a
like-for-like preregistered target if “ready to persist/return” means before
the save. The provider-construction delay alone establishes that the current
field starts too late; the save delay establishes that persistence is a
separate unreported phase. The probe therefore proves a boundary mismatch,
not that all 300 ms belongs in the primary E2E estimand.

### Scientific impact

The current value cannot be described as “accepted valid run through final
result ready to persist/return” from the preregistration. It is usable as a
post-RunState execution duration, but it excludes setup and persistence and
uses a different path for some failures. Provider construction and context
preparation can vary by strategy or condition, so excluding them can change
latency comparisons, not merely shift every result by a constant. Missing
timing for preconstruction failures also makes failure latency and missingness
non-comparable.

### Smallest fix and tests

Add one versioned measurement envelope at the common accepted-run boundary:

- record monotonic start plus UTC start before the phases the preregistration
  says to include;
- record monotonic end plus UTC end immediately when the final result is
  ready to persist/return;
- pass that envelope through provider construction and failure paths;
- persist e2e_ms, e2e_started_at, e2e_ended_at and an
  e2e_definition_version;
- expose shared context-preparation, provider-construction and persistence
  timings separately so they cannot be confused with the primary estimand.

For Compare/Pilot, lock the attribution rule for shared context preparation
before implementation: report it once as a shared unit phase and apply the
same documented attribution to each condition, or publish a separate
unit-level E2E value. Do not silently mix shared-unit and per-strategy
timers.

Minimum tests:

- delayed context preparation, provider construction and persistence with
  assertions for included/excluded fields;
- retry/backoff timing is included;
- parallel-worker timing is close to wall clock, not the sum of workers;
- successful, provider-failure and preconstruction-failure paths all carry
  the same definition/version and boundary fields;
- Compare's four strategies and Pilot conditions use the same timing schema;
- UTC timestamps and monotonic duration are internally consistent within
  clock-resolution tolerance.

Disposition: **P1_FIX_REQUIRED**.

## C. Raw provider-error evidence audit

### What is already safe

app/core/provider_diagnostics.py has normalized categories for not-configured,
network blocked, DNS, timeout, authentication, permission, model-not-found,
rate limit, quota, credit, generic provider error and success. It classifies
using status/error data and returns only a safe message through
ProviderDiagnostic; the diagnostic response does not return the raw body.
Existing tests cover the listed HTTP-style categories and a diagnostic body
containing a synthetic secret marker.

This path is **PASS / ALREADY_SATISFIED** for the requested diagnostic
taxonomy and safe response behavior. It must not be treated as proof that raw
Pilot evidence is safe.

### What raw run evidence currently stores

In app/core/orchestrator.py:_call, exception text is passed through
redact_secrets and is then placed in retry events, agent_error.detail, the
final error, and the saved raw record. redact_secrets removes configured keys
and a few key-shaped patterns, then truncates the string; it does not remove
arbitrary provider response bodies, status text or non-key sensitive values.
Provider adapters return usage/request ID but do not persist response headers
or rate-limit metadata. _retry_delay reads Retry-After or a provider retry
delay but does not record the value.

A temporary simulated non-Fake 429 run demonstrated the gap: the normalized
category was RATE_LIMITED and the safe message was present, but the synthetic
response-body marker was still present in the saved raw error and agent-error
detail. This is a run-evidence issue, not a diagnostic-endpoint issue.

The raw path also loses structured exception information. For many Pilot
failures app/main.py:_apply_run_metadata reclassifies from
str(data.error or stop_reason), after the original exception type, HTTP
status and response fields are gone. This makes category correctness
unproven for SDK-specific failures and empty-text timeout exceptions.
PROVIDER_5XX is not distinguished from generic PROVIDER_ERROR, and no status
code is persisted to make that distinction recoverable.

### Expected safe evidence

Each provider failure attempt should persist only an allowlisted structured
record, for example:

- provider and model;
- normalized category and origin;
- safe message;
- exception class or safe error kind;
- HTTP status when available;
- attempt number, retry count and retry-after seconds when available;
- provider request ID when safe;
- start/end UTC timestamps and duration.

It must not persist Authorization headers, API keys, full response bodies,
unbounded exception text or arbitrary request payloads. The existing
diagnostic response contract should remain unchanged.

Smallest safe fix: normalize the original exception at the provider/runtime
boundary before string redaction, retain only the allowlisted fields above,
and replace raw error/detail fields with the safe message plus structured
metadata. Use the structured category for run metadata; do not reconstruct
it from a later string. Capture retry-after only as a bounded numeric value.

Minimum tests:

- raw Pilot 429, timeout, auth, permission, DNS/network, quota, credit,
  model-not-found and 5xx cases;
- arbitrary response-body and non-key secret markers are absent from every
  raw/event/error field;
- category, status, attempt, retry count and bounded retry-after metadata
  survive persistence;
- local strategy/verifier exceptions are not emitted as provider bodies;
- diagnostic endpoint regression retains its current safe behavior.

Disposition: **P1_FIX_REQUIRED for raw Pilot evidence**; diagnostic endpoint
taxonomy/sanitization is **PASS**.

## D. Incident taxonomy audit

The provider diagnostic taxonomy is not the same thing as a run-outcome
taxonomy. Current Pilot control states and ledger statuses are useful for
execution control, but they do not preserve every scientific distinction
required by the brief.

| Required outcome | Current representation | Determination |
|---|---|---|
| SUCCESS | completed in raw data, observed in ledger; no explicit run-level SUCCESS category. | Operationally present; explicit category is missing. |
| MODEL/STRATEGY TERMINAL FAILURE | failed, stop reason and sometimes STOPPED; RuntimeError is treated as stopped by the orchestrator. | Not reliably distinct from provider incidents. |
| RATE_LIMITED | Provider classifier and diagnostic category exist; raw run evidence may persist a category. | Partly covered; structured capture is required. |
| TIMEOUT | Provider classifier/diagnostic category exists. | Partly covered; original exception type is not preserved in raw runs. |
| NETWORK/DNS | Classifier categories exist. | Partly covered; same raw-evidence limitation. |
| AUTHENTICATION/PERMISSION | AUTHENTICATION_FAILED and PERMISSION_DENIED exist. | Partly covered; same raw-evidence limitation. |
| QUOTA/CREDIT | Classifier categories exist. | Partly covered; same raw-evidence limitation. |
| MODEL_NOT_FOUND | Classifier category exists. | Partly covered; same raw-evidence limitation. |
| PROVIDER_5XX / PROVIDER_ERROR | Generic PROVIDER_ERROR exists; 5xx status is not retained in run evidence. | Incomplete distinction. |
| EXPERIMENT_INFRASTRUCTURE_ERROR | No dedicated run category. | Missing. |
| INVALID_INPUT / INVALID_SCOPE | HTTP validation and PilotExecutorError stop execution, but no canonical run/ledger incident category is emitted. | Missing at the evidence layer. |
| INTERRUPTED / STALE RUN | missing_not_run, control state PENDING and recovery reason execution_interrupted_before_terminal_raw_evidence. | Operationally represented; explicit taxonomy label is absent. |

There is a more serious origin error in the current mapping:

- a non-Fake failed/degraded run is reclassified in execute_once using a
  stringified error;
- STOP_VERIFICATION_UNAVAILABLE is forcibly marked as a provider incident
  in _apply_run_metadata;
- a local strategy/runtime failure can therefore enter the provider-incident
  path even when no provider failed.

This can turn a model/strategy terminal failure into provider missingness and
change quality-denominator interpretation. The distinction must be based on
structured origin, not provider name or status == degraded.

Smallest safe fix: add a run-level incident_category and incident_origin
with a closed allowlist. Keep the existing provider diagnostic categories for
provider diagnostics, but map raw run outcomes explicitly to:

- SUCCESS;
- MODEL_STRATEGY_TERMINAL_FAILURE;
- the provider categories;
- EXPERIMENT_INFRASTRUCTURE_ERROR;
- INVALID_INPUT_OR_SCOPE; and
- INTERRUPTED_OR_STALE_RUN.

For 5xx, either use PROVIDER_5XX or use PROVIDER_ERROR with a retained status
code. Keep evaluator-side NOT_EVALUABLE as an evaluation decision, not as a
provider incident. Update ledger/processed-row mapping only after the runtime
schema is fixed.

Minimum tests:

- a table-driven run-level mapping for every required category;
- Fake/local strategy failure versus provider 429/timeout/5xx;
- verifier-unavailable and budget-stop cases;
- invalid input/scope and interrupted recovery;
- success, ledger status and processed-row output;
- assertion that provider incident is never set solely because a run is
  degraded or non-Fake.

Disposition: **P1_FIX_REQUIRED** for run-level scientific evidence.

## Red-team finding challenge

The relevant findings are not all literally correct:

| Finding interpretation | Challenge |
|---|---|
| “R2-08 is cut by max_chars.” | **FALSE_POSITIVE as literal wording.** R2-08 is 6,803 assembled characters and has truncation.applied=false. The underlying completeness concern remains **P1** because top-k omitted 8/14 chunks and bound sections. |
| “No frozen snapshot is recorded/shared.” | **FALSE_POSITIVE / ALREADY_SATISFIED.** Final context, hash, ID and retrieval metadata are persisted and the same snapshot is passed to strategies. |
| “Parallel latency is computed by summing workers.” | **FALSE_POSITIVE / ALREADY_SATISFIED.** E2E is one monotonic run wall clock around orchestration; worker durations are not summed. |
| “Provider diagnostic raw errors are exposed.” | **FALSE_POSITIVE for the diagnostic endpoint.** Its response is normalized and body-safe. **Verified for raw run evidence**, where exception text can retain arbitrary body content. |
| “Interrupted/stale execution has no representation.” | **Partly false.** Ledger recovery records missing_not_run, PENDING and a recovery reason. An explicit run-level incident label is still a P2/schema improvement. |

The corrected conclusions above are based on the actual runtime paths, not on
the red-team wording alone.

## P0 / P1 / P2 gap register

### P0

**None verified.** No evidence showed that strategies receive unrecorded or
different frozen contexts, or that the experiment is irreparably invalid
before a bounded fix can be applied. Live-provider behavior remains
unverified, not failed.

### P1

**E-P1-01 — Required snapshot coverage is not fail-closed**

- Current: app/core/rag.py:frozen_snapshot selects top-k and slices the
  assembled text; app/core/pilot_executor.py:_snapshot_for_unit does not
  validate benchmark reference_bindings against the final context.
- Expected: all required sections/locators survive, or the unit is
  invalidated/not evaluable with explicit omission evidence.
- Test: benchmark-wide section/locator coverage plus R2-04/R2-05/R2-08
  final-context regression.
- Owner: Runtime/RAG owner with Pilot integration owner.

**E-P1-02 — E2E boundary and failure-path timing are inconsistent**

- Current: RunState starts after provider construction and after Pilot
  context preparation; successful metrics are read before save; Compare
  preconstruction failures use another timer; Pilot preconstruction failures
  can have null E2E.
- Expected: one versioned accepted-run-to-final-ready definition with UTC
  endpoints and explicit shared/setup/persistence attribution.
- Test: delayed-phase boundary tests, retries, parallel workers, Compare and
  Pilot failure paths.
- Owner: Runtime measurement owner; Pilot/experiment integration owner.

**E-P1-03 — Raw provider failures are not safe structured evidence**

- Current: redacted exception strings are persisted in raw/error/event
  fields; arbitrary body text can remain; status, exception type and
  retry-after metadata are lost.
- Expected: allowlisted structured fields from the original exception, with
  no body/credential leakage.
- Test: raw Pilot cases for every provider failure class and body/secret
  sanitization across all persisted fields.
- Owner: Provider adapter/runtime owner with security review.

**E-P1-04 — Provider, strategy and infrastructure origins can collapse**

- Current: non-Fake failures are reclassified from strings, verifier
  unavailability is forced to provider incident, and no run-level closed
  taxonomy covers experiment infrastructure or invalid scope.
- Expected: explicit run-level category plus origin, with provider incidents
  emitted only for provider-origin failures.
- Test: table-driven origin/category mapping, verifier/budget/local failure
  cases, ledger and processed export assertions.
- Owner: Runtime control-plane owner with Pilot ledger owner.

### P2

**E-P2-01 — Omission provenance is too coarse**

- Current: selected/available chunk IDs and aggregate character counts are
  stored, but final dropped ranges/content hashes are not.
- Expected: bounded, non-sensitive omission ranges or chunk/locator IDs and
  before/after hashes sufficient to explain exactly what was removed.
- Test: deterministic omission manifest for top-k and final-slice paths.
- Owner: RAG evidence owner.

**E-P2-02 — Physical provider-attempt measurements are absent**

- Current: only logical agent duration and aggregate retry/request counts are
  available; provider headers and per-attempt latency are absent.
- Expected: separate bounded provider-attempt start/end/duration and safe
  rate-limit metadata when available.
- Test: multi-attempt provider fixture asserting attempt-level records and no
  raw headers.
- Owner: Provider adapter/runtime owner.

**E-P2-03 — Some control states lack explicit run-level taxonomy labels**

- Current: success and interrupted/stale are represented by completed/observed
  and missing_not_run/PENDING/recovery reason, but not by a single closed
  incident field.
- Expected: canonical mapping to SUCCESS and INTERRUPTED_OR_STALE_RUN without
  changing evaluator NOT_EVALUABLE.
- Test: ledger recovery and processed-export mapping.
- Owner: Pilot ledger owner.

**E-P2-04 — Validation-count documentation is stale**

- Current: the current suite passed 80 tests, while existing matrix/current
  state prose reports older totals.
- Expected: documentation and test evidence report the same verified count and
  command.
- Test: release validation check that compares the documented evidence entry
  with the executed result.
- Owner: Integration/release documentation owner.

## Files, owners and integration handoff

### Files inspected

- app/core/rag.py
- app/core/types.py
- app/core/orchestrator.py
- app/main.py
- app/core/pilot_executor.py
- app/core/pilot.py
- app/core/provider_diagnostics.py
- app/core/security.py
- provider adapters under app/providers/
- tests/test_runtime.py, tests/test_pilot_executor.py, tests/test_pilot.py
- docs/PROJECT_CONTRACT.md, docs/CURRENT_STATE.md,
  docs/ORCHESTRATION_AUDIT.md, docs/TEST_MATRIX.md,
  docs/PILOT_PREREGISTRATION.md, docs/PILOT_EXECUTION_PROTOCOL.md,
  docs/QUALITY_EVALUATION_PROTOCOL.md, docs/PRE_PILOT_RED_TEAM_AUDIT.md
- frozen benchmark corpus and declared reference bindings under corpus/pilot/v1/
  and evaluation/pilot/

### File changed by this task

- docs/PRE_PILOT_MEASUREMENT_AUDIT.md — this report only.

No files under app/static/, the benchmark, frozen rubrics/corpus, pilot
manifest, provider/model configuration, pilot_executor.py,
QUALITY_EVALUATION_PROTOCOL.md or PILOT_EXECUTION_PROTOCOL.md were modified.

### Integration handoff

Before pilot execution or scientific scoring:

1. Runtime/RAG owner implements E-P1-01 and adds the benchmark coverage
   regression.
2. Runtime measurement owner implements E-P1-02 and freezes the shared
   context attribution rule.
3. Provider/runtime plus security owner implements E-P1-03; preserve the
   already-safe diagnostic endpoint contract.
4. Control-plane/ledger owners implement E-P1-04 and verify denominator and
   NOT_EVALUABLE handling with the quality protocol.
5. Re-run the full suite and all new focused tests, then regenerate raw
   evidence with the versioned schemas. Do not interpret the current latency,
   provider-incident or completeness fields as final pilot results.

Final evidence state: **PARTIAL**. The system is auditable enough to identify
and repair the gaps, but not yet ready to support claims about pilot quality,
latency ranking or provider-incident rates.

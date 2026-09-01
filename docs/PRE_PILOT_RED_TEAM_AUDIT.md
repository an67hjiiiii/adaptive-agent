# TASK D — Independent Pre-Pilot Red-Team Audit

**Audit date:** 2026-08-31 (Asia/Saigon)  
**Mode:** Read-only red-team review  
**Decision scope:** the proposed 8-task / 3-repeat / 4-strategy Pilot and its
execution/evidence path; no live Pilot authorization

## Scope and method

This audit read the governing contract, preregistration, execution protocol,
quality protocol, benchmark notes, benchmark, rubric, frozen corpus manifest,
Pilot configuration/schema, orchestration/runtime code, Pilot ledger/executor,
provider adapter/diagnostics, tests, and existing generated raw artifacts.
Existing raw artifacts were inspected without treating Fake or PREFLIGHT output
as research evidence. No provider was called and no 96-cell Pilot was started.

The only file created by this audit is this report. Source, frontend,
configuration, benchmark, rubric, corpus, and run-manifest artifacts were not
modified.

## Executive decision

**STATUS: PARTIAL — PILOT_NEEDS_FIXES**

The orchestration paths and the benchmark/rubric separation are mechanically
credible. However, several P1 issues can change latency, missingness,
incident classification, or the quality denominator. These must be resolved or
explicitly gated before interpreting a live Pilot. No P0 rubric-leakage finding
was observed.

Evidence baseline:

- The frozen corpus is `PILOT-CORPUS-V1`; the six declared SHA-256 values
  verified against the six files. All eight benchmark source bindings and
  section IDs resolved.
- The quality-reviewed artifact is `pilot_benchmark_v1@1.1.0`, with eight
  tasks; the rubric contains 36 mandatory criteria, 16 critical-error
  definitions, and eight optional criteria.
- The prepared live shape is 24 comparison units / 96 strategy conditions,
  with six occurrences of every strategy at every ordinal position. The
  inspected generated ledgers contain only `DRY_RUN` or `PREFLIGHT` evidence;
  no `phase=PILOT` research run was found.
- Existing Fake/PREFLIGHT evidence demonstrates control behavior only. It is
  not quality, latency, token, cost, or provider evidence for the live Pilot.

## MULTI-AGENT VALIDITY

**Verdict: PASS mechanically, with a P2 evidence caveat.** This is a
homogeneous multi-agent design, which is consistent with the contract: the
same underlying provider/model may back multiple bounded roles.

| Role/path | Separation and evidence | Verdict |
| --- | --- | --- |
| Direct Solver | A dedicated direct prompt and one bounded provider call; used by Single and direct routes (`app/core/orchestrator.py:37`, `446-448`). | Pass |
| Analyzer | Receives task plus frozen context and returns aspects, dependencies, parallelizable groups, verification demand/reasons, and rationale (`app/core/orchestrator.py:11-29`, `285-302`). | Pass |
| Planner | Returns a bounded DAG; dynamic paths validate it before scheduling (`app/core/orchestrator.py:30-32`, `379-397`, `406-418`). Fixed/Static map only planner goal text into frozen slots. | Pass with registered baseline behavior |
| Worker | Receives one assigned subtask and dependencies; ready nodes are run through `asyncio.gather`, while dependent nodes wait (`app/core/orchestrator.py:399-418`). | Pass |
| Synthesizer | Combines bounded worker outputs into the candidate (`app/core/orchestrator.py:420-425`). | Pass |
| Runtime Verifier | Returns `PASS`, `NEEDS_WORK`, or `FAIL`; Adaptive can perform one bounded targeted repair round (`app/core/orchestrator.py:427-526`). Fixed/Static verifiers are explicitly observational. | Pass with caveat below |

The orchestrator is the controller/policy layer rather than an extra LLM role,
and provider/model/settings are passed through the same Pilot identity for all
four conditions (`docs/PROJECT_CONTRACT.md:14-32`, `app/providers/compatible.py:91-149`).

The caveat is that Fixed verifies the concatenated worker draft before it
synthesizes the final answer (`app/core/orchestrator.py:531-549`). The final
Fixed answer is therefore not the candidate that its observational verifier
examined. This is not hidden route mutation, but the evidence must not be
described as a quality gate on the final Fixed answer.

## RESEARCH SCOPE

**Verdict: PARTIAL.** The valid primary question is the effect of bounded
orchestration under one common provider/model/settings/context, not
multi-model routing or a generic chatbot comparison
(`docs/PROJECT_CONTRACT.md:8-32`). The current implementation respects that
scope.

The quality claim is narrower than the research ambition unless explicitly
bounded. All eight tasks are self-referential technical-document questions
about this project's contract, audit, provider safeguards, evidence, and
baseline closure. The task wording also names the structural situations that
map to the controller's routes: direct conditions in R2-01, dependency/ready
sets in R2-05, targeted repair in R2-06, exception/incident handling in R2-07,
and Fixed/Static closure in R2-08 (`benchmarks/pilot/pilot_benchmark_v1.json:135-147`,
`395-419`, `489-513`, `567-597`, `657-687`).

This is not hidden-label leakage and does not create a P0. It does mean the
block can support a technical contract-conformance/infrastructure result, but
not a broad claim that Adaptive generalizes or wins on ordinary user tasks.
That claim boundary is a P1 design gate unless the scope is narrowed in the
analysis plan. Held-out, non-self-referential task families belong in Main or a
separately versioned robustness block.

## STRATEGY VALIDITY

| Strategy | Current implementation | Verdict |
| --- | --- | --- |
| Single / B0 | Direct Solver only; no Planner, Workers, Synthesizer, or runtime verification path (`app/core/orchestrator.py:528-529`). | Pass |
| Fixed / B1 | Versioned Planner + three fixed Worker slots + observational Verifier + Synthesizer; worker IDs/count/dependency policy are frozen and Adaptive escalation is disabled (`app/core/orchestrator.py:73-89`, `531-549`). | Pass; P2 pre-synthesis verifier caveat |
| Static / B2 | One structural analysis selects one versioned Direct/Parallel/Planned preset; the preset cannot change or escalate at runtime (`app/core/orchestrator.py:91-120`, `551-586`). | Pass |
| Adaptive / P | Structural analysis, rule-based route, bounded execution, verification, and one issue-targeted escalation when budgets allow (`app/core/orchestrator.py:450-526`). | Pass |

The four paths are not collapsed into one implementation: extra roles and
calls are the registered orchestration treatment and are separately counted.
The comparison remains valid only if the P1 timing, provider, missingness, and
evidence controls below are fixed or excluded from interpretation.

## FAIRNESS

**Verdict: PARTIAL — mechanical fairness is present; live comparability is not
yet established.**

| Dimension | Finding |
| --- | --- |
| Provider/model/settings | Frozen in the manifest/configuration and passed to each strategy. No provider substitution was observed. |
| Context identity | The executor creates one snapshot per comparison unit, checks a shared snapshot ID/hash, and passes the same snapshot to all four conditions (`app/core/pilot_executor.py:420-443`, `app/core/pilot.py:1208-1236`). |
| Reference scope | Current code verifies source hashes and resolves the declared section IDs through `_scoped_source_text`; the runtime context is not the whole source file (`app/core/pilot_executor.py:105-145`, `184-259`). This check passes. |
| Order | The seeded Latin-square schedule validates six occurrences per strategy/ordinal position and the executor runs top-level conditions sequentially (`app/core/pilot.py:265-358`, `565-655`). |
| Retry/budget policy | The manifest freezes the same retry and budget ceilings, but provider-side rate effects can still be strategy-dependent because Worker bursts and call counts differ. |
| Latency | Not yet fair for the preregistered metric: context preparation and provider construction occur before `RunState.started_at`, so the stored `e2e_ms` does not cover the full accepted run boundary. |

The order mechanism reduces position imbalance; it does not itself remove
rolling quota windows, provider queue drift, or a burst-shaped treatment.

## BENCHMARK

**Verdict: PARTIAL / P1 completeness and construct-validity risk.**

The positive controls are strong: runtime projection allowlists task text,
corpus bindings, scope, and output instruction, while taxonomy, expected facts,
and quality fields are separate (`benchmarks/pilot/pilot_benchmark_v1.json:109-133`,
`app/core/pilot_executor.py:148-188`). The frozen corpus/binding/hash audit
passed.

There are two independent benchmark risks:

1. **Scope-to-snapshot completeness.** A read-only count of the declared bound
   section bodies, before runtime prefixes/separators, found:

   | Task | Bound section-body characters | RAG default max |
   | --- | ---: | ---: |
   | R2-01 | 2,210 | 7,000 |
   | R2-02 | 3,123 | 7,000 |
   | R2-03 | 3,584 | 7,000 |
   | R2-04 | 9,434 | 7,000 |
   | R2-05 | 8,701 | 7,000 |
   | R2-06 | 5,369 | 7,000 |
   | R2-07 | 4,275 | 7,000 |
   | R2-08 | 14,112 | 7,000 |

   R2-04, R2-05, and R2-08 therefore exceed the default snapshot limit even
   after correct scope slicing. `frozen_snapshot` selects at most six lexical
   chunks or truncates the assembled text and records the loss, but it does
   not assert that every rubric locator/required fact remains in the candidate
   context (`app/core/rag.py:103-119`, `166-228`). All four strategies share
   the same resulting snapshot, so within-unit identity is preserved; however,
   task-family quality and route effects can be confounded by unequal context
   completeness. This is P1 before scoring.

2. **Route-revealing, self-referential tasks.** The benchmark notes say no task
   was selected for an expected winner and that the wording does not tell the
   Analyzer to use a route (`docs/PILOT_BENCHMARK_NOTES.md:19-26`, `117-141`).
   The actual task wording explicitly describes the structural cases that the
   contract maps to specific route behavior. That is acceptable for a
   controller conformance fixture, but not for a broad unbiased test of task
   generalization. Narrow the claim or add an independently authored held-out
   set before making a general quality claim.

## RUBRIC

**Verdict: PASS structurally; P2 construct-validity caveat.**

The rubric is source-supported, atomic, strategy-neutral, verbosity-independent,
and uses `PASS/FAIL/UNCLEAR`, critical-error labels, and a declared
`EVALUABLE/NOT_EVALUABLE` boundary (`docs/QUALITY_EVALUATION_PROTOCOL.md:72-117`).
There is no criterion that rewards a preferred route, agent count, or extra
verbosity. Optional criteria have no primary-score effect.

The rubric does measure exact conformance to a technical contract: named fields,
terminal states, evidence views, and privacy boundaries. That is a valid
construct for this benchmark, but it should not be reported as a general
measure of answer quality. The static audit found no rubric payload in runtime
prompts, frontend code, or the inspected raw evidence path; the protocol's P0
condition was not observed (`docs/QUALITY_EVALUATION_PROTOCOL.md:200-216`).

## QUALITY DENOMINATOR

**Verdict: NOT READY — P1.**

The protocol correctly states that unusable/provider-incident packets are
`NOT_EVALUABLE`, excluded from the answer-quality denominator, and never
silently imputed (`docs/QUALITY_EVALUATION_PROTOCOL.md:62-70`, `185-198`). It
also explicitly leaves the operational missingness threshold open
(`docs/PILOT_PREREGISTRATION.md:308-320`, `440-449`).

The runtime export is not a canonical evaluator dataset:

- `export_processed_dataset` emits every recorded attempt and also emits an
  unrun assignment; it does not select one canonical attempt per condition
  (`app/core/pilot.py:1601-1644`).
- The processed row contains status and resource fields but no final answer,
  evaluator packet ID, `EVALUABLE/NOT_EVALUABLE` label, or explicit attempt
  selection rule (`app/core/pilot.py:1487-1584`). The answer remains in raw
  evidence.
- The existing ledger test intentionally demonstrates two derived rows for one
  condition after an interrupted attempt followed by a retry
  (`tests/test_pilot.py:229-271`). Without a separate audited coordinator, a
  naive denominator can count the interruption and the replacement answer as
  two packets.

Before live scoring, Integration must freeze the canonical packet/attempt rule,
whole-unit incident rerun linkage, usable-answer treatment, and the numerical
missingness threshold that makes a comparison inconclusive.

## RATE LIMIT RISK

**Verdict: P1 — live block must not start without an account-specific pacing
and quota gate.**

The repository's recorded Groq feasibility review gives a 312-request nominal
block, 624-request one-retry stress estimate, and a 1,728-request hard ceiling;
it also records published high-level limits and explicitly recommends
throttled batching, conservative pacing, `Retry-After` handling, block
splitting, and rate-limit metadata capture (`docs/GROQ_PILOT_PREFLIGHT.md:116-160`).
The exact account/project limits remain unavailable.

The implementation has no aggregate rate limiter or inter-condition pacing.
Top-level conditions are sequential, but internal Worker batches are concurrent
(`app/core/orchestrator.py:406-418`, `app/core/pilot_executor.py:565-655`). The
retry helper reads `retry-after` but caps the delay at the frozen maximum and
does not persist the header or a normalized rate-limit pause
(`app/core/orchestrator.py:189-206`, `265-278`). The compatible adapter stores
response usage/request ID but no response rate-limit headers
(`app/providers/compatible.py:118-149`).

Consequences include differential 429s, retries, missingness, and queue latency
by strategy. A successful retry is counted, but the rate-limit cause is not
retained as a first-class physical-request event. The only executor live guard
is `allow_live=True`; the harness does not require a fresh provider diagnostic
or account-limit artifact (`app/core/pilot_executor.py:365-376`,
`scripts/pilot_harness.py:288-302`).

## RAW EVIDENCE

**Verdict: PARTIAL.** Normal-path evidence has useful coverage: answer/status,
event trace, Agent/Logical/Physical counts, usage/cost, snapshot IDs/hashes,
source scope, configuration identities, retries, escalations, and stop state
are persisted (`app/main.py:423-449`, `app/core/pilot_executor.py:460-513`,
`app/core/orchestrator.py:617-651`). Unavailable usage/cost is kept null.

The following P1 evidence defects remain:

- `redact_secrets` removes configured/key-shaped tokens but otherwise persists
  up to 2,000 characters of `str(exception)`. Both provider exceptions and raw
  run errors use this string (`app/core/security.py:7-19`,
  `app/main.py:228-257`, `app/core/orchestrator.py:265-278`). OpenAI-compatible
  HTTP exceptions can include response bodies; this does not meet the protocol
  promise that raw provider bodies are excluded (`docs/PILOT_EXECUTION_PROTOCOL.md:218-219`).
- Any `degraded` run is converted to `provider_incident`, including the generic
  verifier-unavailable path (`app/main.py:201-218`, `app/core/pilot.py:1238-1253`).
  The inspected PREFLIGHT raw control record confirms the result: `status` was
  `degraded`, `stop_reason` was `STOP_VERIFICATION_UNAVAILABLE`, and the record
  was classified `provider_incident=true` / `PROVIDER_ERROR`. This collapses a
  provider outage, verifier failure, and local/runtime defect into one missing
  data category.
- `RunState.started_at` is a monotonic process value created only after provider
  construction; raw evidence has relative event times and `created_at`, but no
  accepted-run UTC start/end pair. The resulting `e2e_ms` is therefore not the
  preregistered full E2E measure (`app/core/types.py:79-105`,
  `app/main.py:410-422`, `app/core/orchestrator.py:638-650`).
- The two-file ledger write is individually atomic but not transactional as a
  pair: manifest is replaced and then ledger is replaced
  (`app/core/pilot.py:923-925`, `1086-1090`). `PilotLedger.open` checks IDs and
  the frozen manifest hash, while `assert_integrity` does not compare the
  mutable condition sets/state between manifest and ledger
  (`app/core/pilot.py:1071-1080`, `1434-1474`). A crash in that window can leave
  a stale reservation view and permit an unsafe resume decision.

## P0

**None observed.** The runtime projection contains task/context/reference data,
not rubric criteria or expected facts; no runtime import/read of the rubric
artifact was found. This conclusion is limited to static inspection and the
existing control artifacts; it is not a live-provider claim.

## P1

1. **RTA-P1-01 — Snapshot completeness is not guaranteed.** Three declared
   task scopes exceed the 7,000-character RAG limit, and no check proves that
   all required facts/locators survive selection/truncation.
2. **RTA-P1-02 — E2E measurement starts too late.** Snapshot preparation and
   provider construction are outside the stored run timer, contrary to the
   preregistered accepted-start-to-final definition.
3. **RTA-P1-03 — Rate-limit/quota control is procedural, not executable.** No
   strategy-neutral aggregate pacing, header capture, account-limit enforcement,
   or required fresh preflight is enforced; 429 effects can be differential.
4. **RTA-P1-04 — Quality denominator is not operationally closed.** Missingness
   threshold, canonical retry/attempt selection, evaluator packet generation,
   and `NOT_EVALUABLE` handling are not represented in the processed export.
5. **RTA-P1-05 — Provider error bodies can enter raw evidence.** Key redaction
   is not equivalent to response-body sanitization.
6. **RTA-P1-06 — Incident taxonomy collapses degraded/local failures into
   provider incidents.** This can misstate root cause and alter missingness.
7. **RTA-P1-07 — Resume safety has a two-file torn-write window.** The ledger
   has no journal/transaction or manifest-vs-ledger mutable-state comparison.
8. **RTA-P1-08 — Benchmark construct/claim boundary is too broad as written.**
   The task set is self-referential and route-revealing at the observable
   condition level; broad generalization is not supported without narrowing or
   adding held-out tasks.

## P2

- Fixed's observational verifier examines a pre-synthesis draft rather than
  the final answer (`app/core/orchestrator.py:531-549`); keep the limitation
  explicit in analysis and evidence interpretation.
- The JSON manifest schema is permissive (`additionalProperties: true`) and
  leaves many cross-field invariants to Python validation
  (`config/pilot/PILOT_RUN_MANIFEST_SCHEMA_V1.json:1-20`,
  `app/core/pilot.py:925-1002`). The application validator is stronger, but
  schema-only consumers could accept an unsafe shape.
- Pricing values are duplicated in code and the Pilot config; current values
  match, but `Orchestrator.metrics` calculates from module constants rather than
  loading the immutable pricing object at execution time
  (`app/core/orchestrator.py:41-58`, `617-650`).
- Scope slicing, crash-window consistency, raw-body sanitization, header
  capture, and full E2E-boundary behavior lack focused regression tests even
  though the current normal-path tests cover order, identity, hidden-field
  exclusion, and basic resume behavior.
- Three repeats are suitable for finding operational defects and variance, not
  precise Main-study inference (`docs/PILOT_PREREGISTRATION.md:107-120`).

## P3

- Add held-out, non-self-referential task families and larger repeat counts for
  Main; do not select them from a favorable Pilot outcome.
- Add uncertainty intervals/hierarchical analysis after the quality and
  missingness rules are frozen.
- Add separately versioned cross-provider/model sensitivity blocks only after
  the homogeneous primary block is stable.
- Calculate and report inter-rater reliability only after the preregistered
  overlap is actually scored; do not infer it from staffing or protocol text.

## TOP 5 RISKS

1. **Incomplete task evidence:** R2-04/R2-05/R2-08 may be scored against facts
   that were in the permitted scope but dropped from the shared snapshot.
2. **Provider-window confounding:** unpaced Worker bursts and unrecorded quota
   state can turn strategy differences into 429, retry, latency, or missingness
   differences.
3. **Invalid latency comparison:** stored E2E excludes part of the accepted
   execution boundary and lacks a persisted start/end audit trail.
4. **Unstable quality denominator:** retries, interrupted attempts, incidents,
   and open missingness thresholds can produce incomparable strategy rates.
5. **Evidence/resume integrity:** raw exception bodies, collapsed incident
   causes, and a torn manifest/ledger pair can make a run unsafe to interpret or
   recover.

## RECOMMENDATION

**PILOT_NEEDS_FIXES.** Do not interpret a live 96-condition block until the P1
items are either fixed and regression-tested or explicitly converted into
pre-registered exclusion/block rules. The current orchestration mechanics do
not justify a claim that Adaptive beats Fixed; report quality, latency,
tokens/calls, cost, retries, and task conditions separately after the controls
are closed.

## HANDOFF TO INTEGRATION

Before authorizing a live block, Integration should obtain evidence for these
gates:

1. Make snapshot completeness explicit: increase/partition the context budget
   or add a fail-closed check that every required reference locator survives
   the shared snapshot. Add a regression for the three oversized tasks.
2. Define and persist the accepted condition start, unit context-preparation
   timing, final-ready time, UTC timestamps, and monotonic durations. State how
   shared per-unit preparation is attributed without changing the preregistered
   estimand.
3. Capture current account-specific Groq limits, implement or document a
   strategy-neutral throttle/pause policy, retain rate-limit headers and
   `Retry-After`, and split/pause the block when the remaining quota cannot
   cover the registered stress budget. Rate-limited conditions must remain
   incidents, not quality failures.
4. Harden raw error handling to persist only exception class/status,
   normalized category, and safe message; distinguish provider incidents from
   verifier/local failures; then scan representative failure artifacts.
5. Add a journal/transaction or a cross-file version/consistency check for
   manifest and ledger persistence, and test crash windows before and after
   reservation/raw recording.
6. Freeze the evaluator packet format, opaque candidate mapping, canonical
   attempt-selection rule, `EVALUABLE/NOT_EVALUABLE` status, whole-unit rerun
   linkage, and the numerical missingness/incomparability threshold.
7. Either narrow the inference statement to this technical contract benchmark
   or deliver a separately reviewed held-out task set. Keep the current rubric
   strategy-neutral and evaluator-blind.
8. Require the recorded fresh provider diagnostic and account-limit decision as
   a live-execution precondition; keep `--allow-live` as an authorization flag,
   not the only gate.

**Handoff state:** no live Pilot authorization; stop after this red-team report.

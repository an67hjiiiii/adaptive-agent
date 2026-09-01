# Pilot preregistration and experiment-design review

**Design status:** `PILOT-R1` design with quality package frozen under `QEP-1.1`

**Scope:** this document specifies a Pilot design only. It does not create
benchmark tasks, author per-task hidden rubrics, change orchestration code, or
start any Pilot run. Pilot observations are for validating and tuning the
design; they are not Main-study evidence.

The current V6.3 Research Baseline Candidate is the design anchor: Single,
Fixed (`FIXED-TOPOLOGY-V1`), Static (`STATIC-PRESETS-V1`), and Adaptive are
distinct strategies; Compare uses one Frozen Context Snapshot and sequential
top-level execution; the verified regression baseline is 58/58 tests. These
facts are implementation inputs, not results of the proposed Pilot.

## 1. Purpose of the Pilot

The Pilot validates whether the task set, taxonomy, evaluation protocol,
fairness controls, instrumentation, and operational limits are usable before a
Main Freeze. It is an engineering and measurement-design check, not a claim
that Adaptive is superior. The Pilot may expose ambiguous tasks, unstable
rubrics, unsuitable budgets, retrieval problems, provider incidents, or
unobservable escalation. Any resulting change must be made and recorded before
Main Freeze.

## 2. Research questions (preserved)

**RQ1.** Đặc điểm nhiệm vụ ảnh hưởng như thế nào đến hiệu quả của các mức
orchestration khác nhau xét theo chất lượng, độ trễ và chi phí?

**RQ2.** Adaptive Orchestrator có thể lựa chọn và tổ chức Agent phù hợp theo
nhiệm vụ để đạt trade-off Quality–Latency–Cost tốt hơn Fixed Multi-Agent hay
không?

These questions remain exploratory during Pilot. No global strategy ranking is
claimed from Pilot data.

## 3. Compared strategies

Each strategy receives exactly the same task, Frozen Context Snapshot, provider,
model, model settings, output requirement, instrumentation, and pricing
snapshot for a comparison unit. Only the pre-registered strategy policy and
its bounded role topology differ.

| ID | Strategy | Frozen policy for this Pilot |
| --- | --- | --- |
| B0 | **Single** | Direct Solver → final answer (`SINGLE-DIRECT-V1`). |
| B1 | **Fixed** | `FIXED-TOPOLOGY-V1`, version 1.0: Planner, exactly three independent Worker slots, observational Runtime Verifier, Synthesizer; no Adaptive route or escalation. |
| B2 | **Static** | One initial structural analysis selects one versioned preset in `STATIC-PRESETS-V1`; the selected preset cannot change or escalate at runtime. |
| P | **Adaptive** | Structural analysis → rule-based DIRECT/PARALLEL/PLANNED route → bounded verification and, only when allowed, targeted escalation. |

The orchestrator is a controller, not an additional LLM execution. Worker
concurrency inside a strategy is allowed; top-level strategies for one unit are
not concurrent.

## 4. Experimental unit

A **comparison unit** is one task and one repeat. It creates one Frozen Context
Snapshot and four raw strategy runs (Single, Fixed, Static, Adaptive). Thus the
working design has 8 × 3 = 24 comparison units and 96 strategy runs.

The unit-level record must contain a stable unit ID, task/reference manifest
hash, repeat ID, snapshot ID/hash, provider/model/settings identities, pricing
identity, strategy order, and links to all four raw run IDs. A provider incident
that makes the unit non-comparable invalidates the whole unit for comparative
quality interpretation; it never deletes the raw runs.

## 5. Task taxonomy

The primary research-only annotations are:

- **T1 Single-focus** — one main answer aspect.
- **T2 Independent multi-aspect** — multiple aspects that can be answered
  independently.
- **T3 Dependency-heavy** — at least one answer is an explicit prerequisite for
  another.
- **T4 Verification/conflict-sensitive** — conflicts, exceptions, or a high
  risk of confusing a rule with an exception.

The benchmark workstream authors tasks from source/reference material, then
derives expected source facts and evaluation criteria, and finally assigns the
taxonomy annotation with a written rationale. It must not choose a task because
it is expected to make Adaptive win. The Analyzer receives only the user task,
Frozen Context, and its public structural schema; it never receives T1–T4
labels, expected answers, or hidden rubric fields.

Required provenance for each task is source document ID/version/hash, task
text/version, expected source facts, evaluation-criteria version, taxonomy
label/rationale, and an ambiguity flag. The frozen benchmark and rubric now
supply that provenance in `benchmarks/pilot/pilot_benchmark_v1.json` and
`evaluation/pilot/pilot_rubrics_v1.json`; this document still does not copy
hidden rubric fields into runtime input.

## 6. Planned task count

| Taxonomy | Planned tasks | Allocation |
| --- | ---: | --- |
| T1 Single-focus | 2 | T1-a, T1-b (IDs to be frozen in the task manifest) |
| T2 Independent multi-aspect | 2 | T2-a, T2-b |
| T3 Dependency-heavy | 2 | T3-a, T3-b |
| T4 Verification/conflict-sensitive | 2 | T4-a, T4-b |
| **Total** | **8** | Working Pilot target |

The labels and task IDs above are placeholders for the separate benchmark
manifest. They are not runtime route hints.

## 7. Planned repeat count

There are **3 repeats per task × strategy condition**, yielding:

```text
8 tasks × 4 strategies × 3 repeats = 96 Pilot runs
8 tasks × 3 repeats = 24 comparison units
```

Repeat IDs are independent draws of the same frozen condition, not new tasks.
Three repeats are adequate for discovering operational defects and output
variance; they are not enough for precise Main-study inference. The Main repeat
count must be reviewed and frozen after Pilot, without selecting it from a
favorable outcome.

## 8. Provider and model plan

The primary Pilot live block uses the currently verified configuration:

- provider: **Groq**;
- model: **`openai/gpt-oss-120b`**;
- model catalog/settings identity: `MODEL-CATALOG-V1` and
  `MODEL-SETTINGS-V1`;
- orchestration identity: `ORCH-ADAPTIVE-AUTO-V1` plus the versioned Fixed and
  Static identities above;
- retrieval identity: `RAG-LEXICAL-V1`;
- pricing identity: `PRICE-TABLE-V1`.

The exact generation settings, budget ceilings, timeout, retry limit, and output
requirement are frozen in the run manifest before the first unit. They are the
same across strategies; strategy-specific role prompts are versioned but not
retuned during a unit. API credentials remain server-side and are never put in
the manifest, evidence, logs, browser, or this document.

Fake is permitted for offline mechanical smoke tests only. Fake output is not
quality, latency, token, or cost evidence for the live Pilot. Gemini, OpenAI,
OpenRouter, or a different model are not silently substituted. Adding another
provider/model requires a versioned amendment before execution and a separate
analysis block.

Before each live block, run one bounded provider diagnostic and record its safe
normalized result, timestamp, model, and configuration identities. A live
diagnostic is a readiness check, not a Pilot observation.

## 9. Frozen-context fairness

For each comparison unit:

1. Parse and retrieve the supplied reference once with deterministic Simple RAG.
2. Create one immutable Frozen Context Snapshot before any strategy run.
3. Persist snapshot ID, context/snapshot hash, source document IDs, selected and
   available chunk IDs, retrieval settings, creation timestamp, and explicit
   truncation metadata. Silent truncation is prohibited.
4. Pass the exact snapshot ID/hash, text, and provenance metadata to all four
   strategies. A strategy may not retrieve again or mutate the snapshot.
5. Freeze provider, model, model settings, budget, prompt versions, and pricing
   identity for the unit.

The four raw runs remain separate evidence. Compare quality is labelled “Not
evaluated” by the application until a formal human-quality protocol is applied;
no weighted QLC, Quality/Cost, or Quality/Latency score is invented.

## 10. Strategy-order policy

Top-level strategy runs are sequential. Internal independent Workers may use
`asyncio` concurrency, and their durations are not summed into E2E latency.

To reduce sequence and provider-drift effects, the Pilot harness will use a
balanced, seeded permutation:

1. Publish the task-manifest hash and a preregistration seed before execution.
2. For each of the 24 units, choose one of the four 4×4 Latin-square rows
   (`Single, Fixed, Static, Adaptive` and its rotations), then apply a seeded
   Fisher–Yates shuffle to the assignment of task/repeat units to rows.
3. Enforce six occurrences of each strategy in each ordinal position (24 units
   × four positions) and record the resulting permutation in unit evidence.
4. Execute the four strategies in that recorded order with no strategy-specific
   warm-up, pause, or retry policy. Provider readiness calls occur outside the
   measured unit.

The current application Compare endpoint is verified to be sequential but uses
the fixed order `Single → Fixed → Static → Adaptive`. Using that endpoint
unchanged would violate this order policy; the Pilot harness/order mechanism
must therefore be validated or amended before Pilot execution (see P0/P1
findings). This design task does not modify runtime orchestration.

## 11. Measurements

All timestamps are UTC for persistence; elapsed time uses a monotonic wall clock.
For every raw run, retain both event evidence and an immutable summary.

**Execution and resource metrics**

- Agent Execution: one bounded runtime role/agent instance activation.
- Logical Model Call: one intended application-level provider invocation;
  retries remain one logical call.
- Physical Provider Request: each actual provider request; every retry increments
  this count.
- Input, output, and total tokens: provider-reported usage only. If unavailable,
  store `null`/`Unavailable`, never zero.
- Calculated API Cost: frozen provider pricing snapshot × recorded billable
  usage; otherwise `null`/`Unavailable`.
- E2E latency: wall-clock from accepted valid run/execution start until the
  final result is ready to persist/return. It includes context preparation,
  retrieval, orchestration, provider/network time, retries, verification,
  escalation, and synthesis. It does not sum parallel Worker durations.

**Control and outcome metrics**

- strategy/config identity and version;
- mode and route evidence;
- Static selected preset (when applicable);
- Agent, logical-call, and physical-request counts separately;
- stop state/reason (`STOP_SUFFICIENT`, budget/timeout/failure/degraded states);
- snapshot ID/hash and chunk provenance;
- verifier status, issues, escalation linkage, and bounded retry evidence;
- provider diagnostic/incident status.

No resource metric is converted into a composite quality or QLC score.

## 12. Quality evaluation framework

The primary formal quality framework is task-specific mandatory criteria and
critical errors, authored independently of runtime routing:

```text
MandatoryCoverage = PassedMandatory / TotalMandatory
SufficientPass = (MandatoryCoverage == 1.0) AND (CriticalErrorCount == 0)
```

Primary report: **Sufficient Pass Rate**. Supporting reports: Mandatory
Coverage and Critical Error Count/Rate. Optional criteria are descriptive only.
No 1–10 subjective score is primary, and no ratio or weighted overall score is
reported.

Evaluators should be blind to strategy, provider, and run order. They receive
the task, permitted source/reference material, answer, and the versioned
criteria; they do not receive hidden prompts or runtime traces by default.

Frozen Pilot evaluator plan: primary role `E1` scores all 96 outputs; second
role `E2` independently scores exactly 24 (25%) selected by the deterministic
taxonomy-by-strategy hash rule in `QEP-1.1`, plus all `UNCLEAR`, borderline,
invalid, and disputed cases. Disagreements are resolved item-by-item against
the cited corpus, with `ADJ-1` for unresolved substantive cases. Evaluator
identities are recorded as role IDs in the research ledger. Inter-rater
reliability is not claimed until the overlap is actually scored and calculated.

## 13. Pilot acceptance and failure criteria

Pilot acceptance means “design ready for Main review”, not “Adaptive wins”. A
Pilot block is operationally acceptable only when all of the following are
verified:

- all 24 units have a preassigned order and frozen manifest/config identities;
- each valid unit has one shared snapshot ID/hash and chunk provenance across
  all four runs;
- Fixed topology signature and Worker count are identical across tasks;
- Static records exactly one initial preset and never changes it or escalates;
- Adaptive route, verifier, escalation, budget, retry, and timeout evidence are
  observable where the task requires them;
- no Analyzer input contains T1–T4 labels or hidden rubric data;
- top-level runs are sequential, order balance is met, and internal Worker
  overlap is measured from timestamps where applicable;
- failed/stopped runs and provider incidents are persisted, not dropped or
  silently retried;
- token/cost fields are null when unavailable, and no secret scan finding exists;
- the evaluation form can be applied without an undefined mandatory criterion,
  and the pre-registered inter-rater rule is met or triggers a rubric revision.

Failure/block conditions include any unequal context/provider/model/settings,
unrecorded order, hidden-label leakage, strategy-specific unregistered tuning,
missing raw evidence, or use of an unapproved provider fallback. A provider
incident or excessive/differential missingness suspends comparative
interpretation; it does not become a fabricated strategy failure.

## 14. Rules for tuning after Pilot

Before Main Freeze, Pilot may motivate changes to benchmark wording, rubric
definitions, prompts, orchestration policy, budgets, timeout, retry limit,
retrieval settings, or repeat count. Every change requires an amendment record
containing the old/new version IDs, rationale, date, affected units, and whether
affected Pilot cells must be rerun. Original evidence is immutable.

The following are prohibited: dropping an inconvenient task, changing a label
because of its result, selecting repeats or order after seeing outcomes,
retuning only one strategy, changing the provider mid-block, or presenting
Pilot observations as Main evidence. A material change resets the relevant
freeze and must be reviewed before execution resumes.

## 15. Rules preventing Main leakage

- Main tasks use held-out source documents and task IDs not used in Pilot.
- Pilot answers, route traces, and outcome summaries are not supplied to the
  Analyzer, Planner, Workers, Verifier, or Synthesizer.
- Expected facts and hidden criteria remain evaluator-side; runtime receives
  only the task and Frozen Context.
- Evaluators are blinded to strategy/provider and see randomized answer IDs.
- The Main manifest, rubric version, order seed, configuration identities, and
  analysis plan are frozen before Main execution.
- Pilot-driven changes are versioned amendments, never silent edits.

## 16. Missing-data handling

Every assigned condition receives one explicit status: `observed`,
`missing_not_run`, `failed`, `stopped`, `provider_incident`, or `invalidated`.
Raw JSON evidence is retained for every status.

There is no imputation of answer, tokens, latency, or cost. Resource fields are
`null`/`Unavailable` when the provider did not return usage. Report both (a)
assigned-unit completion/missingness by strategy and task type and (b) quality
rates among valid, evaluable final answers. The frozen denominator policy is
`QEP-DENOMINATOR-V1`; its differential-missingness policy is
`PILOT-DIFFERENTIAL-MISSINGNESS-V1` with
`MAX_DIFFERENTIAL_MISSINGNESS_PER_ACCEPTED_UNIT = 0`. An accepted comparison
unit is one `task_id × repeat_index` with all four registered strategies under
the same freeze identity. Any provider/infrastructure-missing condition makes
the unit `INCOMPARABLE_UNIT` and requires the existing whole-unit rerun policy;
three valid strategies plus one infrastructure-missing strategy is not
accepted. An explicit `STRATEGY_TERMINAL_FAILURE` remains strategy evidence and
is not counted as infrastructure missingness.

## 17. Failed and stopped runs

`STOP_FAILURE`, timeout, budget exhaustion, verifier-degraded, and other
stopped states remain in the run ledger and comparison record. They contribute
to operational completion and resource reporting, but have no quality verdict
unless a valid final answer is present and the rubric permits evaluation.

Retries inside one run are counted as additional Physical Provider Requests and
remain one Logical Model Call. A post-incident rerun, if approved, gets a new
run ID linked to the original; it never overwrites or hides the original
failure. No run is silently removed because it is inconvenient.

## 18. Provider incident handling

Record only the normalized diagnostic category and safe message (for example,
`NETWORK_BLOCKED`, `TIMEOUT`, `RATE_LIMITED`, `QUOTA_EXHAUSTED`,
`CREDIT_EXHAUSTED`, or `SUCCESS`), with timestamp and provider/model identity.
Never persist keys or raw provider bodies.

If a provider is unavailable before a unit, pause that block; do not substitute
another provider. If an incident occurs during a unit, finish only what is safe,
mark the unit non-comparable, retain all four statuses, and rerun the complete
unit only after a fresh diagnostic and an approved incident note. A credit
exhaustion is an external blocker, not an application defect and must not be
bypassed by changing billing or credentials. Fake remains available for
mechanical regression but cannot replace live quality evidence.

## 19. Reproducibility requirements

Before execution, publish a no-secret run manifest containing:

- preregistration and amendment version;
- task/reference manifest IDs and SHA-256 hashes;
- provider/model and all generation/budget/retry/timeout settings;
- `MODEL-*`, `RAG-*`, `ORCH-*`, `FIXED-*`, `STATIC-*`, and `PRICE-*` identities;
- prompt-version map and application/archive/commit identifier;
- Python version, dependency lock/check result, and safe environment
  diagnostic;
- deterministic order seed and the complete per-unit permutation;
- timezone/clock convention and run start/end timestamps;
- snapshot IDs/hashes, source/chunk IDs, retrieval settings, and truncation;
- raw run/evidence paths, evaluator form version, blinded answer IDs, and
  incident log.

The order seed is derived from the preregistration version, task-manifest hash,
and unit ID using SHA-256, then used by a documented Fisher–Yates/PRNG step.
This makes the schedule reproducible without exposing credentials. A manifest
or snapshot hash mismatch invalidates the affected comparison unit.

## 20. Pilot → Main decision gate

The Pilot review produces one of three decisions:

1. **READY FOR MAIN REVIEW** — task manifest/rubric, order mechanism, provider
   plan, missing-data rule, instrumentation, and evaluator reliability are all
   signed off; amendments are frozen for Main.
2. **REVISE AND RE-RUN PILOT CELLS** — a documented design defect is fixable
   before Main; only affected cells are rerun with new versioned identities,
   while old evidence remains.
3. **BLOCKED** — unresolved validity, provider, staffing, or reproducibility
   issue prevents interpretation; no Main execution is authorized.

Main Freeze occurs only after the decision, manifest, rubric, order seed,
provider/model/settings, analysis rules, and amendment history are archived.
Pilot does not start automatically from this document.

## Critical design review

### P0 — blocking validity risks

1. **Unrandomized sequence risk.** The verified Compare endpoint currently uses
   a fixed Single → Fixed → Static → Adaptive order. Running the Pilot with that
   order confounds strategy with provider warm-up, drift, and rate limiting. A
   balanced seeded order must be implemented or validated in the Pilot harness
   before any Pilot result is interpreted.
2. **Missing frozen task/rubric artifacts — RESOLVED for quality review.** The
   versioned benchmark, immutable corpus bindings, `PILOT-RUBRIC-V1.0`, and
   blinded evaluator procedure are frozen and mechanically audited under
   `QEP-1.1`. Pilot execution still requires the separate integration gates
   below; this resolution does not authorize a live run.
3. **Provider/config drift.** A live block is invalid if provider, model,
   settings, pricing, or snapshot identity changes within a comparison unit or
   if an unregistered fallback is used. The preflight, freeze, and incident
   rules above are mandatory controls.

### P1 — required before Pilot

- **DONE (quality):** Freeze the exact eight-task manifest and independent
  taxonomy rationales.
- **DONE (quality):** Freeze mandatory/critical-error criteria, evaluator
  masking, overlap, adjudication procedure, and 96 planned packet identities
  in `QEP-1.1`; evaluator slots remain explicitly `UNASSIGNED` until staffing
  is actually confirmed.
- Validate the order-randomization mechanism and its six-per-position balance.
- Confirm provider rate-limit/quota budget for 96 live runs, including a pause
  and whole-unit rerun policy.
- **DONE (quality):** Freeze `QEP-DENOMINATOR-V1`, zero differential
  infrastructure-missingness tolerance, Case E administrative allowlist, and
  approval-before-unblinding rule; validate the coordinator packet/status
  records before execution.
- Verify that every run exports the required snapshot, config, count, usage,
  latency, stop, and incident fields before Pilot execution.
- Treat three repeats as Pilot-debugging coverage only; choose Main repeats by a
  documented precision/variance rationale, not by Pilot winner selection.

### P2 — useful safeguards

- Calibrate evaluators on a small held-out set before scoring Pilot outputs.
- Record provider health and queue/rate-limit observations alongside unit IDs.
- Report latency distributions and position-stratified summaries, not only means.
- Add an independent audit of source provenance, secret scanning, and snapshot
  hashes before the decision gate.
- Precompute a workload estimate so evaluator time and API budget are visible.

### P3 — future work

- Larger repeat counts and additional held-out task families for Main.
- Cross-provider/model sensitivity blocks after the primary design is stable.
- Formal uncertainty intervals and hierarchical analyses once the quality data
  and missingness policy are frozen.
- Longitudinal drift checks across provider/model revisions.

## Open decisions for sign-off

1. Integration owner must archive the frozen eight-task manifest and rubric
   identities with the Pilot run manifest.
2. Integration owner must confirm evaluator capacity and record the eventual
   overlap agreement statistic; the current machine-readable slot status is
   `UNASSIGNED`/`UNCONFIRMED`, and no reliability claim is made before scoring.
3. Pilot harness versus an amended Compare API for randomized sequential order.
4. The operational missingness threshold is frozen at zero per
   `PILOT-DIFFERENTIAL-MISSINGNESS-V1`; integration must apply it and report any
   `INCOMPARABLE_UNIT` before comparative interpretation.
5. Exact frozen generation settings and live-run time window for Groq.
6. Main repeat-count rationale after Pilot variance is observed.

## Task H integration clarification (does not amend RQ1/RQ2)

The allowed Pilot conclusion is bounded to controlled, source-grounded
technical-document tasks under the tested frozen provider/model/settings,
`PILOT-CORPUS-V1`, and the registered experiment design. It may describe
observed quality/resource/missingness patterns and design readiness for this
block. It must not claim universally optimal orchestration, that Adaptive is
best for all tasks/models, that Multi-Agent always beats Single, a global
mathematical optimum, or Main-study evidence for RQ1/RQ2.

The canonical artifact chain for integration is:

```text
pilot_benchmark_v1@1.1.0
PILOT-CORPUS-V1
PILOT-RUBRIC-V1.0
QEP-1.1
PILOT-R4-V1 / PILOT-EXECUTION-INFRA-V1@1.0
```

`design_reference.sha256` in the benchmark is historical R1 authoring
provenance. This mutable preregistration is not a runtime answer source; the
immutable corpus bindings are authoritative. The integration candidate is
registered in `docs/PILOT_MANIFEST_REGISTRY.md` and is not authorization to
execute the 96 conditions. A fresh matching provider preflight and the
remaining operational gates are required before any Pilot run.

No Pilot runs were started by PILOT-R1, and no runtime application files were
modified for this design specification.

## Task I-A operational freeze (2026-08-31)

Task I-A freezes the research-control layer without changing runtime
orchestration, pacing, provider preflight, benchmark wording, rubric meaning,
or Pilot authorization. The frozen identities are:

- denominator: `QEP-DENOMINATOR-V1`;
- differential missingness: `PILOT-DIFFERENTIAL-MISSINGNESS-V1`, version
  `1.0`, numeric threshold `0`;
- Case E: `PILOT-CASE-E-ADMIN-V1`, closed administrative allowlist with
  independent approval before unblinding; and
- evaluator operations: `PILOT-EVALUATION-OPS-V1` with packet set
  `PILOT-EVALUATOR-PACKETS-V1`.

The coordinator registry contains 96 stable `PLANNED` packet identities
(24 units × four strategies). A packet is `EVALUABLE` only after matching raw
evidence is bound; `PLANNED` is never scored or included in a quality
denominator. E1 and E2 slots remain `UNASSIGNED`, `ADJ-1` is on demand, and
capacity remains `UNCONFIRMED` until real staffing is recorded. No Pilot
condition was executed or authorized by this freeze.

# Pilot human-quality evaluation protocol

**Protocol version:** `QEP-1.1`  
**Status:** `QUALITY_REVIEWED` / final for Pilot human scoring  
**Benchmark:** `pilot_benchmark_v1@1.1.0`  
**Corpus:** `PILOT-CORPUS-V1` (`corpus/pilot/v1/`)  
**Rubric:** `PILOT-RUBRIC-V1.0` (`evaluation/pilot/pilot_rubrics_v1.json`)

This protocol freezes how the eight Pilot tasks are judged. It is a research
evaluation document, not runtime orchestration policy. The benchmark task
projection is safe for runtime; the rubric, expected facts, evaluator labels,
and reviewer metadata remain evaluator-side.

## 1. Scope and frozen inputs

The immutable answer corpus is the six-file `PILOT-CORPUS-V1` snapshot recorded
in `benchmarks/pilot/pilot_benchmark_v1.json` and
`corpus/pilot/v1/CORPUS_MANIFEST.json`. The benchmark's
`tasks[].reference_bindings` (source IDs, snapshot hashes, and stable section
IDs) are authoritative. Legacy heading/line ranges are human traceability
only. A criterion may use no fact outside the task's permitted scope and may
not infer a fact from general knowledge.

The frozen quality package contains one complete rubric entry for each of
`PILOT-R2-01` through `PILOT-R2-08`. Every entry binds:

- task ID and exact task wording SHA-256;
- `benchmark_version`, `corpus_version`, and `rubric_version`;
- the task's permitted reference scope;
- mandatory criteria and critical-error definitions with source locators; and
- optional criteria that never change a primary outcome.

The benchmark is marked `QUALITY_REVIEWED` only because all eight entries are
present, source-supported, and mechanically bound. A future task, corpus, or
criterion change requires a new version and a fresh review.

## 2. Unit of evaluation

A comparison unit is one task and one repeat. The Pilot design has eight tasks,
three repeats, and four strategy conditions (Single, Fixed, Static, Adaptive):

```text
8 tasks × 3 repeats × 4 strategies = 96 answer packets
8 tasks × 3 repeats = 24 comparison units
```

The evaluator judges an answer packet, not a strategy trace. The coordinator
keeps the private mapping from opaque candidate ID to task, repeat, strategy,
and unit so that stratified review is possible without showing those fields to
the evaluator.

## 3. Evaluator packet and blinding

Each packet contains exactly:

1. an anonymized candidate ID;
2. the exact task wording;
3. the permitted reference scope for that task;
4. the candidate's final answer; and
5. the hidden rubric entry for that task.

Where feasible, the evaluator does not receive strategy, selected route, agent
count, provider, model, latency, token usage, cost, run ID, repeat ID, trace,
or research taxonomy. The packet does not expose evaluator identity. The
research ledger records evaluator role IDs and timestamps separately.

The coordinator-side planned registry is
`evaluation/pilot/pilot_evaluator_packets_v1.json`. It contains 96 stable
packet identities and binding references, but no task answer, expected fact, or
rubric criterion content. Every planned record starts with status `PLANNED`.
It may become `EVALUABLE` only after a valid raw run-evidence record is bound to
the same task, unit, repeat, strategy, and freeze identity. `PLANNED` is never
treated as `EVALUABLE`, and no planned record contributes to a quality
denominator before that evidence gate.

The evaluator may consult only the permitted immutable corpus scope. A final
answer that is absent, unusable, or invalidated by a declared incident is
marked `NOT_EVALUABLE`; it is not silently scored as a failure and is excluded
from answer-level quality denominators.

## 4. Rubric construction contract

Every mandatory criterion is:

- atomic (one judgeable proposition);
- necessary for a source-grounded answer to that task;
- supported by a source ID and locator inside the permitted scope;
- observable in the answer;
- strategy-neutral and independent of verbosity, style, or route preference;
- paired with an explicit observable test, pass rule, fail rule, and non-examples.

Every critical error is a serious source-grounded error for that task. It has a
definition, source support, trigger, and non-examples. A critical error is
counted at most once per answer even if repeated. Minor imprecision, style,
length, or a missing optional detail is not a critical error.

Optional criteria are clarity or useful supporting details only. They do not
enter mandatory coverage, sufficient pass, or the primary aggregate.

## 5. Labels and primary outcomes

The evaluator uses no 1–10 scale and no arbitrary weighted score.

| Object | Allowed labels | Meaning |
| --- | --- | --- |
| Mandatory criterion | `PASS` / `FAIL` / `UNCLEAR` | `PASS` requires the criterion pass rule from the permitted corpus. `UNCLEAR` is not a pass. |
| Critical error | `PRESENT` / `ABSENT` / `UNCLEAR` | `PRESENT` requires the frozen trigger and source support. `UNCLEAR` is held for second review. |
| Answer packet | `EVALUABLE` / `NOT_EVALUABLE` | Packet-level usability/incident status, recorded before answer-level aggregation. |

For an evaluable answer:

```text
MandatoryCoverage = PassedMandatory / TotalMandatory
SufficientPass = (MandatoryCoverage == 1.0)
                 AND (CriticalErrorCount == 0)
```

`PassedMandatory` counts only `PASS`. A mandatory `FAIL` or `UNCLEAR` is not
passed. `CriticalErrorCount` counts `PRESENT`; an `UNCLEAR` critical decision
cannot be treated as absent before review.

The primary aggregate is **Sufficient Pass Rate** over evaluable final
answers. Supporting reporting includes Mandatory Coverage and Critical Error
Count/Rate. There is no QLC score, weighted quality score, Quality/Cost ratio,
or Quality/Latency primary ratio. Missing tokens, latency, cost, or answers
are never imputed.

## 6. Frozen evaluator procedure

The coordinator releases packets with the same rubric version and permitted
scope. For each packet, the evaluator:

1. confirms packet ID, task text, scope, and answer status;
2. marks each mandatory criterion `PASS`, `FAIL`, or `UNCLEAR` and records a
   short source locator/evidence note;
3. marks each critical error `PRESENT`, `ABSENT`, or `UNCLEAR` and records its
   trigger evidence;
4. may record optional observations without changing the primary outcome; and
5. locks the packet before seeing another evaluator's labels.

The evaluator must not reward a preferred strategy, extra verbosity, an
unregistered score, or a citation to a source outside the allowed scope.

## 7. Second review and disagreement resolution

The Pilot staffing plan is frozen as follows:

- **Primary evaluator `E1`:** reviews all 96 answer packets, recording
  `NOT_EVALUABLE` where appropriate.
- **Second reviewer `E2`:** independently reviews a base overlap of exactly
  24 packets (25%), plus every exception listed below.
- **Selection rule:** before packet release, compute
  `SHA-256("PILOT-R2-QA-SUBSET-20260830|" + anonymized_candidate_id)`. Within
  each coordinator-only taxonomy-by-strategy stratum (16 strata), sort by the
  digest and take the first packet from every stratum. Using frozen ordinal
  orders T1,T2,T3,T4 and Single,Fixed,Static,Adaptive, take a second packet
  from exactly those eight strata where `(taxonomy_ordinal +
  strategy_ordinal) mod 2 = 0`. This is deterministic, gives two packets in
  two strata per taxonomy and per strategy, and yields exactly 24 packets.
- **Additional E2 cases:** every `UNCLEAR` label, borderline/unclear critical
  decision, invalid task or rubric finding, and primary/second-review
  disagreement. These cases may make the final E2 workload exceed 24.
- **Identity recording:** the research ledger records `E1`, `E2`, and `ADJ-1`
  role IDs, assignments, timestamps, locked labels, changes, and rationales;
  packet contents remain identity-blind.

E1 and E2 lock independently. A disagreement is resolved item-by-item against
the frozen criterion and cited corpus locator. If the wording or source scope
is ambiguous, the coordinator marks `PILOT-RUBRIC-V1.0` defective, issues a new
rubric version, and re-evaluates every affected packet; a locked score is not
silently edited. An unresolved substantive disagreement goes to blinded
adjudicator `ADJ-1`, whose decision and rationale are retained. Inter-rater
reliability is **not claimed** until the overlap is scored and an agreement
statistic is actually calculated.

The machine-readable evaluator plan records `E1`, `E2`, and `ADJ-1` as role
slots with status `ASSIGNED` or `UNASSIGNED`; it never invents human names.
Before staffing is actually confirmed, all three slots are `UNASSIGNED` and
capacity status is `UNCONFIRMED`. Planned capacity is 96 packets for E1, a
24-packet base overlap plus exceptions for E2, and on-demand adjudication for
ADJ-1.

## 8. Workload and calibration

The current manifest has 36 mandatory criteria, 16 critical-error definitions,
and eight optional criteria (one optional item per task). The practical estimate
is:

| Activity | Estimate |
| --- | ---: |
| Primary: 96 packets × 6–8 minutes | 9.6–12.8 person-hours |
| Second-review base: 24 packets × 6–8 minutes | 2.4–3.2 person-hours |
| Calibration | 0.5–1.0 person-hours |
| Disagreement/adjudication reserve | 1.0–2.0 person-hours |
| **Expected total** | **14–19 person-hours** |

The range is a planning estimate, not a measured result. It is intentionally
not reduced by dropping necessary criteria. Optional criteria are not required
for a packet to pass and should not add scoring time.

## 9. Missingness and analysis boundaries

`NOT_EVALUABLE` packets remain in the raw ledger and are reported by task and
strategy as operational missingness. They are excluded from the evaluable
quality denominator without imputation. Provider incidents, stopped runs, and
budget/timeout states remain raw evidence; they do not become fabricated
quality failures unless a usable final answer exists and the rubric permits an
answer-level judgment.

The numerical differential-missingness rule is frozen as
`PILOT-DIFFERENTIAL-MISSINGNESS-V1`, under denominator policy
`QEP-DENOMINATOR-V1`: `MAX_DIFFERENTIAL_MISSINGNESS_PER_ACCEPTED_UNIT = 0`.
An accepted comparable unit is one `task_id × repeat_index` containing the four
registered strategy conditions under one `freeze_identity`. Its
`infrastructure_missing_count` must be zero. Therefore, three valid strategy
conditions plus one provider/infrastructure-missing condition is
`INCOMPARABLE_UNIT`, not an accepted unit. The affected unit follows the
existing whole-unit rerun policy and every original raw record is retained.

An explicit `STRATEGY_TERMINAL_FAILURE` is legitimate strategy evidence. It is
reported separately and does not count as infrastructure missingness. An
unclassified failed/stopped/missing record is fail-closed as infrastructure
missingness until the coordinator supplies a source-backed classification.

Resource fields remain separate from quality. Tokens and cost are `null` or
`Unavailable` when the provider does not supply usage or a known price. No
resource field is converted into a quality score.

### 9.1 Frozen operational denominator and missingness cases

The evaluator assignment in Section 7 is fixed for this Pilot: primary `E1`
reviews every packet, `E2` independently reviews the deterministic 24-packet
base overlap plus all listed exceptions, and unresolved substantive
disagreements go to blinded adjudicator `ADJ-1`. The following case handling is
locked before any outcome is inspected:

| Case | Operational definition | Quality denominator | Failure/reliability reporting | Rerun | Raw evidence |
| --- | --- | --- | --- | --- | --- |
| **A. Valid answer** | A usable final answer is present and the packet is not invalidated. | **Include** in the strategy/task denominator, whether its rubric outcome passes or fails. | Report rubric outcome; include in E1/E2 overlap and reliability calculations when selected. | No outcome-driven rerun. | Retain original answer and labels. |
| **B. Provider/infrastructure failure** | Network, authentication, quota, provider, timeout, or infrastructure incident leaves no usable answer. | **Exclude** from answer-level quality; count as operational missingness/provider reliability incident. | Report by provider, model, strategy, task, and phase; do not convert to a quality failure. | Permitted only under the pre-specified incident/whole-unit rerun policy; never delete the original attempt. | Retain redacted incident record and original raw attempt. |
| **C. Strategy terminates without evaluable answer** | The strategy reaches a terminal stop/budget state without a usable final answer. | **Exclude** from answer-level quality; count as strategy termination/missingness. | Report termination and missingness separately from answer quality and reliability. | Permitted under the same pre-specified whole-unit policy; no winner-dependent retry. | Retain original terminal raw evidence. |
| **D. Corrupted/invalid experimental unit** | Manifest/config/snapshot/provenance corruption or an invalid unit makes the comparison unit unusable. | **Exclude all conditions in the unit**; do not salvage a favorable strategy denominator. | Report an invalidated unit and integrity incident; it is not a model-quality failure. | Permitted only as an exact, version-linked whole-unit rerun after the defect is fixed; no partial replacement. | Retain every original raw file and invalidation rationale. |
| **E. Manually excluded unit** | One of the closed administrative reason codes in `PILOT-CASE-E-ADMIN-V1` is confirmed independently of outcomes. | **Exclude all conditions in the unit**; exclusions are not imputed. | Report count, unit IDs, reason code, approval timing, and evidence reference; never use exclusion to improve a winner's denominator. | Permitted only when the frozen exclusion policy explicitly allows a whole-unit rerun before outcome review. | Retain original raw evidence, decision, and approver rationale. |

For every strategy, the quality denominator is therefore the count of Case A
packets only. Cases B–E remain visible in the missingness, reliability, and
integrity tables. A rerun creates a new attempt linked to the original; it does
not erase, overwrite, or retroactively reclassify the original case. No
post-hoc winner-dependent denominator, imputation, or selective packet removal
is permitted.

### 9.2 Case E administrative exclusion freeze

Case E is an administrative/non-performance exclusion only. The closed reason
code allowlist is:

- `ADMIN_DUPLICATE_ASSIGNMENT`;
- `ADMIN_CONSENT_OR_PRIVACY_EVENT`; and
- `ADMIN_EXTERNAL_INTERRUPTION`.

Outcome-based reasons are forbidden, including `LOW_QUALITY`, `ADAPTIVE_LOST`,
`FIXED_FAILED`, `OUTLIER_RESULT`, `UNEXPECTED_RESULT`, and equivalent wording.
There is no arbitrary free-text exclusion reason. A Case E exclusion is
whole-unit only, preserves every original raw record, and is reported with its
reason code and evidence reference.

The approval record must contain the operational fields `requester_role`,
`approver_role`, `reason_code`, `requested_at`, `approved_at`,
`approval_status`, `evidence_reference`, and `approved_before_unblinding`.
Requester and approver are distinct role IDs. Only `APPROVED` records may
exclude a unit, and approval must be recorded before comparative outcomes are
exposed. `PENDING` or `REJECTED` is not an exclusion.

## 10. Leakage audit and blocker policy

The research rubric is never runtime input. The audit checks that:

- runtime task projection contains task text, corpus bindings/scopes, and the
  output instruction only;
- `research_annotations`, expected facts, mandatory criteria, critical errors,
  and evaluator fields are not sent to Analyzer, Planner, Worker, Verifier, or
  Synthesizer;
- `app/**`, `app/static/**`, and `runs/**` do not import, read, render, or
  persist `evaluation/pilot/pilot_rubrics_v1.json` or its hidden fields; and
- the frontend exposes no research rubric or evaluator metadata.

Rubric content reaching any runtime role, prompt, frontend, or run evidence is
a **P0 blocker**. A missing/invalid task-rubric binding, broken source scope,
or broken blinding is **P1**. The current static audit is recorded as
`PASS` in the rubric manifest; it does not authorize a live Pilot run.

## 11. Versioning and acceptance gate

The following identities are frozen together for this Pilot quality pass:

```text
QEP-1.1
pilot_benchmark_v1@1.1.0
PILOT-CORPUS-V1
PILOT-RUBRIC-V1.0
QEP-DENOMINATOR-V1
PILOT-DIFFERENTIAL-MISSINGNESS-V1
PILOT-CASE-E-ADMIN-V1
PILOT-EVALUATION-OPS-V1
PILOT-EVALUATOR-PACKETS-V1
```

An amendment must record old/new identities, rationale, date, affected tasks or
packets, and whether locked answers require re-evaluation. No silent rubric
edit, post-outcome criterion, strategy-specific criterion, or source drift is
permitted.

**Quality acceptance:** 8/8 task rubrics valid, 36 mandatory criteria, 16
critical-error definitions, frozen blind labels and review plan, frozen
denominator/Case-E/evaluator operations, 96 `PLANNED` packet identities, and
leakage audit `PASS`.  
**Integration handoff:** integration may consume the public benchmark task
projection and must separately re-audit order randomization, provider/model
and pricing freeze, staffing, and live-run preflight. This document does not
start or authorize execution and does not claim live-provider quality or
production readiness.

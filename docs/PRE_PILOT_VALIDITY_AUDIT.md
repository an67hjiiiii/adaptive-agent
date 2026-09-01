# TASK F — Pre-Pilot Experiment Validity & Claim-Scope Audit

**Audit date:** 2026-08-31 (Asia/Saigon)  
**Mode:** READ-ONLY scientific/experiment audit  
**Scope:** frozen Pilot benchmark, Pilot/Main claim boundary, quality denominator,
resume ledger, experimental-unit identity, incident policy, and validity threats.  
**Execution decision:** this audit did not call a live provider and did not start
the 96-condition Pilot.

## Executive result

**STATUS: `PARTIAL — PILOT_NEEDS_FIXES`**

The research design is defensible as a narrowly bounded engineering/measurement
Pilot for source-grounded technical-document tasks under a frozen provider/model/
configuration. The benchmark and human-quality protocol are structurally strong:
the benchmark is `QUALITY_REVIEWED`, all eight tasks have bound rubrics, and the
Case A–E denominator table is strategy-neutral.

The Pilot is not yet scientifically safe to interpret because several protocol
rules are not fail-closed in the execution/evidence path. In particular, the
processed export has no canonical-attempt/evaluable-answer selection, the code
allows per-condition retries where the protocol requires whole-unit incident
reruns, provider/local failure categories are collapsed, and the manifest/ledger
pair has no complete reconciliation rule. Three task scopes also exceed the
7,000-character snapshot limit without a required-fact survival check.

No observed P0 rubric-leakage defect was found. This is a static conclusion only;
there is no live Pilot evidence in this audit.

## Evidence baseline and method

The audit read the governing contract, current state, Pilot benchmark notes,
preregistration, execution protocol, quality protocol, provider-limit/preflight
documents, benchmark/rubric/corpus artifacts, manifest schema, Pilot ledger and
executor, runtime persistence, provider diagnostics, and focused tests.

The following read-only checks were performed:

| Check | Result |
| --- | --- |
| Benchmark status/version | `QUALITY_REVIEWED`, `pilot_benchmark_v1@1.1.0` |
| Tasks/annotations | 8 tasks, 8 matching research annotations |
| Taxonomy allocation | 2 tasks each for T1, T2, T3, and T4 |
| Rubric package | `QUALITY_REVIEWED`; 36 mandatory criteria, 16 critical-error definitions, 8 optional criteria |
| Frozen corpus | 6/6 source hashes and line counts matched `CORPUS_MANIFEST.json` |
| Prepared design shape | 24 comparison units and 96 strategy conditions, by manifest construction rules |
| Existing research raw runs | None found in the current checkout; no `phase=PILOT` raw evidence was inspected |
| Live provider execution | Not performed |

The project-local `.venv\Scripts\python.exe` is currently a OneDrive reparse
point that returned `Access is denied` when invoked. Therefore this audit does
not claim that the Python regression suite or live runtime checks passed. The
findings below are based on source, artifact, and protocol inspection plus the
read-only JSON/hash/scope checks above.

## A — Benchmark claim scope

### What the experiment can legitimately claim

The narrow supported claim is:

> Under the frozen `PILOT-CORPUS-V1` technical-document benchmark, with the
> registered task/reference scopes, one frozen provider/model/settings tuple
> (`Groq` / `openai/gpt-oss-120b`), fixed retrieval and budgets, shared context
> snapshots, and the registered Single/Fixed/Static/Adaptive policies, the study
> can describe comparative quality, latency, resource use, and operational
> missingness. During Pilot, those observations are exploratory and primarily
> assess design/instrumentation readiness rather than establish an RQ1/RQ2
> conclusion.

The strongest current Pilot-specific claim is even narrower:

> The Pilot can show whether this benchmark, rubric, evaluator workflow,
> snapshot/evidence path, order control, and provider operating procedure are
> usable for a later Main review.

This follows the preregistration's explicit statement that Pilot observations
validate/tune the design and are not Main-study evidence (`docs/PILOT_PREREGISTRATION.md:5-8,18-24,35-36`).

### What the eight tasks actually represent

All eight tasks are self-referential, source-grounded questions about this
project's own contract, implementation audit, provider safeguards, evidence
surfaces, and baseline closure:

| Taxonomy | Tasks | Observed task family |
| --- | --- | --- |
| T1 | R2-01, R2-02 | route/role semantics and retry/metric accounting |
| T2 | R2-03, R2-04 | provider safeguards and evidence-surface summaries |
| T3 | R2-05, R2-06 | DAG scheduling and verifier-repair sequences |
| T4 | R2-07, R2-08 | provider-status exceptions and historical baseline reconciliation |

The task wording intentionally names structural situations that correspond to
the controller's observable paths. For example, R2-01 names a single-focus,
non-dependent, low-verification condition; R2-05 names a particular dependency
trace; and R2-06 names a `NEEDS_WORK` repair sequence. The benchmark notes say
the wording does not prescribe a route, and no hidden T1–T4 labels or rubrics
are sent to runtime. That supports a **controller-conformance / technical
contract** interpretation, but it does not make this an unbiased sample of
ordinary user tasks or a generalization benchmark.

The T1–T4 labels are research-only annotations and no P0 leakage was observed.
They should be treated as descriptive strata, not as independently randomized
causal factors: there are only two tasks per stratum, and task type is entangled
with source document, wording, and evidence structure.

### Claim boundary

| Classification | Legitimate wording |
| --- | --- |
| **SUPPORTED CLAIM** | “For this frozen source-grounded technical-document benchmark, under the registered provider/model/settings and strategy policies, the observed Pilot/Main-block outcomes are …” |
| **SUPPORTED CLAIM** | “The Pilot found the benchmark/evaluation/execution design ready, conditionally ready, or in need of revision for Main review.” |
| **TOO BROAD** | “Adaptive Multi-Agent is universally better.” |
| **TOO BROAD** | “Adaptive works better for all LLM tasks, users, domains, languages, or production workloads.” |
| **TOO BROAD** | “The experiment proves the optimal orchestration architecture.” |
| **TOO BROAD** | “The one-model Groq result generalizes to other providers or models.” |
| **TOO BROAD** | “T1/T2/T3/T4 effects are causal task-complexity effects” without a separate sampling and analysis design. |
| **FUTURE WORK** | Held-out, non-self-referential Main task families, larger repeats, uncertainty intervals, hierarchical task analysis, and separately versioned cross-provider/model sensitivity blocks. |

RQ1 can currently be answered only descriptively within this frozen task set,
and RQ2 can only be a conditional comparison of registered policies under the
same frozen environment. The current documents do not constitute a complete
Main preregistration: they state that Main tasks will be held out and that a
Main Freeze is required, but do not yet freeze a Main sample, estimand,
missingness threshold, statistical model, or precision rationale
(`docs/PILOT_PREREGISTRATION.md:296-305,371-386,440-449`).

## B — Pilot versus Main claims

### Documentary boundary

**PASS at protocol level.** The separation is repeated consistently:

- Pilot is a design/measurement check, not a claim that Adaptive wins
  (`docs/PILOT_PREREGISTRATION.md:16-24`).
- RQ1/RQ2 remain exploratory during Pilot and no global ranking is claimed
  (`docs/PILOT_PREREGISTRATION.md:26-36`).
- Pilot changes must be versioned before Main Freeze, and Pilot observations
  must not be presented as Main evidence (`docs/PILOT_PREREGISTRATION.md:282-305`).
- The quality protocol says it does not authorize execution or claim live
  provider quality (`docs/QUALITY_EVALUATION_PROTOCOL.md:241-264`).

### Enforcement gap

**NEEDS_FIX at execution/export boundary.** The current code makes the boundary
declarative rather than fail-closed in all paths:

1. `PilotExecutor` marks any non-dry-run `phase=PILOT` execution as
   `research_evidence=true`; it permits a `fake` provider because the live gate
   is applied only when `provider != fake` (`app/core/pilot_executor.py:369-405`).
   A manifest built with `provider=fake` and `dry_run=false` can therefore enter
   the default Pilot evidence class even though the preregistration explicitly
   says Fake is mechanical smoke only (`docs/PILOT_PREREGISTRATION.md:141-145`).
2. `export_processed_dataset` includes rows based mainly on the phase. It does
   not require `research_evidence=true`, the approved benchmark state, a live
   provider, or a valid raw evidence path; it also emits an unrun assignment
   when a condition has no attempts (`app/core/pilot.py:1655-1698`).
3. `phase=PREFLIGHT` can be run against an ordinary non-dry-run manifest, and
   the condition is then recorded in that ledger as observed even though its
   raw row is later excluded by phase. There is no separate preflight-ledger
   identity enforced by the executor.

Therefore the documentary Pilot/Main distinction is clear, but a coordinator
must not treat the default processed export as final Main/Pilot evidence until
these gates and the evaluator selection layer are closed.

## C — Quality denominator review

### Intended rule

The quality protocol's Case A–E table is scientifically appropriate and
strategy-neutral (`docs/QUALITY_EVALUATION_PROTOCOL.md:200-221`):

| Case | Quality denominator | Operational reporting | Rerun principle |
| --- | --- | --- | --- |
| A. Valid answer | Include the evaluable answer, whether it passes or fails | Rubric outcome; eligible for planned review overlap | No outcome-driven rerun |
| B. Provider/infrastructure failure, including timeout | Exclude from answer-quality denominator | Provider/reliability missingness | Only under pre-specified incident policy; preserve original |
| C. Strategy stops without an evaluable answer | Exclude from answer-quality denominator | Strategy termination/missingness, separate from provider failure | Only under pre-specified policy; no winner-dependent retry |
| D. Corrupted/invalid unit | Exclude all four conditions in the unit | Integrity incident and invalidated unit | Exact version-linked whole-unit rerun only after repair |
| E. Manual exclusion | Exclude all four conditions in the unit | Reason, timing, approver, and unit count | Only if pre-specified and outcome-independent |

The resulting quality estimand is:

```text
Quality denominator(strategy) = number of canonical Case-A answer packets
Sufficient Pass Rate = Case-A packets with full mandatory coverage and no
                       critical error / Quality denominator(strategy)
```

Cases B–E must remain visible in operational reliability, termination, and
integrity tables. They must not be converted into quality failures, silently
imputed, or removed selectively for one strategy.

### Independent operational review

| Required decision | Current finding |
| --- | --- |
| **Valid answer** | The protocol says “usable final answer,” but the runtime/export path has no frozen machine/coordinator definition of usable, no `EVALUABLE/NOT_EVALUABLE` field, and no evaluator-packet ID. This is not operationally closed. |
| **Provider failure / timeout** | The intended Case B rule is correct. The implementation maps broad non-Fake `failed`/`degraded` outcomes to `provider_incident`, including failures that may be local, budget, parsing, or verifier-related (`app/main.py:450-469`, `app/core/pilot.py:1300-1315`). |
| **No evaluable strategy answer** | The intended Case C rule is correct, but there is no distinct persisted Case-C/evaluator label. A completed status with an empty/unusable answer is not fail-closed at the coordinator layer. |
| **Corrupted unit** | The protocol requires all four conditions to be invalidated. A snapshot/provenance mismatch currently raises from the executor; it does not create a persisted unit-level invalidation record or block state (`app/core/pilot_executor.py:440-463`, `app/core/pilot.py:1270-1298`). |
| **Manual exclusion** | Case E is described but no concrete exclusion criteria, approver record, timing field, or coordinator command is frozen. Using the generic `invalidated` status would not by itself prove an independent exclusion. |
| **Rerun after provider incident** | The protocol requires an approved fresh diagnostic and whole-unit rerun when an incident makes a unit non-comparable (`docs/PILOT_PREREGISTRATION.md:334-347`). The CLI/executor instead allows `--retry-failed` per condition and does not pause the unit or block after an incident (`app/core/pilot_executor.py:473-478,636-705`; `scripts/pilot_harness.py:371-390`). |

### Denominator, reliability, rerun, and raw-evidence verdict

| Item | Required final rule | Current verdict |
| --- | --- | --- |
| **QUALITY DENOMINATOR** | One canonical attempt per strategy condition; Case A only; no imputation | `NEEDS_FIX`: QEP is correct, but export emits every attempt and an unrun row and has no canonical selector or evaluator label (`app/core/pilot.py:1641-1723`). |
| **RELIABILITY/FAILURE DENOMINATOR** | Use assigned condition/unit counts for B–E and report them separately; use physical-request counts only for request-level rates; never use the Case-A quality denominator as reliability denominator | `NEEDS_FIX`: categories are named, but no complete numerical estimand/formula or canonical-attempt basis is frozen. |
| **RERUN ELIGIBILITY** | No outcome-driven rerun; B/C only under approved policy; D/E whole-unit only; new attempt linked to old | `NEEDS_FIX`: current retry is per condition and can retry provider incidents without fresh-diagnostic/whole-unit enforcement. |
| **ORIGINAL RAW EVIDENCE** | Immutable run file, stable run/attempt identity, attempt history, incident/invalidation reason, and no overwrite | `PASS on normal ledger path; NEEDS_FIX for torn writes, orphan/duplicate raw reconciliation, and sanitized provider-error evidence. |

The most dangerous denominator failure is asymmetric missingness. An Adaptive
provider/verification failure must not become “excluded,” while a Fixed bad but
evaluable answer becomes “counted,” unless the same Case A–E rule is applied to
both. The frozen table prevents that in principle; the current export and
incident mapping do not yet guarantee it in practice.

## D — Resume ledger audit

### Identity model

The intended identity layers are:

| Layer | Meaning | Current representation |
| --- | --- | --- |
| **Comparison unit** | One `task_id × repeat_id`; one shared context snapshot and four strategy conditions | Manifest `unit_id`, `task_id`, `repeat_index/repeat_id`; 8 × 3 = 24 |
| **Experimental condition** | One registered `comparison unit × strategy`; the treatment cell, not a provider request | `unit_id::strategy`, strategy/config/provider/model fields |
| **Run / provider attempt** | One invocation of one strategy condition, with one `run_id`/`attempt_id`; may contain retries | Ledger reservation plus attempt history; a rerun gets another ID |
| **Provider attempt/request** | One physical request to the provider | `Budget.physical_requests`; retry increments it inside the same run |
| **Agent Execution** | One bounded role activation in the orchestrator | `agent_executions`; a retry does not create another Agent Execution |

The normal path respects the important distinction: `_call` increments logical
calls and physical requests separately, while the retry loop keeps one logical
role call; the focused tests assert this separation (`app/core/orchestrator.py:212-279`, `tests/test_runtime.py:480-487`). A whole-condition rerun is represented by a new ledger attempt/run ID, and the old attempt is retained (`app/core/pilot.py:1373-1395,1398-1461`).

### Resume behavior that passes on the normal path

- An `observed` condition is not started again (`app/core/pilot.py:1237-1244`).
- Failed, stopped, provider-incident, and invalidated conditions require
  explicit retry opt-in.
- A new retry receives a new run ID and a new raw path; the old path is not
  overwritten.
- A stale running condition with a matching terminal raw record can be
  reconciled; a stale reservation without terminal evidence becomes a retained
  `missing_not_run` attempt and requires a new run ID.
- The manifest hash and task-manifest hash protect against the ordinary case of
  resuming with a different prepared manifest/task artifact
  (`app/core/pilot_executor.py:305-349`).

### Findings against the requested ledger checks

1. **Completed-condition skip: PASS in normal execution.** The executor walks
   the recorded order and skips `observed` conditions.
2. **Failed-condition preservation: PASS in normal execution.** Failed/stopped
   and provider-error raw evidence is retained and retry is explicit.
3. **New attempt ID: PASS in normal execution.** `begin` rejects used IDs and
   appends attempt history.
4. **Stale `RUNNING` recovery: PARTIAL.** Terminal raw evidence is adopted, but
   a non-terminal or malformed raw file is not comprehensively reconciled and
   can leave the operator without a persisted resolution path.
5. **Config-change safety: PARTIAL.** A changed prepared manifest is rejected,
   but the manifest does not bind an application/commit/dependency identity and
   the executor does not verify the current runtime code/configuration against
   the frozen block. A code or dependency change can therefore occur between
   attempts without an unsafe-resume failure.
6. **Interrupted overwrite safety: PARTIAL.** Raw files use unique paths and
   atomic individual writes, but the manifest and ledger are replaced as two
   separate files.
7. **Duplicate detection: PARTIAL.** Ledger run IDs are checked, but there is
   no complete scan proving that every raw file maps to exactly one ledger
   attempt or that every expected manifest condition is present exactly once.
8. **Exact remaining work: FAIL under ledger corruption.** `assert_integrity`
   validates the manifest and iterates whatever conditions are present in the
   ledger, but does not compare the ledger condition set to the manifest's
   expected set/count. A truncated ledger could therefore report no pending
   work and still omit assigned conditions (`app/core/pilot.py:1482-1536`).

### Manifest/ledger disagreement and required reconciliation rule

The two files can disagree. `_persist` writes `manifest.json` first and
`ledger.json` second (`app/core/pilot.py:1148-1152`). A process crash in that
window can leave the manifest with a new reservation/status while the ledger is
still old. `PilotLedger.open` checks only the manifest/ledger ID and validates
the manifest; `assert_integrity` does not compare the mutable condition sets or
state pointers across the two files (`app/core/pilot.py:1134-1142,1496-1536`).

The required reconciliation rule before any further execution is:

1. Treat the frozen manifest schedule/configuration as immutable and verify its
   hash independently.
2. Require the ledger to contain exactly the expected set of
   `unit_id::strategy` keys—no missing and no extra conditions.
3. Compare every ledger condition to its manifest counterpart for immutable
   identity: task/repeat, strategy/config, provider/model/settings, phase,
   benchmark/rubric, source/scope, and order. Compare mutable state separately:
   status, run state, current run ID, current raw path, and attempt history.
4. Inventory every `raw/run_*.json`. Each raw record must map to exactly one
   condition and one attempt by condition ID/run ID, and its identity fields
   must match the frozen condition. Any unmatched, duplicate, malformed, or
   ambiguous raw file blocks execution and is preserved for review.
5. Resolve safe crash cases deterministically: a matching terminal raw file may
   be adopted once; a pending ledger plus terminal orphan must not start a new
   attempt; a terminal ledger with missing raw evidence is an integrity block;
   a manifest/ledger mismatch is never repaired by choosing the newest file.
6. Persist a reconciliation record containing the decision, source file hashes,
   and operator/time identity. Do not delete or rewrite the original evidence.

Without this rule, “resume” is safe only for the tested happy path, not for the
failure modes that matter to scientific evidence preservation.

## E — Research-unit validity

The unit definitions are valid if the analysis keeps the following boundaries:

```text
24 comparison units = 8 tasks × 3 repeats
96 experimental conditions = 24 units × 4 strategies
one condition attempt = one registered strategy invocation
one logical model call = one bounded role call, including its retries
one physical request = one provider request attempt
one Agent Execution = one bounded role activation
```

Consequences:

- A retry after a 429, timeout, or structured-output error is **not** a new
  experimental replicate. It remains the same logical call and same condition
  attempt, while `physical_requests` increases.
- A rerun after an incident is a new attempt of the same condition, not a new
  `task × repeat` unit. It must carry `attempt_index`, a new run/attempt ID,
  `supersedes`/`rerun_of` linkage, and the original status.
- Rerunning an entire invalidated unit creates a new version-linked attempt for
  each of its four conditions. It must not overwrite or retroactively rewrite
  the original unit's raw evidence.
- A quality coordinator must choose one canonical attempt per condition before
  calculating quality. Counting every row from `export_processed_dataset` would
  count an interrupted attempt and its replacement as two answer packets and
  could create an artificial replicate.

The executor's attempt preservation is a good foundation, but the derived row
does not explicitly expose `attempt_index`, and the exporter is intentionally
one-row-per-attempt rather than one-row-per-canonical-condition
(`app/core/pilot.py:1578-1638,1673-1698`). That is acceptable as raw-derived
audit data, not as the final quality-analysis table.

## F — Pilot stop/continue and incident policy

### Protocol coverage

The documents state the right high-level responses: rate-limited attempts are
operational incidents, provider unavailability pauses rather than silently
switches provider, source/hash/config drift invalidates affected evidence, and
rubric leakage is a blocker (`docs/PILOT_PREREGISTRATION.md:276-280,334-347`; `docs/PILOT_EXECUTION_PROTOCOL.md:253-270,392-430`).

### Enforcement review

| Incident | Required disposition | Current finding | Classification |
| --- | --- | --- | --- |
| Isolated 429 | Preserve retry/physical-request evidence; do not score it as a quality failure if no valid answer exists | Per-call retry exists, but the retry event keeps a redacted exception string rather than a normalized rate-limit event/header; no aggregate pacing | P1/P2 |
| Systematic 429 or quota pressure | Pause/split the block; do not continue producing differential missingness | No aggregate limiter, block pause, remaining-quota check, or provider-header persistence in the executor/harness | P1 |
| Source/hash mismatch | Stop before affected condition; fail closed; preserve a block/integrity record | Source mismatch raises before execution, which is safe, but no persisted unit/block incident record is created | P2 |
| Rubric leakage | Stop and invalidate affected runs; P0 if rubric content reaches runtime | Static leakage audit is recorded PASS and no observed leak exists; no live pre-execution gate proves this for every run | P2 (P0 rule remains) |
| Config/provider/model drift | Stop affected block; require a versioned amendment and fresh preflight | Manifest identities are recorded, but arbitrary provider/model preparation and no preflight linkage remain possible | P1 |
| Provider outage | Pause; never silently switch provider | `--allow-live` is the only runtime live-provider gate; fresh diagnostic/account-limit evidence is not required by the executor | P1 |
| Verifier unavailable after usable candidate | Preserve candidate, classify as verifier/local degradation, and apply the frozen evaluator rule | `STOP_VERIFICATION_UNAVAILABLE` is converted to `provider_incident`; this conflates provider, verifier, and local failures | P1 |
| Manual exclusion | Require pre-specified independent criterion, approver, time, and whole-unit handling | No concrete operational record exists | P1 |

The most important incident-control gap is that the protocol says “whole unit
non-comparable,” while `PilotExecutor.run_async` continues through the unit and
`--retry-failed` can later retry only the incident condition. A provider incident
must set a unit/block pause state before further comparative execution can be
authorized.

## G — Validity threats

### Internal validity

**Strengths:** the design holds provider/model/settings and task context fixed
within a comparison unit; the same frozen snapshot is assigned to all four
strategies; strategy identities are distinct; top-level order is balanced by a
seeded Latin square; and internal Worker concurrency is registered as part of
the strategy policy.

**Threats:**

1. **Incomplete common context — P1.** The shared snapshot may be identical but
   incomplete. Read-only scope reconstruction found assembled runtime contexts
   above the 7,000-character default for R2-04 (9,898 chars), R2-05 (9,574),
   and R2-08 (14,837). `frozen_snapshot` may select/truncate chunks and records
   the loss, but no check proves that every rubric locator or required fact
   survives (`app/core/rag.py:103-119,166-228`). This can confound task-family
   quality with retrieval completeness.
2. **Provider-window confounding — P1.** Fixed/Static/Adaptive have different
   call counts and Worker bursts. The Latin square balances ordinal position,
   but no aggregate pacing or quota-state capture removes rolling-window,
   queue, or differential 429 effects.
3. **Invalid latency estimand — P1.** `RunState.started_at` is created only
   after provider construction, while snapshot preparation and provider
   construction occur before it. The stored `e2e_ms` therefore does not cover
   the accepted run boundary specified by the preregistration, and no accepted
   UTC start/end pair is persisted (`app/core/types.py:78-105`,
   `app/main.py:410-471`, `app/core/orchestrator.py:617-650`).
4. **Attempt/missingness selection — P1.** Differential incidents, retries, and
   unrun rows can alter the denominator before quality scoring unless the
   coordinator freezes canonical-attempt and unit-invalidation rules.
5. **Registered policy versus pure orchestration — P2.** The strategies differ
   in role topology, prompts, call count, verification behavior, and escalation
   policy. This identifies a registered strategy package, not an isolated causal
   effect of an abstract “orchestration” variable. Fixed's verifier also examines
   the pre-synthesis worker draft rather than the final synthesized answer
   (`app/core/orchestrator.py:531-549`).
6. **Order control is not complete isolation — P2.** Balanced positions reduce
   sequence imbalance but do not remove provider drift, cache effects, or
   strategy-specific burst shape.

### External validity

The result is bounded to one Groq account/provider, one `openai/gpt-oss-120b`
model, one lexical-retrieval configuration, one small corpus, and eight
self-referential technical-document tasks. One model/provider is a normal
research limitation, not a P0. It is a **P2 scope limitation**: no claim should
generalize to other models, providers, domains, task types, user populations, or
production systems. Cross-provider/model sensitivity belongs in separately
versioned future blocks.

### Construct validity

- **Quality:** the rubric validly measures source-grounded contract conformance
  and critical errors for these tasks. It does not measure universal helpfulness,
  open-domain truth, user satisfaction, or production reliability. Runtime
  verifier `PASS` is not the formal human-quality outcome.
- **Latency:** the intended wall-clock construct is clear, but current evidence
  starts too late; either the boundary must be implemented or the estimand must
  be explicitly renamed and re-registered.
- **Cost:** the verified Groq price snapshot and provider-reported usage support
  conditional cost calculation. Missing usage/cost remains null, which is
  correct. The separate reasoning-token price is unavailable and must not be
  invented.
- **Resource counts:** Agent Execution, Logical Model Call, and Physical
  Provider Request are meaningfully distinct in the normal runtime path. They
  must remain separate from quality and from one another.
- **Retrieval/fairness:** identical truncated context preserves within-unit
  identity but not complete source access; this is a validity limitation, not
  proof of fair information coverage.

### Conclusion validity

Three repeats per task are suitable for finding operational defects and seeing
rough output variance, not for precise Main-study inference
(`docs/PILOT_PREREGISTRATION.md:107-120`). The current design also leaves the
operational missingness threshold and full Main analysis plan open. Therefore:

- Pilot can support design-readiness and exploratory descriptive reporting once
  the P1 controls are closed.
- Pilot cannot establish that Adaptive wins RQ2 or that a task characteristic
  causes a Quality–Latency–Cost improvement.
- Main conclusions require a fresh freeze of held-out tasks, canonical
  denominator/attempt rules, latency boundary, missingness threshold, analysis
  plan, and uncertainty/precision rationale.

## Classification

### P0 — would invalidate Pilot or make conclusions unreliable

**None observed.** The quality package declares rubric content research-only,
the runtime projection allowlists task/reference/output fields, and the static
leakage checks found no rubric payload in runtime prompts, frontend output, or
the inspected raw-evidence path (`evaluation/pilot/pilot_rubrics_v1.json:166-195`).
This does not waive the P0 stop rule if a live leakage check later fails.

### P1 — must resolve before Pilot interpretation

1. **F-P1-01 — Canonical quality dataset is not operationally closed.** The QEP
   denominator table is correct, but runtime export emits every attempt and
   unrun assignments, with no canonical attempt selector, evaluator packet ID,
   or `EVALUABLE/NOT_EVALUABLE` record.
2. **F-P1-02 — Whole-unit incident/rerun policy is not enforced.** The executor
   can continue after a provider incident and `--retry-failed` can retry one
   condition instead of requiring the approved complete-unit rerun.
3. **F-P1-03 — Incident taxonomy is asymmetric/overbroad.** Any non-Fake
   failed/degraded runtime result can be labeled `provider_incident`, including
   verifier-unavailable, budget, parsing, and local failures. This changes
   reliability and quality missingness.
4. **F-P1-04 — Resume integrity is not fail-closed.** Manifest/ledger writes are
   not transactional as a pair; mutable state is not cross-compared; expected
   condition coverage and raw-file bijection are not checked. A damaged ledger
   can misstate remaining work.
5. **F-P1-05 — Live provider gate is procedural, not executable.** The executor
   does not require a fresh matching preflight, account-limit decision, or
   strategy-neutral aggregate throttle/pause; differential 429/quota effects
   can become strategy differences.
6. **F-P1-06 — Snapshot completeness is unverified.** R2-04, R2-05, and R2-08
   exceed the default snapshot cap, with no fail-closed required-fact/locator
   survival check.
7. **F-P1-07 — Latency boundary does not match the preregistered E2E measure.**
   Snapshot preparation/provider construction and accepted UTC start/end
   evidence are missing from the stored timing boundary.
8. **F-P1-08 — Pilot/Main and provider evidence gates have escape paths.** A
   non-dry-run Fake manifest can be stamped research evidence; export trusts
   phase more than research-evidence/approval state; PREFLIGHT is not isolated
   from an ordinary Pilot ledger; arbitrary provider/model preparation is not
   forced into a versioned amendment block.
9. **F-P1-09 — Claim scope is too broad unless analysis is explicitly narrowed.**
   The actual task set supports a self-referential technical contract claim, not
   broad generalization or causal taxonomy conclusions. Main is not yet fully
   preregistered for those broader RQ interpretations.
10. **F-P1-10 — Raw incident evidence can violate the stated privacy boundary.**
    `redact_secrets` removes known/key-shaped tokens but can persist up to 2,000
    characters of an exception; provider error bodies can therefore enter
    events/raw evidence. Normalized category/safe-message-only evidence is not
    consistently enforced (`app/core/security.py:7-19`,
    `app/core/orchestrator.py:265-278`).

### P2 — can proceed only with the limitation documented

- Fixed's observational verifier reviews a pre-synthesis draft, not the final
  answer; do not describe it as a final-answer quality gate.
- The quality construct is contract/source conformance, not generic answer
  quality.
- One provider/model and eight self-referential tasks limit external validity;
  this is not a P0.
- Latin-square position balance does not remove provider queue/cache/quota drift.
- The JSON schema is permissive and leaves cross-field invariants to Python;
  schema-only consumers could accept unsafe shapes
  (`config/pilot/PILOT_RUN_MANIFEST_SCHEMA_V1.json:5-7,24-45`).
- Source/hash failure is fail-closed before execution but lacks a persisted
  unit/block incident record.
- No complete app/dependency/commit identity is included in the run manifest.

### P3 — future work

- Add held-out, non-self-referential Main task families and a justified larger
  repeat count.
- Freeze an uncertainty/precision and hierarchical task-analysis plan before
  Main; do not select it from a favorable Pilot outcome.
- Add separately versioned cross-provider/model sensitivity blocks after the
  homogeneous primary block is stable.
- Measure and report inter-rater reliability only after the planned overlap is
  actually scored; the current protocol correctly makes no pre-score claim.
- Add longitudinal provider/model drift checks and production-oriented
  reliability studies as separate research questions.

## Final report fields

**STATUS:** `PARTIAL — PILOT_NEEDS_FIXES`

**SUPPORTED RESEARCH CLAIM:** A controlled, source-grounded comparison/design
study for this frozen technical-document benchmark under the frozen
Groq/`openai/gpt-oss-120b` configuration; Pilot conclusions are exploratory and
about design readiness until Main Freeze.

**CLAIMS THAT MUST NOT BE MADE:** Universal Adaptive superiority; “works for all
LLM tasks”; optimal architecture; production readiness; cross-provider/model
generalization; causal T1–T4 effects from this eight-task block; or Main/RQ1/RQ2
evidence from Pilot observations without the explicitly exploratory label.

**PILOT VS MAIN:** `PASS` in the written protocols; `NEEDS_FIX` in fail-closed
execution/export enforcement (F-P1-08).

**QUALITY DENOMINATOR:** `NEEDS_FIX` operationally. Intended rule is Case A
only; canonical attempt, evaluator status, reliability formula, and threshold
are not yet fully executable.

**RESUME LEDGER:** `NEEDS_FIX`. Normal attempts are preserved and reruns get new
IDs, but pairwise reconciliation, exact condition coverage, raw bijection, and
code/config drift protection are missing.

**EXPERIMENTAL UNIT IDENTITY:** `PARTIAL/PASS` for the normal runtime counters;
one comparison unit is task × repeat, one condition is unit × strategy, retries
stay within one run, and reruns are new linked attempts. Final analysis still
needs canonical-attempt selection.

**INCIDENT STOP POLICY:** `NEEDS_FIX` enforcement. The written policy covers
429/quota, source/hash, rubric, drift, and outage cases, but the executor does
not yet pause the unit/block, require fresh preflight, or persist all incident
decisions as a fail-closed control state.

**VALIDITY:**

- **internal:** `PARTIAL/NEEDS_FIX` — shared context/provider/order controls are
  strong, but snapshot truncation, provider-window effects, latency boundary,
  and missingness selection can confound strategy comparisons.
- **external:** `P2 LIMITATION` — one provider/model and this project's
  self-referential technical-document corpus only.
- **construct:** `PARTIAL/NEEDS_FIX` — rubric and resource definitions are
  appropriate for the narrow construct; latency and snapshot completeness need
  closure, and runtime verification is not human quality.
- **conclusion:** `NEEDS_FIX BEFORE INFERENCE` — Pilot is suitable for design
  debugging, not precise RQ1/RQ2/Main inference.

**P0:** None observed; static-only conclusion.  
**P1:** F-P1-01 through F-P1-10 above.  
**P2:** documented limitations above.  
**P3:** future Main/robustness work above.

**FILES CREATED:**

- `docs/PRE_PILOT_VALIDITY_AUDIT.md` only.

**HANDOFF TO INTEGRATION:**

1. Freeze the canonical-attempt, evaluator-packet, usable-answer,
   `NOT_EVALUABLE`, reliability, and numerical missingness/incomparability rules
   before any scoring or interpretation.
2. Enforce whole-unit incident pause/rerun linkage; require a fresh matching
   provider diagnostic and account-limit decision; add strategy-neutral pacing
   and rate-limit evidence capture.
3. Make snapshot completeness fail closed or increase/partition the snapshot
   budget for R2-04/R2-05/R2-08, with regressions proving required locators/facts
   survive.
4. Add manifest/ledger transaction or journal semantics, exact condition-set
   reconciliation, raw-file bijection/duplicate checks, and a no-execution state
   for unresolved disagreement.
5. Persist the preregistered accepted start/end boundary and UTC/monotonic
   timing, with an explicit rule for shared per-unit snapshot preparation.
6. Close Fake/PREFLIGHT/export escape paths and bind provider/model/settings,
   application/dependency identity, and approved amendments to the live block.
7. Narrow the Pilot/Main claim text to this controlled technical-contract scope;
   freeze the held-out Main task set and analysis/precision plan separately.

**STOP.**

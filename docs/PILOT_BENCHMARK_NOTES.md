# PILOT-R2 benchmark construction notes

**Artifact:** `benchmarks/pilot/pilot_benchmark_v1.json`  
**Benchmark version:** `pilot_benchmark_v1@1.1.0` (`artifact_version` `1.1.0`)  
**Artifact SHA-256:** `18c1941c4f057f85160634bba334866795aa06b5746e9107cbe902c1f73ba706`  
**Frozen corpus:** `PILOT-CORPUS-V1` (`corpus/pilot/v1/`)  
**Design status:** `QUALITY_REVIEWED` under `QEP-1.1`; Pilot execution is not authorized by this artifact.

## Scope and construction rule

This benchmark was authored from the versioned V6.3 technical corpus that is
already in the project. The authoring order was:

```text
source section -> realistic developer/research question -> expected facts
-> structural annotation
```

No task was selected because a particular Adaptive route or strategy was
expected to win. The runtime-safe `tasks` array contains only the task text,
corpus version, immutable source bindings/scopes, and an output-format
instruction. Taxonomy, expected facts, authoring rationale, ambiguity, and the
quality-criteria metadata lives in the separate `research_annotations` array;
the frozen quality binding is the research-only `PILOT-RUBRIC-V1.0` manifest.
A runtime consumer must project only the fields listed under
`runtime_projection.send_only_fields`.

## Corpus manifest

The immutable snapshots and their authoritative metadata live in
`corpus/pilot/v1/`. `CORPUS_MANIFEST.json` records the corpus version, source
ID, snapshot SHA-256, line count, origin/provenance, snapshot timestamp, and
stable section IDs. The benchmark's `reference_bindings` are authoritative;
the older `reference_scope` line ranges remain only for human traceability.
The three living documents that caused the original drift (`CURRENT_STATE.md`,
`TEST_MATRIX.md`, and `README.md`) are no longer direct benchmark sources.

| Source ID | Frozen path | Version | Use in benchmark |
| --- | --- | --- | --- |
| `contract-v0.6.3` | `corpus/pilot/v1/PROJECT_CONTRACT.md` | 0.6.3 | Stable research semantics, structural signals, comparison fairness, verifier, provider, and measurement definitions |
| `state-v6.3` | `corpus/pilot/v1/CURRENT_STATE.md` | V6.3 | Verified implementation facts, V6.3 baseline closure, provider status, and declared limits |
| `audit-v6.3` | `corpus/pilot/v1/ORCHESTRATION_AUDIT.md` | V6.3 | Runtime fixtures, graph/scheduler/verifier evidence, retry/budget evidence, and baseline audit |
| `matrix-v0.6.3` | `corpus/pilot/v1/TEST_MATRIX.md` | 0.6.3 | Regression rows that make the claimed behavior mechanically checkable |
| `fixes-v0.6` | `corpus/pilot/v1/AUDIT_FIXES.md` | v0.6 | Documented privacy, provider-status, retry-accounting, and research invariants |
| `readme-v0.6` | `corpus/pilot/v1/README.md` | v0.6 | Operator-facing provider, flow, persistence, and evidence descriptions |

The snapshots were copied verbatim from the benchmark-authoring revision whose
hashes were declared by the original artifact. This preserves the source facts
without pretending that later edits to living project-management documents are
part of the Pilot corpus. Any future source change requires a new corpus
version; no snapshot in `v1` may be edited in place.

### PILOT-FIX-A drift record

The root cause was post-authoring edits to living documents: the current
`docs/CURRENT_STATE.md`, `docs/TEST_MATRIX.md`, and `README.md` hash to
`98c1d39f…` (183 lines), `2183e6c0…` (98 lines), and `7d60a833…` (100 lines),
respectively, while the benchmark-authoring snapshots were 163, 92, and 82
lines. The frozen copies retain the original declared hashes and are now the
only answer-source paths used by task bindings. This is a rebind, not a hash
refresh of mutable files.

`docs/PILOT_PREREGISTRATION.md` is recorded as the design reference
(`PILOT-R1`) but is not used as an answer source for any task. It supplies the
working taxonomy and the eight-task allocation only.

## Frozen task set

The task IDs are neutral (`PILOT-R2-01` … `PILOT-R2-08`) on purpose. They do
not encode T1/T2/T3/T4 in runtime input. The distribution is exactly two tasks
per research taxonomy.

| ID | Research type | What the task asks | Why this structure is defensible |
| --- | --- | --- | --- |
| `PILOT-R2-01` | T1 Single-focus | Apply the contract's single-focus/no-prerequisite decision rule and explain role participation and successful terminal behavior. | One route-semantics need, one contiguous contract region, no answer ordering. |
| `PILOT-R2-02` | T1 Single-focus | Count one retried bounded role execution across Agent Execution, Logical Model Call, and Physical Provider Request, including unavailable usage/cost. | One instrumentation rule; the metrics are different views of the same event. |
| `PILOT-R2-03` | T2 Independent multi-aspect | Compare diagnostic output, secret handling, and key/model-change status invalidation. | Three meaningful safeguards come from distinct source sections and can be answered separately. |
| `PILOT-R2-04` | T2 Independent multi-aspect | Summarize snapshot provenance, inspector views, and comparison missingness conventions. | Three evidence surfaces are independently enumerable; no ordering is required. |
| `PILOT-R2-05` | T3 Dependency-heavy | Trace the audited graph with two initial independent nodes and a later dependent node through validation, scheduling, worker timing, verification, and stop evidence. | The answer is a causal trace: graph construction and validation precede ready sets, and prerequisites precede the later node. |
| `PILOT-R2-06` | T3 Dependency-heavy | Trace the control sequence from `NEEDS_WORK` through targeted repairs, synthesis/re-verification, and PASS/FAIL terminal branches. | Later actions are enabled by the verifier result and remaining budgets; ordering is source-defined. |
| `PILOT-R2-07` | T4 Verification/conflict-sensitive | Resolve an `unknown` badge, model-change invalidation, and upstream error without overclaiming application failure or exposing secrets. | It combines conditional status semantics and a documented exception/misinterpretation risk. |
| `PILOT-R2-08` | T4 Verification/conflict-sensitive | Reconcile the comparison contract with the V6.3 fixed/static baseline closure and retain the remaining readiness limits. | A correct answer must cross-check historical gap vs closure and preserve the non-production caveat. |

### Expected source facts (research-only)

The corresponding `research_annotations.expected_source_facts` are authoring
references for the quality workstream; they must not be sent to any runtime
role. In summary:

- `PILOT-R2-01`: structural signals are validated; the single-focus condition
  follows the direct decision rule; Planner is not part of that path; verifier
  `PASS` yields `STOP_SUFFICIENT`.
- `PILOT-R2-02`: one role activation is one Agent Execution; retry remains one
  logical call; two attempts are two physical requests; retry evidence is
  recorded and unavailable usage/cost is not represented as zero.
- `PILOT-R2-03`: diagnostics are normalized and safe; credentials/raw bodies
  remain private; configured-but-unchecked is `unknown`, no-key is `missing`,
  and a key/model change invalidates the old badge.
- `PILOT-R2-04`: snapshots retain deterministic IDs/hashes, provenance,
  retrieval settings, timestamp, truncation, and exact text; the Inspector has
  Overview/Graph/Agents/Metrics/Raw; comparison missingness is `null` or
  `Unavailable` and quality remains `Not evaluated`.
- `PILOT-R2-05`: the fixture has a first ready set of `S1 + S3`, then `S2`;
  invalid graphs are rejected; Kahn-style ready sets and `asyncio.gather`
  enforce the dependency/concurrency boundary; successful verification stops
  sufficiently.
- `PILOT-R2-06`: `NEEDS_WORK` creates bounded issue-targeted repairs when
  budget permits, then synthesis and targeted re-verification; `PASS` stops;
  `FAIL` does not escalate.
- `PILOT-R2-07`: `unknown` is not provider failure; changing key/model requires
  a fresh badge; upstream errors are normalized incidents; raw provider data
  and credentials are never exposed.
- `PILOT-R2-08`: V6.3 freezes the fixed topology and static preset identity,
  keeps their verifiers observational, persists configuration identities, and
  still does not claim production readiness or Main Freeze.

## Leakage and bias review

### Runtime leakage check

- Runtime IDs are neutral and contain no taxonomy code.
- Runtime task text does not include T1/T2/T3/T4, hidden rubrics, expected
  facts, mandatory criteria, critical errors, or an expected strategy winner.
- Runtime reference bindings contain only a corpus version, source IDs, corpus
  paths, hashes, and stable section IDs; legacy line ranges are traceability
  metadata. Research-only annotations are not part of the projection.
- The task wording describes observable source conditions. It does not tell the
  Analyzer to use a route, to analyze in parallel, or to prefer a strategy.

### Bias review

- T1 tasks are not trivia: one asks for a complete decision boundary and one
  asks for three distinct accounting definitions plus missingness handling.
- T2 tasks use separate source surfaces and ask for a comparison/summary, not a
  phrase such as “analyze these in parallel”.
- T3 tasks use actual dependency and escalation sequences from the audit; no
  artificial dependency is added.
- T4 tasks contain real conditional/exception or cross-version reconciliation
  risks, rather than merely being long.
- No task contains a difficulty label, hidden score, intended route, or expected
  strategy winner. The artifact therefore cannot be used as a scoring rubric.

## Validation performed

The following offline checks are intended for the benchmark artifact only (no
Pilot run and no runtime modification):

1. JSON parses successfully; the canonical artifact hash matches the declared
   `artifact_sha256` (computed with that field omitted).
2. There are eight unique task IDs and eight matching research annotations.
3. The distribution contains exactly two IDs for each of T1, T2, T3, and T4,
   with no duplicate assignment.
4. All six frozen files exist, match their manifest SHA-256 and line counts,
   and every referenced source ID/section ID resolves in `CORPUS_MANIFEST.json`.
5. Every task has the `PILOT-CORPUS-V1` binding, a non-empty immutable scope,
   and an output instruction; the legacy ranges remain consistent with the
   frozen authoring revision.
6. The runtime projection contains only the allowlisted fields; its excluded
   fields are present only in research annotations/authoring metadata.
7. Each task's reference source IDs match the IDs used in both its immutable
   bindings and legacy scopes. A hash change in living `CURRENT_STATE.md` does
   not change the frozen snapshot hash.
8. `evaluation/pilot/pilot_rubrics_v1.json` parses with eight unique task
   entries, 36 mandatory criteria, 16 critical-error definitions, and one
   optional criterion per task; every criterion has a source-supported locator
   inside its task scope and every task wording hash matches the benchmark.
9. Static leakage checks find no rubric file/criteria payload in runtime
   prompts, frontend output, or run evidence; the benchmark runtime projection
   remains free of taxonomy, expected facts, and hidden quality fields.

The validation is schema/provenance checking only. It does not run the app,
call a provider, calculate quality, or start the Pilot.

For integration handoff, `scripts/pilot_harness.py prepare` also produced
`runs/pilot/prepared-corpus-v1-quality-reviewed/manifest.json`: 8 tasks × 3
repeats, 24 comparison units, 96 strategy conditions, balanced order, and no
research evidence (`research_evidence=false`). Preparation is not Pilot
execution.

## Handoffs and blockers

**Handoff from quality chat:** `evaluation/pilot/pilot_rubrics_v1.json` binds all
eight neutral task IDs to `PILOT-RUBRIC-V1.0` under `QEP-1.1`, with immutable
source support, blind labels, and a frozen second-review plan. The rubric is
research-only and must not be copied into runtime input.

**Handoff to integration:** add the artifact to the Pilot manifest path and
implement/validate a runtime projection that sends only the allowlisted fields.
The artifact itself does not change `app/**`, strategy semantics, ordering, or
the Compare endpoint.

**Blockers:** no corpus insufficiency was found and all eight references and
rubrics are valid. Pilot execution remains gated by the separate integration
preflight for randomized order, provider/config freeze, pricing verification,
and staffing. This benchmark is `QUALITY_REVIEWED`; it does not claim
live-provider quality or production readiness.

## Task H integration reconciliation (2026-08-31)

The canonical prepared candidate is `runs/pilot/taskh-final-manifest-v5.json`
(`pm_9eced06dc61e`, SHA-256
`9eced06dc61ef8dc7ec61b543eb5e8bb97067c4eb10b07d77590d92839bbb028`). It
binds this benchmark, `PILOT-CORPUS-V1`, `PILOT-RUBRIC-V1.0`, the frozen
Groq settings/pricing identities, 24 comparison units, and 96 conditions. The
older v2/v3 and `taskfix*` preparations remain historical and are not
interchangeable with this candidate.

The benchmark's `design_reference` hash for `docs/PILOT_PREREGISTRATION.md`
is intentionally retained as authoring provenance. That document is mutable
design metadata, not an answer source; all answer scopes resolve only through
the immutable corpus. Later edits therefore explain the hash drift and must
not be repaired by refreshing a mutable-file hash or changing task wording.

The latest bounded Groq probe after the final integration code/config/test
changes is `PASS` for the frozen settings; the preceding sandbox-blocked probe
is historical only. No current rate-limit headers were exposed by the adapter,
so the historical safe header snapshot remains the account-limit evidence. No
Pilot condition was executed.

# TASK G — Parallel Chat Integration Conflict Audit

Audit date: 2026-08-31 (Asia/Saigon). Read-only audit. No source, config,
benchmark, rubric, corpus, manifest, or test file was modified by this audit.

Evidence was read from the required project documents, current source/tests,
Pilot artifacts, and ignored `runs/` JSON. The final stable source snapshot was
observed at approximately 01:03:34 local time; generated run files continued to
receive writes until at least 01:06:47. This is therefore a time-bounded audit,
not proof that the checkout remained unchanged after the snapshot.

## STATUS:

PARTIAL — FINAL INTEGRATION IS BLOCKED UNTIL THE P1 ITEMS BELOW ARE
RECONCILED.

No P0 research/data corruption was observed. The frozen corpus, benchmark
bindings, rubric bindings, UI identifier boundary, and current Pilot identity
values pass static checks. However:

- The checkout has no usable Git baseline: branch `master` has no `HEAD`,
  `git ls-files` returns zero files, and the project is entirely untracked.
- Pilot source/tests/config files received late writes while this audit was in
  progress, and generated Pilot manifests have multiple competing generations.
- The current declaration count is 81 test methods, while living documents
  claim 73/73 and older audit documents claim 58/58 or 26/26.
- The benchmark declares a `PILOT-R1` preregistration design-reference hash
  that does not match the current `docs/PILOT_PREREGISTRATION.md` bytes.

The repository must not be treated as Pilot-authorized from this report.

## PARALLEL EDIT CONFLICTS:

### Baseline and ownership evidence

Exact overwrite/revert detection is not possible. There are no commits, no
tracked files, and no patch history against which to compare the independent
chat outputs. The current content can show present state and some generated
artifact-to-artifact differences, but cannot prove that an earlier untracked
file was never overwritten or that a removed untracked test never existed.

No file-level ownership manifest was found. The only explicit ownership rule is
the execution protocol's general instruction that Integration accepts the
benchmark/task manifest, rubric reference, provider preflight, and prepared
order (`docs/PILOT_EXECUTION_PROTOCOL.md:446-455`).

### Recent write clusters

The filesystem chronology is useful as a conflict signal, not as authorship
proof:

| Local time | Files/workstream signal |
| --- | --- |
| 00:17:16–00:17:39 | `docs/TERMINOLOGY_VI.md`, `docs/PROJECT_CONTRACT.md` |
| 00:32:31–00:34:55 | `app/static/app.js`, `app/static/index.html`, `tests/test_runtime.py` |
| 00:34:11–00:35:01 | quality/red-team/execution protocol documents |
| 00:58:47–01:03:34 | `app/core/pilot_executor.py`, `tests/test_pilot_executor.py`, `app/core/pilot.py`, `config/pilot/PILOT_CONFIG_V1.json`, `tests/test_pilot.py` |
| through 01:06:47 | generated `runs/` and provider/conversation evidence |

`tests/test_runtime.py` remained at SHA-256
`9211cba05422d1b937bff4618994f502d3c520fde63141e1dced663fbd873bda` during
the later Pilot writes. That is evidence against a later Pilot insertion into
that file, but not historical proof because no baseline exists.

### Generated manifest conflict found exactly

The two prepared artifacts below have the same canonical benchmark/provider/
model/rubric identities and 24-unit/96-condition shape, but they are not the
same frozen manifest:

- `runs/pilot/taskc-final-manifest-v2.json` has `manifest_id=pm_d418aa64bf3e`
  and `run_manifest_hash=d418aa64...`; its generation parameter status at
  line 127 is `store=UNUSED_BY_DESIGN`.
- `runs/pilot/taskc-final-manifest-v3.json` has `manifest_id=pm_d4d1956fdf05`
  and `run_manifest_hash=d4d1956f...`; its line 127 is
  `store=UNSUPPORTED_BY_GROQ`.

A read-only structural comparison found exactly four differing fields:
`configuration.generation_settings.parameter_status.store`, `created_at`,
`manifest_id`, and `run_manifest_hash`. The v3 value matches the current
`MODEL_PILOT_V1.json`, `PILOT_CONFIG_V1.json`, and `app/core/pilot.py`; v2 is a
stale sibling and must not be selected implicitly.

The ignored `runs/pilot/` tree also contains older prepared manifests such as
`prepared-from-pilot-r2`, `prepared-from-pilot-r2-v2`, and `prepared-final`
whose task version is `1.0.0`, whose benchmark identity is empty or only
`PILOT-R2`, and whose rubric reference is absent. These are operational
selection hazards, not evidence that the checked-in benchmark was changed.

## TEST_RUNTIME REVIEW:

### Current file and localization change surface

`tests/test_runtime.py` currently has 1,367 lines and 59 unittest-style
`test_...` method declarations. Its classes cover runtime flow, graph/RAG,
provider diagnostics, API contracts, V6 regressions, and frontend contracts.
The clearly localization-specific addition is:

- `FrontendV6Tests.test_vietnamese_ui_localization_keeps_runtime_identifiers_intact`
  at `tests/test_runtime.py:1348-1362`.

That test checks Vietnamese labels, the `UI_TEXT` map, raw
`DIRECT`/`PARALLEL`/`PLANNED`/`PASS`/`FAIL`/`NEEDS_WORK` values, and
`JSON.stringify(rawEvents...)`. It validates UI translation and preservation of
selected runtime values; it does not define or change research expectations.

`V06RegressionTests.test_config_lists_dev_providers_without_exposing_keys` at
`tests/test_runtime.py:1154` is a separate provider/configuration regression,
not a localization test. It should not be attributed to the UI workstream.

The current `test_runtime.py` contains no `PILOT-R2`, benchmark, rubric,
`research_annotations`, expected-source-fact, or task-manifest references.
Its existing assertions still cover route semantics, Fixed/Static behavior,
retry accounting, budgets, snapshots, provider safety, and resource metrics.
No weakened research assertion was observed in the current content.

### Test ownership and disappearance check

There is no ownership record, so whether a test was modified outside its
assigned chat cannot be proven. The shared `test_runtime.py` file mixes core
runtime and UI tests, making it a collision point. Pilot tests are separated
into `tests/test_pilot.py` and `tests/test_pilot_executor.py`; no Pilot-specific
content was observed in `test_runtime.py`.

Static declaration counts at the audit snapshot are:

| File | Declared test methods |
| --- | ---: |
| `tests/test_runtime.py` | 59 |
| `tests/test_pilot.py` | 10 |
| `tests/test_pilot_executor.py` | 12 |
| Total | 81 |

`docs/TEST_MATRIX.md` contains 72 unique direct `Class.test_method`
references, and all 72 resolve to current declarations. Nine current methods
are not individually referenced there:

```text
FrontendV6Tests.test_vietnamese_ui_localization_keeps_runtime_identifiers_intact
PilotExecutorTests.test_benchmark_scope_includes_declared_sections_and_excludes_undeclared
PilotExecutorTests.test_explicit_whole_document_binding_is_the_only_full_document_path
PilotExecutorTests.test_invalid_declared_section_fails_closed
PilotExecutorTests.test_scoped_snapshot_is_shared_by_all_four_strategies
PilotExecutorTests.test_source_id_without_binding_cannot_use_inline_context_as_whole_document
PilotManifestTests.test_authorization_snapshots_and_denominator_rules_are_frozen
PilotManifestTests.test_manifest_uses_one_authoritative_benchmark_identity
V06RegressionTests.test_config_lists_dev_providers_without_exposing_keys
```

The frozen `corpus/pilot/v1/TEST_MATRIX.md` has 57 direct references; all 57
still resolve. This is positive evidence that no named test in the frozen
matrix disappeared. It is not proof that an unreferenced test was never
removed.

The apparent progression is not a valid pass criterion by itself:

- `TEST_REPORT_V5.md` records historical 26/26.
- `docs/ORCHESTRATION_AUDIT.md` and `docs/PILOT_PREREGISTRATION.md` record
  historical 58/58.
- `docs/CURRENT_STATE.md` and `docs/TEST_MATRIX.md` claim 73/73.
- The current source declares 81 methods, with nine not individually mapped.

The Python unittest command was not executed in this audit because
`.venv\Scripts\python.exe` returned Access Denied and no system Python was
available. Therefore 81 is a static declaration count, not a passing count.
`node --check app/static/app.js` passed, and read-only JSON parsing passed for
the seven benchmark/config/schema files.

## RESEARCH ARTIFACT INTEGRITY:

### Frozen corpus and benchmark/rubric binding

All six files declared by `corpus/pilot/v1/CORPUS_MANIFEST.json` match their
declared line counts and SHA-256 values:

| Source | Lines | SHA-256 prefix |
| --- | ---: | --- |
| `contract-v0.6.3` | 130 | `42cfbe2f...` |
| `state-v6.3` | 163 | `91c28933...` |
| `audit-v6.3` | 476 | `67c6676a...` |
| `matrix-v0.6.3` | 92 | `5deafd5b...` |
| `fixes-v0.6` | 87 | `40ff37df...` |
| `readme-v0.6` | 82 | `a9caf7c5...` |

The following static checks passed:

- `pilot_benchmark_v1@1.1.0` has 8 tasks and 8 research annotations.
- Its 25 source bindings and 51 section references resolve against the frozen
  corpus with zero bad source/hash/section matches.
- The benchmark's declared canonical artifact hash is
  `18c1941c4f057f85160634bba334866795aa06b5746e9107cbe902c1f73ba706`.
  The canonical JSON self-hash check passes; the raw-file SHA differs because
  the declared hash excludes the self-referential `artifact_sha256` field.
- The rubric artifact has 8 bound tasks, 36 mandatory criteria, 16 critical
  error definitions, and 8 optional criteria. All eight rubric task wording
  hashes match the corresponding benchmark task text hashes.
- The rubric benchmark binding points to the same canonical benchmark hash,
  and the benchmark points to the same corpus-manifest hash.

### Living documents versus frozen answer sources

The current living files are intentionally not byte-identical to the frozen
corpus:

- `docs/PROJECT_CONTRACT.md`: 152 lines versus frozen 130. The current added
  Multi-Agent/Multi-Model section shifts `Runtime structural signals` from
  line 49 in the frozen source to line 69 in the living source.
- `docs/CURRENT_STATE.md`: 210 versus frozen 163 lines.
- `docs/TEST_MATRIX.md`: 108 versus frozen 92 lines.
- `README.md`: 117 versus frozen 82 lines.
- `docs/ORCHESTRATION_AUDIT.md` and `AUDIT_FIXES.md` still match their frozen
  copies exactly.

`docs/PILOT_BENCHMARK_NOTES.md:28-61` explicitly records this rebind and says
that the frozen copies are the answer-source paths. The Pilot executor also
checks source hashes and section bindings before constructing runtime context.
Thus no frozen research file was modified by the UI/localization or
terminology work observed here. The integration gate must nevertheless use
`corpus/pilot/v1/`, never substitute current living documents by path.

The UI files contain no benchmark, rubric, corpus-manifest, or research-only
annotation strings. The current run scan found 192 parseable JSON files, 30
phase-tagged records, and zero records with both `phase=PILOT` and
`research_evidence=true`. Existing DRY_RUN/PREFLIGHT/Fake artifacts are not
Pilot research evidence.

## INTERNAL IDENTIFIERS:

Static result: PASS for observed preservation, with a test-coverage caveat.

- `docs/PROJECT_CONTRACT.md:14-32` and `docs/TERMINOLOGY_VI.md:5-15,20-63`
  consistently define a homogeneous Multi-Agent experiment with one fixed
  Provider/Model/settings block. The Orchestrator is the policy/controller
  layer, not an extra LLM role.
- `docs/PROJECT_CONTRACT.md:138-145` and
  `docs/TERMINOLOGY_VI.md:135-141` distinguish Agent Execution, Logical Model
  Call, and Physical Provider Request. Runtime code uses the corresponding
  `agent_executions`, `logical_calls`, and `physical_requests` fields.
- `app/static/app.js:10-110` localizes through `UI_TEXT`, `modeText`,
  `strategyText`, `statusText`, and display-only role/event functions. Raw
  values remain keys and raw events remain serialized as raw events.
- The UI still uses raw modes `DIRECT`, `PARALLEL`, `PLANNED`, and `AUTO`, raw
  strategies `single`, `fixed`, `static`, and `adaptive`, and the existing
  status/stop values. Existing local-storage keys and API JSON fields were not
  translated.
- A search of `app/static/` found no `MODEL-*`, `RAG-*`, `ORCH-*`, `FIXED-*`,
  `STATIC-*`, `PRICE-*`, `PILOT-*`, or `pilot_benchmark_v1` identifiers. This
  is expected: config IDs and benchmark IDs are not UI vocabulary.

The localization test does not enumerate every JSON field/config ID, so it is
not sufficient by itself to prove the whole boundary. The source inspection
found no rename. The UI also uses shorter English parentheticals `Logical
Calls` and `Physical Requests`, and maps `Runtime Verifier` to the display
label `Verifier`; these are terminology-precision issues, not internal-ID
changes.

## VERSION/IDENTITY CONFLICTS:

### Internally aligned current identity chain

The current checked-in/configured chain is coherent:

```text
application 0.6.3 / V6.3
preregistration design PILOT-R1
benchmark pilot_benchmark_v1@1.1.0
benchmark provenance label PILOT-R2 (not a second benchmark identity)
corpus PILOT-CORPUS-V1
quality protocol QEP-1.1
rubric PILOT-RUBRIC-V1.0
execution control PILOT-R4-V1 / PILOT-EXECUTION-INFRA-V1@1.0
provider Groq / model openai/gpt-oss-120b
limits GROQ-PILOT-LIMITS-V1: RPM 30, RPD 1000, TPM 8000, TPD 200000
pricing PRICE-PILOT-V1@1.1
```

The current Pilot config, model snapshot, price snapshot, provider-limits
document, preflight record, benchmark, rubric, and latest v3 prepared manifest
agree on the provider/model, benchmark/rubric/corpus identities, request
settings, limits, and price values. The protocol correctly says the current
Compare endpoint's fixed order is not the live Pilot order.

### Conflicts requiring explicit reconciliation

1. `benchmarks/pilot/pilot_benchmark_v1.json:27` declares design-reference
   SHA-256 `b3ac71e7...` for `docs/PILOT_PREREGISTRATION.md`, while the current
   file hashes to `c8d6b1f5...`. `docs/PILOT_BENCHMARK_NOTES.md:63-65` says the
   preregistration is design-only and not an answer source, which limits the
   data risk, but the provenance declaration is still not reproducible.

2. `docs/PILOT_PREREGISTRATION.md:13` and
   `docs/ORCHESTRATION_AUDIT.md:474-476` retain 58/58 claims; current living
   state/matrix documents retain 73/73 claims; current source declares 81
   methods. `docs/CURRENT_STATE.md:136` also says there are seven executor
   checks while the current executor test file declares 12. This is an
   unresolved evidence/version accounting conflict.

3. The prepared-manifest generations are not interchangeable. The v2-to-v3
   change in `store` status changed the manifest hash/ID. Older `runs/pilot`
   manifests still carry `PILOT-R2`/1.0.0-era identities, while v3 carries the
   current canonical identity. The generated tree has duplicate IDs, including
   v1/v2/v3-era copies; selection must be explicit.

4. The root living contract/state/matrix/README differ from their frozen
   corpus copies. This is documented drift, not accidental frozen-artifact
   mutation, but the line-range shift makes using a living path in place of a
   frozen path a research-validity risk.

5. Ordinary runtime defaults in `app/main.py:102-113` and
   `app/core/types.py:33-42` use a 45-second call timeout and 60-second retry
   maximum, while the Pilot identity is 60 seconds and 30 seconds. This is
   intentional for the Pilot because `app/core/pilot_executor.py:570-584`
   passes the manifest budget/settings explicitly, but the distinction must be
   preserved in the final operator instructions.

6. `PILOT_CONFIG_V1.json:7-16` lists runtime source files but omits the
   dedicated `app/core/pilot_executor.py` and `scripts/pilot_harness.py` even
   though the execution protocol treats them as the control plane. This is a
   source-of-truth documentation gap, not evidence of changed research data.

## P0:

None observed in the static audit.

Specifically, no rubric leakage into the UI or `tests/test_runtime.py`, no
frozen corpus hash failure, no benchmark/rubric binding failure, no UI rename
of config/benchmark IDs, and no live `phase=PILOT` research evidence were
found. This does not replace the unavailable Python regression run, live
provider check, or final account/integration gate.

## P1:

1. Quiesce all other chats and take a new immutable checkout snapshot. Obtain
   a real Git commit/patch baseline before accepting any overwrite/revert
   conclusion; rerun this conflict audit after the late Pilot writes stop.
2. Reconcile the test inventory: run the exact 81-method suite when the
   project interpreter is available, reconcile the 73/58/26 historical claims,
   map the nine currently unlisted methods, and report pass counts separately
   from declaration counts. Do not accept a count increase as coverage proof.
3. Select one prepared manifest generated from the final current source/config
   and validate it. The latest observed candidate is
   `runs/pilot/taskc-final-manifest-v3.json`; it is only a candidate until
   revalidated after quiescence. Do not select v2 or the older R2/1.0.0
   manifests by directory order.
4. Reconcile the benchmark design-reference hash: either preserve an
   immutable R1 reference copy or record a versioned/amended reference. Do not
   silently replace the declared hash with the current mutable preregistration.
5. Confirm that all runtime source resolution uses the frozen corpus paths and
   hashes. Treat any use of current `docs/PROJECT_CONTRACT.md` or
   `docs/CURRENT_STATE.md` for Pilot answer context as a fail-closed condition.
6. Obtain one final owner decision on the R1/R2/R4/QEP identity chain and close
   the preregistration open decisions at `docs/PILOT_PREREGISTRATION.md:440-449`.
7. Re-run the independent red-team P1 gates already recorded in
   `docs/PRE_PILOT_RED_TEAM_AUDIT.md`, including context completeness,
   evaluator denominator/missingness, E2E timing, aggregate pacing/rate limits,
   raw-error/incident handling, and ledger consistency. These remain Pilot
   gates even though they were not caused by localization.

## P2:

- Make the living `docs/TEST_MATRIX.md` enumerate or deliberately group all
  current Pilot/UI tests; annotate the historical 58/58 and 73/73 scopes.
- Keep one operator-visible canonical prepared-manifest path and mark old
  generated copies as stale/quarantined without deleting raw evidence.
- Align UI parentheticals with the exact canonical metric terms, or explicitly
  document the shorter display aliases. Preserve `Runtime Verifier` when that
  distinction matters to an evidence view.
- Add `app/core/pilot_executor.py` and `scripts/pilot_harness.py` to the
  documented Pilot control-plane source list.
- Document that ordinary chat/Compare budgets are not the Pilot budget
  snapshot. Keep historical `TEST_REPORT_V5.md` clearly historical.
- Consider stricter manifest-schema validation; the current schema's
  permissiveness was noted by the red-team audit and is not a localization
  issue.

## P3:

- Establish a Git baseline and per-workstream branch/commit convention before
  future parallel changes.
- Add a small ownership/change manifest for shared files, especially
  `tests/test_runtime.py`, `docs/CURRENT_STATE.md`, `docs/TEST_MATRIX.md`, and
  Pilot control/config documents.
- Add held-out/non-self-referential task families and larger Main repeats only
  after the current Pilot validity gates are closed.

## FILES REQUIRING INTEGRATION REVIEW:

- Shared semantics and terminology: `docs/PROJECT_CONTRACT.md`,
  `docs/TERMINOLOGY_VI.md`.
- Living evidence/accounting: `docs/CURRENT_STATE.md`, `docs/TEST_MATRIX.md`,
  `docs/ORCHESTRATION_AUDIT.md`, `docs/PILOT_PREREGISTRATION.md`.
- Pilot protocol/gates: `docs/PILOT_EXECUTION_PROTOCOL.md`,
  `docs/QUALITY_EVALUATION_PROTOCOL.md`, `docs/PRE_PILOT_RED_TEAM_AUDIT.md`,
  `docs/PILOT_PROVIDER_LIMITS.md`, `docs/GROQ_PILOT_PREFLIGHT.md`.
- Pilot implementation: `app/core/pilot.py`, `app/core/pilot_executor.py`,
  `scripts/pilot_harness.py`, `app/main.py`,
  `app/core/orchestrator.py`, `app/core/types.py`.
- Pilot config/identities: `config/pilot/PILOT_CONFIG_V1.json`,
  `config/pilot/MODEL_PILOT_V1.json`, `config/pilot/PRICE_PILOT_V1.json`,
  `config/pilot/PILOT_RUN_MANIFEST_SCHEMA_V1.json`.
- Frozen research artifacts: `benchmarks/pilot/pilot_benchmark_v1.json`,
  `evaluation/pilot/pilot_rubrics_v1.json`,
  `corpus/pilot/v1/CORPUS_MANIFEST.json`, and every frozen corpus file. These
  require one artifact owner and must not be edited in place.
- UI/shared test surface: `app/static/index.html`, `app/static/app.js`,
  `tests/test_runtime.py`, `tests/test_pilot.py`,
  `tests/test_pilot_executor.py`.
- Generated evidence selection: `runs/pilot/**`. These are ignored/generated,
  not source artifacts, but their canonical/stale distinction must be explicit.

## RECOMMENDED AUTHORITATIVE OWNER:

Assign one named Final Integration/Gate owner for the quiescent snapshot,
identity reconciliation, test-count reconciliation, manifest selection, and
Pilot authorization decision. Parallel chats should stop writing before that
owner accepts the tree.

Recommended domain ownership beneath that gate:

- Research semantics and terminology: one owner for `PROJECT_CONTRACT` and
  `TERMINOLOGY_VI`; any semantic change requires a new frozen corpus/version
  decision.
- Implementation facts and coverage accounting: one owner for `CURRENT_STATE`
  and `TEST_MATRIX`.
- UI localization: one UI owner for `app/static/*` and its explicitly mapped
  frontend tests; changes must preserve raw API/event identifiers.
- Pilot execution: one control-plane owner for `app/core/pilot.py`,
  `pilot_executor.py`, `scripts/pilot_harness.py`, the Pilot config, limits,
  and execution protocol.
- Research artifacts/evaluation: one artifact owner for the benchmark, rubric,
  frozen corpus, and manifest bindings; no UI or execution chat may edit them.
- Generated evidence: one integration operator chooses the accepted prepared
  manifest and distinguishes DRY_RUN/PREFLIGHT from research evidence.

## FILES CREATED:

Only this report was created by this audit:

`docs/PARALLEL_INTEGRATION_AUDIT.md`

No source, configuration, benchmark, rubric, corpus, manifest, or test file was
modified by this audit.

## HANDOFF TO FINAL INTEGRATION:

Do not start the live 96-condition Pilot from the current shared checkout.
First stop/quiesce the other chats, capture a real baseline, revalidate the
current v3-or-later manifest against the final source/config, reconcile the
test inventory and preregistration design-reference hash, and confirm the
frozen corpus path/hash boundary. Then perform the account, pacing, evaluator,
missingness, raw-evidence, and ledger gates from the red-team/protocol audits.

The observed generated artifacts are preparation/control evidence only. No
live Pilot research evidence was found in the scan. This report authorizes no
provider call, no artifact mutation, and no final Integration Gate acceptance.

STOP.

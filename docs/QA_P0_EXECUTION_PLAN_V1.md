# QA P0 Execution Plan V1

## Boundary

This plan is derived only from the P0 rows marked PARTIAL or MISSING in docs/QA_COVERAGE_MATRIX_V1.md. It contains exactly 21 scenarios: 10 MISSING and 11 PARTIAL. It is an execution map, not an authorization to change code during this audit. Existing tests are read-only baselines; no provider, browser, Research/Pilot, benchmark, dependency installation, or git-history work is included.

PROD_FIX_REQUIRED is a conditional outcome: a production fix is allowed only inside the owning track if its new focused test/evaluation demonstrates a defect. A missing test alone is TEST_ONLY.

## 1. Exact P0 gaps

| Scenario | Status | Existing test | Exact gap | Work type |
| -------- | ------ | ------------- | --------- | --------- |
| CHAT-003 | MISSING | — | No empty/blank prompt test proves the request is blocked before any provider call. | TEST_ONLY |
| CFG-003 | PARTIAL | tests/test_product_wiring.py::ProductEndpointIsolationTests.test_product_mode_and_model_reach_executor_without_live_provider | Offline OpenAI propagation exists, but no end-to-end Groq/model selection evidence proves the named pair reaches the backend. | MANUAL_E2E |
| CFG-004 | MISSING | — | No test drives provider-then-model changes and proves only the final selection executes. | MANUAL_E2E |
| CFG-005 | MISSING | — | No test drives model changes within one provider and proves only the final model executes. | MANUAL_E2E |
| CTX-003 | MISSING | — | No exact 100000-byte boundary test distinguishes accepted-at-limit from rejected-over-limit behavior. | TEST_ONLY |
| GND-001 | PARTIAL | tests/test_runtime.py::RuntimeFlowTests.test_fake_worker_output_does_not_leak_internal_prefix; tests/test_product_qa.py::ProductQATests.test_fake_chat_contract_persists_conversation_and_frozen_provenance | A Fake answer contains a supplied fact, but no evaluator checks fact correctness and supporting source attribution together. | LLM_EVAL |
| GND-002 | MISSING | — | No missing-file trap verifies abstention without inventing a path. | LLM_EVAL |
| GND-003 | MISSING | — | No absent-DB trap verifies abstention when a fixture has no MySQL/PostgreSQL evidence. | LLM_EVAL |
| GND-004 | MISSING | — | No absent-auth trap verifies that middleware/file names are not fabricated. | LLM_EVAL |
| GND-005 | MISSING | — | No fabricated-route premise test verifies correction rather than confirmation. | LLM_EVAL |
| GND-006 | PARTIAL | tests/test_context_v1.py::ContextProductFlowTests.test_prepared_content_reaches_normal_product_execution_and_source_identity | Source identity is transported, but no evaluator proves the cited source semantically supports the answer claim. | LLM_EVAL |
| GND-007 | MISSING | — | No unsupported-inference trap tests that Flask evidence does not imply a database. | LLM_EVAL |
| ROUTE-002 | PARTIAL | tests/test_project_workspace_v12.py::ProjectWorkspaceRuntimeContractTests.test_relevance_gate_keeps_greetings_general_chat_and_auto_separate | The arithmetic prompt is classified as non-project, but the complete AUTO execution route is not asserted as DIRECT. | TEST_ONLY |
| PERSIST-002 | PARTIAL | tests/test_product_persistence.py::ProductConversationPersistenceTests.test_create_store_message_and_reopen_preserves_identity_and_fields | API reopen and a fresh repository view are covered, but browser refresh state is not. | MANUAL_E2E |
| PERSIST-003 | PARTIAL | tests/test_product_persistence.py::ProductConversationPersistenceTests.test_list_rename_search_delete_and_unrelated_run_survival | API deletion and 404 are covered, but the active UI transition to New Chat is not. | MANUAL_E2E |
| ERR-001 | PARTIAL | tests/test_runtime.py::RuntimeFlowTests.test_timeout_stops_failed_run; tests/test_runtime.py::ApiContractTests.test_fatal_stream_has_conversation_metadata_and_persists_failed_turn | Timeout terminal state and failed persistence are separate checks; no single case proves bounded timeout plus continued conversation usability. | TEST_ONLY |
| ERR-002 | PARTIAL | tests/test_runtime.py::ApiContractTests.test_fatal_stream_has_conversation_metadata_and_persists_failed_turn | Provider failure yields a terminal fatal/persisted turn, but no mid-stream disconnect test covers UI exit and partial state. | MANUAL_E2E |
| PERF-001 | PARTIAL | tests/test_runtime.py::RuntimeFlowTests.test_all_strategies_use_the_same_e2e_boundary_contract | One-run E2E timing exists, but repeated Simple DIRECT Fake measurements and p50/p95 reporting are absent. | PERFORMANCE |
| SEC-003 | MISSING | — | No indirect prompt-injection-in-source evaluation verifies source text is treated as data. | LLM_EVAL |
| SEC-005 | PARTIAL | tests/test_runtime.py::RuntimeFlowTests.test_fake_answers_current_task_without_history_or_context_contamination | Current task is separated from unrelated context, but explicit system/product-constraint override protection is not tested. | LLM_EVAL |
| UI-001 | PARTIAL | tests/test_product_qa.py::ProductQATests.test_fake_chat_contract_persists_conversation_and_frozen_provenance; tests/test_product_wiring.py::ProductEndpointIsolationTests.test_product_mode_and_model_reach_executor_without_live_provider | Offline valid-send and propagation checks exist, but browser send with the selected Groq/model and stale-config behavior are unverified. | MANUAL_E2E |

## 2. Ownership matrix

Each production file appears in exactly one track below. Existing tests named in section 1 remain read-only; dedicated test owners are proposed for the implementation wave.

| Scenario | Likely production owner | Likely test owner | Dependency |
| -------- | ----------------------- | ----------------- | ---------- |
| CHAT-003 | app/main.py: ChatRequest.message | tests/test_qa_p0_product_boundary.py | None; preserve current min_length contract |
| CFG-003 | app/main.py: validated_model, execute_once, chat; app/static/app.js: runChat | tests/test_qa_p0_product_e2e.py | Current catalog/config contract |
| CFG-004 | app/static/app.js: renderModelPicker, selectedModel, runChat; app/main.py: chat | tests/test_qa_p0_product_e2e.py | CFG-003 selection/evidence contract |
| CFG-005 | app/static/app.js: renderModelPicker, selectedModel, runChat; app/main.py: chat | tests/test_qa_p0_product_e2e.py | CFG-003 selection/evidence contract |
| CTX-003 | app/core/context_files.py: MAX_CONTEXT_FILE_BYTES, prepare_context_file | tests/test_qa_p0_context_boundary.py | None |
| GND-001 | app/core/orchestrator.py: prompt, verify; app/core/rag.py: frozen_snapshot | tests/test_qa_p0_grounding_eval.py | Frozen fixture and source identity |
| GND-002 | app/core/orchestrator.py: prompt, verify | tests/test_qa_p0_grounding_eval.py | Golden missing-file fixture |
| GND-003 | app/core/orchestrator.py: prompt, verify | tests/test_qa_p0_grounding_eval.py | Golden no-DB fixture |
| GND-004 | app/core/orchestrator.py: prompt, verify | tests/test_qa_p0_grounding_eval.py | Golden no-auth fixture |
| GND-005 | app/core/orchestrator.py: prompt, verify | tests/test_qa_p0_grounding_eval.py | Fabricated-route premise fixture |
| GND-006 | app/core/orchestrator.py: verify; app/core/rag.py: frozen_snapshot | tests/test_qa_p0_grounding_eval.py | Source-attribution oracle |
| GND-007 | app/core/orchestrator.py: prompt, verify | tests/test_qa_p0_grounding_eval.py | Flask-without-DB fixture |
| ROUTE-002 | app/core/orchestrator.py: product_auto_fast_path, choose_product_mode | tests/test_qa_p0_routing.py | None; offline deterministic route |
| PERSIST-002 | app/core/conversation_repository.py: read; app/main.py: get_conversation; app/static/app.js: loadConversation | tests/test_qa_p0_product_e2e.py | Completed conversation fixture |
| PERSIST-003 | app/core/conversation_repository.py: delete; app/main.py: delete_conversation; app/static/app.js: confirmDeleteConversation, newConversation | tests/test_qa_p0_product_e2e.py | Active conversation fixture |
| ERR-001 | app/core/orchestrator.py: _call, run | tests/test_qa_p0_reliability.py | Bounded timeout budget |
| ERR-002 | app/main.py: chat generator/StreamingResponse; app/static/app.js: runChat | tests/test_qa_p0_product_e2e.py | Stream interruption harness |
| PERF-001 | app/core/orchestrator.py: metrics, _call | tests/test_qa_p0_performance.py | Fake DIRECT measurement protocol |
| SEC-003 | app/core/orchestrator.py: prompt, verify | tests/test_qa_p0_grounding_eval.py | Injection fixture and non-compliance oracle |
| SEC-005 | app/core/orchestrator.py: prompt, verify | tests/test_qa_p0_grounding_eval.py | Product/system constraint oracle |
| UI-001 | app/main.py: validated_model, chat; app/static/app.js: runChat, renderModelPicker | tests/test_qa_p0_product_e2e.py | CFG-003 and current model catalog |

## 3. Conflict matrix

CG-PRODUCT-UI owns app/main.py, app/static/app.js and app/core/conversation_repository.py. CG-CONTEXT owns app/core/context_files.py. CG-RAG-ORCH owns app/core/rag.py and app/core/orchestrator.py. No two tracks may modify the same conflict group or any existing shared test file; dedicated test files keep the proposed work isolated.

| Scenario | Production owner | Test owner | Conflict group |
| -------- | ---------------- | ---------- | -------------- |
| CHAT-003 | app/main.py: ChatRequest.message | tests/test_qa_p0_product_boundary.py | CG-PRODUCT-UI |
| CFG-003 | app/main.py: validated_model/execute_once/chat; app/static/app.js: runChat | tests/test_qa_p0_product_e2e.py | CG-PRODUCT-UI |
| CFG-004 | app/static/app.js: renderModelPicker/selectedModel/runChat; app/main.py: chat | tests/test_qa_p0_product_e2e.py | CG-PRODUCT-UI |
| CFG-005 | app/static/app.js: renderModelPicker/selectedModel/runChat; app/main.py: chat | tests/test_qa_p0_product_e2e.py | CG-PRODUCT-UI |
| CTX-003 | app/core/context_files.py: MAX_CONTEXT_FILE_BYTES/prepare_context_file | tests/test_qa_p0_context_boundary.py | CG-CONTEXT |
| GND-001 | app/core/orchestrator.py: prompt/verify; app/core/rag.py: frozen_snapshot | tests/test_qa_p0_grounding_eval.py | CG-RAG-ORCH |
| GND-002 | app/core/orchestrator.py: prompt/verify | tests/test_qa_p0_grounding_eval.py | CG-RAG-ORCH |
| GND-003 | app/core/orchestrator.py: prompt/verify | tests/test_qa_p0_grounding_eval.py | CG-RAG-ORCH |
| GND-004 | app/core/orchestrator.py: prompt/verify | tests/test_qa_p0_grounding_eval.py | CG-RAG-ORCH |
| GND-005 | app/core/orchestrator.py: prompt/verify | tests/test_qa_p0_grounding_eval.py | CG-RAG-ORCH |
| GND-006 | app/core/orchestrator.py: verify; app/core/rag.py: frozen_snapshot | tests/test_qa_p0_grounding_eval.py | CG-RAG-ORCH |
| GND-007 | app/core/orchestrator.py: prompt/verify | tests/test_qa_p0_grounding_eval.py | CG-RAG-ORCH |
| ROUTE-002 | app/core/orchestrator.py: product_auto_fast_path/choose_product_mode | tests/test_qa_p0_routing.py | CG-RAG-ORCH |
| PERSIST-002 | app/core/conversation_repository.py: read; app/main.py: get_conversation; app/static/app.js: loadConversation | tests/test_qa_p0_product_e2e.py | CG-PRODUCT-UI |
| PERSIST-003 | app/core/conversation_repository.py: delete; app/main.py: delete_conversation; app/static/app.js: confirmDeleteConversation/newConversation | tests/test_qa_p0_product_e2e.py | CG-PRODUCT-UI |
| ERR-001 | app/core/orchestrator.py: _call/run | tests/test_qa_p0_reliability.py | CG-RAG-ORCH |
| ERR-002 | app/main.py: chat generator; app/static/app.js: runChat | tests/test_qa_p0_product_e2e.py | CG-PRODUCT-UI |
| PERF-001 | app/core/orchestrator.py: metrics/_call | tests/test_qa_p0_performance.py | CG-RAG-ORCH |
| SEC-003 | app/core/orchestrator.py: prompt/verify | tests/test_qa_p0_grounding_eval.py | CG-RAG-ORCH |
| SEC-005 | app/core/orchestrator.py: prompt/verify | tests/test_qa_p0_grounding_eval.py | CG-RAG-ORCH |
| UI-001 | app/main.py: validated_model/chat; app/static/app.js: runChat/renderModelPicker | tests/test_qa_p0_product_e2e.py | CG-PRODUCT-UI |

Conflict rule: scenarios in CG-PRODUCT-UI must stay in TRACK-PRODUCT-BOUNDARY; scenarios in CG-RAG-ORCH must stay in TRACK-CORE-QUALITY; CTX-003 is the sole CG-CONTEXT owner. CG-INDEPENDENT is unused because every gap has a concrete owner or shared runtime dependency.

## 4. Parallel tracks

### TRACK-CONTEXT-P0

P0 scenarios: CTX-003.

Goal: add the exact-at-limit byte boundary evidence without changing the context contract.

Production files owned: app/core/context_files.py only.

Test files owned: tests/test_qa_p0_context_boundary.py only. Existing tests/test_context_v1.py is read-only baseline.

Read-only files: docs/QA_COVERAGE_MATRIX_V1.md, Adaptive_Agent_QA_Master_Plan_V1.md, adaptive_agent_qa_scenarios_v1.json, app/main.py endpoint shape, existing context fixtures/tests.

Forbidden files: app/main.py changes, app/static/*, app/core/orchestrator.py, app/core/rag.py, app/core/conversation_repository.py, app/providers/*, tests/test_runtime.py edits, Research/Pilot/benchmark/evaluation artifacts, dependency or config changes.

Dependency: none.

Can run parallel with: TRACK-CORE-QUALITY-P0 during Wave 1.

Must not run parallel with: any other track claiming app/core/context_files.py or tests/test_qa_p0_context_boundary.py.

Expected output: one focused accepted-at-100000 and rejected-at-100001 test; PROD_FIX_REQUIRED only if the boundary test exposes a defect.

Recommended test tier: T0 focused unit.

### TRACK-CORE-QUALITY-P0

P0 scenarios: GND-001, GND-002, GND-003, GND-004, GND-005, GND-006, GND-007, ROUTE-002, ERR-001, PERF-001, SEC-003, SEC-005.

Goal: close grounding, unsupported-inference, route, timeout, security-instruction and baseline-performance evidence around the shared orchestrator/RAG core.

Production files owned: app/core/orchestrator.py and app/core/rag.py only.

Test files owned: tests/test_qa_p0_grounding_eval.py, tests/test_qa_p0_routing.py, tests/test_qa_p0_reliability.py and tests/test_qa_p0_performance.py. Existing tests/test_runtime.py and tests/test_project_understanding_v11.py are read-only baselines.

Read-only files: QA matrix/pack, tests/fixtures/v11_projects, tests/fixtures/v11_evaluation/cases.json, app/main.py call boundary, app/providers/fake.py behavior. No live provider is part of this plan.

Forbidden files: app/main.py, app/static/*, app/core/context_files.py, app/core/conversation_repository.py, app/providers/* modifications, product UI changes, Research/Pilot/benchmark/evaluation outputs, dependency changes and opportunistic prompt/router refactors.

Dependency: none for deterministic scaffolding; use frozen local fixtures and Fake/Scripted doubles only.

Can run parallel with: TRACK-CONTEXT-P0 during Wave 1.

Must not run parallel with: any other track claiming app/core/orchestrator.py, app/core/rag.py or the four dedicated core test files.

Expected output: explicit missing-evidence/source-attribution evaluations, arithmetic DIRECT assertion, timeout usability case and a repeated DIRECT Fake p50/p95 harness; any behavior defect is handed to this same track.

Recommended test tier: T1 deterministic plus LLM_EVAL and PERFORMANCE review; no live calls in this audit.

### TRACK-PRODUCT-BOUNDARY-P0

P0 scenarios: CHAT-003, CFG-003, CFG-004, CFG-005, PERSIST-002, PERSIST-003, ERR-002, UI-001.

Goal: prove request validation, final provider/model selection, persistence/reload/delete UI transitions, stream interruption handling and truthful selected-model UI evidence.

Production files owned: app/main.py, app/static/app.js and app/core/conversation_repository.py only.

Test files owned: tests/test_qa_p0_product_boundary.py and tests/test_qa_p0_product_e2e.py. Existing tests/test_product_wiring.py, tests/test_product_persistence.py, tests/test_runtime.py and tests/test_product_qa.py are read-only baselines.

Read-only files: QA matrix/pack, current model catalog/config, existing persistence fixtures, provider Fake/Scripted doubles and static UI contracts.

Forbidden files: app/core/context_files.py, app/core/rag.py, app/core/orchestrator.py, app/providers/*, tests/test_runtime.py edits, Research/Pilot/benchmark/evaluation artifacts, asset-version/UI redesign, dependency changes and unrelated API refactors.

Dependency: unit/API phase may be prepared independently; browser/manual phase consumes the stable catalog and persistence contracts handed off by Wave 1.

Can run parallel with: Wave 1 track work only for non-overlapping read-only preparation; production edits and manual E2E are scheduled in Wave 2.

Must not run parallel with: any other track claiming app/main.py, app/static/app.js, app/core/conversation_repository.py or either dedicated product test file.

Expected output: empty-prompt, final-selection and persistence/API focused evidence plus a manual E2E checklist for UI/model and stream cases; no live Groq call is authorized by this audit.

Recommended test tier: T0 focused API/static, then T1 MANUAL_E2E under a separate approved execution.

## 5. Waves

### WAVE 1 — independent contract work

Run TRACK-CONTEXT-P0 and TRACK-CORE-QUALITY-P0 in parallel. They have disjoint production files and disjoint dedicated test files. Work is limited to deterministic scaffolding, fixture/evaluator design and focused boundary evidence; no integration run, browser session or provider call belongs here.

### WAVE 2 — shared product boundary work

Run TRACK-PRODUCT-BOUNDARY-P0 after the Wave 1 handoff. Keep all app/main.py, app/static/app.js and conversation_repository changes serialized inside this one owner track. The manual UI/persistence/stream portions remain gated until an approved environment exists.

### WAVE 3 — integration and P0 regression

A single integration owner reconciles the three track outputs and runs the 21-scenario P0 regression as one serial gate. Verify no dedicated test file or production owner was claimed twice, then evaluate the LLM and performance artifacts against the matrix. Integration is deliberately not in Wave 1. This audit does not execute that gate.

## 6. Dependency graph

TRACK-CONTEXT-P0 ─────┐
                      ├──> TRACK-PRODUCT-BOUNDARY-P0 ───> WAVE-3-P0-INTEGRATION
TRACK-CORE-QUALITY-P0 ┘

The arrow is a handoff/serialization guard, not a production-code dependency: the product track may prepare its unit tests independently, but its shared-file and manual-E2E phase waits for the two Wave 1 owners to publish their focused results. WAVE-3 is serial and owns no production file.

## 7. Recommended execution order

1. Freeze the 21-row scope from the current matrix and quiesce other writers.
2. Execute the context boundary and core-quality planning/implementation tracks in parallel, each using only its owned files.
3. Review each track's diff for incidental changes; report, do not absorb, unrelated findings.
4. Hand off the Wave 1 evidence and run TRACK-PRODUCT-BOUNDARY-P0 as the sole owner of the product/UI files.
5. Assemble the integration manifest, then run the serial WAVE-3 P0 regression and classify any discovered defect as TEST_ONLY, PROD_FIX_REQUIRED, LLM_EVAL, MANUAL_E2E or PERFORMANCE within its existing track.
6. Stop after the P0 gate report; do not merge Research/Pilot, benchmark, rate-limit or unrelated refactors.

P0 GAP TOTAL: 21
TRACK TOTAL: 3
WAVE 1: TRACK-CONTEXT-P0, TRACK-CORE-QUALITY-P0
WAVE 2: TRACK-PRODUCT-BOUNDARY-P0
WAVE 3: WAVE-3-P0-INTEGRATION (serial)
CONFLICT-FREE: YES — unique production-file ownership and dedicated test-file ownership are explicit; Wave 3 is serial.

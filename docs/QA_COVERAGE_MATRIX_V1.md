# QA Coverage Matrix V1

Scope: static, read-only audit of the 148 scenario IDs in `adaptive_agent_qa_scenarios_v1.json` against existing product tests under `tests/`. The QA pack was extracted from the supplied ZIP into the workspace root as requested. Pilot/research/benchmark suites, live providers, browser execution, and test/code changes are out of scope.

Status rule: COVERED means an existing test asserts the scenario's expected behavior; PARTIAL means a related test exists but leaves a material part unasserted; MISSING means no corresponding behavioral test was found. Test references below are existing functions; no test was added or modified.

| Scenario | Priority | Status | Existing Test | Evidence | Gap |
| -------- | -------- | ------- | ------------- | --------- | ----- |
| CHAT-001 | P0 | COVERED | tests/test_product_qa.py::ProductQATests.test_fake_chat_contract_persists_conversation_and_frozen_provenance | Fresh chat endpoint yields one completed final, two persisted messages and one turn. | — |
| CHAT-002 | P0 | COVERED | tests/test_runtime.py::ApiContractTests.test_two_turns_persist_under_one_conversation | Second request reuses the same conversation and receives exactly the first user/assistant history. | — |
| CHAT-003 | P0 | COVERED | tests/test_qa_p0_product_boundary.py::ProductBoundaryP0Tests.test_blank_prompt_is_rejected_before_provider_call_or_persistence | Empty, whitespace, newline and tab prompts return 422 before execution and create no run/conversation artifact. | — |
| CHAT-004 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| CHAT-005 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| CHAT-006 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| CHAT-007 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| CHAT-008 | P1 | PARTIAL | tests/test_runtime.py::ApiContractTests.test_two_turns_persist_under_one_conversation | Two-turn order/history is asserted. | No rapid post-completion/stale-state transition is exercised. |
| CHAT-009 | P1 | PARTIAL | tests/test_runtime.py::ApiContractTests.test_fatal_stream_has_conversation_metadata_and_persists_failed_turn | Failed turn is persisted and reloadable. | No subsequent successful turn proves recovery. |
| CHAT-010 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| CHAT-011 | P2 | MISSING | — | — | No existing test covers this expected behavior. |
| CHAT-012 | P2 | MISSING | — | — | No existing test covers this expected behavior. |
| CFG-001 | P0 | COVERED | tests/test_product_wiring.py::ProductCatalogTests.test_provider_and_model_catalog_is_explicit_and_provider_scoped | Catalog and validated IDs are explicit and provider-scoped. | — |
| CFG-002 | P0 | COVERED | tests/test_product_wiring.py::ProductCatalogTests.test_mismatched_product_provider_model_is_rejected_without_provider_call | Mismatched Groq/provider selection is rejected and factory is not called. | — |
| CFG-003 | P0 | MANUAL_E2E_REQUIRED | tests/test_product_wiring.py::ProductEndpointIsolationTests.test_product_mode_and_model_reach_executor_without_live_provider | Offline OpenAI propagation is verified; browser send with selected Groq/model remains unexecuted by policy. | Requires approved browser/manual Groq/model evidence. |
| CFG-004 | P0 | MANUAL_E2E_REQUIRED | — | Provider/model picker implementation is present but no browser state-transition execution is authorized here. | Requires browser sequence Provider A→Model A1→Provider B→Model B1→Send. |
| CFG-005 | P0 | MANUAL_E2E_REQUIRED | — | Model picker implementation is present but no browser state-transition execution is authorized here. | Requires browser sequence Model A→Model B→Send. |
| CFG-006 | P1 | COVERED | tests/test_runtime.py::ApiContractTests.test_provider_diagnostic_missing_key_is_truthful_and_safe | Unconfigured provider returns NOT_CONFIGURED without constructing a provider. | — |
| CFG-007 | P1 | COVERED | tests/test_product_qa.py::ProductQATests.test_openai_catalog_and_invalid_product_selections_are_safe | Unsupported provider/model selection produces structured error, not success. | — |
| CFG-008 | P1 | COVERED | tests/test_product_qa.py::ProductQATests.test_openai_catalog_and_invalid_product_selections_are_safe | Unknown provider request returns 422 without traceback. | — |
| CFG-009 | P1 | COVERED | tests/test_product_qa.py::ProductQATests.test_openai_catalog_and_invalid_product_selections_are_safe | Unknown model emits Unsupported model selection and no traceback. | — |
| CFG-010 | P1 | COVERED | tests/test_product_wiring.py::ProductEndpointIsolationTests.test_product_selection_does_not_mutate_frozen_pilot_identity | Product selection changes are checked against unchanged frozen provider/model identity. | — |
| CFG-011 | P1 | COVERED | tests/test_product_qa.py::ProductQATests.test_product_modes_normalize_without_changing_model | All mode aliases normalize while model and strategy remain unchanged. | — |
| CFG-012 | P0 | COVERED | tests/test_runtime.py::ApiContractTests.test_config_and_frontend_do_not_expose_configured_secrets | Config response/frontend are checked for absent keys, tokens and configured secrets. | — |
| CTX-001 | P0 | COVERED | tests/test_context_v1.py::ContextProductFlowTests.test_prepared_content_reaches_normal_product_execution_and_source_identity | UTF-8 prepared content reaches execution; source identity is preserved in final and persisted records. | — |
| CTX-002 | P0 | COVERED | tests/test_context_v1.py::ContextProductFlowTests.test_mini_project_fixture_preserves_all_small_files_for_context_retrieval | Five supported files are prepared and all filenames/markers remain in the frozen context. | — |
| CTX-003 | P0 | COVERED | tests/test_qa_p0_context_boundary.py::ContextBoundaryP0Tests.test_file_size_boundary_accepts_limit_and_rejects_over_limit | 99,999 and 100,000 byte files are accepted; 100,001 bytes returns FILE_TOO_LARGE. | — |
| CTX-004 | P0 | COVERED | tests/test_context_v1.py::ContextFilePreparationTests.test_unsupported_empty_oversized_decode_parser_and_path_fail_closed | MAX_CONTEXT_FILE_BYTES+1 is rejected with FILE_TOO_LARGE. | — |
| CTX-005 | P0 | COVERED | tests/test_context_v1.py::ContextFilePreparationTests.test_unsupported_empty_oversized_decode_parser_and_path_fail_closed | Traversal filename case is rejected with INVALID_FILENAME. | — |
| CTX-006 | P0 | COVERED | tests/test_project_understanding_v11.py::ProjectPathSafetyTests.test_unsafe_relative_paths_fail_closed_and_legacy_filename_still_works | Absolute and drive paths are rejected with INVALID_RELATIVE_PATH. | — |
| CTX-007 | P1 | COVERED | tests/test_context_v1.py::ContextFilePreparationTests.test_unsupported_empty_oversized_decode_parser_and_path_fail_closed | Whitespace-only file is rejected with EMPTY_FILE. | — |
| CTX-008 | P1 | COVERED | tests/test_context_v1.py::ContextFilePreparationTests.test_unsupported_empty_oversized_decode_parser_and_path_fail_closed | NUL-containing file is rejected with PARSER_FAILED. | — |
| CTX-009 | P1 | COVERED | tests/test_context_v1.py::ContextFilePreparationTests.test_unsupported_empty_oversized_decode_parser_and_path_fail_closed | Invalid base64/UTF-8 case is rejected with DECODE_FAILED. | — |
| CTX-010 | P1 | COVERED | tests/test_product_qa.py::ProductQATests.test_context_prepare_formats_parser_errors_and_source_identity | Unsupported PDF returns UNSUPPORTED_FORMAT/415 and is not treated as readable text. | — |
| CTX-011 | P1 | PARTIAL | tests/test_context_v1.py::ContextFilePreparationTests.test_supported_text_source_matrix_uses_one_safe_parser; tests/test_product_qa.py::ProductQATests.test_context_prepare_formats_parser_errors_and_source_identity | Each supported extension preserves format/source identity in isolated prepares. | No single mixed multi-file request asserts every listed extension together. |
| CTX-012 | P1 | COVERED | tests/test_project_understanding_v11.py::ProjectPathSafetyTests.test_relative_path_is_optional_and_keeps_duplicate_basenames_distinct | Same basename with two logical paths remains distinct by relative_path and source_id. | — |
| CTX-013 | P1 | PARTIAL | tests/test_runtime.py::ApiContractTests.test_explicit_context_remains_available_after_historical_reload | Explicit context/source survives one reload-follow-up. | Does not cover multiple follow-ups or source stability across all turns. |
| CTX-014 | P2 | PARTIAL | tests/test_context_v1.py::ContextUiContractTests.test_ui_uses_backend_preparation_and_truthful_states | Static UI contract includes removal function/state and request source plumbing. | No browser/request assertion proves a removed attachment is omitted. |
| RAG-001 | P0 | COVERED | tests/test_runtime.py::GraphAndRagTests.test_frozen_rag_snapshot_is_deterministic_and_selective | Unique matching topic is selected into the frozen snapshot. | — |
| RAG-002 | P0 | COVERED | tests/test_project_understanding_v11.py::ProjectRagTests.test_path_signal_is_modest_against_strong_content | Two-file fixture selects the content-relevant file over the unrelated one. | — |
| RAG-003 | P0 | COVERED | tests/test_project_understanding_v11.py::ProjectRagTests.test_path_signal_is_modest_against_strong_content | A path/name hint cannot displace the strongly matching content source. | — |
| RAG-004 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| RAG-005 | P1 | PARTIAL | tests/test_project_understanding_v11.py::ProjectRagTests.test_manifest_is_deterministic_bounded_and_retrieval_keeps_paths | 20-file retrieval is deterministic, bounded and path-aware. | No near-duplicate/noise-ranking assertion. |
| RAG-006 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| RAG-007 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| RAG-008 | P1 | PARTIAL | tests/test_context_v1.py::ContextProductFlowTests.test_mini_project_fixture_preserves_all_small_files_for_context_retrieval | Five-file fixture keeps all relevant markers in a full-small-context snapshot. | No two-fact budgeted query checks both selected sources. |
| RAG-009 | P1 | PARTIAL | tests/test_project_workspace_v12.py::ProjectWorkspaceRuntimeContractTests.test_project_context_uses_path_aware_rag_and_records_selected_paths | Path-aware source metadata is retained across project context selection. | README-versus-code same-topic distinction is not tested. |
| RAG-010 | P1 | COVERED | tests/test_runtime.py::GraphAndRagTests.test_frozen_rag_records_explicit_truncation | Near budget snapshot has deterministic max_chars truncation metadata and intact bounded length. | — |
| RAG-011 | P2 | MISSING | — | — | No existing test covers this expected behavior. |
| RAG-012 | P2 | MISSING | — | — | No existing test covers this expected behavior. |
| GND-001 | P0 | READY_FOR_LIVE_EVAL | tests/test_qa_p0_grounding_eval.py::CoreP0GroundingEvalTests.test_frozen_eval_registry_has_explicit_oracles_for_all_core_quality_cases | Frozen grounding oracle and source fixture are locally validated; model claim/source judgment is deferred. | READY_FOR_LIVE_EVAL; no live model result. |
| GND-002 | P0 | READY_FOR_LIVE_EVAL | tests/test_qa_p0_grounding_eval.py::CoreP0GroundingEvalTests.test_ground_truth_anchors_and_missing_evidence_are_derived_from_frozen_sources | Missing-file abstention oracle and absent-path trap are locally prepared. | READY_FOR_LIVE_EVAL; no live model result. |
| GND-003 | P0 | READY_FOR_LIVE_EVAL | tests/test_qa_p0_grounding_eval.py::CoreP0GroundingEvalTests.test_ground_truth_anchors_and_missing_evidence_are_derived_from_frozen_sources | No-database-evidence trap is locally validated from the frozen fixture. | READY_FOR_LIVE_EVAL; no live model result. |
| GND-004 | P0 | READY_FOR_LIVE_EVAL | tests/test_qa_p0_grounding_eval.py::CoreP0GroundingEvalTests.test_ground_truth_anchors_and_missing_evidence_are_derived_from_frozen_sources | No-auth-middleware-evidence trap is locally validated from the frozen fixture. | READY_FOR_LIVE_EVAL; no live model result. |
| GND-005 | P0 | READY_FOR_LIVE_EVAL | tests/test_qa_p0_grounding_eval.py::CoreP0GroundingEvalTests.test_ground_truth_anchors_and_missing_evidence_are_derived_from_frozen_sources | Fabricated-route correction oracle is locally prepared. | READY_FOR_LIVE_EVAL; no live model result. |
| GND-006 | P0 | READY_FOR_LIVE_EVAL | tests/test_qa_p0_grounding_eval.py::CoreP0GroundingEvalTests.test_rag_snapshot_preserves_supporting_source_identity_for_grounded_cases | Frozen source identity and supporting-source oracle pass locally; semantic claim support is deferred. | READY_FOR_LIVE_EVAL; no live model result. |
| GND-007 | P0 | READY_FOR_LIVE_EVAL | tests/test_qa_p0_grounding_eval.py::CoreP0GroundingEvalTests.test_ground_truth_anchors_and_missing_evidence_are_derived_from_frozen_sources | Flask-without-database unsupported-inference trap is locally validated. | READY_FOR_LIVE_EVAL; no live model result. |
| GND-008 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| GND-009 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| GND-010 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| GND-011 | P1 | PARTIAL | tests/test_project_understanding_v11.py::ProjectRagTests.test_path_signal_is_modest_against_strong_content | Selected source path is checked against a competing path. | No generated answer attribution assertion. |
| GND-012 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| GND-013 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| GND-014 | P1 | PARTIAL | tests/test_runtime.py::RuntimeFlowTests.test_fake_answers_current_task_without_history_or_context_contamination; tests/test_runtime.py::RuntimeFlowTests.test_fake_analyzer_focuses_on_task_not_unrelated_context | Unrelated history/context is not copied into the Fake response/route. | No explicit missing-evidence abstention oracle. |
| GND-015 | P1 | PARTIAL | tests/test_product_qa.py::ProductQATests.test_fake_chat_contract_persists_conversation_and_frozen_provenance | Vietnamese question with English context returns a Vietnamese fact in the Fake path. | No broader language/fact-evaluation assertion. |
| GND-016 | P2 | MISSING | — | — | No existing test covers this expected behavior. |
| ROUTE-001 | P0 | COVERED | tests/test_project_workspace_v12.py::ProjectWorkspaceRuntimeContractTests.test_product_auto_greeting_uses_direct_solver_and_verifier_without_analyzer | AUTO greeting is routed DIRECT with no Analyzer and STOP_SUFFICIENT. | — |
| ROUTE-002 | P0 | COVERED | tests/test_qa_p0_routing.py::CoreP0RoutingTests.test_auto_arithmetic_records_direct_route_and_skips_other_topologies | Arithmetic AUTO execution records DIRECT and skips Analyzer/Planner/Worker/Synthesizer. | — |
| ROUTE-003 | P0 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_product_auto_route_matrix_uses_task_structure_not_context_size | Entry-point/file-location prompts are explicitly expected to choose DIRECT. | — |
| ROUTE-004 | P1 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_product_auto_route_matrix_uses_task_structure_not_context_size | Three independent-module prompts are expected to choose PARALLEL. | — |
| ROUTE-005 | P1 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_dependency_welcome_example_routes_planned | Dependency-heavy prompt chooses PLANNED and validates a DAG. | — |
| ROUTE-006 | P1 | COVERED | tests/test_product_wiring.py::ProductModeTests.test_explicit_modes_force_topology_without_changing_model | Explicit DIRECT bypasses AUTO chooser and emits Product mode selected DIRECT. | — |
| ROUTE-007 | P1 | COVERED | tests/test_product_wiring.py::ProductModeTests.test_explicit_modes_force_topology_without_changing_model | Explicit PARALLEL bypasses AUTO chooser and emits PARALLEL. | — |
| ROUTE-008 | P1 | COVERED | tests/test_product_wiring.py::ProductModeTests.test_explicit_modes_force_topology_without_changing_model | Explicit PLANNED bypasses AUTO chooser and emits PLANNED. | — |
| ROUTE-009 | P1 | PARTIAL | tests/test_product_qa.py::ProductQATests.test_product_auto_wiring_q0_ignores_context_file_count; tests/test_product_qa.py::ProductQATests.test_fake_chat_executes_auto_and_parallel_product_modes | Backend route trace/meta is asserted for AUTO. | No UI rendering integration proves displayed evidence equals the trace. |
| ROUTE-010 | P1 | PARTIAL | tests/test_product_qa.py::ProductQATests.test_product_auto_wiring_q0_ignores_context_file_count | Fast path asserts two calls and no Analyzer for a simple project question. | No measured DIRECT baseline comparison. |
| ROUTE-011 | P1 | PARTIAL | tests/test_runtime.py::RuntimeFlowTests.test_product_auto_route_matrix_uses_task_structure_not_context_size | Several simple prompts are expected DIRECT. | No 30-prompt distribution/stability run. |
| ROUTE-012 | P2 | MISSING | — | — | No existing test covers this expected behavior. |
| AGENT-001 | P0 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_direct_auto_skips_planner_and_stops_sufficient | DIRECT topology is asserted as Analyzer, Direct Solver, Verifier with no Planner. | — |
| AGENT-002 | P0 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_parallel_workers_run_concurrently_without_planner | Three workers run on parallel scheduler with no Planner and concurrent activity. | — |
| AGENT-003 | P0 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_planned_mode_validates_and_schedules_dependencies | Planner is called, DAG is validated, and dependent batch starts after prerequisite. | — |
| AGENT-004 | P0 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_agent_execution_evidence_is_distinct_from_calls_and_bounded | Trace agent starts/ends/requests are cross-checked for IDs, goals, timing, status and bounded previews. | — |
| AGENT-005 | P1 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_direct_auto_skips_planner_and_stops_sufficient | Verifier PASS path stops sufficiently without an extra repair execution. | — |
| AGENT-006 | P1 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_targeted_escalation_evidence_links_issue_to_repair_worker | NEEDS_WORK creates bounded targeted repair linked to the issue and later verification. | — |
| AGENT-007 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| AGENT-008 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| AGENT-009 | P1 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_structured_output_retry_is_one_logical_call_two_requests | Logical call, physical request and retry counts are asserted separately. | — |
| AGENT-010 | P1 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_e2e_wall_clock_includes_provider_delay_and_parallel_critical_path | Parallel E2E duration is checked against max worker duration, below their sum, with concurrency=3. | — |
| AGENT-011 | P1 | PARTIAL | tests/test_runtime.py::RuntimeFlowTests.test_product_auto_fast_path_does_not_change_research_adaptive | Product and research paths are compared for isolation. | No artifact scan proves a product run cannot create/modify Pilot files. |
| AGENT-012 | P2 | MISSING | — | — | No existing test covers this expected behavior. |
| PERSIST-001 | P0 | COVERED | tests/test_product_persistence.py::ProductConversationPersistenceTests.test_create_store_message_and_reopen_preserves_identity_and_fields | Fresh repository/process view reloads the completed conversation and full messages. | — |
| PERSIST-002 | P0 | MANUAL_E2E_REQUIRED | tests/test_product_persistence.py::ProductConversationPersistenceTests.test_create_store_message_and_reopen_preserves_identity_and_fields | API reopen and fresh repository reload pass; browser refresh state is not executed here. | Requires approved browser refresh after a completed turn. |
| PERSIST-003 | P0 | MANUAL_E2E_REQUIRED | tests/test_product_persistence.py::ProductConversationPersistenceTests.test_list_rename_search_delete_and_unrelated_run_survival | API deletion/404 and run cleanup pass; active UI transition is not executed here. | Requires approved browser delete-active→New Chat evidence. |
| PERSIST-004 | P1 | PARTIAL | tests/test_product_persistence.py::ProductConversationPersistenceTests.test_list_rename_search_delete_and_unrelated_run_survival | PATCH rename and refreshed list preserve the new title. | No fresh-process reload assertion after rename. |
| PERSIST-005 | P1 | COVERED | tests/test_product_persistence.py::ProductConversationPersistenceTests.test_blank_rename_is_rejected_without_corrupting_title | Whitespace rename returns 422 and preserves the prior title. | — |
| PERSIST-006 | P1 | COVERED | tests/test_conversation_repository.py::ConversationRepositoryTests.test_json_create_reload_order_and_failed_turn_metadata | Failed turn metadata and prior message order survive JSON reload. | — |
| PERSIST-007 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| PERSIST-008 | P1 | COVERED | tests/test_product_persistence.py::ProductConversationPersistenceTests.test_list_rename_search_delete_and_unrelated_run_survival | Title/preview search is checked while list/conversation state remains intact. | — |
| PERSIST-009 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| PERSIST-010 | P2 | MISSING | — | — | No existing test covers this expected behavior. |
| ERR-001 | P0 | COVERED | tests/test_qa_p0_reliability.py::CoreP0ReliabilityTests.test_timeout_is_bounded_safe_and_follow_up_run_remains_usable | Deterministic timeout is bounded, terminal, safe, persisted and followed by a usable turn. | — |
| ERR-002 | P0 | MANUAL_E2E_REQUIRED | tests/test_runtime.py::ApiContractTests.test_fatal_stream_has_conversation_metadata_and_persists_failed_turn | Terminal provider failure/persistence is covered; mid-stream disconnect UI is not executed here. | Requires approved browser stream interruption and recovery evidence. |
| ERR-003 | P1 | PARTIAL | tests/test_runtime.py::GraphAndRagTests.test_retry_delay_uses_provider_retry_hint; tests/test_runtime.py::ProviderDiagnosticTests.test_raw_provider_incident_is_structured_without_body_or_sensitive_headers | 429 retry hint and safe incident fields are tested. | No provider retry-loop/count test proves no infinite retry. |
| ERR-004 | P1 | PARTIAL | tests/test_runtime.py::ProviderDiagnosticTests.test_error_taxonomy_covers_every_failure_category; tests/test_product_qa.py::ProductQATests.test_provider_failure_is_safe_and_persisted_as_structured_fatal | 500 classification and provider failure terminal handling are covered. | No explicit HTTP 500/503 integration response asserts no fake success. |
| ERR-005 | P1 | PARTIAL | tests/test_runtime.py::RuntimeFlowTests.test_structured_output_retry_is_one_logical_call_two_requests | Invalid analyzer payload triggers bounded structured retry. | No malformed provider payload/parser-failure matrix. |
| ERR-006 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| ERR-007 | P1 | PARTIAL | tests/test_context_v1.py::ContextFilePreparationTests.test_prepare_endpoint_errors_are_safe_and_truthful; tests/test_product_qa.py::ProductQATests.test_context_prepare_formats_parser_errors_and_source_identity | Context preparation failures return truthful safe errors. | No following chat assertion prevents a grounded claim after prepare failure. |
| ERR-008 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| ERR-009 | P1 | PARTIAL | tests/test_runtime.py::FrontendV6Tests.test_locked_ui_failed_turn_has_real_bounded_retry; tests/test_runtime.py::ApiContractTests.test_fatal_stream_has_conversation_metadata_and_persists_failed_turn | UI retry affordance and failed persistence exist. | No execution-level assertion that retry creates a controlled new run without silent history rewrite. |
| ERR-010 | P1 | COVERED | tests/test_conversation_repository.py::ConversationRepositoryTests.test_json_create_reload_order_and_failed_turn_metadata | A failed conversation record is parsed/reloaded with status, provider, model and context. | — |
| ERR-011 | P2 | COVERED | tests/test_runtime.py::FrontendV6Tests.test_upstream_html_errors_are_replaced_before_markdown | Recoverable upstream/stack errors are mapped to friendly text with no HTML or traceback body. | — |
| ERR-012 | P2 | MISSING | — | — | No existing test covers this expected behavior. |
| PERF-001 | P0 | COVERED | tests/test_qa_p0_performance.py::CoreP0PerformanceTests.test_repeated_direct_fake_runs_report_local_p50_and_p95 | Ten repeated local Fake DIRECT runs report deterministic p50/p95 latency evidence. | — |
| PERF-002 | P1 | PARTIAL | tests/test_runtime.py::RuntimeFlowTests.test_product_auto_route_matrix_uses_task_structure_not_context_size | AUTO fast path avoids Analyzer for simple product prompts. | No timing measurement against DIRECT. |
| PERF-003 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| PERF-004 | P1 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_e2e_wall_clock_includes_provider_delay_and_parallel_critical_path | Parallel timing uses critical-path wall clock rather than summing worker durations. | — |
| PERF-005 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| PERF-006 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| PERF-007 | P1 | PARTIAL | tests/test_runtime.py::ApiContractTests.test_product_chat_uses_bounded_repository_append_and_timing_identity; tests/test_runtime.py::RuntimeFlowTests.test_missing_provider_usage_remains_null_not_zero | Timing fields and unavailable usage semantics are statically/runtime checked. | No TTFT capture or explicit unavailable TTFT metric. |
| PERF-008 | P1 | COVERED | tests/test_runtime.py::RuntimeFlowTests.test_structured_output_retry_is_one_logical_call_two_requests | Token, logical-call and physical-request metrics are asserted as consistent finite values. | — |
| PERF-009 | P2 | MISSING | — | — | No existing test covers this expected behavior. |
| PERF-010 | P2 | PARTIAL | tests/test_runtime.py::RuntimeFlowTests.test_timeout_stops_failed_run | Timeout terminal status and stop reason are asserted. | No latency report separates timeout samples from success samples. |
| SEC-001 | P0 | COVERED | tests/test_runtime.py::ApiContractTests.test_config_and_frontend_do_not_expose_configured_secrets | /api/config and frontend are checked for no configured secrets or keys. | — |
| SEC-002 | P0 | COVERED | tests/test_context_v1.py::ContextFilePreparationTests.test_unsupported_empty_oversized_decode_parser_and_path_fail_closed | Traversal filename is rejected fail-closed. | — |
| SEC-003 | P0 | READY_FOR_LIVE_EVAL | tests/test_qa_p0_grounding_eval.py::CoreP0GroundingEvalTests.test_source_and_candidate_are_data_in_prompt_boundary_and_guards_are_declared | Indirect source-injection fixture and guard contract pass locally; model resistance is deferred. | READY_FOR_LIVE_EVAL; no live model result. |
| SEC-004 | P0 | COVERED | tests/test_runtime.py::ApiContractTests.test_reloaded_historical_context_is_not_active_for_unrelated_turn | Conversation/project context is absent from unrelated and new turns while historical record remains stored. | — |
| SEC-005 | P0 | READY_FOR_LIVE_EVAL | tests/test_qa_p0_grounding_eval.py::CoreP0GroundingEvalTests.test_source_and_candidate_are_data_in_prompt_boundary_and_guards_are_declared | Explicit system/product-constraint override fixture and guard contract pass locally; model resistance is deferred. | READY_FOR_LIVE_EVAL; no live model result. |
| SEC-006 | P1 | PARTIAL | tests/test_context_v1.py::ContextUiContractTests.test_ui_source_filename_is_escaped_and_rendered_in_product_surfaces; tests/test_runtime.py::FrontendV6Tests.test_upstream_html_errors_are_replaced_before_markdown | Source labels are escaped and upstream HTML is sanitized. | No prompt HTML/script render test. |
| SEC-007 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| SEC-008 | P1 | COVERED | tests/test_product_qa.py::ProductQATests.test_provider_failure_is_safe_and_persisted_as_structured_fatal | Provider exception is persisted as structured fatal with secret text removed. | — |
| SEC-009 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| SEC-010 | P1 | PARTIAL | tests/test_project_understanding_v11.py::ProjectPathSafetyTests.test_project_limit_accepts_twenty_and_rejects_twenty_one; tests/test_context_v1.py::ContextFilePreparationTests.test_unsupported_empty_oversized_decode_parser_and_path_fail_closed | Count and individual size bounds are tested. | No combined near-limit multi-file request. |
| SEC-011 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| SEC-012 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| SEC-013 | P2 | PARTIAL | tests/test_runtime.py::ApiContractTests.test_config_and_frontend_do_not_expose_configured_secrets | Config/frontend secret absence is checked. | No explicit pre-demo debug/configuration review assertion. |
| SEC-014 | P2 | MISSING | — | — | No existing test covers this expected behavior. |
| UI-001 | P0 | MANUAL_E2E_REQUIRED | tests/test_product_qa.py::ProductQATests.test_fake_chat_contract_persists_conversation_and_frozen_provenance; tests/test_product_wiring.py::ProductEndpointIsolationTests.test_product_mode_and_model_reach_executor_without_live_provider | Offline valid-send and propagation pass; browser send with selected Groq/model is not executed here. | Requires approved browser send and stale-config evidence. |
| UI-002 | P1 | PARTIAL | tests/test_context_v1.py::ContextUiContractTests.test_ui_uses_backend_preparation_and_truthful_states; tests/test_runtime.py::FrontendV6Tests.test_failed_turn_has_friendly_error_hierarchy | Static UI states and friendly failure classes are asserted. | No streamed loading-to-terminal lifecycle test. |
| UI-003 | P1 | PARTIAL | tests/test_context_v1.py::ContextUiContractTests.test_ui_source_filename_is_escaped_and_rendered_in_product_surfaces; tests/test_context_v1.py::ContextProductFlowTests.test_real_fake_execution_emits_and_persists_source_identity | Source identity and escaping hooks are checked. | No browser render proves source belongs to the current answer. |
| UI-004 | P1 | PARTIAL | tests/test_runtime.py::FrontendV6Tests.test_execution_inspector_exposes_required_evidence_views; tests/test_runtime.py::RuntimeFlowTests.test_agent_execution_evidence_is_distinct_from_calls_and_bounded | Inspector surfaces and backend trace metadata are each checked. | No UI/backend integration assertion connects the displayed details. |
| UI-005 | P1 | PARTIAL | tests/test_product_qa.py::ProductQATests.test_product_controls_have_accessible_names_and_status_announcements | Composer/context labels and limits have aria-labels. | Focus order/keyboard interaction is not exercised. |
| UI-006 | P1 | COVERED | tests/test_product_qa.py::ProductQATests.test_product_controls_have_accessible_names_and_status_announcements | Toast container has status/live-region semantics. | — |
| UI-007 | P2 | PARTIAL | tests/test_runtime.py::FrontendV6Tests.test_locked_sidebar_search_and_adaptive_mode_contract; tests/test_runtime.py::FrontendV6Tests.test_v20_history_and_model_picker_match_the_approved_interaction | Search popup hooks and layout rules are asserted statically. | No long-title render/selectability test. |
| COMPAT-001 | P0 | COVERED | tests/test_conversation_repository.py::ConversationRepositoryTests.test_relative_path_roundtrip_and_legacy_source_compatibility | Legacy source records and older conversations remain readable without relative_path. | — |
| COMPAT-002 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| COMPAT-003 | P1 | MISSING | — | — | No existing test covers this expected behavior. |
| COMPAT-004 | P1 | PARTIAL | tests/test_project_understanding_v11.py::ProjectPathSafetyTests.test_unsafe_relative_paths_fail_closed_and_legacy_filename_still_works; tests/test_conversation_repository.py::ConversationRepositoryTests.test_relative_path_roundtrip_and_legacy_source_compatibility | Windows/absolute path metadata is rejected safely and legacy source data remains readable. | No supported separator-normalization case. |
| COMPAT-005 | P1 | PARTIAL | tests/test_product_persistence.py::ProductConversationPersistenceTests.test_create_store_message_and_reopen_preserves_identity_and_fields | Fresh repository and repeated API reload preserve state. | No browser-reload/server-restart order matrix. |

## Summary

TOTAL: 148
COVERED: 59
PARTIAL: 34
MISSING: 39
READY_FOR_LIVE_EVAL: 9
MANUAL_E2E_REQUIRED: 7

P0 TOTAL: 45
P0 COVERED: 29
P0 READY_FOR_LIVE_EVAL: 9
P0 MANUAL_E2E_REQUIRED: 7
P0 FAILED: 0

P1 TOTAL: 87
P1 COVERED: 29
P1 PARTIAL: 30
P1 MISSING: 28

P2 TOTAL: 16
P2 COVERED: 1
P2 PARTIAL: 4
P2 MISSING: 11

## TOP P0 GAPS

1. Grounding/hallucination — GND-001..GND-007 require live-model oracle/missing-evidence and hallucination-resistance evaluation.
2. Security — SEC-003 and SEC-005 require live-model prompt-injection and instruction-boundary resistance evidence.
3. Provider/model — CFG-003, CFG-004 and CFG-005 require approved browser/live-provider selection-sequencing evidence.
4. Persistence — PERSIST-002 and PERSIST-003 require browser refresh/reload and active-UI→New Chat evidence.
5. Error/UI — ERR-002 and UI-001 require browser stream interruption/recovery and selected-provider/model evidence.

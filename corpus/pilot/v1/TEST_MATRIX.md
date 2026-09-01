# Test matrix — Adaptive Agent Lab v0.6.3

Legend: **PASS** means the named check was run and passed; **UNVERIFIED** means
there is no valid evidence yet; **FAIL** is reserved for an executed assertion
that failed. Live provider availability is never inferred from network absence.

| Feature / contract | Relevant check | Current result |
| --- | --- | --- |
| Main chat is Adaptive AUTO and hides baseline choice | `ApiContractTests.test_chat_always_dispatches_adaptive_and_hides_baseline_choice` | PASS |
| Analyzer separates current task from recent history | `RuntimeFlowTests.test_fake_analyzer_focuses_on_task_not_unrelated_context` | PASS |
| Analyzer structural JSON validation | `RuntimeFlowTests.test_direct_auto_skips_planner_and_stops_sufficient` | PASS |
| DIRECT route skips Planner | `RuntimeFlowTests.test_direct_auto_skips_planner_and_stops_sufficient` | PASS |
| PARALLEL route and no Planner | `RuntimeFlowTests.test_parallel_workers_run_concurrently_without_planner` | PASS |
| Independent workers run concurrently | same test; `max_active_workers=3` | PASS |
| PLANNED route calls Planner | `RuntimeFlowTests.test_planned_mode_validates_and_schedules_dependencies` | PASS |
| DAG cycle/unknown dependency rejection | `GraphAndRagTests.test_dag_rejects_cycle_and_unknown_dependency` | PASS |
| Dependency-aware ready sets | `RuntimeFlowTests.test_planned_mode_validates_and_schedules_dependencies` | PASS |
| Runtime Verifier PASS → stop sufficient | `RuntimeFlowTests.test_direct_auto_skips_planner_and_stops_sufficient` | PASS |
| Structural Analyzer input excludes internal task labels | `RuntimeFlowTests.test_structural_analyzer_does_not_receive_hidden_task_labels` | PASS |
| NEEDS_WORK targeted escalation | `RuntimeFlowTests.test_needs_work_targets_independent_fixes_concurrently` | PASS |
| FAIL does not escalate | `RuntimeFlowTests.test_fail_verdict_does_not_escalate` | PASS |
| Verifier unavailable preserves candidate | `RuntimeFlowTests.test_verifier_failure_preserves_candidate_as_degraded_final` | PASS |
| Retry accounting: one logical, two requests | `RuntimeFlowTests.test_structured_output_retry_is_one_logical_call_two_requests` | PASS |
| Provider retry hint handling | `GraphAndRagTests.test_retry_delay_uses_provider_retry_hint` | PASS |
| Timeout enforcement | `RuntimeFlowTests.test_timeout_stops_failed_run` | PASS |
| Logical-call budget enforcement | `RuntimeFlowTests.test_logical_budget_stops_before_solver` | PASS |
| Physical-request budget emits explicit stop state | `RuntimeFlowTests.test_physical_budget_stops_with_explicit_terminal_state` | PASS |
| Deterministic/selective Frozen Context Snapshot with IDs/provenance | `GraphAndRagTests.test_frozen_rag_snapshot_is_deterministic_and_selective` | PASS |
| Frozen snapshot records explicit truncation | `GraphAndRagTests.test_frozen_rag_records_explicit_truncation` | PASS |
| Compare is sequential and reuses one snapshot ID/hash/chunks | `ApiContractTests.test_compare_is_sequential_and_reuses_one_snapshot` | PASS |
| Compare freezes provider/model/settings and reports execution order | `ApiContractTests.test_compare_is_sequential_and_reuses_one_snapshot` | PASS |
| Compare exposes answers/resource metrics, null-unavailable fields and Not evaluated quality | `RuntimeFlowTests.test_missing_provider_usage_remains_null_not_zero`; `FrontendV6Tests.test_compare_ui_exposes_full_resource_metrics_without_quality_score` | PASS |
| Compare failures remain visible as four distinct raw runs | `ApiContractTests.test_compare_failure_persists_four_distinct_raw_runs` | PASS |
| Two turns remain one conversation | `ApiContractTests.test_two_turns_persist_under_one_conversation`; `runtime_check.py --write-test` | PASS |
| Grouped turns, rename, delete | `V06RegressionTests.test_conversation_api_returns_grouped_turns_and_supports_rename_delete` | PASS |
| Transcript turn keeps execution evidence behind a compact action | `FrontendV6Tests.test_transcript_groups_turn_and_keeps_execution_progressive` | PASS |
| Readable answer/question/sidebar metadata typography | `FrontendV6Tests.test_readable_type_and_collapsible_responsive_layout_contract` | PASS |
| Sidebar/inspector collapse state, responsive tracks, accessible controls | `FrontendV6Tests.test_panel_state_and_accessible_controls_are_persisted` | PASS |
| V6.2 chat-first hierarchy removes visual debt and keeps research actions advanced | `FrontendV6Tests.test_v62_chat_first_visual_debt_is_mechanically_reduced` | PASS |
| V6.2 drawers, tabs, Raw actions, and keyboard affordances | `FrontendV6Tests.test_v62_accessible_drawers_tabs_and_raw_actions_are_present` | PASS |
| V6.2 metrics keep Agent/Logical/Physical and usage/cost fields separate | `FrontendV6Tests.test_v62_metrics_keep_provider_fields_separate_and_unavailable` | PASS |
| Agent Execution identity/goal/timing/usage is distinct from calls/requests | `RuntimeFlowTests.test_agent_execution_evidence_is_distinct_from_calls_and_bounded` | PASS |
| Targeted escalation links verifier issue to repair Worker and reverify | `RuntimeFlowTests.test_targeted_escalation_evidence_links_issue_to_repair_worker` | PASS |
| Execution Inspector Overview/Graph/Agents/Metrics/Raw views | `FrontendV6Tests.test_execution_inspector_exposes_required_evidence_views` | PASS |
| Safe bounded execution metadata excludes hidden prompts | `FrontendV6Tests.test_execution_metadata_contract_is_instrumented_without_prompts` | PASS |
| T6 audit maps all 16 adaptive components to code/tests/evidence | `docs/ORCHESTRATION_AUDIT.md` plus full regression | PASS |
| Failed stream persists conversation metadata | `ApiContractTests.test_fatal_stream_has_conversation_metadata_and_persists_failed_turn` | PASS |
| Raw failed run evidence is saved | same test; evidence JSON assertion | PASS |
| Raw stopped run evidence is saved | `ApiContractTests.test_stopped_run_is_saved_as_raw_evidence` | PASS |
| JSON run evidence saves snapshot/chunk provenance | `ApiContractTests.test_execute_once_saves_json_evidence` | PASS |
| Single/Fixed/Static/Adaptive remain distinct | `ApiContractTests.test_compare_strategy_names_remain_distinct_in_execution` | PASS |
| Fixed topology/count/dependency policy is identical across task shapes | `RuntimeFlowTests.test_fixed_topology_is_identical_across_task_shapes` | PASS |
| Fixed Verifier is observational and cannot escalate | `RuntimeFlowTests.test_fixed_verifier_needs_work_is_observational_only` | PASS |
| Static selects one explicit versioned preset without Adaptive router | `RuntimeFlowTests.test_static_selects_one_versioned_preset_without_adaptive_router` | PASS |
| Static NEEDS_WORK cannot change preset or add repair Worker | `RuntimeFlowTests.test_static_needs_work_does_not_change_preset_or_escalate` | PASS |
| Static preset selection is deterministic | `RuntimeFlowTests.test_static_preset_identity_is_deterministic_for_same_signals` | PASS |
| Fixed/Static strategy config identity is persisted in raw evidence | `ApiContractTests.test_strategy_config_identity_is_persisted_for_fixed_and_static` | PASS |
| Safe provider/model config and unknown-model rejection | `ApiContractTests.test_config_exposes_safe_model_choices_and_rejects_unknown_model` | PASS |
| Secrets absent from config/frontend; `.env` ignored | `ApiContractTests.test_config_and_frontend_do_not_expose_configured_secrets` | PASS |
| Provider list and key-change badge invalidation | V06 regression tests for config/status | PASS |
| Normalized diagnostic schema and Fake SUCCESS | `ApiContractTests.test_provider_diagnostic_endpoint_has_normalized_schema`; `ProviderDiagnosticTests.test_fake_provider_returns_normalized_success` | PASS |
| Every provider error category is distinct and safe | `ProviderDiagnosticTests.test_error_taxonomy_covers_every_failure_category` | PASS |
| Credit exhaustion is classified and raw error is not returned | `ApiContractTests.test_provider_diagnostic_maps_credit_exhaustion_without_raw_error` | PASS |
| Missing key does not construct/call provider | `ProviderDiagnosticTests.test_unconfigured_provider_does_not_call_factory`; `ApiContractTests.test_provider_diagnostic_missing_key_is_truthful_and_safe` | PASS |
| Provider/model/key changes invalidate live status | `V06RegressionTests.test_provider_status_is_invalidated_when_key_changes`; `V06RegressionTests.test_provider_status_is_invalidated_when_model_changes` | PASS |
| Standalone smoke emits safe normalized JSON (Fake + live Groq) | `scripts/provider_probe.py fake`; `scripts/provider_probe.py groq` | PASS |
| Wrapped SDK connection errors map to network blockage | `ProviderDiagnosticTests.test_wrapped_sdk_connection_error_is_network_blocked` | PASS |
| Gemini Interactions response parsing | `V06RegressionTests.test_gemini_interaction_step_parser` | PASS |
| OpenAI-compatible SDK hidden retries disabled | `V06RegressionTests.test_openai_compatible_provider_disables_hidden_sdk_retries` | PASS |
| Python compilation | `python -m compileall -q app tests scripts` | PASS |
| Browser JavaScript syntax | `node --check app/static/app.js` | PASS |
| Static UI exposes supported context formats and provenance panel | `ApiContractTests.test_local_ui_contract_disables_stale_browser_cache` | PASS |
| FastAPI health/config/static runtime | `scripts/runtime_check.py --write-test --timeout 30` | PASS |
| Project-local Windows startup and dependency-blocked diagnostic | `START_WINDOWS.ps1 -NoBrowser`; forced missing-import branch | PASS |
| T9 API release checks (persistence, rename/delete, upload contract, graphs, Compare, export) | release-gate smoke commands against `http://127.0.0.1:8000` | PASS |
| Gemini live API request | `scripts/provider_probe.py gemini` | UNVERIFIED (NETWORK_BLOCKED) |
| OpenAI live API request | `scripts/provider_probe.py openai` | UNVERIFIED (safe upstream `PROVIDER_ERROR`) |
| Groq live API request | `provider_probe.py groq`; V6.1 live T1–T4; V6.2 final minimal diagnostic | PASS (`openai/gpt-oss-120b`; generation and usage metadata verified) |
| OpenRouter live API request | `/api/provider/test` with configured model | PASS (`openrouter/free`; usage available) |
| Visual browser interaction at 1366x768, 1920x1080, ~900px | in-app Browser DOM/viewport QA | PASS (required controls visible; no horizontal overflow) |

The full local regression command is:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The latest audited result was **58/58 PASS**. This includes prior V6/V6.1/V6.2
coverage plus six V6.3 baseline-contract regressions. The parallel and planned-flow rows also assert
wall-clock overlap and dependency completion ordering from execution metadata.
Do not convert any UNVERIFIED row
to PASS without a real provider request or browser observation.

# Product V1.3 — Adaptive Fast Path Analysis

Status: `FAST_PATH_NEEDS_MORE_DESIGN`
Scope: Product AUTO measurement only; no production, test, RAG, routing, or provider configuration change was made.

## Measurement integrity

The local Uvicorn listener was restarted before measurement. The first listener returned a run whose raw evidence did not include the V1.2.2 execution-policy record, despite the checked source containing that contract. Case A is therefore preserved as an `INVALID_PRECONDITION` first-run record and was not retried. The listener was then stopped and restarted as one fresh process; Case B confirmed the V1.2.2 policy record in persisted evidence.

Cases D–F were not sent. The runtime guard requires explicit authorization before the private `web-dev-basics-main` workspace contents can be transmitted to Groq. No workaround or indirect transmission was attempted. This leaves the project-grounded part of the requested six-case set unmeasured, so this report does not authorize an implementation.

Provider/model for attempted measurements: `groq` / `openai/gpt-oss-120b`.
Mode: `adaptive-auto`. Each submitted case was a single request; no provider retry was issued.

| Case | Scope | Evidence | Retrieval | Route | Calls | Latency | Tokens | Quality | Risk |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |
| A — `2 + 2 bằng bao nhiêu?` | GENERAL (inferred) | OPTIONAL (inferred) | SKIPPED | DIRECT | 3 | 3,071 ms | 1,221 | Correct, but trace is pre-V1.2.2/stale | INVALID_PRECONDITION |
| B — `MVC là gì? Giải thích ngắn gọn.` | GENERAL | OPTIONAL | SKIPPED | DIRECT | 2 | 4,498 ms | 1,104 | Correct explanation; longer than requested but usable | LOW_RISK |
| C — 3 API, sequential vs fully parallel wait | GENERAL | OPTIONAL | SKIPPED | PARALLEL | 4 | 6,577 ms | 3,171 | Correct theoretical answer: about 1 second | MEDIUM_RISK |
| D — project entry point | BLOCKED | REQUIRED | UNVERIFIED | UNVERIFIED | — | — | — | Workspace egress authorization required | HIGH_RISK |
| E — multi-file form-to-result flow | BLOCKED | REQUIRED | UNVERIFIED | UNVERIFIED | — | — | — | Workspace egress authorization required | HIGH_RISK |
| F — project database | BLOCKED | REQUIRED | UNVERIFIED | UNVERIFIED | — | — | — | Workspace egress authorization required | HIGH_RISK |

`Calls` is both logical calls and physical provider requests here: no retry occurred. Agent executions equal calls for the measured serial stages. Tokens are provider-reported totals.

## Current call graph

| Resolved route | Stages |
| --- | --- |
| DIRECT, normal AUTO | Analyzer → Direct Solver → Runtime Verifier |
| DIRECT, existing Product fast path | Direct Solver → Runtime Verifier |
| PARALLEL | Analyzer → concurrent Worker batch → Synthesizer → Runtime Verifier |
| PLANNED | Analyzer → Planner → dependency-aware Worker batches → Synthesizer → Runtime Verifier |

The controller, not an LLM, selects the route. Planner is only called by the PLANNED branch. The verifier may add bounded targeted escalation after a `NEEDS_WORK` verdict; neither measured valid case escalated.

## Existing fast path

`Orchestrator.product_auto_fast_path()` is already deterministic. It derives task-only signals and returns DIRECT when the request is marked simple or conversational and has neither planned nor parallel signals. `run_adaptive()` then bypasses the Analyzer; the Direct Solver and Runtime Verifier remain. It does not use model classification, embeddings, context size, source count, or an extra provider request.

Case B exercised this path: its evidence records `source=product-auto-fast-path`, DIRECT, two calls, and no Analyzer. Case C contained explicit parallel wording, did not qualify, and used Analyzer → Worker → Synthesizer → Verifier.

## Per-stage latency

Per-stage durations are available from `agent_end` evidence.

| Case | Analyzer | Solver/Worker | Synthesizer | Verifier | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| A (invalid) | 1,490 ms | 696 ms | — | 882 ms | Analyzer was about 49% of stale-run E2E; non-comparable evidence only. |
| B | skipped | Solver 2,321 ms | — | 551 ms | Existing fast path preserved the verifier. |
| C | 2,300 ms | Worker 1,907 ms | 1,298 ms | 1,068 ms | All four stages were serial for this one-worker result. |

## Analyzer and verifier value

For Case B, the Analyzer did not add route-selection value because the existing deterministic fast path selected DIRECT. The verifier consumed one bounded call and returned PASS; there is no quality-sensitive evidence here to justify removing it. In particular, the candidate was more detailed than the requested short explanation, so PASS alone is not evidence that every response-quality dimension can safely lose a verifier.

For Case C, Analyzer changed the topology to PARALLEL because the request explicitly described parallel execution. The route therefore should not be collapsed to a one-call fast path based on apparent arithmetic simplicity.

Project HIT, multi-file, and MISS verifier value remains unmeasured. Their evidence/abstention protections must remain a hard boundary.

## Candidate eligibility rule for a later implementation

Do not implement from this report. The smallest conservative candidate is:

```text
FAST_DIRECT only if
  policy.scope == GENERAL
  AND policy.evidence_policy == OPTIONAL
  AND policy.retrieval_state == SKIPPED
  AND deterministic task signal is simple or conversational
  AND NOT planned
  AND NOT parallel
  AND NOT multi_goal
```

The last condition makes the existing fast path narrower rather than broader. It should retain `Direct Solver → Runtime Verifier`, avoiding only Analyzer. It must not inspect project contents or add a model classifier.

## Target graph and safety boundary

| Category | Target calls | Boundary |
| --- | --- | --- |
| GENERAL SIMPLE | 2: Solver → Verifier | Candidate only; same as existing fast path. |
| GENERAL COMPLEX | Route-dependent current graph | Keep Analyzer and selected topology. |
| PROJECT SIMPLE HIT | 2 only after live validation | Retain source grounding and provenance. |
| PROJECT MULTI-FILE | Current Analyzer + route-specific graph | Preserve decomposition and citations. |
| PROJECT MISS | Current grounding-aware graph | Preserve required-evidence abstention. |

Expected benefit is one avoided logical/physical request for eligible GENERAL requests. No valid before/after latency delta was measured in this task; the stale Case A duration must not be used as a product performance claim.

## Risks and implementation owner

Any later change must preserve project-grounded evidence enforcement, retrieval MISS abstention, source provenance, active-project persistence, GENERAL turns with unrelated active projects, and DIRECT/PARALLEL/PLANNED semantics. The likely implementation owner is `app/core/orchestrator.py`, with `ExecutionPolicy` in `app/core/types.py` as the contract input. No change is authorized until the D–F workspace egress measurement is explicitly approved and completes with the fresh V1.2.2 trace.

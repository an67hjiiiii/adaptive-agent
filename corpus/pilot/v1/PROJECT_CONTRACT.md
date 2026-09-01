# Project contract — Adaptive Agent Lab

This document is the stable research contract. It describes the semantics that
future changes must preserve; it is not permission to redesign the experiment.
Implementation facts and any code/contract discrepancy are recorded separately in
`docs/CURRENT_STATE.md`.

## Research purpose

The prototype studies an adaptive multi-agent LLM controller under a common task,
context, provider/model, and instrumentation. The controller is an orchestrator,
not one unconstrained “super-agent”.

## Comparison strategies

All strategies receive the same task and the same Frozen Context Snapshot.

| Strategy | Contractual topology |
| --- | --- |
| **B0 Single** | Task + frozen context → Direct Solver → final answer. |
| **B1 Fixed Multi-Agent** | A frozen full topology is selected before the comparison and reused for every task; it does not adapt its topology at runtime. |
| **B2 Static Routing** | Analyze once, select a frozen preset, then execute that preset without runtime strategy changes. |
| **P Adaptive** | Structural analysis → initial route → bounded execution → verification → early stop or targeted escalation. |

Single, Fixed, and Static are comparison baselines. The main chat uses Adaptive
AUTO; users do not select a baseline strategy in the main chat.

## Frozen Context fairness

Simple RAG may retrieve relevant pieces of the supplied textual reference (`.txt`,
`.md`, `.json`, or `.csv`). Parsing is safe text normalization only; it must not
execute document content. Chunking and lexical retrieval are deterministic. The
selected text plus retrieval metadata becomes one immutable **Frozen Context
Snapshot** for the run. Its evidence records a deterministic `snapshot_id`,
`snapshot_hash`/`context_hash`, source document IDs, selected/available chunk IDs,
retrieval settings, creation timestamp, and explicit truncation details when any
text is dropped. The run's `context` field stores the exact snapshot text.

Compare must create one snapshot once and pass that exact snapshot ID/hash and
chunk provenance to Single, Fixed, Static, and Adaptive. Top-level strategy runs
are sequential so their wall-clock measurements do not overlap. Failed or
stopped runs remain evidence; raw evidence is not replaced by aggregates. Each
result exposes its answer, stop state, Agent/Logical/Physical counts, token
usage, E2E latency, and calculated cost when the provider supplies usage and a
known price. Missing provider fields stay unavailable (`null` in the API), and
comparison quality is `Not evaluated` until a formal human-quality protocol
exists; no weighted overall score is claimed.

## Runtime structural signals

The Structural Analyzer receives the current user task and frozen context (with
recent conversation context kept separate). Its validated JSON reports:

- `aspects` — bounded aspects/goals of the task;
- `dependencies` — prerequisite edges between aspects;
- `parallelizable_groups` — aspects that can be worked independently;
- `verification_demand` — `low`, `medium`, or `high`;
- `verification_reasons` — why that demand was selected;
- `rationale` — human-readable routing rationale.

It must not emit hidden research labels or replace structural signals with an
Easy/Medium/Hard or A/N/V/R score.

## Rule-based Adaptive Controller

The controller owns routing, agent selection, DAG validation, scheduling, retry,
timeout, budgets, stop, escalation, and instrumentation:

- **PLANNED** when dependencies exist or verification demand is high;
- **PARALLEL** when multiple aspects have a useful parallelizable group and no
  dependency/high-verification trigger applies;
- **DIRECT** for a single focus or no useful decomposition.

Planner is called only for a planned route. Independent ready nodes may execute
concurrently; dependent nodes wait for their prerequisites.

## Runtime roles

- **Direct Solver** — solves a direct route.
- **Planner** — emits a bounded DAG of subtasks.
- **Worker** — solves one assigned aspect/subtask.
- **Verifier** — checks a candidate against task and frozen context.
- **Synthesizer** — combines bounded worker results into the final answer.

The orchestrator is the policy/controller layer, not an additional LLM role.

## Verifier and terminal behavior

The Runtime Verifier returns exactly one of `PASS`, `NEEDS_WORK`, or `FAIL`, plus
targeted issues and rationale.

- `PASS` ends the run with `STOP_SUFFICIENT`.
- `NEEDS_WORK` may trigger targeted repair workers only for reported missing
  issues and only while escalation and call/request budgets remain.
- `FAIL` does not automatically rerun the whole pipeline; the run stops under
  the applicable verification/budget terminal state.
- If verification becomes unavailable after a usable candidate exists, preserve
  that candidate and mark the run degraded with an explicit stop reason.

## Provider diagnostics

`/api/provider/test` (also exposed as `/api/provider/diagnostic`) performs one
bounded live generation check and returns one normalized result. It reports
configuration, network reachability, authentication, model access, generation,
usage metadata, latency, an error category, and a safe message. The allowed
categories are `NOT_CONFIGURED`, `NETWORK_BLOCKED`, `DNS_ERROR`, `TIMEOUT`,
`AUTHENTICATION_FAILED`, `PERMISSION_DENIED`, `MODEL_NOT_FOUND`,
`RATE_LIMITED`, `QUOTA_EXHAUSTED`, `CREDIT_EXHAUSTED`, `PROVIDER_ERROR`, and
`SUCCESS`.

Provider badges are based on the last live check for the current key/model;
configured-but-never-checked providers remain `unknown`. Fake is a local,
network-free provider and reports successful generation without claiming a
network check. Raw provider errors and credentials never leave the server.

## Measurement definitions

- **Agent Execution** — one bounded role execution recorded by the controller.
- **Logical Model Call** — one orchestration-level provider call for that role;
  retries remain one logical call.
- **Physical Provider Request** — each request attempt sent to the provider;
  retries increment this count.
- **Tokens** — provider-reported input/output usage when available.
- **E2E latency** — wall-clock from accepted run start to final result; parallel
  worker durations are not summed.
- **Calculated cost** — model price-table calculation from recorded usage when a
  price is known; otherwise leave it unavailable.

These three execution/call/request counts must remain separately observable in
run evidence and UI metrics.

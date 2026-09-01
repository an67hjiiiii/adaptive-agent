# Pilot manifest registry

This registry names the current prepared successor for a future Pilot. Every
manifest under `runs/pilot/` is local preparation/evidence; historical files
are preserved and are never silently overwritten or selected by directory
order.

## CANONICAL SUCCESSOR CANDIDATE (NOT AUTHORIZED)

- path: `runs/pilot/taskk-final-manifest-v7.json`
- manifest ID: `pm_b38bd5d7e85c`
- run manifest SHA-256: `b38bd5d7e85c677facad22c18f52e9b0da1fb02c46f6a89e987aa09ecdcf93f0`
- predecessor: `runs/pilot/taskh-final-manifest-v5.json` (`pm_9eced06dc61e`)
- benchmark binding: `pilot_benchmark_v1@1.1.0`
- corpus binding: `PILOT-CORPUS-V1`
- quality/QEP binding: `PILOT-RUBRIC-V1.0` / `QEP-1.1`
- provider/model: `groq` / `openai/gpt-oss-120b`
- model settings: `MODEL-SETTINGS-V1`
- strategy/config identities: `SINGLE-DIRECT-V1`, `FIXED-TOPOLOGY-V1`,
  `STATIC-PRESETS-V1`, `ORCH-ADAPTIVE-AUTO-V1`
- units/conditions: `24` / `96`
- order: balanced Latin square, top-level sequential
- packet registry: `evaluation/pilot/pilot_evaluator_packets_v2_taskk.json`
  (`PILOT-EVALUATOR-PACKETS-V2` v2.0, 96 `PLANNED` packets, evaluator slots
  `UNASSIGNED`)
- preparation status: `PREPARED`, not executed
- authorization: `UNBOUND`
- live window: `UNBOUND`
- fresh provider preflight: `UNBOUND`; historical stale preflight is not
  accepted as a live binding

Checkout provenance is part of the successor's hashed `configuration`:
commit `e5d1c49fb58b8597b79fd516ec3dfad7f9017ff2` on `master`, Git tree
`5924d0f83f9aa0ba9cacb5a359c9472a80870cda`. This is the post-UI baseline
source tree against which the successor was prepared; the later artifact commit
only records the successor/registry files and does not change runtime semantics.

## PREDECESSOR / HISTORICAL (PRESERVED)

- `runs/pilot/taskh-final-manifest-v5.json` (`pm_9eced06dc61e`) — strongest
  validated predecessor; unchanged.
- `runs/pilot/taskj-final-manifest-v6.json` (`pm_fc24a4e14c47`) — historical
  candidate, unchanged; its old preflight is stale and its manifest-level
  rubric references were null, so it is not the successor.
- `evaluation/pilot/pilot_evaluator_packets_v1.json` — V1 packet registry is
  preserved unchanged (`PILOT-EVALUATOR-PACKETS-V1`, 96 planned packets).
- `evaluation/pilot/pilot_evaluator_packets_v2.json` — historical Task J V2
  generation is preserved unchanged; the Task K packet file above is the new
  successor binding.

Other generated manifests under `runs/pilot/` remain archived preparation
outputs. No raw evidence is removed by this registry. No Pilot condition,
Main run, live provider request, authorization, live window, or fresh preflight
was created by successor preparation.

The owner still must complete evaluator staffing, explicit
`AUTHORIZE_PILOT_EXECUTION`, a timezone-aware live window, one fresh
successor-bound preflight, and the final Pilot Freeze before any execution.

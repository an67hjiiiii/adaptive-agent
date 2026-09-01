# Pilot manifest registry

This registry names the one manifest candidate that may be used for a future
Pilot after the final gate.  Generated manifests in `runs/pilot/` are local
evidence and are never silently deleted.

## CANONICAL PILOT MANIFEST CANDIDATE

- path: `runs/pilot/taskh-final-manifest-v5.json`
- manifest ID: `pm_9eced06dc61e`
- run manifest SHA-256: `9eced06dc61ef8dc7ec61b543eb5e8bb97067c4eb10b07d77590d92839bbb028`
- benchmark binding: `pilot_benchmark_v1@1.1.0`
- provider/model: `groq` / `openai/gpt-oss-120b`
- units/conditions: `24` / `96`
- order: balanced Latin square, top-level sequential
- preparation status: `PREPARED`, not executed
- freeze identity: `PILOT-FREEZE-CANDIDATE-V1`

This candidate was generated after the Task H RAG settings, evidence-gate,
and quality-denominator alignment changes. A fresh successful Groq PREFLIGHT
now exists (see `docs/GROQ_PILOT_PREFLIGHT.md`), but it is not embedded as a
`preflight_binding` in this candidate; explicit binding plus the remaining
research sign-offs are required before any live Pilot command is accepted.

## SUPERSEDED / HISTORICAL

- `taskc-final-manifest-v3.json` (`pm_d4d1956fdf05`) — `SUPERSEDED`; it was
  prepared before the RAG settings and manifest-integrity changes.
- `taskh-final-manifest-v4.json` (`pm_e2d1221f6f2a`) — `SUPERSEDED`; it was
  prepared before the final Case C denominator identity alignment.
- `taskc-final-manifest-v2.json` and older `prepared-*` manifests —
  `ARCHIVED` historical preparation outputs; do not resume or export them as
  Pilot evidence.
- All other generated manifest files under `runs/pilot/` (including `fixd-*`,
  `taskfixc-*`, and `taskc-final-manifest.json`) are `ARCHIVED` unless named
  above. Directory order is never a selection rule; only the canonical v5
  path may be proposed for a future gate.

No raw evidence is removed by this registry.  A new frozen manifest requires a
new path, ID, hash, and explicit registry entry.

The Task H integration gate remains `NOT_PILOT_READY`: this prepared candidate
is not a Pilot authorization or a Main Freeze. Do not execute its 96
conditions until the recorded research-side P1 sign-offs and preflight
binding are complete.

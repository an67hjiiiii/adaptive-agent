# Product V1.2 Context Scope + Active Project Integration

## Track A: Context Scope Router

PASS. `GENERAL` permits normal model knowledge without a no-source abstention;
`SOURCE_REQUIRED` retains the V1.1 project/context grounding policy. The local
scope decision is independent from `DIRECT`, `PARALLEL`, and `PLANNED`, and it
adds no provider classifier request.

## Track B: Active Project Context UX

PASS. The active workspace is represented by the compact `Đang dùng` indicator.
Draft attachments remain separate. Send/follow-up retain the active project;
detach, New Chat, and conversation switching clear or restore it by conversation.

## Asset version

Production static assets are consistently `v39`. There were no `v38` test or
runtime assertions to reconcile, and no asset bump was needed.

## Integration evidence

| Contract | Result |
| --- | --- |
| General, no project | PASS — `GENERAL`; deterministic Fake result is not source-abstained. |
| Active project + general | PASS — workspace remains stored but is absent from the execution snapshot. |
| General then project follow-up | PASS — later project request is `SOURCE_REQUIRED` and receives RAG workspace context. |
| Missing project evidence | PASS — `SOURCE_REQUIRED`; deterministic Fake preserves insufficient-evidence result. |
| Explicit source request | PASS — `README.md` request is source-required with selected source identity. |
| Remove project / New Chat | PASS — detach prevents stale workspace metadata; a new conversation has no prior workspace. |
| Normal attachment | PASS — `notes.txt` remains an attachment source, not an active project workspace. |

## Validation

- V1.2 focused suites: 14/14 PASS (`context_scope` + `active_project_ui`).
- V1.2 integration suite: 4/4 PASS.
- V1.1 project regression: 30/30 PASS.
- Relevant chat/orchestrator regression: 18/18 PASS.
- `node --check app/static/app.js`: PASS.
- `git diff --check`: PASS.

## Changes and boundaries

No production integration fix was required. This integration adds
`tests/test_product_v12_integration.py` and this report only. `app/core/rag.py`,
strategy definitions, provider configuration, Research/Pilot artifacts, and live
providers were not changed or invoked.

## Known gaps

The checks are deterministic/Fake and do not establish current-world factual
accuracy, browser E2E behavior, or live-provider answer quality. V1.2 adds no
web search.

## Decision

`PRODUCT_V12_READY_FOR_LIVE_PRODUCT_TEST`

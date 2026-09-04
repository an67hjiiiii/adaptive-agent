# Product V1.1 Integration Report

## V1.1 build state

Wave 3 validated the local-project-understanding connection with local,
deterministic fixtures and Fake/mocked execution only. No live provider,
semantic quality evaluation, browser E2E, Research, or Pilot activity was run.

## Track status

| Track | Status | Evidence |
| --- | --- | --- |
| V11-A Context | PASS | 4 focused tests: safe relative paths, format/size limits, flat-file compatibility, and 20-source boundary. |
| V11-B RAG | PASS | 6 focused tests: deterministic bounded manifests, path-aware retrieval, flat-file compatibility, and unsafe-path removal. |
| V11-C API/chat wiring | PASS | 4 focused Fake/API tests: workspace handoff, normal attachments, invalid references, and attachment-free chat. |
| V11-D frontend UX | PASS | 6 static tests plus `node --check app/static/app.js`: folder menu, path/noise/extension filtering, bounds, attachment states, and synchronized assets. |

## Fixtures

| Fixture | Useful files | Result |
| --- | ---: | --- |
| S (`small`) | 5 | PASS — nested routes and obvious entry point. |
| M (`medium`) | 10 | PASS — multiple route/service candidates. |
| L (`large`) | 20 | PASS — nested structure, duplicate route basenames, and irrelevant content. |

## Integration acceptance

- Ingestion: PASS. Every useful fixture file passes the canonical preparation contract with a safe project-relative source identity.
- Project structure: PASS. Workspace source blocks are canonicalized by Simple RAG into deterministic, sorted, bounded manifests.
- Retrieval and provenance: PASS. Known `app/main.py` and `services/user_service.py` paths participate in selected chunks and remain relative; no absolute path is emitted.
- API handoff: PASS with mocked execution. Prepared workspace context reaches normal `/api/chat/stream` and selected sources reach assistant/evidence metadata.
- Normal attachments: PASS. Attachment-free and flat-file flows remain covered.
- Limits and noise: PASS. 20 accepted, 21 rejected; noise is segment-based, so `src/build_helper.py` remains eligible while `build/output.js` is excluded.
- Cross-conversation: PASS. A workspace in conversation A is absent from conversation B.

## Test evidence

- Focused track suite: **20/20 PASS**.
- Shared V1.1 integration suite: **11/11 PASS**.
- Relevant regression slice: **62/62 PASS**.
- Static syntax: `node --check app/static/app.js` PASS.

## Production fixes

None in Wave 3. The integration tests found no A/B/C/D connection defect requiring a production change. Existing uncommitted track changes were preserved.

## Known gaps

Live-provider semantic quality and manual browser E2E remain intentionally unverified; they are outside this deterministic plumbing acceptance task.

## Decision

**PRODUCT_V11_READY_FOR_REAL_REPO_TEST**

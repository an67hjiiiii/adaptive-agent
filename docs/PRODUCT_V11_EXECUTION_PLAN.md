# Product V1.1 — Local Project Understanding Execution Plan

**Mode:** implementation planning only. No production or test file is changed by this document.  The current baseline already contains most of the V1.1 path; the plan therefore extends the existing contracts rather than introducing a second ingestion or retrieval architecture.

## 1. Current implementation map

| Capability | Current implementation point | Current responsibility | V1.1 disposition |
| --- | --- | --- | --- |
| A. File/context preparation | `app/core/context_files.py::prepare_context_file`; `_safe_filename`; `_decode_content`; `_normalize_text`; `normalize_relative_path`; `normalize_context_sources` | Validates one UTF-8 textual file, byte/format/name limits, safe optional project-relative identity, deterministic `ctx_...` source identity, and the 20-source cap. | Reuse this canonical contract for every discovered file; do not add a second parser or upload store. |
| B. Supported formats | `PRODUCT_CONTEXT_EXTENSIONS` / `SUPPORTED_CONTEXT_EXTENSIONS` and `_safe_filename(..., require_supported=True)`; `app/main.py::config`; `app/static/app.js::loadConfig` and `supportedProjectFiles` | Server is the authority for TXT/MD/PY/JS/TS/JSON/HTML/CSS/CSV; `/api/config` exposes the list and the browser uses it for `accept` and folder filtering. | Keep one server-provided allow-list. A folder file is accepted only after extension, path, and content validation. |
| C. Request/API entry point | `app/main.py::ContextFileRequest`, `ProjectWorkspaceFileRequest`, `ProjectWorkspaceRequest`, `ChatRequest`; `/api/context/prepare`; `/api/conversations/project-workspace`; `/api/chat/stream`; `project_relevance_gate`; `workspace_context`; `workspace_selected_sources` | Receives prepared file bytes, stores the existing small project workspace contract, adds project context only for project-relevant questions, and maps selected RAG chunks back to source metadata. | Preserve these endpoints and normal chat semantics. Only align the V1.1 request/source contract and boundary validation where required. |
| D. Simple RAG indexing/retrieval | `app/core/rag.py::normalize_source`, `terms`, `chunk_text`, `_safe_project_path`, `_project_context`, `_chunk_records`, `frozen_snapshot` | Parses `[PROJECT STRUCTURE]` / `[RETRIEVED CONTEXT]` without interpreting code, chunks files, scores content with a capped path signal, bounds project selection to six chunks, and emits deterministic snapshot/provenance metadata. | Reuse lexical Simple RAG; make the project envelope, deterministic ordering, and path-aware provenance explicit. No vector/AST index. |
| E. Source metadata | `prepare_context_file` source object; `normalize_context_sources`; `frozen_snapshot` `source_documents`/`selected_chunks`; `workspace_selected_sources`; frontend `safeContextFilename`, `sourceFilename`, `sourceEntries`, `renderUserAttachments`, `renderContextAttachments` | Carries filename, optional `relative_path`, source id, parser and counts through preparation, retrieval, persistence, evidence, and rendered chips/source labels. | Relative path is the display and retrieval identity; preserve duplicate basenames by path and never expose a local absolute path. |
| F. Attachment UI | `app/static/index.html` `#contextFile`, `#contextFolder`, `#attachmentMenu`, `#chooseFiles`, `#chooseFolder`; `app.js::processContextFile`, `folderRelativePath`, `isProjectNoise`, `supportedProjectFiles`, `importProjectFolder`, `projectStructure`, `rebuildContextFromAttachments`, `renderContextAttachments`; `.attachment-menu` / `.composer-attachments` CSS | Supports ordinary multi-file attachments and local `webkitdirectory` selection, filters noise, sorts paths, builds the project envelope, shows chips/states, and submits the existing workspace request. | Keep ordinary attachment flow unchanged; add only the minimum folder UX/contract work. If static content changes, bump CSS/JS cache versions together exactly once (current baseline is `v38`). |
| G. Chat request payload | `app.js::activeContextForRequest`, `contextSourcesForRequest`, `runChat`; `app/main.py::ChatRequest` and `chat` | Sends `message`, active context, `context_sources`, provider/model/mode, conversation id, and bounded history; backend freezes context before Adaptive execution. | Add no new chat protocol. Project context remains opt-in through the existing relevance gate and source metadata remains attached to the answer/evidence. |

### Baseline conclusion

The smallest V1.1 implementation is a contract-and-test hardening pass over the points above: browser discovery produces safe relative paths, the existing preparation contract validates each file, the existing project envelope feeds Simple RAG, and the existing chat path receives only bounded frozen context. The server must never walk a user directory, execute uploaded code, or infer project facts outside supplied text.

## 2. Minimal V1.1 design

1. Freeze one `ProjectFile` shape at the boundary: `filename`, `relative_path`, and validated textual `content`, with the existing source metadata attached after preparation.
2. In the browser, derive `webkitRelativePath` to a normalized project-relative path, remove the selected root directory, reject empty paths, filter the existing noise-directory set (`.git`, `node_modules`, `.venv`, `venv`, `__pycache__`, `dist`, `build`, `coverage`, `.next`), keep the server-provided extension list, sort by path, and enforce `MAX_PROJECT_FILES = 20`.
3. Send each accepted file through `/api/context/prepare`; reject unsafe paths, unsupported formats, empty content, invalid UTF-8, and the existing 100,000-byte boundary using the current error contract.
4. Build the deterministic envelope with `[PROJECT STRUCTURE]`, sorted relative paths, `[RETRIEVED CONTEXT]`, and `SOURCE: <relative_path>` blocks. Do not add AST parsing, code execution, or a new index.
5. Let `frozen_snapshot` perform the existing lexical retrieval. Content overlap remains primary; path overlap is only a capped structural hint. Snapshot ids, selected chunk order, and source paths remain deterministic and inspectable.
6. Keep the current `project_relevance_gate` separate from Adaptive topology. Project questions can retrieve the saved envelope; greetings, arithmetic, and ordinary non-project attachments retain their current path.
7. Render source identity from the safe relative path in chips, answer/footer source surfaces, and evidence. A duplicate basename is valid when its relative paths differ.

## 3. Exclusive ownership matrix

Every production file has one and only one implementation-track owner. Other tracks may read the contract but may not edit the owner’s file.

| File | Track owner | Functions/blocks owned | Other tracks read-only |
| --- | --- | --- | --- |
| `app/core/context_files.py` | `V11-A` | `_safe_filename`, `normalize_relative_path`, `_decode_content`, `_normalize_text`, `prepare_context_file`, `normalize_context_sources`, format/size constants | `V11-B`, `V11-C`, `V11-D` |
| `app/core/rag.py` | `V11-B` | `chunk_text`, `_safe_project_path`, `_project_context`, `_chunk_records`, `frozen_snapshot`, project retrieval constants | `V11-A`, `V11-C`, `V11-D` |
| `app/main.py` | `V11-C` | request models, `config`, `prepare_context`, `save_project_workspace`, `chat`, `project_relevance_gate`, `workspace_context`, `workspace_selected_sources` | `V11-A`, `V11-B`, `V11-D` |
| `app/static/app.js` | `V11-D` | config/model-independent attachment handling, folder discovery/filtering, project envelope construction, attachment render/handlers, `runChat` payload wiring | `V11-A`, `V11-B`, `V11-C` |
| `app/static/index.html` | `V11-D` | attachment inputs/menu and related ids/markup | `V11-A`, `V11-B`, `V11-C` |
| `app/static/styles.css` | `V11-D` | attachment/project-workspace presentation classes and cache-version-related static assertions | `V11-A`, `V11-B`, `V11-C` |
| `tests/test_project_understanding_v11.py` | Wave 3 integration owner only | Existing shared fixture, RAG, path-safety, product-isolation, and UI contract baseline | All implementation tracks read-only; no parallel edits |
| `tests/fixtures/v11_projects/**` and `tests/fixtures/v11_evaluation/cases.json` | Wave 3 integration owner only | Acceptance fixtures/cases (5, 10, 20 useful files) | All implementation tracks read-only; generated `__pycache__`/`.pyc` is never a source fixture |

Proposed focused test files are deliberately separate from the existing shared test: `tests/test_project_understanding_v11_context.py` (`V11-A`), `tests/test_project_understanding_v11_rag.py` (`V11-B`), `tests/test_project_understanding_v11_api.py` (`V11-C`), and `tests/test_project_understanding_v11_ui.py` (`V11-D`). They are future track outputs, not files created by this planning task.

## 4. Conflict matrix

| Pair/resource | Conflict | Safe rule |
| --- | --- | --- |
| `V11-A` ↔ `V11-B` | Both consume the source/envelope contract; changing field names or markers while the other track is coding would invalidate retrieval assumptions. | Freeze `ProjectFile` fields, markers, limits, and path rules before Wave 1. With that contract frozen, A and B may run in parallel and must not edit each other’s file. |
| `V11-A` ↔ `V11-C` | API models and error responses depend on preparation/source validation. | C reads A’s contract and waits for the contract handoff; C never duplicates validation in `main.py`. |
| `V11-B` ↔ `V11-C` | `workspace_context` and chat metadata depend on RAG markers, source paths, and snapshot fields. | C waits for B’s envelope/provenance contract; only B edits RAG behavior. |
| `V11-C` ↔ `V11-D` | `runChat` and folder import depend on exact endpoint names, payload fields, and response shape. | C owns the API. D starts only after the API contract is frozen (recommended serial order C → D). |
| Any track ↔ shared V1.1 test/fixtures | The existing test file and fixture tree are shared state; fixture-generated `.pyc` can look like source. | Read-only during Waves 1–2. Wave 3 alone updates integration assertions or fixture hygiene if a direct regression proves it necessary. |
| Any track ↔ Research/Evaluation/Pilot | Those areas have different evidence and execution semantics. | Hard boundary: no reads, edits, live provider calls, or Pilot/research changes. |

## 5. Parallel implementation tracks

### TRACK V11-A — Project ingestion/context

- **Goal:** Own the canonical safe preparation contract for 5–20 local textual files.
- **Exact production files owned:** `app/core/context_files.py` only.
- **Exact functions/blocks:** `_safe_filename`, `normalize_relative_path`, `_decode_content`, `_normalize_text`, `prepare_context_file`, `normalize_context_sources`, and their existing constants.
- **Test files owned:** proposed `tests/test_project_understanding_v11_context.py` only.
- **Read-only dependencies:** `app/main.py` request models/endpoints, browser path fields in `app/static/app.js`, existing V1.1 test and fixtures.
- **Forbidden files/areas:** `app/core/rag.py`, `app/main.py`, all `app/static/*`, persistence/schema code, provider code, `research/`, `evaluation/`, `runs/pilot/`, benchmark artifacts.
- **Dependency:** start after the shared `ProjectFile`/source contract is frozen; no implementation output from another track is required.
- **Can run parallel with:** `V11-B`.
- **Must wait for:** contract freeze before Wave 1; Wave 3 before touching the shared existing test.
- **Expected change:** reuse/harden server-side format, UTF-8, byte, empty-content, filename, relative-path, deduplication, and 20-file checks; no upload directory and no execution.
- **Recommended test tier:** T0/T1 focused unittest.
- **Acceptance:** 20 valid sources are retained, 21 is rejected; 100,000 bytes is accepted and 100,001 rejected; duplicate basenames remain distinct by safe relative path; unsafe/absolute/traversal paths fail closed.

### TRACK V11-B — Project structure/retrieval

- **Goal:** Make the project manifest and Simple RAG retrieval deterministic, bounded, and path-aware without changing the retrieval architecture.
- **Exact production files owned:** `app/core/rag.py` only.
- **Exact functions/blocks:** `normalize_source`, `terms`, `chunk_text`, `_safe_project_path`, `_project_context`, `_chunk_records`, `frozen_snapshot`, and project retrieval settings/constants.
- **Test files owned:** proposed `tests/test_project_understanding_v11_rag.py` only.
- **Read-only dependencies:** V11-A’s frozen source/envelope contract, `app/main.py::workspace_context` and `workspace_selected_sources`, V1.1 fixtures/cases.
- **Forbidden files/areas:** `app/core/context_files.py`, `app/main.py`, all `app/static/*`, vector/GraphRAG/AST code, persistence schema, providers, research/evaluation/Pilot.
- **Dependency:** the marker/source-path contract must be frozen before coding; no A implementation details beyond that contract are needed.
- **Can run parallel with:** `V11-A` after contract freeze.
- **Must wait for:** V11-A/B contract review before V11-C begins.
- **Expected change:** reuse `[PROJECT STRUCTURE]`/`[RETRIEVED CONTEXT]`, sorted source paths, capped path contribution, deterministic chunk/snapshot ids, and bounded project selection.
- **Recommended test tier:** T0/T1 focused unittest.
- **Acceptance:** 5-, 10-, and 20-file fixtures produce stable manifests and hashes; relevant content wins over a path-only hint; selected metadata retains correct relative paths; no absolute path or code execution appears.

### TRACK V11-C — API/chat integration

- **Goal:** Connect the validated project contract to the existing product chat flow while preserving ordinary attachments and Adaptive/provider/model semantics.
- **Exact production files owned:** `app/main.py` only.
- **Exact functions/blocks:** `ContextSource`, `ChatRequest`, `ContextFileRequest`, `ProjectWorkspaceFileRequest`, `ProjectWorkspaceRequest`; `config`, `prepare_context`, `save_project_workspace`, `chat`, `project_relevance_gate`, `workspace_context`, `workspace_selected_sources`.
- **Test files owned:** proposed `tests/test_project_understanding_v11_api.py` only.
- **Read-only dependencies:** V11-A preparation errors/source fields, V11-B envelope/RAG metadata, existing conversation-storage interface invoked by `main.py`, frontend payload expectations.
- **Forbidden files/areas:** `app/core/context_files.py`, `app/core/rag.py`, all `app/static/*`, database migrations/schema redesign, provider adapters, research/evaluation/Pilot.
- **Dependency:** waits for both Wave 1 contracts; API shape must be written down before frontend implementation.
- **Can run parallel with:** none by default; a second engineer may review only. V11-D must not edit `main.py`.
- **Must wait for:** V11-A and V11-B handoff, then V11-D and Wave 3 consume the stable API.
- **Expected change:** preserve the existing `/api/context/prepare`, workspace endpoint, chat stream, relevance gate, frozen context, and attached-source metadata; add no second chat path.
- **Recommended test tier:** T1 focused API/Fake tests.
- **Acceptance:** safe 5–20-file workspace reaches a project question with path-aware sources; >20/unsafe/invalid files return truthful bounded errors; a normal single-file attachment and non-project chat remain unchanged.

### TRACK V11-D — Frontend local-project UX

- **Goal:** Deliver the smallest local folder selection and project-file presentation using the existing backend contract.
- **Exact production files owned:** `app/static/app.js`, `app/static/index.html`, and `app/static/styles.css`.
- **Exact functions/blocks:** `loadConfig`, `activeContextForRequest`, `contextSourcesForRequest`, `processContextFile`, `folderRelativePath`, `isProjectNoise`, `supportedProjectFiles`, `importProjectFolder`, `projectStructure`, `rebuildContextFromAttachments`, `renderContextAttachments`, attachment-menu/input handlers; the related HTML ids and CSS classes.
- **Test files owned:** proposed `tests/test_project_understanding_v11_ui.py` only, plus `node --check app/static/app.js` as a focused static check.
- **Read-only dependencies:** V11-C endpoint/request/response contract, V11-A supported extensions and path rules, V11-B envelope markers, existing UI baseline tests.
- **Forbidden files/areas:** `app/main.py`, `app/core/context_files.py`, `app/core/rag.py`, persistence/schema, provider/model, research/evaluation/Pilot; no unrelated visual redesign.
- **Dependency:** starts only after V11-C freezes the API shape and after A/B field names are stable.
- **Can run parallel with:** none in the recommended safe order; it may only be parallelized with C if the API contract is frozen and neither track changes it.
- **Must wait for:** V11-C handoff; then Wave 3 integration and any asset-version assertion update.
- **Expected change:** preserve the accepted UI, add/retain file/folder menu, noise filtering, 20-file message, deterministic relative-path chips/manifest, retry/removal states, and synchronized static asset query versions (current `v38`, bump once only if necessary).
- **Recommended test tier:** T0 static/Node checks; browser E2E is not part of this implementation map.
- **Acceptance:** folder picker exposes `webkitdirectory`; only supported, non-noise files are submitted; 20 is accepted and 21 is rejected visibly; relative paths and duplicate basenames remain visible; ordinary file selection still works.

## 6. Dependency waves

### WAVE 1 — Independent contract implementations

Run `V11-A` and `V11-B` concurrently after the shared data/marker contract is frozen. They own disjoint production files and disjoint proposed focused tests. Neither edits `app/main.py`, the frontend, or the shared existing V1.1 test.

### WAVE 2 — Contract consumers

Run `V11-C` first against the A/B handoff and freeze the API payload/response shape. Then run `V11-D` against that frozen API. This serial C → D order is the default conflict-safe choice; parallel C/D is allowed only when the API schema is immutable and explicitly reviewed before both start.

### WAVE 3 — Single integration task

Quiesce all track writers. The integration owner reads the four focused test outputs, runs the focused V1.1 slice, checks `node --check`, validates the 5/10/20 fixtures and asset references, then runs the reserved relevant product regression once. Only this wave may edit `tests/test_project_understanding_v11.py` or fixture hygiene, and only for a proven integration/isolation failure. No live model, browser E2E, provider, Pilot, or research work is part of Wave 3 of this plan.

## 7. Dependency graph and recommended order

```text
Freeze ProjectFile + envelope + limits
             |
       +-----+-----+
       |           |
   V11-A ingest  V11-B RAG
       \           /
        \         /
          V11-C API/chat
                |
          V11-D frontend UX
                |
          Wave 3 integration
```

Recommended execution order:

1. Freeze the source fields, markers, error codes, limits, and no-execution/security invariants.
2. Start `V11-A` and `V11-B` in parallel; review their contracts before merging.
3. Implement `V11-C` using only the reviewed A/B outputs; keep normal chat and attachment behavior intact.
4. Implement `V11-D` against the frozen C API; update CSS/JS cache references only if actual static content changed.
5. Stop all parallel work, integrate once in Wave 3, and run the focused checks plus one relevant product regression.
6. Record any live semantic or manual-browser evidence as a separate follow-up; do not relabel local/static evidence as live quality proof.

## 8. Acceptance criteria

| Area | Required evidence |
| --- | --- |
| Fixture A | A deterministic 5-useful-file project is discovered, noise is excluded, safe relative paths are preserved, and all expected files are represented. |
| Fixture B | A deterministic 10–20-useful-file project is discovered and bounded at 20; a 21st accepted file is rejected before workspace/chat submission. |
| Safety/boundaries | `.git`, `node_modules`, `.venv`, `venv`, `__pycache__`, `dist`, `build`, `coverage`, and `.next` are excluded; unsupported, empty, oversized, invalid UTF-8, absolute, traversal, and mismatched basename/path cases fail closed. |
| Structure | Manifest is sorted and compact, contains no local absolute path, and is carried by the existing project envelope markers. |
| Retrieval | Existing Simple RAG is deterministic and bounded; strong content relevance beats a weak filename/path hint; selected chunks expose correct `relative_path` source identity. |
| Product flow | Project questions use the existing relevance gate and chat stream; greetings/arithmetic and ordinary single-file attachments keep their current behavior. |
| Presentation | Project-file chips, answer/footer sources, and evidence use safe relative paths; duplicate basenames remain distinguishable; retry/removal states stay truthful. |
| Security/scope | No uploaded code is executed, no shell/filesystem walk is introduced, no provider is called by tests, and no Research/Pilot artifact changes. |

## 9. Explicit out of scope

- GitHub clone/import.
- ZIP ingestion.
- GraphRAG or vector databases.
- AST/framework indexing.
- Coding Agent, shell execution, or code-modification Agent behavior.
- Large-repository indexing beyond the 5–20 useful-file target.
- Database migration or new persistence architecture.
- New provider, model, retry architecture, or Adaptive policy change.
- Live LLM evaluation, manual E2E as an implementation dependency, provider benchmarking, Research, or Pilot changes.
- Unrelated UI redesign, asset churn, repository refactor, or opportunistic cleanup.

## Plan handoff

**Production owners:** 4 tracks over 6 production files, with no shared production owner.  **Wave order:** A+B parallel → C → D → one Wave 3 integration.  **Expected future file count:** up to 4 new focused test files plus the existing shared test remaining integration-only; no files are created by this planning task.  **Current task result:** documentation only; no code/test execution performed.

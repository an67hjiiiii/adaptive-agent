# Adaptive Agent Lab — project map

## Purpose

This is a local research prototype for adaptive multi-agent LLM orchestration.
It studies quality, latency, and cost trade-offs; it is not a generic chatbot.

## Source of truth

- Stable research semantics: `docs/PROJECT_CONTRACT.md`.
- Verified implementation facts and known discrepancies: `docs/CURRENT_STATE.md`.
- Correctness evidence for the adaptive controller: `docs/ORCHESTRATION_AUDIT.md`.
- Feature-to-test coverage: `docs/TEST_MATRIX.md`.
- If code, tests, and prose disagree, report the conflict before changing code.

## Important paths

- `app/main.py` — FastAPI app, HTTP contracts, persistence, compare endpoint.
- `app/core/orchestrator.py` — routing, agent calls, verification, budgets.
- `app/core/graph.py` — DAG validation and ready-set scheduling.
- `app/core/rag.py` — lexical retrieval and Frozen Context Snapshot.
- `app/core/provider_diagnostics.py` — normalized live-provider diagnostics and safe error taxonomy.
- `app/core/types.py` — run state, usage, provider result, budgets.
- `app/providers/` — Fake, Gemini, OpenAI, Groq, and OpenRouter adapters.
- `app/static/` — the served browser UI (`index.html`, `app.js`, `styles.css`).
- `tests/test_runtime.py` — unit, flow, API, security, and regression tests.
- `scripts/` — runtime check, fake smoke matrix, provider probe, server host.
- `runs/` — local JSON evidence and conversation persistence; generated only.

## Exact local commands (PowerShell)

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START_WINDOWS.ps1
```

Open `http://127.0.0.1:8000`. Direct fallback:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Validation:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app tests scripts
.\.venv\Scripts\python.exe scripts\runtime_check.py --write-test
.\.venv\Scripts\python.exe scripts\smoke_matrix.py --provider fake
node --check app\static\app.js
```

For a provider diagnostic (Fake is offline; live providers require explicit
approval): `python scripts\provider_probe.py <fake|gemini|openai|groq|openrouter>`.

## Anti-guessing rules

- Inspect the repository tree, definitions, call sites, and relevant tests first.
- Prefer actual runtime/code/tests over docs, then the research contract, then assumptions.
- Mark unavailable evidence `UNVERIFIED` or `TBD`; never turn network absence into provider FAIL.
- Work one bounded task at a time; make the smallest compatible patch.
- Run focused tests plus regression tests, then inspect the resulting file list.
- Do not silently change the research design or add hidden labels/routing scores.

## Secret handling

- Keep provider keys only in the local server-side `.env`.
- `.gitignore` must contain `.env`; never commit `.env`, virtualenvs, or run secrets.
- Never print, log, persist, document, or send API keys to frontend code or browser output.
- Use redacted errors and safe provider status only; do not expose key fingerprints.

## Definition of Done

- State is `PASS`, `PARTIAL`, or `BLOCKED` with root cause and evidence.
- Files changed and exact tests/results are reported; remaining blockers are explicit.
- Runtime behavior is unchanged for documentation-only tasks.
- No unrelated files are reformatted or rewritten.

## Out of scope

Mobile clients, microservices, Kubernetes, GraphRAG, autonomous browser agents,
coding agents, reinforcement learning/contextual bandits, and broad research redesign.

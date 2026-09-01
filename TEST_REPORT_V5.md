# Test Report — Adaptive Agent Lab v0.6

## Audit target

This build is a direct repair of the uploaded V4 project. The goal was not to redesign the research scope, but to make the current prototype easier to run, easier to understand, and closer to the capstone's Adaptive Orchestration contract.

## Important fixes verified

- Main chat always dispatches **Adaptive AUTO**; Single/Fixed/Static remain research baselines in Compare only.
- Current user task is separated from recent conversation context, so the Structural Analyzer does not accidentally classify old turns as part of the current task.
- Every persisted turn is returned as one grouped object (`user + assistant + run metadata`) and rendered as one `turn-card`.
- Sidebar conversations include title, latest question preview, turn count, provider, timestamp, rename and delete.
- Simple RAG produces a deterministic Frozen Context Snapshot.
- Analyzer validates structural JSON before routing.
- AUTO routing selects DIRECT / PARALLEL / PLANNED from aspects, dependency and verification demand.
- PARALLEL skips Planner and creates independent work directly from structural aspects.
- PLANNED validates the Planner DAG and executes Kahn-style ready sets.
- Independent ready nodes run concurrently with `asyncio.gather`.
- Runtime Verifier supports PASS / NEEDS_WORK / FAIL.
- NEEDS_WORK can create targeted repair workers within the escalation/budget limit.
- A usable candidate is preserved if the Runtime Verifier later becomes unavailable.
- Logical Model Calls and Physical Provider Requests are tracked separately.
- OpenAI/OpenAI-compatible SDK internal retries are disabled (`max_retries=0`) so retries are owned by the Orchestrator and physical-request accounting is not silently undercounted.
- Retry, timeout, logical-call budget, physical-request budget and escalation budget are enforced by runtime code.
- Provider API-test badges are invalidated when the server-side API key changes, using a one-way local fingerprint; an old green badge is not reused for a new key.
- Gemini adapter uses the Interactions API rather than the old Generate Content path.
- Groq and OpenRouter development adapters are available in addition to Gemini/OpenAI/Fake.
- Provider secrets are not exposed by `/api/config` or frontend assets.
- Context upload is limited to the backend's 100,000-character contract instead of failing later with an opaque 422.
- Old standalone preview HTML files were removed from the distributable project so the UI cannot be mistaken for the real FastAPI app again.

## Automated tests

Command:

```bash
python -m unittest discover -s tests -v
```

Result: **26/26 PASS**.

The same suite also passes when run directly with:

```bash
python tests/test_runtime.py
```

## Fake-provider research matrix

Command:

```bash
python scripts/smoke_matrix.py --provider fake
```

Result:

- simple -> **DIRECT / STOP_SUFFICIENT / PASS**
- independent multi-aspect -> **PARALLEL / STOP_SUFFICIENT / PASS**
- dependency-heavy -> **PLANNED / STOP_SUFFICIENT / PASS**
- conflict-sensitive -> **PLANNED + 1 targeted escalation / STOP_SUFFICIENT / PASS**

## Live FastAPI runtime check

A real local Uvicorn instance was started during QA and checked through HTTP.

- `/api/health` -> PASS (`adaptive-agent-lab`, version `0.6.0`)
- `/api/config` -> PASS
- static `app.js` -> HTTP 200 + no-store cache headers
- conversation persistence diagnostic -> PASS (2 turns / 2 runs in the same conversation)
- frontend JavaScript syntax (`node --check`) -> PASS
- Python compile check -> PASS

## External-provider limitation of this QA environment

No user API credential is included in this fixed archive. The sandbox QA therefore does not claim that a specific user's Gemini/Groq/OpenRouter/OpenAI account, billing, quota or key is valid. Use the in-app API Test after adding a key to the local `.env`.

## Main Experiment warning

`openrouter/free` is useful for development/demo but is not appropriate as the frozen provider/model for the Main Experiment because the router can choose different free backends. Freeze one provider + one model + one config before Main.

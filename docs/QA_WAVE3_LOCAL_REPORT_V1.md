# Adaptive Agent QA — Wave 3 Local Integration Report

## BUILD/WORKTREE STATE

- Wave 1/2 changes were present before reconciliation: `app/core/orchestrator.py` (Core Quality) and `app/main.py` (blank-prompt Product Boundary guard). They were preserved; no history or reset operation was used.
- Wave QA artifacts remained available in `tests/test_qa_p0_*.py`; Product browser cases have no local browser runner in this task.

## FILES INTEGRATED

- Context: `tests/test_qa_p0_context_boundary.py` (CTX-003).
- Core Quality: `app/core/orchestrator.py`, `tests/test_qa_p0_grounding_eval.py`, `tests/test_qa_p0_routing.py`, `tests/test_qa_p0_reliability.py`, `tests/test_qa_p0_performance.py`.
- Product Boundary: `app/main.py`, `tests/test_qa_p0_product_boundary.py` (CHAT-003).

## FOCUSED QA RESULT

The combined Wave slice passed: 9 tests, `OK`, using only `.venv\Scripts\python.exe`. No live provider, browser, Pilot, or research execution occurred.

## PRODUCT REGRESSION RESULT

The canonical discovery was run once: 217 tests, 4 failures, 1 error, 2 skipped. The two captured Project Understanding failures were reproduced; generated fixture `__pycache__/*.pyc` files were being treated as source. The fixture discovery filter was corrected and only those two affected tests were rerun; both passed. The remaining three failure outcomes were not reproducible from the truncated first-run output and were not investigated or rerun.

## P0 STATUS SUMMARY

### LOCAL AUTOMATED

- COVERED: 29
- FAILED: 0

### LIVE LLM

- READY: 9 (`GND-001`–`GND-007`, `SEC-003`, `SEC-005`)
- PASS: 0 (not executed)
- FAIL: 0 (not executed)

### MANUAL E2E

- REQUIRED: 7 (`CFG-003`, `CFG-004`, `CFG-005`, `PERSIST-002`, `PERSIST-003`, `ERR-002`, `UI-001`)
- PASS: 0 (not executed)
- FAIL: 0 (not executed)

## INTEGRATION FIXES

- Test-only hygiene: `tests/test_project_understanding_v11.py::fixture_files` now excludes `__pycache__` directories and `.pyc` files. No production behavior was changed.
- `docs/QA_COVERAGE_MATRIX_V1.md` was reconciled for all 45 P0 rows; no P0 remains `PARTIAL` or `MISSING`.

## KNOWN GAPS

- Live model grounding/security resistance and seven browser/manual Product gates remain open by policy. Full discovery had residual unidentified outcomes after the one allowed run; focused affected tests pass, so release-wide regression is not claimed.

## RELEASE STATE

Wave 3 local reconciliation is `PARTIAL`: local P0 evidence is green and honestly split from deferred live/manual gates, but the initial full-suite residuals prevent a full regression PASS claim. No research/Pilot artifacts or settings were changed.

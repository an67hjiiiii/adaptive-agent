"""Resume-safe execution of a frozen Pilot Run Manifest.

The executor is intentionally a control layer.  It resolves the benchmark's
runtime-safe task projection, creates one Frozen Context Snapshot per comparison
unit, and delegates every strategy run to ``app.main.execute_once``.  It does
not contain an orchestration implementation of its own.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Mapping

from app.core.pilot import (
    PILOT_STRATEGIES,
    PilotLedger,
    _reference_scope_summary,
    _normalized_task_records,
    _task_manifest_hash,
    control_state_from_status,
    validate_pilot_manifest,
    PILOT_FREEZE_IDENTITY,
)
from app.core.pilot_authorization import (
    AUTHORIZED_PILOT_SCOPE,
    DEFAULT_PROJECT_TIMEZONE,
    LocalPilotUsageLedger,
    PILOT_OWNER_ROLE,
    PILOT_PREFLIGHT_BINDING_SCHEMA_ID,
    PilotAuthorizationError,
    PreflightBindingError,
    validate_authorization_record,
    validate_live_window,
    validate_preflight_binding,
)
from app.core.incidents import safe_provider_incident
from app.core.rag import frozen_snapshot


class PilotExecutorError(RuntimeError):
    """A deterministic control or manifest error, not a provider response."""


class SnapshotFairnessError(PilotExecutorError):
    """The required comparison-unit snapshot cannot be kept identical."""


# A preflight is a live account/model/settings check, not a permanent
# capability badge.  Keep the acceptance window deliberately short so a
# changed key, model, or provider limit cannot silently reuse old evidence.
PILOT_PREFLIGHT_MAX_AGE_SECONDS = 15 * 60


class AsyncRequestPacer:
    """Strategy-neutral aggregate request limiter for live Pilot execution."""

    def __init__(self, *, requests_per_minute: int = 20, max_in_flight: int = 3, tokens_per_minute: int = 8000):
        self.interval = 60.0 / max(1, int(requests_per_minute))
        self.semaphore = asyncio.Semaphore(max(1, int(max_in_flight)))
        self.lock = asyncio.Lock()
        self.next_allowed = 0.0
        self.tokens_per_minute = max(1, int(tokens_per_minute))
        self.token_window: list[tuple[float, int]] = []

    async def acquire(self):
        await self.semaphore.acquire()
        try:
            loop = asyncio.get_running_loop()
            async with self.lock:
                now = loop.time()
                self.token_window = [item for item in self.token_window if now - item[0] < 60.0]
                used_tokens = sum(item[1] for item in self.token_window)
                wait_for = max(0.0, self.next_allowed - now)
                if used_tokens >= self.tokens_per_minute and self.token_window:
                    token_wait = max(0.0, 60.0 - (now - self.token_window[0][0]))
                    # Keep the request interval and token window additive: the
                    # stricter account-level constraint wins.
                    wait_for = max(wait_for, token_wait)
                self.next_allowed = max(now, self.next_allowed) + self.interval
            if wait_for:
                await asyncio.sleep(wait_for)
        except BaseException:
            self.semaphore.release()
            raise

        released = False

        def release():
            nonlocal released
            if not released:
                released = True
                self.semaphore.release()

        return release

    async def __call__(self):
        return await self.acquire()

    def record_tokens(self, tokens: int | None) -> None:
        if tokens is None:
            return
        try:
            value = max(0, int(tokens))
        except (TypeError, ValueError):
            return
        try:
            loop = asyncio.get_running_loop()
            now = loop.time()
        except RuntimeError:
            return
        self.token_window = [item for item in self.token_window if now - item[0] < 60.0]
        self.token_window.append((now, value))

    def note_retry_after(self, seconds: float | None) -> None:
        """Push the shared request window past a provider retry hint."""

        try:
            delay = max(0.0, float(seconds))
        except (TypeError, ValueError):
            return
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            return
        self.next_allowed = max(self.next_allowed, now + delay)


def _aware_timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise PilotExecutorError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PilotExecutorError(f"{field} must include a timezone offset")
    return parsed


class PilotLiveRequestGate:
    """Fail-closed operational gate shared by all live Pilot requests."""

    def __init__(
        self,
        *,
        manifest: Mapping[str, Any],
        preflight: Mapping[str, Any],
        authorization: Mapping[str, Any],
        live_window: Mapping[str, Any],
        usage_ledger: LocalPilotUsageLedger,
        pacer: AsyncRequestPacer,
    ):
        self.manifest = deepcopy(dict(manifest))
        self.preflight = deepcopy(dict(preflight))
        self.authorization = deepcopy(dict(authorization))
        self.live_window = deepcopy(dict(live_window))
        self.usage_ledger = usage_ledger
        self.pacer = pacer
        self._lock = asyncio.Lock()

    def validate(self, *, now: datetime | None = None) -> bool:
        reference = now or datetime.now(timezone.utc)
        try:
            validate_preflight_binding(self.preflight, manifest=self.manifest, now=reference)
            validate_authorization_record(
                self.authorization,
                manifest=self.manifest,
                preflight_binding=self.preflight,
                live_window=self.live_window,
                now=reference,
            )
            validate_live_window(self.live_window, now=reference, require_future=False)
        except PilotAuthorizationError as exc:
            raise PilotExecutorError(str(exc)) from exc

        if str(self.authorization.get("role")) != PILOT_OWNER_ROLE:
            raise PilotExecutorError("PILOT_AUTHORIZATION_ROLE_INVALID")
        if str(self.authorization.get("authorized_scope")) != AUTHORIZED_PILOT_SCOPE:
            raise PilotExecutorError("PILOT_AUTHORIZATION_SCOPE_INVALID")
        if str(self.authorization.get("status") or "").upper() != "AUTHORIZED":
            raise PilotExecutorError("PILOT_AUTHORIZATION_REQUIRED")
        if _aware_timestamp(self.authorization.get("timestamp"), field="authorization timestamp") > reference:
            raise PilotExecutorError("PILOT_AUTHORIZATION_NOT_YET_VALID")

        if str(self.live_window.get("status") or "").upper() != "ACTIVE":
            raise PilotExecutorError("PILOT_LIVE_WINDOW_NOT_ACTIVE")
        if self.live_window.get("manifest_id") != self.manifest.get("manifest_id"):
            raise PilotExecutorError("PILOT_LIVE_WINDOW_MANIFEST_MISMATCH")
        freeze = self.live_window.get("freeze_candidate_id") or self.live_window.get("freeze/candidate_id")
        if freeze != self.manifest.get("freeze_identity"):
            raise PilotExecutorError("PILOT_LIVE_WINDOW_FREEZE_MISMATCH")
        if self.live_window.get("authorization_id") != self.authorization.get("authorization_id"):
            raise PilotExecutorError("PILOT_LIVE_WINDOW_AUTHORIZATION_MISMATCH")

        before = _aware_timestamp(self.live_window.get("not_before"), field="not_before")
        after = _aware_timestamp(self.live_window.get("not_after"), field="not_after")
        if reference < before:
            raise PilotExecutorError("PILOT_LIVE_WINDOW_NOT_STARTED")
        if reference > after:
            raise PilotExecutorError("PILOT_LIVE_WINDOW_EXPIRED")
        return True

    def bind(self, *, unit_id: str, attempt_id: str, condition_id: str):
        parent = self

        class BoundGate:
            async def __call__(self):
                async with parent._lock:
                    now = datetime.now(timezone.utc)
                    parent.validate(now=now)
                    try:
                        parent.usage_ledger.guard_before_request(
                            requests=1,
                            estimated_tokens=1,
                            now=now,
                        )
                    except PilotAuthorizationError as exc:
                        raise PilotExecutorError(str(exc)) from exc
                    release = await parent.pacer.acquire()
                    try:
                        parent.usage_ledger.record(
                            requests=1,
                            tokens=None,
                            now=now,
                            unit_id=unit_id,
                            attempt_id=attempt_id,
                            condition_id=condition_id,
                        )
                    except Exception as exc:
                        release()
                        if isinstance(exc, PilotAuthorizationError):
                            raise PilotExecutorError(str(exc)) from exc
                        raise
                    return release

            def record_tokens(self, tokens: int | None) -> None:
                parent.pacer.record_tokens(tokens)
                if tokens is not None:
                    try:
                        parent.usage_ledger.record_token_observation(
                            tokens,
                            unit_id=unit_id,
                            attempt_id=attempt_id,
                            condition_id=condition_id,
                        )
                    except PilotAuthorizationError as exc:
                        raise PilotExecutorError(str(exc)) from exc

            def note_retry_after(self, seconds: float | None) -> None:
                parent.pacer.note_retry_after(seconds)

        return BoundGate()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_source_path(path_value: str, *, roots: list[Path]) -> Path:
    candidate_value = Path(path_value)
    if candidate_value.is_absolute():
        candidates = [candidate_value.resolve()]
    else:
        candidates = [(root / candidate_value).resolve() for root in roots]
    for candidate in candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        for root in roots:
            try:
                candidate.relative_to(root.resolve())
                return candidate
            except ValueError:
                continue
    raise PilotExecutorError(f"Referenced source file is unavailable or outside the workspace: {path_value}")


def _line_range(value: Any, *, source_id: str, section_id: str) -> tuple[int, int]:
    """Parse a frozen corpus section line range (1-based, inclusive)."""

    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", value)
        if match:
            start, end = (int(item) for item in match.groups())
        else:
            raise PilotExecutorError(f"Invalid line range for {source_id}/{section_id}")
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            start, end = (int(item) for item in value)
        except (TypeError, ValueError) as exc:
            raise PilotExecutorError(f"Invalid line range for {source_id}/{section_id}") from exc
    else:
        raise PilotExecutorError(f"Missing line range for {source_id}/{section_id}")
    if start < 1 or end < start:
        raise PilotExecutorError(f"Invalid line range for {source_id}/{section_id}")
    return start, end


def _scope_hash(scope: list[dict[str, Any]], source_hashes: list[str]) -> str:
    encoded = json.dumps(
        {"scope": scope, "source_document_hashes": source_hashes},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _scoped_source_text(
    *,
    task_id: str,
    source_id: str,
    source_text: str,
    source: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> str:
    """Resolve exactly the declared sections, or an explicit whole document."""

    normalized = source_text.replace("\r\n", "\n").replace("\r", "\n")
    if bool(binding.get("whole_document")):
        return f"[source_document:{source_id}]\n{normalized.strip()}"

    sections = source.get("sections")
    if not isinstance(sections, list):
        raise PilotExecutorError(f"Task {task_id} source {source_id} has no frozen section catalog")
    catalog = {
        _safe_text(item.get("section_id")): item
        for item in sections
        if isinstance(item, Mapping) and _safe_text(item.get("section_id"))
    }
    lines = normalized.split("\n")
    fragments: list[str] = []
    section_ids = [str(item) for item in (binding.get("section_ids") or [])]
    if not section_ids:
        raise PilotExecutorError(f"Task {task_id} source {source_id} has no declared section IDs")
    if len(section_ids) != len(set(section_ids)):
        raise PilotExecutorError(f"Task {task_id} source {source_id} declares duplicate section IDs")
    for section_id in section_ids:
        section = catalog.get(section_id)
        if section is None:
            raise PilotExecutorError(f"Task {task_id} references invalid section {source_id}/{section_id}")
        start, end = _line_range(section.get("line_range"), source_id=source_id, section_id=section_id)
        if end > len(lines):
            raise PilotExecutorError(f"Task {task_id} section {source_id}/{section_id} exceeds source line count")
        content = "\n".join(lines[start - 1:end]).strip()
        if not content:
            raise PilotExecutorError(f"Task {task_id} section {source_id}/{section_id} is empty")
        fragments.append(f"[reference_section:{section_id}]\n{content}")
    return f"[source_document:{source_id}]\n" + "\n\n--- referenced section ---\n\n".join(fragments)


def _section_catalog(source: Mapping[str, Any], *, source_path: Path, roots: list[Path]) -> Mapping[str, Any]:
    """Load the frozen section catalog without changing the corpus files.

    Some benchmark manifests inline source hashes/paths but keep the section
    catalog in the adjacent frozen ``CORPUS_MANIFEST.json``.  Both forms are
    accepted; no heuristic heading search is used.
    """

    if isinstance(source.get("sections"), list):
        return source
    candidates = [
        source_path.parent / "CORPUS_MANIFEST.json",
        *(root / "corpus" / "pilot" / "v1" / "CORPUS_MANIFEST.json" for root in roots),
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen or not candidate.exists() or not candidate.is_file():
            continue
        seen.add(candidate)
        try:
            manifest = _read_json(candidate)
        except (OSError, json.JSONDecodeError):
            continue
        for item in manifest.get("documents") or []:
            if isinstance(item, Mapping) and str(item.get("source_id")) == str(source.get("source_id")):
                return item
    return source


def _runtime_task_records(
    task_manifest: Mapping[str, Any],
    *,
    source_roots: list[str | Path],
) -> dict[str, dict[str, Any]]:
    """Build only the task projection permitted to reach the runtime.

    Research annotations, expected facts, rubric versions, and authoring notes
    are deliberately never read from the task record used to build prompts.
    """

    raw_tasks = task_manifest.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise PilotExecutorError("Task manifest must contain a non-empty tasks[] list")
    roots = [Path(item).resolve() for item in source_roots]
    corpus = {
        str(item.get("source_id")): item
        for item in (task_manifest.get("corpus_manifest") or [])
        if isinstance(item, Mapping) and item.get("source_id")
    }
    records: dict[str, dict[str, Any]] = {}
    for raw in raw_tasks:
        if not isinstance(raw, Mapping):
            raise PilotExecutorError("Every task manifest item must be an object")
        task_id = _safe_text(raw.get("task_id") or raw.get("id"))
        task_text = _safe_text(raw.get("task_text") or raw.get("message") or raw.get("prompt"))
        if not task_id or not task_text:
            raise PilotExecutorError(f"Runtime task projection is incomplete for {task_id or '<unknown>'}")
        if task_id in records:
            raise PilotExecutorError(f"Duplicate task_id: {task_id}")

        output_instruction = _safe_text(raw.get("expected_output_instruction"))
        message = task_text
        if output_instruction:
            message += f"\n\nOUTPUT REQUIREMENT:\n{output_instruction}"

        source_ids = [str(item) for item in (raw.get("reference_source_ids") or raw.get("source_document_ids") or [])]
        try:
            reference_scope = _reference_scope_summary(raw)
        except ValueError as exc:
            raise PilotExecutorError(f"Task {task_id} has invalid reference bindings: {exc}") from exc
        if reference_scope:
            scoped_source_ids = [str(item["source_id"]) for item in reference_scope]
            if source_ids and source_ids != scoped_source_ids:
                raise PilotExecutorError(f"Task {task_id} source IDs do not match reference_bindings")
            source_ids = scoped_source_ids
        if not source_ids:
            source_ids = [
                _safe_text(item.get("source_id"))
                for item in (raw.get("reference_scope") or [])
                if isinstance(item, Mapping) and _safe_text(item.get("source_id"))
            ]
        source_sections: list[str] = []
        source_hashes: list[str] = []
        resolved_scope: list[dict[str, Any]] = []
        binding_by_source = {str(item["source_id"]): item for item in reference_scope}
        inline_context = raw.get("context")
        if inline_context is None:
            inline_context = raw.get("reference_context")
        inline_context = _safe_text(inline_context)
        for source_id in source_ids:
            source = corpus.get(source_id)
            if not isinstance(source, Mapping) or not _safe_text(source.get("path")):
                raise PilotExecutorError(f"Task {task_id} references an unavailable source: {source_id}")
            path = _resolve_source_path(_safe_text(source["path"]), roots=roots)
            expected_hash = _safe_text(source.get("sha256"))
            actual_hash = _sha256_file(path)
            if expected_hash and actual_hash != expected_hash.lower():
                raise PilotExecutorError(f"Source hash mismatch for {source_id}: {path}")
            source_hashes.append(actual_hash)
            source_text = path.read_text(encoding="utf-8")
            binding = binding_by_source.get(source_id)
            if reference_scope and binding is None:
                raise PilotExecutorError(f"Task {task_id} source {source_id} has no reference binding")
            if binding is None:
                # A source ID without an explicit binding would make an
                # inline context an implicit whole-document escape hatch.
                # Close that path; only source-free infrastructure tasks may
                # provide inline context directly.
                raise PilotExecutorError(f"Task {task_id} source {source_id} has no explicit section scope or whole_document binding")
            source_sections.append(
                _scoped_source_text(
                    task_id=task_id,
                    source_id=source_id,
                    source_text=source_text,
                    source=_section_catalog(source, source_path=path, roots=roots),
                    binding=binding,
                )
            )
            resolved_scope.append(deepcopy(dict(binding)))

        context = inline_context
        if source_sections:
            context = "\n\n--- referenced source ---\n\n".join(source_sections)
        elif not context and source_ids:
            raise PilotExecutorError(f"Task {task_id} has source IDs but no resolved reference context")

        scope_hash = _scope_hash(resolved_scope, source_hashes) if resolved_scope else None

        normalized = _normalized_task_records({
            "tasks": [raw],
            "benchmark_id": task_manifest.get("benchmark_id") or task_manifest.get("manifest_id"),
            "benchmark_version": task_manifest.get("benchmark_version"),
            "pilot_version": task_manifest.get("pilot_version"),
            "rubric_version_reference": task_manifest.get("rubric_version_reference"),
            "reference_manifest_id": task_manifest.get("reference_manifest_id") or task_manifest.get("benchmark_id"),
            "reference_manifest_version": task_manifest.get("reference_manifest_version") or task_manifest.get("artifact_version"),
            "corpus_manifest": task_manifest.get("corpus_manifest") or [],
        })[0]
        records[task_id] = {
            "task_id": task_id,
            "task_hash": normalized["task_hash"],
            "task_version": normalized["task_version"],
            "benchmark_id": normalized.get("benchmark_id"),
            "benchmark_version": normalized.get("benchmark_version"),
            "benchmark_provenance_version": normalized.get("benchmark_provenance_version"),
            "message": message,
            "context": context,
            "source_document_ids": source_ids,
            "source_document_hashes": source_hashes,
            "reference_scope": resolved_scope,
            "reference_scope_hash": scope_hash,
        }
    return records


def snapshot_completeness_report(
    task_record: Mapping[str, Any],
    *,
    snapshot: str,
    retrieval_meta: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate that every declared reference section survives the snapshot.

    This is an offline research-side check.  It consumes only the runtime-safe
    task projection and stable section bindings; hidden rubric/expected-fact
    fields are never consulted or sent to a provider.
    """

    required: list[str] = []
    for binding in task_record.get("reference_scope") or []:
        source_id = str(binding.get("source_id") or "")
        for section_id in binding.get("section_ids") or []:
            required.append(f"{source_id}:{section_id}")
    present: list[str] = []
    for item in required:
        source_id, section_id = item.split(":", 1)
        source_marker = f"[source_document:{source_id}]"
        source_start = snapshot.find(source_marker)
        source_end = snapshot.find("[source_document:", source_start + len(source_marker)) if source_start >= 0 else -1
        source_text = snapshot[source_start:source_end if source_end >= 0 else len(snapshot)] if source_start >= 0 else ""
        if f"[reference_section:{section_id}]" in source_text:
            present.append(item)
    missing = [item for item in required if item not in present]
    truncation = deepcopy(dict(retrieval_meta.get("truncation") or {}))
    return {
        "task_id": task_record.get("task_id"),
        "snapshot_id": retrieval_meta.get("snapshot_id"),
        "snapshot_hash": retrieval_meta.get("snapshot_hash"),
        "truncated": bool(truncation.get("applied")),
        "truncation": truncation,
        "retrieved_chunk_ids": list(retrieval_meta.get("chunk_ids") or []),
        "retrieval_omissions": deepcopy(dict(retrieval_meta.get("retrieval_omissions") or {})),
        "retrieved_sections": present,
        "required_sections": required,
        "missing_sections": missing,
        "required_support_present": not missing,
        "evidence_policy": "declared_reference_sections_are_required_supporting_spans",
    }


def validate_snapshot_completeness(
    task_manifest: Mapping[str, Any],
    *,
    source_roots: list[str | Path],
    top_k: int | None = None,
    max_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Build actual snapshots for all tasks and fail closed on missing spans."""

    records = _runtime_task_records(task_manifest, source_roots=source_roots)
    reports: list[dict[str, Any]] = []
    for task_id, task in records.items():
        kwargs = {}
        if top_k is not None:
            kwargs["top_k"] = int(top_k)
        if max_chars is not None:
            kwargs["max_chars"] = int(max_chars)
        snapshot, retrieval_meta = frozen_snapshot(task["message"], task["context"], **kwargs)
        report = snapshot_completeness_report(
            task,
            snapshot=snapshot,
            retrieval_meta=retrieval_meta,
        )
        report["task_id"] = task_id
        reports.append(report)
    return reports


def open_or_create_ledger(
    root: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> PilotLedger:
    """Open an existing ledger or atomically create one from a prepared file."""

    root_path = Path(root).resolve()
    existing_manifest = root_path / "manifest.json"
    existing_ledger = root_path / "ledger.json"
    supplied = Path(manifest_path).resolve() if manifest_path is not None else None
    if existing_manifest.exists() or existing_ledger.exists():
        ledger = PilotLedger.open(root_path)
        if supplied is not None:
            candidate = _read_json(supplied)
            validate_pilot_manifest(
                candidate,
                require_balanced=(candidate.get("order_policy", {}).get("balance_status") == "balanced"),
            )
            if candidate.get("run_manifest_hash") != ledger.manifest.get("run_manifest_hash"):
                raise PilotExecutorError("Supplied manifest does not match the existing Pilot ledger")
        return ledger
    if supplied is None:
        raise PilotExecutorError("A new Pilot ledger requires --manifest")
    return PilotLedger(root_path, _read_json(supplied))


def validate_task_binding(manifest: Mapping[str, Any], task_manifest: Mapping[str, Any]) -> bool:
    declared = manifest.get("task_manifest_hash")
    actual = _task_manifest_hash(task_manifest)
    if declared != actual:
        raise PilotExecutorError("Task manifest hash does not match the frozen Pilot manifest")
    expected_id = manifest.get("task_manifest_id")
    actual_id = task_manifest.get("manifest_id") or task_manifest.get("benchmark_id")
    if expected_id and actual_id and str(expected_id) != str(actual_id):
        raise PilotExecutorError("Task manifest ID does not match the frozen Pilot manifest")
    expected_benchmark_id = _safe_text(manifest.get("benchmark_id"))
    actual_benchmark_id = _safe_text(task_manifest.get("benchmark_id") or task_manifest.get("manifest_id"))
    if expected_benchmark_id and (not actual_benchmark_id or expected_benchmark_id != actual_benchmark_id):
        raise PilotExecutorError("Authoritative benchmark identity does not match the frozen Pilot manifest")
    expected_benchmark_version = _safe_text(manifest.get("benchmark_version"))
    actual_benchmark_version = _safe_text(task_manifest.get("benchmark_version"))
    if expected_benchmark_version and (not actual_benchmark_version or expected_benchmark_version != actual_benchmark_version):
        raise PilotExecutorError("Authoritative benchmark version does not match the frozen Pilot manifest")
    return True


class PilotExecutor:
    """Execute scheduled conditions one at a time with append-only attempts."""

    def __init__(
        self,
        ledger: PilotLedger,
        task_manifest: Mapping[str, Any],
        *,
        phase: str = "PILOT",
        allow_live: bool = False,
        allow_unreviewed: bool = False,
        runtime_module: Any | None = None,
        source_roots: list[str | Path] | None = None,
        preflight: Mapping[str, Any] | None = None,
        authorization: Mapping[str, Any] | None = None,
        live_window: Mapping[str, Any] | None = None,
        local_usage_ledger: LocalPilotUsageLedger | None = None,
    ):
        self.ledger = ledger
        self.manifest = ledger.manifest
        self.task_manifest = task_manifest
        self.phase = str(phase).upper()
        if self.phase == "MAIN":
            raise PilotExecutorError(
                "MAIN_FREEZE_REQUIRED: PilotExecutor cannot execute MAIN; use a separate Main manifest and freeze"
            )
        if self.phase not in {"PILOT", "PREFLIGHT", "DRY_RUN"}:
            raise PilotExecutorError("phase must be PILOT, PREFLIGHT, or DRY_RUN")
        self.dry_run = bool(self.manifest.get("dry_run", False))
        if self.phase == "DRY_RUN" and not self.dry_run:
            raise PilotExecutorError("DRY_RUN phase requires a dry-run manifest")
        if self.phase != "DRY_RUN" and self.dry_run:
            raise PilotExecutorError("A dry-run manifest cannot be executed as PILOT/PREFLIGHT")
        validate_pilot_manifest(
            self.manifest,
            require_balanced=(self.manifest.get("order_policy", {}).get("balance_status") == "balanced"),
        )
        validate_task_binding(self.manifest, task_manifest)
        if self.phase == "PILOT" and not self.dry_run:
            if self.manifest.get("freeze_identity") not in {PILOT_FREEZE_IDENTITY}:
                raise PilotExecutorError("PILOT_FREEZE_IDENTITY_REQUIRED")
        benchmark_status = str(task_manifest.get("status") or "").upper()
        if (
            self.phase == "PILOT"
            and benchmark_status in {"DRAFT", "DRAFT_FOR_QUALITY_REVIEW", "UNAPPROVED", "NEEDS_REVIEW"}
            and not allow_unreviewed
        ):
            raise PilotExecutorError(
                "Benchmark/task manifest is not approved for PILOT execution; use PREFLIGHT or explicit review override"
            )
        provider = str(self.manifest.get("provider") or "").lower()
        if provider != "fake" and not allow_live:
            raise PilotExecutorError("Live provider execution requires explicit allow_live=True")
        self.preflight = deepcopy(dict(preflight or self.manifest.get("preflight_binding") or {}))
        self.authorization = deepcopy(dict(authorization or self.manifest.get("authorization") or {}))
        self.live_window = deepcopy(dict(live_window or self.manifest.get("live_window") or {}))
        self.live_request_gate: PilotLiveRequestGate | None = None
        if self.phase == "PILOT" and provider != "fake":
            if self.preflight.get("binding_schema_id") != PILOT_PREFLIGHT_BINDING_SCHEMA_ID:
                raise PilotExecutorError(
                    "FRESH_PILOT_PREFLIGHT_REQUIRED: a versioned manifest-bound preflight is required"
                )
            try:
                validate_preflight_binding(self.preflight, manifest=self.manifest)
            except PreflightBindingError as exc:
                raise PilotExecutorError(str(exc)) from exc
            self.preflight.setdefault("settings_identity", self.preflight.get("model_settings_identity"))
            if not self.authorization:
                raise PilotExecutorError("PILOT_AUTHORIZATION_REQUIRED")
            if not self.live_window:
                raise PilotExecutorError("PILOT_LIVE_WINDOW_REQUIRED")

        self.request_pacer = (
            AsyncRequestPacer(
                requests_per_minute=int(((self.manifest.get("configuration") or {}).get("pacing_policy") or {}).get("conservative_requests_per_minute_until_header_observation", 20)),
                max_in_flight=int(((self.manifest.get("configuration") or {}).get("pacing_policy") or {}).get("max_in_flight_workers", 3)),
                tokens_per_minute=int(((self.manifest.get("configuration") or {}).get("pacing_policy") or {}).get("aggregate_token_ceiling_per_minute", 8000)),
            )
            if provider != "fake"
            else None
        )
        if self.phase == "PILOT" and provider != "fake":
            usage = local_usage_ledger or LocalPilotUsageLedger(
                self.ledger.root / "pilot_local_usage.json",
                timezone_name=str(self.live_window.get("timezone") or DEFAULT_PROJECT_TIMEZONE),
                window_id=str(self.live_window.get("window_id") or "UNBOUND"),
            )
            assert self.request_pacer is not None
            self.live_request_gate = PilotLiveRequestGate(
                manifest=self.manifest,
                preflight=self.preflight,
                authorization=self.authorization,
                live_window=self.live_window,
                usage_ledger=usage,
                pacer=self.request_pacer,
            )
            self.live_request_gate.validate()
        if source_roots is None:
            source_roots = [Path.cwd()]
        self.tasks = _runtime_task_records(task_manifest, source_roots=source_roots)
        self.runtime = runtime_module

    def status(self) -> dict[str, Any]:
        self.ledger.assert_integrity()
        result = self.ledger.status_summary()
        result.update({
            "phase": self.phase,
            "dry_run": self.dry_run,
            "research_evidence": self.phase == "PILOT" and not self.dry_run,
        })
        return result

    def _runtime(self) -> Any:
        if self.runtime is None:
            import app.main as runtime_module
            self.runtime = runtime_module
        return self.runtime

    def _task_for_unit(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        task_id = str(unit.get("task_id"))
        try:
            task = self.tasks[task_id]
        except KeyError as exc:
            raise PilotExecutorError(f"Task {task_id} is missing from the supplied task manifest") from exc
        if unit.get("task_version") not in {None, task.get("task_version")}:
            raise PilotExecutorError(f"Task version mismatch for {task_id}")
        if unit.get("benchmark_id") not in {None, task.get("benchmark_id")}:
            raise PilotExecutorError(f"Benchmark identity mismatch for {task_id}")
        if unit.get("benchmark_version") not in {None, task.get("benchmark_version")}:
            raise PilotExecutorError(f"Benchmark version mismatch for {task_id}")
        declared_sources = [str(item) for item in (unit.get("source_document_ids") or [])]
        if declared_sources != task.get("source_document_ids", []):
            raise PilotExecutorError(f"Source identity mismatch for {task_id}")
        declared_hashes = [str(item) for item in (unit.get("source_document_hashes") or [])]
        if declared_hashes and declared_hashes != task.get("source_document_hashes", []):
            raise PilotExecutorError(f"Source hash mismatch for {task_id}")
        declared_scope = unit.get("reference_scope") or []
        if declared_scope != task.get("reference_scope", []):
            raise PilotExecutorError(f"Reference scope mismatch for {task_id}")
        if unit.get("reference_scope_hash") not in {None, task.get("reference_scope_hash")}:
            raise PilotExecutorError(f"Reference scope hash mismatch for {task_id}")
        return task

    def _snapshot_for_unit(self, unit: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        snapshot_started = time.perf_counter()
        task = self._task_for_unit(unit)
        rag_settings = (self.manifest.get("configuration") or {}).get("rag_settings") or {}
        snapshot, retrieval_meta = frozen_snapshot(
            task["message"],
            task["context"],
            top_k=int(rag_settings.get("top_k", 32)),
            max_chars=int(rag_settings.get("max_chars", 16000)),
        )
        retrieval_meta = deepcopy(retrieval_meta)
        # Keep benchmark source provenance adjacent to (not inside) the RAG
        # implementation's generated document identity.
        retrieval_meta["pilot_source_document_ids"] = list(task["source_document_ids"])
        retrieval_meta["pilot_source_document_hashes"] = list(task["source_document_hashes"])
        retrieval_meta["pilot_reference_scope"] = deepcopy(task.get("reference_scope") or [])
        retrieval_meta["pilot_reference_scope_hash"] = task.get("reference_scope_hash")
        retrieval_meta["pilot_reference_section_ids"] = [
            f"{item['source_id']}:{section_id}"
            for item in (task.get("reference_scope") or [])
            for section_id in (item.get("section_ids") or [])
        ]
        completeness = snapshot_completeness_report(
            task,
            snapshot=snapshot,
            retrieval_meta=retrieval_meta,
        )
        retrieval_meta["snapshot_completeness"] = completeness
        if not completeness["required_support_present"]:
            raise SnapshotFairnessError(
                "SNAPSHOT_REQUIRED_EVIDENCE_MISSING: "
                + ",".join(completeness["missing_sections"])
            )
        # The accepted comparison-unit boundary includes source resolution,
        # retrieval and completeness validation.  The caller backdates each
        # strategy by this one measured preparation span.
        retrieval_meta["context_prep_ms"] = round((time.perf_counter() - snapshot_started) * 1000)
        try:
            self.ledger.set_unit_snapshot(
                str(unit["unit_id"]),
                snapshot_id=str(retrieval_meta["snapshot_id"]),
                snapshot_hash=str(retrieval_meta["snapshot_hash"]),
                metadata=retrieval_meta,
            )
        except RuntimeError as exc:
            raise SnapshotFairnessError(str(exc)) from exc
        return snapshot, retrieval_meta

    @staticmethod
    def _condition_map(unit: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        return {
            str(condition.get("strategy")): condition
            for condition in (unit.get("conditions") or [])
            if isinstance(condition, Mapping)
        }

    @staticmethod
    def _is_eligible(condition: Mapping[str, Any], *, retry_failed: bool) -> bool:
        status = condition.get("status")
        if status == "missing_not_run":
            return True
        return bool(retry_failed and status in {"failed", "stopped", "provider_incident", "invalidated"})

    def _metadata(
        self,
        unit: Mapping[str, Any],
        condition: Mapping[str, Any],
        retrieval_meta: Mapping[str, Any],
    ) -> dict[str, Any]:
        identities = deepcopy(self.manifest.get("config_identities") or {})
        pilot_identities = deepcopy(self.manifest.get("pilot_config_identities") or {})
        return {
            "phase": self.phase,
            "dry_run": self.dry_run,
            "research_evidence": self.phase == "PILOT" and not self.dry_run,
            "evidence_class": "DRY_RUN" if self.dry_run else self.phase,
            "pilot_manifest_id": self.manifest.get("manifest_id"),
            "run_manifest_hash": self.manifest.get("run_manifest_hash"),
            "freeze_identity": self.manifest.get("freeze_identity"),
            "preflight_checked_at": self.preflight.get("checked_at") if self.preflight else None,
            "condition_id": f"{unit['unit_id']}::{condition['strategy']}",
            "attempt_id": condition.get("run_id"),
            "unit_id": unit.get("unit_id"),
            "task_id": unit.get("task_id"),
            "repeat_index": unit.get("repeat_index"),
            "repeat_id": unit.get("repeat_id"),
            "strategy": condition.get("strategy"),
            "execution_order": condition.get("execution_order"),
            "order_seed": unit.get("order_seed"),
            "strategy_config_id": condition.get("strategy_config_id"),
            "strategy_config_version": condition.get("strategy_config_version"),
            "pilot_strategy_config_id": condition.get("pilot_strategy_config_id"),
            "provider": condition.get("provider"),
            "model": condition.get("model"),
            "model_settings_identity": condition.get("model_settings_identity"),
            "rag_config_id": condition.get("rag_config_id"),
            "rag_pilot_config_id": condition.get("rag_pilot_config_id"),
            "price_config_id": condition.get("price_config_id"),
            "pricing_version": condition.get("pricing_version"),
            "pilot_pricing_version": condition.get("pilot_pricing_version"),
            "benchmark_id": unit.get("benchmark_id"),
            "benchmark_version": unit.get("benchmark_version"),
            "benchmark_provenance_version": unit.get("benchmark_provenance_version"),
            "rubric_version_reference": unit.get("rubric_version_reference"),
            "task_manifest_id": self.manifest.get("task_manifest_id"),
            "task_manifest_version": self.manifest.get("task_manifest_version"),
            "task_manifest_hash": self.manifest.get("task_manifest_hash"),
            "source_document_ids": list(unit.get("source_document_ids") or []),
            "source_document_hashes": list(unit.get("source_document_hashes") or []),
            "reference_scope": deepcopy(unit.get("reference_scope") or []),
            "reference_scope_hash": unit.get("reference_scope_hash"),
            "reference_section_ids": list(retrieval_meta.get("pilot_reference_section_ids") or []),
            "context_snapshot_id": retrieval_meta.get("snapshot_id"),
            "context_snapshot_hash": retrieval_meta.get("snapshot_hash"),
            "snapshot_completeness": deepcopy(retrieval_meta.get("snapshot_completeness") or {}),
            "snapshot_metadata": deepcopy(retrieval_meta),
            "unit_attempt_id": condition.get("unit_attempt_id"),
            "config_identities": identities,
            "pilot_config_identities": pilot_identities,
            "attempt_index": condition.get("attempt_index"),
            "run_state": "RUNNING",
        }

    async def _execute_condition(
        self,
        unit: Mapping[str, Any],
        condition: Mapping[str, Any],
        *,
        snapshot: str,
        retrieval_meta: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        runtime = self._runtime()
        strategy = str(condition["strategy"])
        run_id = str(condition["run_id"])
        raw_path = self.ledger.root / str(condition["raw_evidence_path"])
        e2e_started_at = time.perf_counter() - (float(retrieval_meta.get("context_prep_ms") or 0) / 1000.0)
        pilot_meta = self._metadata(unit, condition, retrieval_meta)
        comparison_meta = {
            "comparison_id": f"{self.manifest['manifest_id']}::{unit['unit_id']}",
            "unit_id": unit.get("unit_id"),
            "order": condition.get("execution_order"),
            "total": len(PILOT_STRATEGIES),
            "phase": self.phase,
            "dry_run": self.dry_run,
            "evidence_class": pilot_meta["evidence_class"],
            "provider": condition.get("provider"),
            "model": condition.get("model"),
            "snapshot_id": retrieval_meta.get("snapshot_id"),
            "snapshot_hash": retrieval_meta.get("snapshot_hash"),
            "run_manifest_hash": self.manifest.get("run_manifest_hash"),
        }
        request_gate = None
        if self.live_request_gate is not None:
            request_gate = self.live_request_gate.bind(
                unit_id=str(unit.get("unit_id") or ""),
                attempt_id=run_id,
                condition_id=f"{unit.get('unit_id')}::{strategy}",
            )
        elif self.request_pacer is not None:
            request_gate = self.request_pacer

        async def sink(_event: Mapping[str, Any]) -> None:
            return None

        old_runs = getattr(runtime, "RUNS", None)
        runtime.RUNS = self.ledger.raw_dir
        data: Mapping[str, Any] | None = None
        try:
            try:
                data = await runtime.execute_once(
                    strategy=strategy,
                    provider_name=str(condition["provider"]),
                    model_name=str(condition["model"]),
                    message=self._task_for_unit(unit)["message"],
                    frozen_context=snapshot,
                    retrieval_meta=deepcopy(dict(retrieval_meta)),
                    history=[],
                    emit=sink,
                    budget_config=deepcopy((self.manifest.get("configuration") or {}).get("budget") or {}),
                    comparison_meta=comparison_meta,
                    run_id=run_id,
                    run_metadata=pilot_meta,
                    generation_settings=deepcopy((self.manifest.get("configuration") or {}).get("generation_settings") or {}),
                    e2e_started_at=e2e_started_at,
                    request_gate=request_gate,
                )
            except Exception as exc:
                # A constructor/model/key failure occurs before execute_once can
                # create a RunState.  Save exactly one redacted provider-error
                # record under the reserved attempt ID; never fall back.
                if raw_path.exists():
                    data = _read_json(raw_path)
                else:
                    incident = safe_provider_incident(
                        exc,
                        provider=str(condition["provider"]),
                        model=str(condition["model"]),
                    )
                    failed_meta = deepcopy(pilot_meta)
                    failed_meta.update({
                        "provider_incident": True,
                        "provider_error_category": incident.get("provider_error_category"),
                        "provider_error_message": incident.get("safe_message"),
                        "incident": incident,
                        "incident_records": [incident],
                        "outcome_category": incident.get("category"),
                        "run_state": "PROVIDER_ERROR",
                    })
                    data = runtime.save_failed_run_evidence(
                        strategy=strategy,
                        provider=str(condition["provider"]),
                        model=str(condition["model"]),
                        message=self._task_for_unit(unit)["message"],
                        context=snapshot,
                        retrieval_meta=deepcopy(dict(retrieval_meta)),
                        history=[],
                        error=exc,
                        comparison_meta=comparison_meta,
                        budget_config=deepcopy((self.manifest.get("configuration") or {}).get("budget") or {}),
                        run_id=run_id,
                        run_metadata=failed_meta,
                        incident=incident,
                        e2e_ms=round((time.perf_counter()-e2e_started_at)*1000),
                        context_prep_ms=retrieval_meta.get("context_prep_ms"),
                    )
            if not isinstance(data, Mapping):
                raise PilotExecutorError("Runtime returned no raw evidence mapping")
            if str(data.get("run_id") or "") != run_id:
                raise PilotExecutorError("Runtime raw evidence run_id does not match the ledger reservation")
            if not raw_path.exists():
                # This branch is useful for a controlled test double; the real
                # application path already persists before returning.
                runtime.save(dict(data))
            if not raw_path.exists():
                raise PilotExecutorError("Runtime returned without persisting raw evidence")
            recorded = self.ledger.record(
                str(unit["unit_id"]),
                strategy,
                raw_path=raw_path,
                raw=data,
            )
            return recorded, dict(data)
        finally:
            if old_runs is not None:
                runtime.RUNS = old_runs

    async def run_async(
        self,
        *,
        limit: int | None = 1,
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        if limit is not None and int(limit) < 1:
            raise PilotExecutorError("limit must be positive")
        limit = None if limit is None else int(limit)
        if self.phase == "PREFLIGHT" and (limit is None or limit > 1):
            raise PilotExecutorError("PREFLIGHT is limited to one condition")
        if self.live_request_gate is not None:
            self.live_request_gate.validate()

        recovered = self.ledger.recover_interrupted()
        executed: list[dict[str, Any]] = []
        skipped_completed = 0
        skipped_terminal = 0
        for unit in self.manifest.get("units") or []:
            condition_map = self._condition_map(unit)
            unit_marker = self.ledger.unit_attempt_status(str(unit.get("unit_id")))
            provider_incident_pending = bool(
                unit_marker and unit_marker.get("status") == "provider_incident"
            ) or any(
                condition.get("status") == "provider_incident"
                for condition in condition_map.values()
            )
            whole_unit_rerun = False
            if provider_incident_pending and retry_failed:
                if limit is not None and limit < len(PILOT_STRATEGIES):
                    raise PilotExecutorError(
                        "WHOLE_UNIT_RERUN_REQUIRES_ALL_FOUR_CONDITIONS"
                    )
                self.ledger.begin_unit_attempt(str(unit["unit_id"]))
                # Manifest condition mirrors are updated by begin_unit_attempt.
                condition_map = self._condition_map(unit)
                whole_unit_rerun = True
            elif provider_incident_pending:
                for condition in condition_map.values():
                    if condition.get("status") == "provider_incident":
                        skipped_terminal += 1
                continue
            if not any(
                self._is_eligible(
                    condition_map.get(strategy, {}),
                    retry_failed=(retry_failed and not provider_incident_pending),
                )
                for strategy in unit.get("strategy_order") or []
            ):
                for condition in condition_map.values():
                    if condition.get("status") == "observed":
                        skipped_completed += 1
                    elif condition.get("status") in {"failed", "stopped", "provider_incident", "invalidated"}:
                        skipped_terminal += 1
                continue
            snapshot, retrieval_meta = self._snapshot_for_unit(unit)
            for strategy in unit.get("strategy_order") or []:
                if limit == 0:
                    break
                condition = condition_map.get(strategy)
                if condition is None:
                    raise PilotExecutorError(f"Manifest unit {unit.get('unit_id')} is missing {strategy}")
                if not self._is_eligible(condition, retry_failed=(retry_failed and not provider_incident_pending)):
                    if condition.get("status") == "observed":
                        skipped_completed += 1
                    elif condition.get("status") in {"failed", "stopped", "provider_incident", "invalidated"}:
                        skipped_terminal += 1
                    continue
                started = self.ledger.begin(
                    str(unit["unit_id"]),
                    strategy,
                    retry=retry_failed,
                )
                recorded, raw = await self._execute_condition(
                    unit,
                    started,
                    snapshot=snapshot,
                    retrieval_meta=retrieval_meta,
                )
                executed.append({
                    "condition_id": recorded.get("condition_key"),
                    "attempt_id": recorded.get("run_id"),
                    "run_id": recorded.get("run_id"),
                    "task_id": recorded.get("task_id"),
                    "repeat_index": recorded.get("repeat_index"),
                    "strategy": recorded.get("strategy"),
                    "execution_order": recorded.get("execution_order"),
                    "status": recorded.get("status"),
                    "run_state": recorded.get("run_state") or control_state_from_status(recorded.get("status")),
                    "phase": raw.get("phase") or self.phase,
                    "raw_evidence_path": recorded.get("raw_evidence_path"),
                })
                if raw.get("provider_incident") is True or raw.get("incident_origin") == "provider":
                    self.ledger.mark_unit_incident(
                        str(unit["unit_id"]),
                        category=raw.get("provider_error_category") or raw.get("incident_category"),
                        reason=raw.get("provider_error_message") or raw.get("error"),
                    )
                    # Remaining conditions are intentionally left pending;
                    # only an explicit whole-unit rerun may restart them.
                    break
                if limit is not None:
                    limit -= 1
            if whole_unit_rerun:
                marker = self.ledger.unit_attempt_status(str(unit["unit_id"]))
                if marker and marker.get("status") == "running":
                    remaining = [
                        condition for condition in self._condition_map(unit).values()
                        if condition.get("status") not in {"observed", "failed", "stopped", "provider_incident", "invalidated"}
                    ]
                    if not remaining:
                        self.ledger.complete_unit_attempt(str(unit["unit_id"]))
            if limit == 0:
                break

        self.ledger.assert_integrity()
        summary = self.ledger.status_summary()
        return {
            "status": "completed" if not summary["pending_count"] and not summary["running_count"] else "partial",
            "phase": self.phase,
            "dry_run": self.dry_run,
            "research_evidence": self.phase == "PILOT" and not self.dry_run,
            "manifest_id": self.manifest.get("manifest_id"),
            "run_manifest_hash": self.manifest.get("run_manifest_hash"),
            "recovered_count": len(recovered),
            "executed_count": len(executed),
            "skipped_completed_count": skipped_completed,
            "skipped_terminal_count": skipped_terminal,
            "remaining_pending_count": summary["pending_count"],
            "results": executed,
            "status_counts": summary["status_counts"],
            "control_state_counts": summary["control_state_counts"],
        }

    def run(self, *, limit: int | None = 1, retry_failed: bool = False) -> dict[str, Any]:
        return asyncio.run(self.run_async(limit=limit, retry_failed=retry_failed))


def validate_manifest_file(path: str | Path) -> dict[str, Any]:
    manifest = _read_json(Path(path))
    validate_pilot_manifest(
        manifest,
        require_balanced=(manifest.get("order_policy", {}).get("balance_status") == "balanced"),
    )
    return {
        "status": "valid",
        "manifest_id": manifest.get("manifest_id"),
        "run_manifest_hash": manifest.get("run_manifest_hash"),
        "comparison_units": manifest.get("expected_comparison_units"),
        "strategy_runs": manifest.get("expected_strategy_runs"),
        "order_balance": (manifest.get("order_policy") or {}).get("balance_status"),
        "top_level_sequential": (manifest.get("order_policy") or {}).get("top_level_sequential") is True,
        "provider": manifest.get("provider"),
        "model": manifest.get("model"),
    }


__all__ = [
    "PilotExecutor",
    "PilotExecutorError",
    "SnapshotFairnessError",
    "open_or_create_ledger",
    "validate_manifest_file",
    "validate_task_binding",
    "snapshot_completeness_report",
    "validate_snapshot_completeness",
]

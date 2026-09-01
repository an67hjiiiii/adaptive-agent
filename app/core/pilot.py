"""Pilot execution control and evidence utilities.

This module is deliberately a thin experiment-control layer around the
existing runtime.  It does not choose a research strategy, create benchmark
content, or evaluate answers.  Its responsibilities are limited to versioned
configuration snapshots, deterministic top-level order, an append-oriented
condition ledger, and a derived processed export.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import uuid
from typing import Any, Iterable, Mapping

from app.core.orchestrator import (
    CONFIG_VERSION,
    CACHED_INPUT_PRICE_PER_MTOK,
    FIXED_CONFIG_ID,
    MODEL_CONFIG_ID,
    MODEL_SETTINGS_ID,
    ORCH_CONFIG_ID,
    PRICE_CONFIG_ID,
    PRICE_PER_MTOK,
    PROMPT_VERSIONS,
    RAG_CONFIG_ID,
    SINGLE_CONFIG_ID,
    STATIC_CONFIG_ID,
)
from app.core.rag import (
    DEFAULT_CHUNK_CHARS,
    DEFAULT_MAX_CHARS,
    DEFAULT_TOP_K,
    RAG_SETTINGS_VERSION,
)
from app.core.types import Budget
from app.core.pilot_authorization import (
    AUTHORIZED_PILOT_SCOPE,
    PILOT_AUTHORIZATION_SCHEMA_ID,
    PILOT_AUTHORIZATION_SCHEMA_VERSION,
    PILOT_LIVE_WINDOW_SCHEMA_ID,
    PILOT_LIVE_WINDOW_SCHEMA_VERSION,
    PILOT_PACING_POLICY,
    PILOT_PACING_POLICY_ID,
    PILOT_PACING_POLICY_VERSION,
    PILOT_PREFLIGHT_BINDING_SCHEMA_ID,
    PILOT_PREFLIGHT_BINDING_SCHEMA_VERSION,
)


PILOT_EXECUTION_CONFIG_ID = "PILOT-EXECUTION-INFRA-V1"
PILOT_EXECUTION_CONFIG_VERSION = "1.0"
PILOT_RUN_MANIFEST_VERSION = "PILOT-R4-V1"
PILOT_LEDGER_VERSION = "PILOT-LEDGER-V1"
PILOT_PROCESSED_DATASET_VERSION = "PILOT-PROCESSED-V1"
PILOT_INCIDENT_TAXONOMY_VERSION = "INCIDENT-TAXONOMY-V1"
PILOT_DENOMINATOR_POLICY_VERSION = "QEP-DENOMINATOR-V1"
PILOT_EXECUTOR_VERSION = "PILOT-EXECUTOR-V1.1"
PILOT_FREEZE_IDENTITY = "PILOT-FREEZE-CANDIDATE-V1"
PILOT_PREREGISTRATION_VERSION = "PILOT-R1"

# The benchmark workstream exposes ``PILOT-R2`` as a provenance/workstream
# label, while the quality-reviewed artifact has a canonical identity and
# version.  Runtime and export evidence carry both so a workstream label cannot
# silently become a second benchmark identity.
PILOT_BENCHMARK_ID = "pilot_benchmark_v1"
PILOT_BENCHMARK_VERSION = "pilot_benchmark_v1@1.1.0"
PILOT_BENCHMARK_PROVENANCE = "PILOT-R2"

DEFAULT_PILOT_PROVIDER = "groq"
DEFAULT_PILOT_MODEL = "openai/gpt-oss-120b"
PILOT_STRATEGIES = ("single", "fixed", "static", "adaptive")
PILOT_STATUSES = (
    "observed",
    "missing_not_run",
    "failed",
    "stopped",
    "provider_incident",
    "invalidated",
)
PILOT_CONTROL_STATES = (
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "STOPPED",
    "PROVIDER_ERROR",
)
_ACTIVE_STATUS = "running"
_TERMINAL_STATUSES = {"observed", "failed", "stopped", "provider_incident", "invalidated"}
_RETRYABLE_TERMINAL_STATUSES = {"failed", "stopped", "provider_incident", "invalidated"}


def control_state_from_status(status: str | None) -> str:
    """Map the protocol's persisted status to a small operator-facing state."""

    if status in {None, "missing_not_run"}:
        return "PENDING"
    if status == _ACTIVE_STATUS:
        return "RUNNING"
    if status == "observed":
        return "COMPLETED"
    if status == "stopped":
        return "STOPPED"
    if status == "provider_incident":
        return "PROVIDER_ERROR"
    if status in {"failed", "invalidated"}:
        return "FAILED"
    raise ValueError(f"Unsupported Pilot condition status: {status}")

LATIN_SQUARE_ROWS = (
    ("single", "fixed", "static", "adaptive"),
    ("fixed", "static", "adaptive", "single"),
    ("static", "adaptive", "single", "fixed"),
    ("adaptive", "single", "fixed", "static"),
)

DEFAULT_PILOT_BUDGET = {
    "max_logical_calls": 12,
    "max_physical_requests": 18,
    "max_workers": 3,
    "max_escalations": 1,
    "max_retries_per_call": 1,
    "retry_base_seconds": 1.0,
    "retry_max_seconds": 30.0,
    "call_timeout_seconds": 60.0,
}

STRATEGY_CONFIG_IDS = {
    "single": SINGLE_CONFIG_ID,
    "fixed": FIXED_CONFIG_ID,
    "static": STATIC_CONFIG_ID,
    "adaptive": ORCH_CONFIG_ID,
}

# Pilot-scoped aliases point at the existing runtime identities below.  They
# are manifest labels for a frozen experiment block, not a second config
# registry or a second source of model/strategy values.
MODEL_PILOT_CONFIG_ID = "MODEL-PILOT-V1"
MODEL_PILOT_CONFIG_VERSION = "1.1"
MODEL_PILOT_VERIFIED_AT = "2026-08-30T14:04:25Z"
RAG_PILOT_CONFIG_ID = "RAG-PILOT-V1"
ORCH_PILOT_CONFIG_ID = "ORCH-PILOT-V1"
FIXED_PILOT_CONFIG_ID = "FIXED-PILOT-V1"
STATIC_PILOT_CONFIG_ID = "STATIC-PILOT-V1"
PRICE_PILOT_CONFIG_ID = "PRICE-PILOT-V1"
PRICE_PILOT_CONFIG_VERSION = "1.1"
PRICE_PILOT_VERIFIED_AT = "2026-08-30T13:49:38Z"
PILOT_CONFIG_IDENTITIES = {
    "model_pilot_config_id": MODEL_PILOT_CONFIG_ID,
    "rag_pilot_config_id": RAG_PILOT_CONFIG_ID,
    "orch_pilot_config_id": ORCH_PILOT_CONFIG_ID,
    "fixed_pilot_config_id": FIXED_PILOT_CONFIG_ID,
    "static_pilot_config_id": STATIC_PILOT_CONFIG_ID,
    "price_pilot_config_id": PRICE_PILOT_CONFIG_ID,
}
PILOT_STRATEGY_CONFIG_IDS = {
    "single": SINGLE_CONFIG_ID,
    "fixed": FIXED_PILOT_CONFIG_ID,
    "static": STATIC_PILOT_CONFIG_ID,
    "adaptive": ORCH_PILOT_CONFIG_ID,
}

# Frozen Groq request controls for the Pilot candidate.  ``include_reasoning``
# is carried through the OpenAI-compatible adapter's ``extra_body`` because
# the installed SDK does not expose that Groq field as a typed argument.
PILOT_GROQ_REQUEST_PARAMETERS = {
    "temperature": 0.6,
    "max_completion_tokens": 4096,
    # Groq documents top_p=1 as its default; setting it explicitly leaves all
    # diversity control to the frozen temperature value.
    "top_p": 1.0,
    "reasoning_effort": "medium",
    "include_reasoning": False,
    "response_format": {"type": "text"},
    "stream": False,
    "n": 1,
    "service_tier": "on_demand",
    # A seed is intentionally not sent: repeated Pilot conditions should not
    # be forced into identical samples.
    "seed": None,
}
PILOT_GROQ_PARAMETER_STATUS = {
    "temperature": "EXPLICIT",
    "max_completion_tokens": "EXPLICIT",
    "top_p": "EXPLICIT",
    "reasoning_effort": "EXPLICIT",
    "include_reasoning": "EXPLICIT_VIA_EXTRA_BODY",
    "response_format": "EXPLICIT",
    "stream": "EXPLICIT",
    "n": "EXPLICIT",
    "service_tier": "EXPLICIT",
    "seed": "UNUSED_BY_DESIGN",
    "reasoning_format": "UNSUPPORTED",
    "stop": "PROVIDER_DEFAULT_NULL",
    "citation_options": "PROVIDER_DEFAULT_ENABLED_NO_DOCUMENTS_OR_SEARCH",
    "compound_custom": "UNUSED_BY_DESIGN_NO_COMPOUND",
    "documents": "UNUSED_BY_DESIGN_NO_DOCUMENTS",
    "exclude_domains": "UNUSED_BY_DESIGN_NO_WEB_SEARCH",
    "include_domains": "UNUSED_BY_DESIGN_NO_WEB_SEARCH",
    "tools": "UNUSED_BY_DESIGN_NO_TOOLS",
    "tool_choice": "PROVIDER_DEFAULT_NONE_NO_TOOLS",
    "parallel_tool_calls": "PROVIDER_DEFAULT_TRUE_NO_TOOLS",
    "stream_options": "NOT_APPLICABLE_STREAM_FALSE",
    "user": "UNUSED_BY_DESIGN",
    "store": "UNSUPPORTED_BY_GROQ",
    "search_settings": "UNUSED_BY_DESIGN_NO_WEB_SEARCH",
    "max_tokens": "DEPRECATED_NOT_SENT",
    "metadata": "UNSUPPORTED_BY_GROQ",
    "logit_bias": "UNSUPPORTED_BY_GROQ_MODELS",
    "functions": "DEPRECATED_NOT_SENT",
    "function_call": "DEPRECATED_NOT_SENT",
    "disable_tool_validation": "UNUSED_BY_DESIGN",
    "presence_penalty": "UNSUPPORTED_BY_GROQ_MODELS",
    "frequency_penalty": "UNSUPPORTED_BY_GROQ_MODELS",
    "logprobs": "UNSUPPORTED_BY_GROQ_MODELS",
    "top_logprobs": "UNSUPPORTED_BY_GROQ_MODELS",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def derive_order_seed(
    preregistration_version: str,
    task_manifest_hash: str,
    unit_id: str,
) -> str:
    """Derive a reproducible, no-secret seed for one comparison unit."""

    material = "|".join((str(preregistration_version), str(task_manifest_hash), str(unit_id)))
    return sha256_text(material)


def _seed_int(seed: str) -> int:
    try:
        return int(str(seed), 16)
    except ValueError:
        return int(sha256_text(str(seed)), 16)


def fisher_yates(values: Iterable[Any], seed: str) -> list[Any]:
    """Return a deterministic Fisher–Yates permutation without mutating input."""

    result = list(values)
    generator = random.Random(_seed_int(seed))
    for index in range(len(result) - 1, 0, -1):
        swap_index = generator.randrange(index + 1)
        result[index], result[swap_index] = result[swap_index], result[index]
    return result


def _master_order_seed(
    preregistration_version: str,
    task_manifest_hash: str,
    seed: str | None,
) -> str:
    if seed is not None:
        return sha256_text(str(seed))
    return sha256_text(f"{preregistration_version}|{task_manifest_hash}|pilot-order-v1")


def build_balanced_order_schedule(
    unit_ids: Iterable[str],
    *,
    preregistration_version: str = PILOT_PREREGISTRATION_VERSION,
    task_manifest_hash: str,
    seed: str | None = None,
) -> list[dict[str, Any]]:
    """Assign units to balanced 4x4 Latin-square rows.

    The returned list follows the caller's unit order.  Assignment to rows is
    shuffled separately from the row labels, so every strategy occurs equally
    often in every ordinal position when the number of units is divisible by
    four (24 units therefore gives six occurrences per position).
    """

    units = [str(item) for item in unit_ids]
    if not units or len(units) % len(PILOT_STRATEGIES):
        raise ValueError("Balanced Latin-square scheduling requires a non-empty unit count divisible by four")
    if len(set(units)) != len(units):
        raise ValueError("Comparison unit IDs must be unique")

    master_seed = _master_order_seed(preregistration_version, task_manifest_hash, seed)
    row_count = len(units) // len(PILOT_STRATEGIES)
    expanded_rows = [row for row in range(len(LATIN_SQUARE_ROWS)) for _ in range(row_count)]
    shuffled_units = fisher_yates(units, f"{master_seed}|units")
    shuffled_rows = fisher_yates(expanded_rows, f"{master_seed}|rows")
    assigned: dict[str, dict[str, Any]] = {}
    for unit_id, row_index in zip(shuffled_units, shuffled_rows):
        unit_seed = derive_order_seed(preregistration_version, task_manifest_hash, unit_id)
        order = list(LATIN_SQUARE_ROWS[row_index])
        assigned[unit_id] = {
            "unit_id": unit_id,
            "latin_square_row": row_index,
            "order_seed": unit_seed,
            "strategy_order": order,
            "execution_order": {strategy: index + 1 for index, strategy in enumerate(order)},
        }
    return [assigned[unit_id] for unit_id in units]


def _dry_run_order_schedule(
    unit_ids: Iterable[str],
    *,
    preregistration_version: str,
    task_manifest_hash: str,
) -> list[dict[str, Any]]:
    result = []
    for unit_id in unit_ids:
        unit_seed = derive_order_seed(preregistration_version, task_manifest_hash, unit_id)
        order = list(PILOT_STRATEGIES)
        result.append({
            "unit_id": str(unit_id),
            "latin_square_row": None,
            "order_seed": unit_seed,
            "strategy_order": order,
            "execution_order": {strategy: index + 1 for index, strategy in enumerate(order)},
        })
    return result


def validate_order_schedule(
    schedule: Iterable[Mapping[str, Any]],
    unit_ids: Iterable[str],
    *,
    require_balanced: bool = True,
) -> bool:
    rows = list(schedule)
    units = [str(item) for item in unit_ids]
    if len(rows) != len(units) or {str(row.get("unit_id")) for row in rows} != set(units):
        raise ValueError("Order schedule does not cover exactly the declared comparison units")
    if len({str(row.get("unit_id")) for row in rows}) != len(rows):
        raise ValueError("Order schedule contains a duplicate comparison unit")
    position_counts = {
        strategy: [0] * len(PILOT_STRATEGIES)
        for strategy in PILOT_STRATEGIES
    }
    for row in rows:
        order = list(row.get("strategy_order") or [])
        if order != list(dict.fromkeys(order)) or set(order) != set(PILOT_STRATEGIES):
            raise ValueError("Each order row must contain Single, Fixed, Static and Adaptive exactly once")
        for index, strategy in enumerate(order):
            position_counts[strategy][index] += 1
        execution_order = row.get("execution_order") or {}
        if execution_order != {strategy: index + 1 for index, strategy in enumerate(order)}:
            raise ValueError("Execution order mapping does not match strategy order")
        if not isinstance(row.get("order_seed"), str) or not row["order_seed"]:
            raise ValueError("Each comparison unit needs a derived order seed")
    if require_balanced and len(set(units)) % len(PILOT_STRATEGIES) == 0:
        expected = len(rows) // len(PILOT_STRATEGIES)
        if any(count != expected for counts in position_counts.values() for count in counts):
            raise ValueError(f"Strategy order is not balanced by ordinal position: {position_counts}")
    elif require_balanced:
        raise ValueError("Balanced validation requires a unit count divisible by four")
    return True


def _budget_snapshot(budget: Budget | Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(budget, Budget):
        values = {
            "max_logical_calls": budget.max_logical_calls,
            "max_physical_requests": budget.max_physical_requests,
            "max_workers": budget.max_workers,
            "max_escalations": budget.max_escalations,
            "max_retries_per_call": budget.max_retries_per_call,
            "call_timeout_seconds": budget.call_timeout_seconds,
            "retry_base_seconds": budget.retry_base_seconds,
            "retry_max_seconds": budget.retry_max_seconds,
        }
    else:
        values = dict(DEFAULT_PILOT_BUDGET)
        if isinstance(budget, Mapping):
            values.update({key: value for key, value in budget.items() if value is not None})
    for key in (
        "max_logical_calls",
        "max_physical_requests",
        "max_workers",
        "max_escalations",
        "max_retries_per_call",
    ):
        values[key] = int(values[key])
    for key in ("retry_base_seconds", "retry_max_seconds", "call_timeout_seconds"):
        values[key] = float(values[key])
    return values


def _pricing_snapshot(provider: str, model: str) -> dict[str, Any]:
    rate = PRICE_PER_MTOK.get(model)
    pricing: dict[str, Any] = {
        "pricing_id": PRICE_PILOT_CONFIG_ID,
        "pricing_version": PRICE_PILOT_CONFIG_VERSION,
        "price_config_id": PRICE_CONFIG_ID,
        "price_config_version": PRICE_PILOT_CONFIG_VERSION,
        "price_pilot_config_id": PRICE_PILOT_CONFIG_ID,
        "price_pilot_config_version": PRICE_PILOT_CONFIG_VERSION,
        "provider": provider,
        "model": model,
        "unit": "USD per 1M tokens",
        "currency": "USD",
    }
    if provider == DEFAULT_PILOT_PROVIDER and model == DEFAULT_PILOT_MODEL and rate is not None:
        pricing.update({
            "input_usd_per_million_tokens": rate[0],
            "output_usd_per_million_tokens": rate[1],
            "cached_input_usd_per_million_tokens": CACHED_INPUT_PRICE_PER_MTOK.get(model),
            "reasoning_token_rate": "Unavailable",
            "reasoning_token_treatment": (
                "No separate Groq reasoning rate is published; reported "
                "completion_tokens (including any reasoning-token detail) use "
                "the output rate."
            ),
            "cost_formula": "((input_tokens-cached_input_tokens)*input_rate + cached_input_tokens*cached_input_rate + completion_tokens*output_rate) / 1000000",
            "status": "VERIFIED",
            "allow_cost_calculation": True,
            "source": "https://console.groq.com/docs/model/openai/gpt-oss-120b",
            "cached_input_source": "https://console.groq.com/docs/prompt-caching",
            "verified_at": PRICE_PILOT_VERIFIED_AT,
            "rule": "Do not replace unavailable cost with zero.",
        })
    elif rate is not None:
        pricing.update({
            "input_usd_per_million_tokens": rate[0],
            "output_usd_per_million_tokens": rate[1],
            "status": "PRICE_UNVERIFIED",
            "allow_cost_calculation": False,
            "source": "existing local PRICE_PER_MTOK configuration; independent verification is not recorded",
        })
    else:
        pricing.update({
            "status": "PRICE_UNVERIFIED",
            "allow_cost_calculation": False,
            "source": "No verified pricing snapshot exists for this provider/model.",
            "note": "No local price metadata exists for this provider/model.",
        })
    return pricing


def pilot_config_snapshot(
    *,
    provider: str = DEFAULT_PILOT_PROVIDER,
    model: str = DEFAULT_PILOT_MODEL,
    budget: Budget | Mapping[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build a no-secret snapshot from existing application identities."""

    provider = str(provider).lower()
    model = str(model)
    compatible = provider in {"groq", "openrouter"}
    settings = {
        "model_settings_id": MODEL_SETTINGS_ID,
        "model_settings_version": MODEL_PILOT_CONFIG_VERSION if provider == DEFAULT_PILOT_PROVIDER and model == DEFAULT_PILOT_MODEL else CONFIG_VERSION,
        "provider_adapter": "openai-compatible" if compatible else ("fake-offline" if provider == "fake" else provider),
        "request_shape": ["model", "messages.system", "messages.user"],
        "request_parameters": {},
        "parameter_status": {},
        "provider_timeout_seconds": None,
        "sdk_max_retries": 0 if compatible else None,
        "note": "Frozen Groq request controls. seed is intentionally omitted so Pilot repeats remain independent; reasoning_format is unsupported for GPT-OSS.",
    }
    if provider == DEFAULT_PILOT_PROVIDER and model == DEFAULT_PILOT_MODEL:
        settings.update({
            "request_parameters": deepcopy(PILOT_GROQ_REQUEST_PARAMETERS),
            "parameter_status": deepcopy(PILOT_GROQ_PARAMETER_STATUS),
            "provider_timeout_seconds": 60.0,
            "sdk_max_retries": 0,
            "retry_owner": "orchestrator",
            "verified_at": MODEL_PILOT_VERIFIED_AT,
        })
    identities = {
        "model_config_id": MODEL_CONFIG_ID,
        "model_settings_id": MODEL_SETTINGS_ID,
        "rag_config_id": RAG_CONFIG_ID,
        "orchestrator_config_id": ORCH_CONFIG_ID,
        "single_config_id": SINGLE_CONFIG_ID,
        "fixed_config_id": FIXED_CONFIG_ID,
        "static_config_id": STATIC_CONFIG_ID,
        "price_config_id": PRICE_CONFIG_ID,
        "prompt_versions": dict(PROMPT_VERSIONS),
        **PILOT_CONFIG_IDENTITIES,
        "model_pilot_config_version": MODEL_PILOT_CONFIG_VERSION,
        "price_pilot_config_version": PRICE_PILOT_CONFIG_VERSION,
    }
    return {
        "pilot_execution_config_id": PILOT_EXECUTION_CONFIG_ID,
        "pilot_execution_config_version": PILOT_EXECUTION_CONFIG_VERSION,
        "provider": provider,
        "model": model,
        "benchmark_binding": {
            "benchmark_id": PILOT_BENCHMARK_ID,
            "benchmark_version": PILOT_BENCHMARK_VERSION,
            "provenance_label": PILOT_BENCHMARK_PROVENANCE,
            "source": "benchmarks/pilot/pilot_benchmark_v1.json",
        },
        "quality_binding": {
            "protocol_version": "QEP-1.1",
            "rubric_version": "PILOT-RUBRIC-V1.0",
            "corpus_version": "PILOT-CORPUS-V1",
        },
        "model_settings_identity": MODEL_SETTINGS_ID,
        "pilot_config_identities": dict(PILOT_CONFIG_IDENTITIES),
        "generation_settings": settings,
        "budget": _budget_snapshot(budget),
        "reference_scope_policy": {
            "authoritative_binding": "tasks[].reference_bindings",
            "section_resolution": "frozen CORPUS_MANIFEST.json line_range by section_id",
            "invalid_section_action": "FAIL_CLOSED",
            "whole_document": "EXPLICIT_ONLY",
            "snapshot_provenance_fields": [
                "source_document_ids",
                "source_document_hashes",
                "reference_scope",
                "reference_scope_hash",
                "context_snapshot_id",
                "context_snapshot_hash",
            ],
        },
        "rag_settings": {
            "version": RAG_SETTINGS_VERSION,
            "top_k": DEFAULT_TOP_K,
            "max_chars": DEFAULT_MAX_CHARS,
            "chunk_chars": DEFAULT_CHUNK_CHARS,
            "completeness_policy": "ALL_DECLARED_REFERENCE_SECTIONS_REQUIRED",
            "truncation_policy": "RECORD_AND_FAIL_CLOSED_WHEN_REQUIRED_SECTION_MISSING",
        },
        "provider_limits_snapshot": {
            "snapshot_id": "GROQ-PILOT-LIMITS-V1",
            "snapshot_version": "1.0",
            "organization_rpm": 30,
            "organization_rpd": 1000,
            "organization_tpm": 8000,
            "organization_tpd": 200000,
            "project_override": "NONE",
            "itpm_otpm": "SEPARATE_ITPM_OTPM_NOT_VERIFIED",
            "source": "docs/PILOT_PROVIDER_LIMITS.md",
        },
        "pacing_policy": deepcopy(PILOT_PACING_POLICY),
        "authorization_mechanism": {
            "authorization_schema_id": PILOT_AUTHORIZATION_SCHEMA_ID,
            "authorization_schema_version": PILOT_AUTHORIZATION_SCHEMA_VERSION,
            "preflight_binding_schema_id": PILOT_PREFLIGHT_BINDING_SCHEMA_ID,
            "preflight_binding_schema_version": PILOT_PREFLIGHT_BINDING_SCHEMA_VERSION,
            "live_window_schema_id": PILOT_LIVE_WINDOW_SCHEMA_ID,
            "live_window_schema_version": PILOT_LIVE_WINDOW_SCHEMA_VERSION,
            "authorized_scope": AUTHORIZED_PILOT_SCOPE,
            "owner_role": "PROJECT_OWNER",
            "final_authorization": "INTEGRATION_DECISION_REQUIRED",
            "execution_side_effect": False,
        },
        "incident_taxonomy": {
            "version": PILOT_INCIDENT_TAXONOMY_VERSION,
            "provider_vs_runtime_origins": True,
        },
        "denominator_policy": {
            "version": PILOT_DENOMINATOR_POLICY_VERSION,
            "canonical_attempt_per_condition": True,
            "case_a_evaluable": "quality_denominator",
            "case_b_provider_or_infrastructure": "reliability_only",
            # The frozen QEP treats a terminal run with no usable answer as
            # strategy missingness, not an answer-level rubric failure.
            "case_c_strategy_terminal_without_answer": "strategy_missingness",
            "case_d_invalid_unit": "exclude_and_report",
            "case_e_manual_exclusion": "predeclared_only",
        },
        "identities": identities,
        "pricing": _pricing_snapshot(provider, model),
        "dry_run": bool(dry_run),
        "secrets": "excluded by design",
    }


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _reference_scope_summary(raw_task: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the task's declarative, runtime-safe reference scope.

    ``reference_bindings`` is authoritative for the frozen benchmark.  A
    whole-document binding is accepted only when it is explicit; a binding
    without section IDs is otherwise invalid and must be rejected by the
    execution layer.  This summary intentionally contains no task text or
    evaluator material and is safe to persist in a manifest/export.
    """

    bindings = raw_task.get("reference_bindings")
    if bindings is None:
        if raw_task.get("whole_document") is True or str(raw_task.get("reference_scope_mode") or "").lower() == "whole_document":
            source_ids = _string_list(raw_task.get("source_document_ids") or raw_task.get("reference_source_ids"))
            if not source_ids:
                raise ValueError("An explicit whole-document task needs source IDs")
            return [
                {"source_id": source_id, "section_ids": [], "whole_document": True}
                for source_id in source_ids
            ]
        return []
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("reference_bindings must be a non-empty list when supplied")
    result: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise ValueError("Every reference binding must be an object")
        source_id = _safe_text(binding.get("source_id"))
        if not source_id:
            raise ValueError("Every reference binding needs source_id")
        if source_id in seen_sources:
            raise ValueError(f"Duplicate reference binding source_id: {source_id}")
        seen_sources.add(source_id)
        explicit_whole = bool(
            binding.get("whole_document") is True
            or str(binding.get("scope_mode") or "").lower() == "whole_document"
        )
        section_ids = _string_list(binding.get("section_ids"))
        if explicit_whole and section_ids:
            raise ValueError(f"Reference binding {source_id} cannot combine whole_document and section_ids")
        if not explicit_whole and not section_ids:
            raise ValueError(f"Reference binding {source_id} must declare section_ids or explicit whole_document")
        result.append({
            "source_id": source_id,
            "section_ids": section_ids,
            "whole_document": explicit_whole,
        })
    return result


def _task_manifest_hash(task_manifest: Mapping[str, Any]) -> str:
    declared = _safe_text(task_manifest.get("manifest_hash"))
    if declared:
        return declared
    source = deepcopy(dict(task_manifest))
    source.pop("manifest_hash", None)
    return sha256_json(source)


_MUTABLE_MANIFEST_FIELDS = {
    "context_snapshot_id",
    "context_snapshot_hash",
    "run_id",
    "status",
    "run_state",
    "raw_evidence_path",
    "attempts",
    "attempt_index",
    "started_at",
    "recorded_at",
    "recovered_at",
    "stop_reason",
    "snapshot_metadata",
    "unit_attempt_id",
    "preflight_binding",
}


def _frozen_manifest_units(units: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return the immutable part of units for the manifest integrity hash.

    The ledger mirrors runtime state back into the manifest for operator
    visibility.  Run IDs, snapshot assignments, and statuses therefore cannot
    be part of the hash that identifies the frozen schedule.
    """

    frozen: list[dict[str, Any]] = []
    for unit in units:
        item = deepcopy(dict(unit))
        conditions = []
        for condition in item.get("conditions") or []:
            conditions.append({
                key: deepcopy(value)
                for key, value in dict(condition).items()
                if key not in _MUTABLE_MANIFEST_FIELDS
            })
        item["conditions"] = conditions
        frozen.append(item)
    return frozen


def _manifest_hash_identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_manifest_version": manifest.get("run_manifest_version"),
        "preregistration_version": manifest.get("preregistration_version"),
        "task_manifest_id": manifest.get("task_manifest_id"),
        "task_manifest_version": manifest.get("task_manifest_version"),
        "task_manifest_hash": manifest.get("task_manifest_hash"),
        "benchmark_id": manifest.get("benchmark_id"),
        "benchmark_version": manifest.get("benchmark_version"),
        "benchmark_provenance_version": manifest.get("benchmark_provenance_version"),
        "provider": manifest.get("provider"),
        "model": manifest.get("model"),
        "phase": manifest.get("phase"),
        "freeze_identity": manifest.get("freeze_identity"),
        "config": deepcopy(dict(manifest.get("configuration") or {})),
        "units": _frozen_manifest_units(manifest.get("units") or []),
        "balance_status": (manifest.get("order_policy") or {}).get("balance_status"),
    }


def _normalized_task_records(task_manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_tasks = task_manifest.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("Task manifest must contain a non-empty tasks[] list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    defaults = {
        "benchmark_id": _safe_text(task_manifest.get("benchmark_id") or task_manifest.get("manifest_id")),
        "benchmark_version": _safe_text(task_manifest.get("benchmark_version") or task_manifest.get("pilot_version")),
        "benchmark_provenance_version": _safe_text(task_manifest.get("pilot_version")),
        "rubric_version_reference": _safe_text(task_manifest.get("rubric_version_reference")),
        "reference_manifest_id": _safe_text(task_manifest.get("reference_manifest_id") or task_manifest.get("benchmark_id")),
        "reference_manifest_version": _safe_text(task_manifest.get("reference_manifest_version") or task_manifest.get("artifact_version")),
    }
    corpus = {
        str(item.get("source_id")): item
        for item in (task_manifest.get("corpus_manifest") or [])
        if isinstance(item, Mapping) and item.get("source_id")
    }
    for raw in raw_tasks:
        if not isinstance(raw, Mapping):
            raise ValueError("Every task manifest item must be an object")
        task_id = _safe_text(raw.get("task_id") or raw.get("id"))
        if not task_id:
            raise ValueError("Every task manifest item needs task_id")
        if task_id in seen:
            raise ValueError(f"Duplicate task_id: {task_id}")
        seen.add(task_id)
        task_hash = _safe_text(raw.get("task_hash")) or sha256_json(dict(raw))
        source_ids = _string_list(raw.get("source_document_ids") or raw.get("reference_source_ids"))
        source_hashes = _string_list(raw.get("source_document_hashes"))
        reference_scope = _reference_scope_summary(raw)
        if reference_scope:
            scoped_source_ids = [item["source_id"] for item in reference_scope]
            # A binding list is the authoritative source order.  If the task
            # also carries a source-ID list, it must describe the same set so
            # provenance cannot drift between manifest and runtime.
            if source_ids and source_ids != scoped_source_ids:
                raise ValueError(f"Task {task_id} source IDs do not match reference_bindings")
            source_ids = scoped_source_ids
        if not source_hashes:
            source_hashes = [
                str(corpus[source_id].get("sha256"))
                for source_id in source_ids
                if source_id in corpus and corpus[source_id].get("sha256")
            ]
        reference_scope_hash = (
            sha256_json({"scope": reference_scope, "source_document_hashes": source_hashes})
            if reference_scope
            else None
        )
        result.append({
            "task_id": task_id,
            "task_version": _safe_text(raw.get("task_version") or raw.get("task_text_version") or raw.get("version") or raw.get("pilot_version")) or "UNVERSIONED",
            "task_hash": task_hash,
            "reference_manifest_id": _safe_text(raw.get("reference_manifest_id")) or defaults["reference_manifest_id"],
            "reference_manifest_version": _safe_text(raw.get("reference_manifest_version")) or defaults["reference_manifest_version"],
            "source_document_ids": source_ids,
            "source_document_hashes": source_hashes,
            "reference_scope": reference_scope,
            "reference_scope_hash": reference_scope_hash,
            "benchmark_id": _safe_text(raw.get("benchmark_id")) or defaults["benchmark_id"],
            # The top-level quality-reviewed benchmark version is canonical;
            # per-task ``pilot_version`` is retained only as provenance.
            "benchmark_version": _safe_text(raw.get("benchmark_version")) or defaults["benchmark_version"] or _safe_text(raw.get("pilot_version")),
            "benchmark_provenance_version": _safe_text(raw.get("pilot_version")) or defaults["benchmark_provenance_version"],
            "rubric_version_reference": _safe_text(raw.get("rubric_version_reference")) or defaults["rubric_version_reference"],
            "ambiguity_flag": (
                raw.get("ambiguity_flag")
                if isinstance(raw.get("ambiguity_flag"), bool)
                else None
            ),
        })
    return result


def _strategy_condition(
    strategy: str,
    *,
    provider: str,
    model: str,
    execution_order: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "strategy_config_id": STRATEGY_CONFIG_IDS[strategy],
        "strategy_config_version": CONFIG_VERSION,
        "provider": provider,
        "model": model,
        "model_settings_identity": MODEL_SETTINGS_ID,
        "context_snapshot_id": None,
        "context_snapshot_hash": None,
        "benchmark_version": None,
        "rubric_version_reference": None,
        "pricing_version": f"{PRICE_CONFIG_ID}@{PRICE_PILOT_CONFIG_VERSION}",
        "pilot_pricing_version": f"{PRICE_PILOT_CONFIG_ID}@{PRICE_PILOT_CONFIG_VERSION}",
        "pilot_strategy_config_id": PILOT_STRATEGY_CONFIG_IDS[strategy],
        "rag_config_id": RAG_CONFIG_ID,
        "rag_pilot_config_id": RAG_PILOT_CONFIG_ID,
        "price_config_id": PRICE_CONFIG_ID,
        "phase": "DRY_RUN" if dry_run else "PILOT",
        "execution_order": execution_order,
        "run_id": None,
        "status": "missing_not_run",
        "run_state": "PENDING",
        "raw_evidence_path": None,
        "attempts": [],
        "dry_run": bool(dry_run),
    }


def build_pilot_manifest(
    task_manifest: Mapping[str, Any],
    *,
    repeat_count: int = 3,
    provider: str = DEFAULT_PILOT_PROVIDER,
    model: str = DEFAULT_PILOT_MODEL,
    preregistration_version: str = PILOT_PREREGISTRATION_VERSION,
    seed: str | None = None,
    budget: Budget | Mapping[str, Any] | None = None,
    dry_run: bool = False,
    require_balanced: bool | None = None,
    preflight_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a no-task-content Pilot Run Manifest."""

    if int(repeat_count) < 1:
        raise ValueError("repeat_count must be positive")
    repeat_count = int(repeat_count)
    provider = str(provider).lower()
    model = str(model)
    tasks = _normalized_task_records(task_manifest)
    benchmark_ids = {task.get("benchmark_id") for task in tasks if task.get("benchmark_id")}
    benchmark_versions = {task.get("benchmark_version") for task in tasks if task.get("benchmark_version")}
    rubric_versions = {task.get("rubric_version_reference") for task in tasks if task.get("rubric_version_reference")}
    if len(benchmark_ids) > 1 or len(benchmark_versions) > 1 or len(rubric_versions) > 1:
        raise ValueError("Pilot tasks must share one benchmark identity/version and rubric version")
    benchmark_id = next(iter(benchmark_ids), _safe_text(task_manifest.get("benchmark_id") or task_manifest.get("manifest_id")))
    benchmark_version = next(iter(benchmark_versions), _safe_text(task_manifest.get("benchmark_version") or task_manifest.get("pilot_version")))
    rubric_version = next(iter(rubric_versions), _safe_text(task_manifest.get("rubric_version_reference")))
    manifest_hash = _task_manifest_hash(task_manifest)
    units: list[dict[str, Any]] = []
    for task in tasks:
        for repeat_index in range(1, repeat_count + 1):
            unit_id = f"{task['task_id']}-r{repeat_index}"
            units.append({
                "unit_id": unit_id,
                "task_id": task["task_id"],
                "repeat_index": repeat_index,
                "repeat_id": f"{task['task_id']}-repeat-{repeat_index}",
                "task_manifest_hash": manifest_hash,
                "task_version": task["task_version"],
                "reference_manifest_id": task["reference_manifest_id"],
                "reference_manifest_version": task["reference_manifest_version"],
                "source_document_ids": task["source_document_ids"],
                "source_document_hashes": task["source_document_hashes"],
                "reference_scope": deepcopy(task["reference_scope"]),
                "reference_scope_hash": task["reference_scope_hash"],
                "benchmark_id": task["benchmark_id"],
                "benchmark_version": task["benchmark_version"],
                "benchmark_provenance_version": task["benchmark_provenance_version"],
                "rubric_version_reference": task["rubric_version_reference"],
                "ambiguity_flag": task["ambiguity_flag"],
            })

    if require_balanced is None:
        require_balanced = not dry_run
    if dry_run:
        schedule = _dry_run_order_schedule(
            [unit["unit_id"] for unit in units],
            preregistration_version=preregistration_version,
            task_manifest_hash=manifest_hash,
        )
        balance_status = "not_applicable_dry_run"
    elif len(units) % len(PILOT_STRATEGIES) == 0:
        schedule = build_balanced_order_schedule(
            [unit["unit_id"] for unit in units],
            preregistration_version=preregistration_version,
            task_manifest_hash=manifest_hash,
            seed=seed,
        )
        balance_status = "balanced"
    else:
        if require_balanced:
            raise ValueError("A live Pilot manifest must have a comparison-unit count divisible by four")
        schedule = _dry_run_order_schedule(
            [unit["unit_id"] for unit in units],
            preregistration_version=preregistration_version,
            task_manifest_hash=manifest_hash,
        )
        balance_status = "unbalanced_requires_review"
    validate_order_schedule(schedule, [unit["unit_id"] for unit in units], require_balanced=balance_status == "balanced")
    schedule_by_unit = {row["unit_id"]: row for row in schedule}
    config = pilot_config_snapshot(provider=provider, model=model, budget=budget, dry_run=dry_run)
    for unit in units:
        order_info = schedule_by_unit[unit["unit_id"]]
        unit.update({
            "order_seed": order_info["order_seed"],
            "latin_square_row": order_info["latin_square_row"],
            "strategy_order": order_info["strategy_order"],
            "execution_order": order_info["execution_order"],
            "conditions": [
                _strategy_condition(
                    strategy,
                    provider=provider,
                    model=model,
                    execution_order=order_info["execution_order"][strategy],
                    dry_run=dry_run,
                )
                for strategy in order_info["strategy_order"]
            ],
        })
        for condition in unit["conditions"]:
            condition["benchmark_id"] = unit["benchmark_id"]
            condition["benchmark_version"] = unit["benchmark_version"]
            condition["benchmark_provenance_version"] = unit["benchmark_provenance_version"]
            condition["rubric_version_reference"] = unit["rubric_version_reference"]

    task_manifest_id = _safe_text(task_manifest.get("manifest_id") or task_manifest.get("benchmark_id")) or "TASK-MANIFEST-UNNAMED"
    task_manifest_version = _safe_text(task_manifest.get("version") or task_manifest.get("manifest_version") or task_manifest.get("artifact_version")) or "UNVERSIONED"
    manifest_identity = _manifest_hash_identity({
        "run_manifest_version": PILOT_RUN_MANIFEST_VERSION,
        "preregistration_version": preregistration_version,
        "task_manifest_id": task_manifest_id,
        "task_manifest_version": task_manifest_version,
        "task_manifest_hash": manifest_hash,
        "benchmark_id": benchmark_id,
        "benchmark_version": benchmark_version,
        "benchmark_provenance_version": _safe_text(task_manifest.get("pilot_version")),
        "provider": provider,
        "model": model,
        "phase": "DRY_RUN" if dry_run else "PILOT",
        "freeze_identity": "DRY-RUN-NONE" if dry_run else PILOT_FREEZE_IDENTITY,
        "configuration": config,
        "preflight_binding": deepcopy(dict(preflight_binding)) if preflight_binding else None,
        "units": units,
        "order_policy": {"balance_status": balance_status},
    })
    run_manifest_hash = sha256_json(manifest_identity)
    manifest = {
        "manifest_type": "pilot_run_manifest",
        "run_manifest_version": PILOT_RUN_MANIFEST_VERSION,
        "manifest_id": f"pm_{run_manifest_hash[:12]}",
        "run_manifest_hash": run_manifest_hash,
        "created_at": utc_now(),
        "status": "dry_run" if dry_run else "prepared",
        "phase": "DRY_RUN" if dry_run else "PILOT",
        "freeze_identity": "DRY-RUN-NONE" if dry_run else PILOT_FREEZE_IDENTITY,
        "dry_run": bool(dry_run),
        "preregistration_version": preregistration_version,
        "task_manifest_id": task_manifest_id,
        "task_manifest_version": task_manifest_version,
        "task_manifest_hash": manifest_hash,
        "benchmark_id": benchmark_id,
        "benchmark_version": benchmark_version,
        "benchmark_provenance_version": _safe_text(task_manifest.get("pilot_version")),
        "rubric_version_reference": rubric_version,
        "provider": provider,
        "model": model,
        "model_settings_identity": MODEL_SETTINGS_ID,
        "pricing_version": f"{PRICE_CONFIG_ID}@{PRICE_PILOT_CONFIG_VERSION}",
        "pilot_config_identities": dict(PILOT_CONFIG_IDENTITIES),
        "config_identities": config["identities"],
        "configuration": config,
        "prompt_versions": dict(PROMPT_VERSIONS),
        "preflight_binding": deepcopy(dict(preflight_binding)) if preflight_binding else None,
        "order_policy": {
            "algorithm": "balanced-latin-square-v1" if not dry_run else "canonical-dry-run-order",
            "seed": _master_order_seed(preregistration_version, manifest_hash, seed) if not dry_run else None,
            "seed_derivation": "SHA-256(preregistration_version|task_manifest_hash|unit_id) per unit",
            "strategy_rows": [list(row) for row in LATIN_SQUARE_ROWS],
            "balance_status": balance_status,
            "top_level_sequential": True,
            "internal_worker_parallelism_allowed": True,
        },
        "expected_task_count": len(tasks),
        "repeat_count": repeat_count,
        "expected_comparison_units": len(units),
        "expected_strategy_runs": len(units) * len(PILOT_STRATEGIES),
        "units": units,
    }
    validate_pilot_manifest(manifest, require_balanced=balance_status == "balanced")
    return manifest


def _condition_key(unit_id: str, strategy: str) -> str:
    return f"{unit_id}::{strategy}"


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError as exc:
        raise ValueError("Raw evidence path must remain inside the Pilot ledger directory") from exc


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ledger_state_hash(ledger: Mapping[str, Any]) -> str:
    """Hash mutable ledger state for pairwise manifest/ledger reconciliation.

    The frozen schedule hash deliberately excludes run state.  This second
    hash covers the append-oriented mutable state and detects a crash between
    the two atomic file replacements.
    """

    state = {
        "ledger_version": ledger.get("ledger_version"),
        "manifest_id": ledger.get("manifest_id"),
        "conditions": ledger.get("conditions") or [],
        "unit_attempts": ledger.get("unit_attempts") or [],
        "integrity_block": ledger.get("integrity_block"),
    }
    return sha256_json(state)


def validate_pilot_manifest(manifest: Mapping[str, Any], *, require_balanced: bool = True) -> bool:
    if manifest.get("run_manifest_version") != PILOT_RUN_MANIFEST_VERSION:
        raise ValueError("Unsupported Pilot Run Manifest version")
    declared_hash = manifest.get("run_manifest_hash")
    if not isinstance(declared_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", declared_hash):
        raise ValueError("Pilot Run Manifest needs a valid run_manifest_hash")
    expected_hash = sha256_json(_manifest_hash_identity(manifest))
    if declared_hash != expected_hash:
        raise ValueError("Pilot Run Manifest hash does not match its frozen schedule/configuration")
    if manifest.get("manifest_id") != f"pm_{declared_hash[:12]}":
        raise ValueError("Pilot Run Manifest ID does not match its hash")
    if manifest.get("model_settings_identity") != MODEL_SETTINGS_ID:
        raise ValueError("Pilot model settings identity is not frozen")
    expected_phase = "DRY_RUN" if manifest.get("dry_run", False) else "PILOT"
    if manifest.get("phase") not in {None, expected_phase}:
        raise ValueError("Pilot phase does not match dry-run classification")
    if not manifest.get("dry_run", False) and manifest.get("freeze_identity") not in {None, PILOT_FREEZE_IDENTITY}:
        raise ValueError("Pilot freeze identity is not recognized")
    if not _safe_text(manifest.get("benchmark_id")) or not _safe_text(manifest.get("benchmark_version")):
        raise ValueError("Pilot benchmark identity/version is not frozen")
    rag_settings = (manifest.get("configuration") or {}).get("rag_settings") or {}
    if rag_settings.get("version") != RAG_SETTINGS_VERSION:
        raise ValueError("Pilot RAG settings version is not frozen")
    if int(rag_settings.get("top_k", 0)) < 1 or int(rag_settings.get("max_chars", 0)) < 1:
        raise ValueError("Pilot RAG settings are incomplete")
    if manifest.get("dry_run") and (manifest.get("status") not in {"dry_run", "prepared"}):
        raise ValueError("Dry-run manifest has an invalid status")
    units = manifest.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("Pilot Run Manifest needs a non-empty units[] list")
    unit_ids = [str(unit.get("unit_id")) for unit in units]
    if any(item in {"", "None"} for item in unit_ids) or len(set(unit_ids)) != len(unit_ids):
        raise ValueError("Pilot comparison unit IDs must be unique")
    schedules = []
    for unit in units:
        if unit.get("benchmark_id") != manifest.get("benchmark_id"):
            raise ValueError("Unit benchmark identity does not match the manifest")
        if unit.get("benchmark_version") != manifest.get("benchmark_version"):
            raise ValueError("Unit benchmark version does not match the manifest")
        order = list(unit.get("strategy_order") or [])
        schedules.append({
            "unit_id": unit["unit_id"],
            "order_seed": unit.get("order_seed"),
            "strategy_order": order,
            "execution_order": unit.get("execution_order"),
        })
        conditions = unit.get("conditions")
        if not isinstance(conditions, list) or len(conditions) != len(PILOT_STRATEGIES):
            raise ValueError(f"Unit {unit['unit_id']} must contain four strategy conditions")
        if {condition.get("strategy") for condition in conditions} != set(PILOT_STRATEGIES):
            raise ValueError(f"Unit {unit['unit_id']} does not contain all four strategies")
        for condition in conditions:
            strategy = condition.get("strategy")
            if condition.get("strategy_config_id") != STRATEGY_CONFIG_IDS[strategy]:
                raise ValueError(f"Unexpected config identity for {strategy}")
            if condition.get("pilot_strategy_config_id") != PILOT_STRATEGY_CONFIG_IDS[strategy]:
                raise ValueError(f"Unexpected Pilot config identity for {strategy}")
            if condition.get("benchmark_id") != manifest.get("benchmark_id"):
                raise ValueError("Condition benchmark identity does not match the manifest")
            if condition.get("benchmark_version") != manifest.get("benchmark_version"):
                raise ValueError("Condition benchmark version does not match the manifest")
            if condition.get("benchmark_provenance_version") != unit.get("benchmark_provenance_version"):
                raise ValueError("Condition benchmark provenance does not match its unit")
            if condition.get("rubric_version_reference") != unit.get("rubric_version_reference"):
                raise ValueError("Condition rubric version does not match its unit")
            if condition.get("strategy_config_version") != CONFIG_VERSION:
                raise ValueError("Strategy config version is not frozen")
            if condition.get("model_settings_identity") != MODEL_SETTINGS_ID:
                raise ValueError("Model settings identity is not frozen")
            if condition.get("rag_config_id") != RAG_CONFIG_ID:
                raise ValueError("RAG config identity is not frozen")
            if condition.get("rag_pilot_config_id") != RAG_PILOT_CONFIG_ID:
                raise ValueError("Pilot RAG config identity is not frozen")
            if condition.get("price_config_id") != PRICE_CONFIG_ID:
                raise ValueError("Pricing config identity is not frozen")
            if condition.get("pricing_version") != f"{PRICE_CONFIG_ID}@{PRICE_PILOT_CONFIG_VERSION}":
                raise ValueError("Pricing version is not frozen")
            if condition.get("provider") != manifest.get("provider"):
                raise ValueError("Provider is not frozen across Pilot conditions")
            if condition.get("model") != manifest.get("model"):
                raise ValueError("Model is not frozen across Pilot conditions")
            if condition.get("execution_order") != unit["execution_order"].get(strategy):
                raise ValueError("Condition execution order does not match its unit")
            if condition.get("status") not in set(PILOT_STATUSES) | {_ACTIVE_STATUS}:
                raise ValueError(f"Unsupported condition status: {condition.get('status')}")
            if condition.get("run_state") is not None:
                expected_state = control_state_from_status(condition.get("status"))
                if condition.get("run_state") != expected_state:
                    raise ValueError("Condition run_state does not match its status")
            if bool(condition.get("dry_run", False)) != bool(manifest.get("dry_run", False)):
                raise ValueError("Dry-run classification is not frozen across Pilot conditions")
            if condition.get("phase") != expected_phase:
                raise ValueError("Condition phase does not match the manifest")
    validate_order_schedule(schedules, unit_ids, require_balanced=require_balanced)
    return True


def _flatten_manifest_conditions(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for unit in manifest.get("units") or []:
        for condition in unit.get("conditions") or []:
            item = deepcopy(dict(condition))
            item.update({
                "unit_id": unit.get("unit_id"),
                "task_id": unit.get("task_id"),
                "repeat_index": unit.get("repeat_index"),
                "repeat_id": unit.get("repeat_id"),
                "task_manifest_hash": unit.get("task_manifest_hash"),
                "task_version": unit.get("task_version"),
                "reference_manifest_id": unit.get("reference_manifest_id"),
                "reference_manifest_version": unit.get("reference_manifest_version"),
                "source_document_ids": unit.get("source_document_ids") or [],
                "source_document_hashes": unit.get("source_document_hashes") or [],
                "reference_scope": deepcopy(unit.get("reference_scope") or []),
                "reference_scope_hash": unit.get("reference_scope_hash"),
                "benchmark_id": unit.get("benchmark_id"),
                "benchmark_version": unit.get("benchmark_version"),
                "benchmark_provenance_version": unit.get("benchmark_provenance_version"),
                "rubric_version_reference": unit.get("rubric_version_reference"),
                "order_seed": unit.get("order_seed"),
                "strategy_order": unit.get("strategy_order"),
            })
            item["condition_key"] = _condition_key(item["unit_id"], item["strategy"])
            result.append(item)
    return result


class PilotLedger:
    """Append-oriented ledger for one Pilot manifest.

    A terminal condition cannot be started again through this ledger.  An
    interrupted in-flight condition is recovered as ``missing_not_run`` and a
    later attempt receives a new run ID, leaving the old attempt reference
    intact.  Raw evidence files are never edited or deleted here.
    """

    def __init__(self, root: str | Path, manifest: Mapping[str, Any] | None = None):
        # Store one canonical root so callers can safely pass either relative
        # or absolute output directories without double-prefixing raw paths.
        self.root = Path(root).resolve()
        self.manifest_path = self.root / "manifest.json"
        self.ledger_path = self.root / "ledger.json"
        self.raw_dir = self.root / "raw"
        if manifest is not None:
            if self.manifest_path.exists() or self.ledger_path.exists():
                raise FileExistsError(
                    "Pilot manifest/ledger already exists; open it for resume instead of replacing it"
                )
            if self.raw_dir.exists() and any(self.raw_dir.glob("run_*.json")):
                raise FileExistsError(
                    "Pilot raw evidence already exists without a fresh ledger; choose a new output directory"
                )
            validate_pilot_manifest(manifest, require_balanced=manifest.get("order_policy", {}).get("balance_status") == "balanced")
            self.manifest = deepcopy(dict(manifest))
            self.ledger = {
                "ledger_version": PILOT_LEDGER_VERSION,
                "manifest_id": self.manifest["manifest_id"],
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "conditions": [],
                "unit_attempts": [],
            }
            for condition in _flatten_manifest_conditions(self.manifest):
                self.ledger["conditions"].append(condition)
            self._persist()
        else:
            self.manifest = _read_json(self.manifest_path)
            self.ledger = _read_json(self.ledger_path)
            if self.ledger.get("manifest_id") != self.manifest.get("manifest_id"):
                raise ValueError("Manifest and ledger IDs do not match")
            validate_pilot_manifest(
                self.manifest,
                require_balanced=(self.manifest.get("order_policy", {}).get("balance_status") == "balanced"),
            )
            manifest_state_hash = self.manifest.get("ledger_state_hash")
            ledger_state_hash = self.ledger.get("state_hash")
            if manifest_state_hash or ledger_state_hash:
                if manifest_state_hash != ledger_state_hash or ledger_state_hash != _ledger_state_hash(self.ledger):
                    raise RuntimeError("DATA_INTEGRITY_ERROR: manifest and ledger mutable state diverged")
            else:
                # Legacy ledgers predate the pair hash.  A one-time migration
                # is safe only when both files are present and otherwise
                # internally consistent; a one-sided field is never repaired.
                self._persist()
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def open(cls, root: str | Path) -> "PilotLedger":
        return cls(root)

    def _persist(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger["updated_at"] = utc_now()
        state_hash = _ledger_state_hash(self.ledger)
        self.ledger["state_hash"] = state_hash
        self.manifest["ledger_state_hash"] = state_hash
        _atomic_write_json(self.manifest_path, self.manifest)
        _atomic_write_json(self.ledger_path, self.ledger)

    def _find(self, unit_id: str, strategy: str) -> dict[str, Any]:
        key = _condition_key(unit_id, strategy)
        for condition in self.ledger.get("conditions") or []:
            if condition.get("condition_key") == key:
                return condition
        raise KeyError(f"Unknown Pilot condition: {key}")

    def _inside(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        _safe_relative(candidate, self.root)
        return candidate

    def _sync_manifest_condition(self, condition: Mapping[str, Any]) -> None:
        for unit in self.manifest.get("units") or []:
            if unit.get("unit_id") != condition.get("unit_id"):
                continue
            for item in unit.get("conditions") or []:
                if item.get("strategy") == condition.get("strategy"):
                    for key in (
                        "context_snapshot_id",
                        "context_snapshot_hash",
                        "snapshot_metadata",
                        "unit_attempt_id",
                        "run_id",
                        "status",
                        "run_state",
                        "raw_evidence_path",
                        "attempts",
                        "attempt_index",
                        "recorded_at",
                        "started_at",
                        "recovered_at",
                        "stop_reason",
                    ):
                        if key in condition:
                            item[key] = deepcopy(condition[key])
                    return
        raise KeyError(f"Manifest condition not found: {condition.get('condition_key')}")

    def _used_run_ids(self) -> set[str]:
        used: set[str] = set()
        for condition in self.ledger.get("conditions") or []:
            if condition.get("run_id"):
                used.add(str(condition["run_id"]))
            for attempt in condition.get("attempts") or []:
                if attempt.get("run_id"):
                    used.add(str(attempt["run_id"]))
        return used

    def condition(self, unit_id: str, strategy: str) -> dict[str, Any]:
        return deepcopy(self._find(unit_id, strategy))

    def _find_orphan_terminal_raw(self, condition: Mapping[str, Any]) -> dict[str, Any] | None:
        """Find an unrecorded terminal raw file for this exact condition.

        This protects a restart after an unusual crash window where the runtime
        persisted raw evidence but the ledger update did not complete.
        """

        known_ids = {
            str(item.get("run_id"))
            for item in condition.get("attempts") or []
            if item.get("run_id")
        }
        if condition.get("run_id"):
            known_ids.add(str(condition["run_id"]))
        for path in sorted(self.raw_dir.glob("run_*.json")):
            try:
                raw = _read_json(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            pilot = raw.get("pilot") if isinstance(raw.get("pilot"), Mapping) else {}
            condition_id = pilot.get("condition_id") or raw.get("condition_id")
            run_id = str(raw.get("run_id") or "")
            if condition_id != condition.get("condition_key") or run_id in known_ids:
                continue
            if self.status_from_raw(raw) in _TERMINAL_STATUSES:
                return {"path": str(path), "raw": raw}
        return None

    def begin(
        self,
        unit_id: str,
        strategy: str,
        *,
        run_id: str | None = None,
        retry: bool = False,
    ) -> dict[str, Any]:
        condition = self._find(unit_id, strategy)
        status = condition.get("status")
        if status == "observed":
            raise RuntimeError(f"CONDITION_ALREADY_TERMINAL:{condition['condition_key']}:{status}")
        if status == "provider_incident" and retry:
            raise RuntimeError(
                f"WHOLE_UNIT_RERUN_REQUIRED:{condition.get('unit_id')}:{condition['condition_key']}"
            )
        if status in _TERMINAL_STATUSES and not (retry and status in _RETRYABLE_TERMINAL_STATUSES):
            raise RuntimeError(f"CONDITION_ALREADY_TERMINAL_RETRY_REQUIRES_OPT_IN:{condition['condition_key']}:{status}")
        if status == _ACTIVE_STATUS:
            raise RuntimeError(f"CONDITION_ALREADY_RUNNING:{condition['condition_key']}")
        orphan = self._find_orphan_terminal_raw(condition)
        if orphan is not None:
            raise RuntimeError(
                f"UNRECORDED_TERMINAL_RAW_EVIDENCE:{condition['condition_key']}:{orphan['raw'].get('run_id')}"
            )
        selected_run_id = run_id or new_run_id()
        if not re.fullmatch(r"run_[A-Za-z0-9_-]+", selected_run_id):
            raise ValueError("Invalid run ID")
        if selected_run_id in self._used_run_ids():
            raise RuntimeError(f"RUN_ID_ALREADY_USED:{selected_run_id}")
        raw_path = self.root / "raw" / f"{selected_run_id}.json"
        if raw_path.exists():
            raise RuntimeError(f"RUN_ID_OR_RAW_PATH_ALREADY_EXISTS:{selected_run_id}")
        condition.update({
            "status": _ACTIVE_STATUS,
            "run_state": "RUNNING",
            "run_id": selected_run_id,
            "started_at": utc_now(),
            "raw_evidence_path": f"raw/{selected_run_id}.json",
            "attempt_index": len(condition.get("attempts") or []) + 1,
        })
        self._sync_manifest_condition(condition)
        self._persist()
        return deepcopy(condition)

    def set_unit_snapshot(
        self,
        unit_id: str,
        *,
        snapshot_id: str,
        snapshot_hash: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Freeze one snapshot identity across all four conditions in a unit."""

        if not snapshot_id or not snapshot_hash:
            raise ValueError("A comparison unit needs both snapshot_id and snapshot_hash")
        conditions = [
            condition
            for condition in self.ledger.get("conditions") or []
            if condition.get("unit_id") == unit_id
        ]
        if len(conditions) != len(PILOT_STRATEGIES):
            raise KeyError(f"Unknown or incomplete Pilot comparison unit: {unit_id}")
        for condition in conditions:
            if condition.get("context_snapshot_id") not in {None, snapshot_id}:
                raise RuntimeError(f"SNAPSHOT_FAIRNESS_MISMATCH:{unit_id}:snapshot_id")
            if condition.get("context_snapshot_hash") not in {None, snapshot_hash}:
                raise RuntimeError(f"SNAPSHOT_FAIRNESS_MISMATCH:{unit_id}:snapshot_hash")
        for condition in conditions:
            condition["context_snapshot_id"] = snapshot_id
            condition["context_snapshot_hash"] = snapshot_hash
            if metadata is not None:
                existing_metadata = condition.get("snapshot_metadata")
                if existing_metadata is not None:
                    left = deepcopy(dict(existing_metadata))
                    right = deepcopy(dict(metadata))
                    # Created time is provenance, not snapshot identity; a
                    # resumed process recomputes it but must retain the first
                    # persisted timestamp.
                    for volatile in ("created_at", "context_prep_ms"):
                        left.pop(volatile, None)
                        right.pop(volatile, None)
                    if left != right:
                        raise RuntimeError(f"SNAPSHOT_FAIRNESS_MISMATCH:{unit_id}:snapshot_metadata")
                else:
                    condition["snapshot_metadata"] = deepcopy(dict(metadata))
            self._sync_manifest_condition(condition)
        self._persist()
        return {
            "unit_id": unit_id,
            "context_snapshot_id": snapshot_id,
            "context_snapshot_hash": snapshot_hash,
            "snapshot_metadata": deepcopy(dict(metadata)) if metadata is not None else None,
        }

    def mark_unit_incident(
        self,
        unit_id: str,
        *,
        category: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Pause a comparison unit after a provider/infrastructure incident.

        The four conditions remain intact and their raw evidence is never
        rewritten.  A later retry must call :meth:`begin_unit_attempt`, which
        gives the complete unit a new identity instead of selectively retrying
        the affected strategy.
        """

        conditions = [
            condition
            for condition in self.ledger.get("conditions") or []
            if condition.get("unit_id") == unit_id
        ]
        if len(conditions) != len(PILOT_STRATEGIES):
            raise KeyError(f"Unknown or incomplete Pilot comparison unit: {unit_id}")
        unit_attempt_id = next(
            (str(condition.get("unit_attempt_id")) for condition in conditions if condition.get("unit_attempt_id")),
            f"ua_{uuid.uuid4().hex[:12]}",
        )
        for condition in conditions:
            condition["unit_attempt_id"] = unit_attempt_id
            self._sync_manifest_condition(condition)
        attempts = self.ledger.setdefault("unit_attempts", [])
        record = next((item for item in attempts if item.get("unit_attempt_id") == unit_attempt_id), None)
        if record is None:
            record = {
                "unit_attempt_id": unit_attempt_id,
                "unit_id": unit_id,
                "status": "provider_incident",
                "rerunnable": True,
                "provider_error_category": category,
                "reason": str(reason or "provider/infrastructure incident")[:500],
                "created_at": utc_now(),
            }
            attempts.append(record)
        else:
            record.update({
                "status": "provider_incident",
                "rerunnable": True,
                "provider_error_category": category or record.get("provider_error_category"),
                "reason": str(reason or record.get("reason") or "provider/infrastructure incident")[:500],
            })
        self._persist()
        return deepcopy(record)

    def begin_unit_attempt(self, unit_id: str) -> dict[str, Any]:
        """Start a complete four-strategy rerun for an incident-invalid unit."""

        conditions = [
            condition
            for condition in self.ledger.get("conditions") or []
            if condition.get("unit_id") == unit_id
        ]
        if len(conditions) != len(PILOT_STRATEGIES):
            raise KeyError(f"Unknown or incomplete Pilot comparison unit: {unit_id}")
        prior = [
            item for item in self.ledger.get("unit_attempts") or []
            if item.get("unit_id") == unit_id
        ]
        if not prior or not any(item.get("rerunnable") for item in prior):
            raise RuntimeError(f"UNIT_RERUN_NOT_ALLOWED:{unit_id}")
        if any(condition.get("status") == _ACTIVE_STATUS for condition in conditions):
            raise RuntimeError(f"UNIT_RERUN_ALREADY_RUNNING:{unit_id}")
        unit_attempt_id = f"ua_{uuid.uuid4().hex[:12]}"
        record = {
            "unit_attempt_id": unit_attempt_id,
            "unit_id": unit_id,
            "status": "running",
            "rerunnable": False,
            "created_at": utc_now(),
            "reason": "predeclared whole-unit rerun after provider/infrastructure incident",
        }
        for prior in self.ledger.get("unit_attempts") or []:
            if prior.get("unit_id") == unit_id and prior.get("rerunnable") is True:
                prior["rerunnable"] = False
                prior["superseded_by"] = unit_attempt_id
        self.ledger.setdefault("unit_attempts", []).append(record)
        for condition in conditions:
            condition.update({
                "unit_attempt_id": unit_attempt_id,
                "status": "missing_not_run",
                "run_state": "PENDING",
                "run_id": None,
                "raw_evidence_path": None,
                "stop_reason": None,
                "attempt_index": len(condition.get("attempts") or []),
            })
            self._sync_manifest_condition(condition)
        self._persist()
        return deepcopy(record)

    def unit_attempt_status(self, unit_id: str) -> dict[str, Any] | None:
        attempts = [
            item for item in self.ledger.get("unit_attempts") or []
            if item.get("unit_id") == unit_id
        ]
        if not attempts:
            return None
        return deepcopy(attempts[-1])

    def complete_unit_attempt(self, unit_id: str, *, status: str = "completed") -> dict[str, Any] | None:
        """Close the current unit-attempt marker after all four conditions finish."""

        attempts = self.ledger.get("unit_attempts") or []
        record = next(
            (item for item in reversed(attempts) if item.get("unit_id") == unit_id and item.get("status") == "running"),
            None,
        )
        if record is None:
            return None
        record["status"] = status
        record["completed_at"] = utc_now()
        record["rerunnable"] = False
        for prior in attempts:
            if prior is not record and prior.get("unit_id") == unit_id and prior.get("status") == "provider_incident":
                prior["status"] = "superseded"
                prior["superseded_by"] = record.get("unit_attempt_id")
        self._persist()
        return deepcopy(record)

    @staticmethod
    def status_from_raw(raw: Mapping[str, Any]) -> str:
        incident = raw.get("incident") if isinstance(raw.get("incident"), Mapping) else {}
        if raw.get("provider_incident") is True or incident.get("origin") == "provider" or raw.get("incident_origin") == "provider":
            return "provider_incident"
        if raw.get("provider_error_category"):
            return "provider_incident"
        status = raw.get("status")
        if status == "completed":
            return "observed"
        if status == "stopped":
            return "stopped"
        if status == "failed":
            return "failed"
        if status == "degraded":
            return "stopped"
        return "invalidated"

    def record(
        self,
        unit_id: str,
        strategy: str,
        *,
        raw_path: str | Path,
        raw: Mapping[str, Any] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        condition = self._find(unit_id, strategy)
        if condition.get("status") != _ACTIVE_STATUS:
            raise RuntimeError(f"CONDITION_NOT_RUNNING:{condition['condition_key']}")
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root / path
        path = self._inside(path)
        if not path.exists():
            raise FileNotFoundError(f"Raw evidence is required before recording a condition: {path}")
        if raw is None:
            raw = _read_json(path)
        selected_status = status or self.status_from_raw(raw)
        if selected_status not in _TERMINAL_STATUSES:
            raise ValueError(f"Unsupported terminal condition status: {selected_status}")
        run_id = str(condition.get("run_id") or raw.get("run_id") or "")
        if not run_id or raw.get("run_id") != run_id:
            raise ValueError("Raw evidence run_id does not match the ledger reservation")
        if raw.get("strategy") is not None and raw.get("strategy") != strategy:
            raise ValueError("Raw evidence strategy does not match the ledger reservation")
        if raw.get("strategy_config_id") is not None and raw.get("strategy_config_id") != condition.get("strategy_config_id"):
            raise ValueError("Raw evidence config identity does not match the manifest")
        if raw.get("strategy_config_version") is not None and raw.get("strategy_config_version") != condition.get("strategy_config_version"):
            raise ValueError("Raw evidence config version does not match the manifest")
        for key in ("provider", "model"):
            if raw.get(key) is not None and raw.get(key) != condition.get(key):
                raise ValueError(f"Raw evidence {key} does not match the manifest")
        if raw.get("dry_run") is not None and bool(raw.get("dry_run")) != bool(condition.get("dry_run", False)):
            raise ValueError("Raw evidence dry-run classification does not match the manifest")
        pilot = raw.get("pilot") if isinstance(raw.get("pilot"), Mapping) else {}
        if pilot.get("condition_id") is not None and pilot.get("condition_id") != condition.get("condition_key"):
            raise ValueError("Raw evidence condition identity does not match the ledger reservation")
        if pilot.get("attempt_id") is not None and pilot.get("attempt_id") != run_id:
            raise ValueError("Raw evidence attempt identity does not match the ledger reservation")
        for key in ("task_id", "unit_id", "execution_order", "strategy_config_id", "pilot_strategy_config_id"):
            if pilot.get(key) is not None and pilot.get(key) != condition.get(key):
                raise ValueError(f"Raw evidence Pilot {key} does not match the manifest")
        for key in ("snapshot_id", "snapshot_hash"):
            existing = condition.get("context_snapshot_id" if key == "snapshot_id" else "context_snapshot_hash")
            if existing is not None and raw.get(key) is not None and raw.get(key) != existing:
                raise ValueError(f"Raw evidence {key} does not match the unit snapshot")
            if raw.get(key) is not None:
                for sibling in self.ledger.get("conditions") or []:
                    if sibling.get("unit_id") == condition.get("unit_id") and sibling is not condition:
                        sibling_key = "context_snapshot_id" if key == "snapshot_id" else "context_snapshot_hash"
                        if sibling.get(sibling_key) is not None and sibling[sibling_key] != raw[key]:
                            raise ValueError(f"Unit snapshot mismatch for {key}")
        relative_path = _safe_relative(path, self.root)
        attempt = {
            "attempt_index": condition.get("attempt_index", 1),
            "run_id": run_id,
            "attempt_id": run_id,
            "status": selected_status,
            "run_state": control_state_from_status(selected_status),
            "raw_evidence_path": relative_path,
            "recorded_at": utc_now(),
            "stop_reason": raw.get("stop_reason"),
        }
        condition.setdefault("attempts", []).append(attempt)
        condition.update({
            "status": selected_status,
            "run_state": control_state_from_status(selected_status),
            "raw_evidence_path": relative_path,
            "recorded_at": attempt["recorded_at"],
            "stop_reason": raw.get("stop_reason"),
        })
        for key in ("context_snapshot_id", "context_snapshot_hash"):
            if raw.get(key) is not None:
                condition[key] = raw[key]
        self._sync_manifest_condition(condition)
        self._persist()
        return deepcopy(condition)

    def recover_interrupted(self) -> list[dict[str, Any]]:
        recovered = []
        for condition in self.ledger.get("conditions") or []:
            if condition.get("status") != _ACTIVE_STATUS:
                continue
            raw_path = self._inside(str(condition.get("raw_evidence_path") or ""))
            if raw_path.exists():
                try:
                    raw = _read_json(raw_path)
                    raw_snapshot_id = raw.get("snapshot_id")
                    raw_snapshot_hash = raw.get("snapshot_hash")
                    if raw_snapshot_id and raw_snapshot_hash:
                        unit_conditions = [
                            sibling
                            for sibling in self.ledger.get("conditions") or []
                            if sibling.get("unit_id") == condition.get("unit_id")
                        ]
                        for sibling in unit_conditions:
                            if sibling.get("context_snapshot_id") not in {None, raw_snapshot_id}:
                                raise RuntimeError("Interrupted raw evidence conflicts with the unit snapshot")
                            if sibling.get("context_snapshot_hash") not in {None, raw_snapshot_hash}:
                                raise RuntimeError("Interrupted raw evidence conflicts with the unit snapshot")
                        for sibling in unit_conditions:
                            sibling["context_snapshot_id"] = raw_snapshot_id
                            sibling["context_snapshot_hash"] = raw_snapshot_hash
                            self._sync_manifest_condition(sibling)
                    if raw.get("run_id") == condition.get("run_id") and (
                        raw.get("status") in {"completed", "failed", "stopped", "degraded"}
                        or raw.get("provider_incident") is True
                        or raw.get("provider_error_category")
                    ):
                        recovered.append(self.record(
                            condition["unit_id"],
                            condition["strategy"],
                            raw_path=raw_path,
                            raw=raw,
                        ))
                        continue
                    # A present but non-terminal raw file is ambiguous: it
                    # may be a torn write or a process that was interrupted
                    # before finalization.  Preserve it and block resume;
                    # silently converting it to a fresh attempt would risk
                    # duplicate or selectively missing observations.
                    self.ledger["integrity_block"] = {
                        "code": "DATA_INTEGRITY_ERROR",
                        "reason": f"non-terminal raw evidence for {condition.get('condition_key')}",
                        "recorded_at": utc_now(),
                    }
                    self._persist()
                    raise RuntimeError(
                        "DATA_INTEGRITY_ERROR: non-terminal raw evidence "
                        f"for {condition.get('condition_key')}"
                    )
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    self.ledger["integrity_block"] = {
                        "code": "DATA_INTEGRITY_ERROR",
                        "reason": f"malformed raw evidence for {condition.get('condition_key')}",
                        "recorded_at": utc_now(),
                    }
                    self._persist()
                    raise RuntimeError(
                        "DATA_INTEGRITY_ERROR: malformed raw evidence "
                        f"for {condition.get('condition_key')}"
                    ) from exc
            old_run_id = condition.get("run_id")
            interrupted_attempt = {
                "attempt_index": condition.get("attempt_index", 1),
                "run_id": old_run_id,
                "attempt_id": old_run_id,
                "status": "missing_not_run",
                "run_state": "PENDING",
                "raw_evidence_path": condition.get("raw_evidence_path"),
                "recorded_at": utc_now(),
                "recovery_reason": "execution_interrupted_before_terminal_raw_evidence",
            }
            condition.setdefault("attempts", []).append(interrupted_attempt)
            condition.update({
                "status": "missing_not_run",
                "run_state": "PENDING",
                "run_id": None,
                "raw_evidence_path": None,
                "recovered_at": interrupted_attempt["recorded_at"],
            })
            self._sync_manifest_condition(condition)
            recovered.append(deepcopy(condition))
        if recovered:
            self._persist()
        return recovered

    def pending(self) -> list[dict[str, Any]]:
        return [
            deepcopy(condition)
            for condition in self.ledger.get("conditions") or []
            if condition.get("status") == "missing_not_run"
        ]

    def status_summary(self) -> dict[str, Any]:
        """Return operator-facing state counts without changing the ledger."""

        statuses = {status: 0 for status in (*PILOT_STATUSES, _ACTIVE_STATUS)}
        states = {state: 0 for state in PILOT_CONTROL_STATES}
        for condition in self.ledger.get("conditions") or []:
            status = str(condition.get("status"))
            statuses.setdefault(status, 0)
            statuses[status] += 1
            state = condition.get("run_state") or control_state_from_status(status)
            states.setdefault(state, 0)
            states[state] += 1
        conditions = self.ledger.get("conditions") or []
        completed = sum(1 for item in conditions if item.get("status") == "observed")
        remaining = sum(1 for item in conditions if item.get("status") == "missing_not_run")
        failed = sum(1 for item in conditions if item.get("status") in {"failed", "stopped"})
        invalid = sum(1 for item in conditions if item.get("status") == "invalidated")
        rerunnable_units = {
            str(item.get("unit_id"))
            for item in (self.ledger.get("unit_attempts") or [])
            if item.get("rerunnable") is True
        }
        blocked_units = {
            str(item.get("unit_id"))
            for item in (self.ledger.get("unit_attempts") or [])
            if item.get("status") == "provider_incident"
        }
        return {
            "manifest_id": self.manifest.get("manifest_id"),
            "run_manifest_hash": self.manifest.get("run_manifest_hash"),
            "expected_strategy_runs": self.manifest.get("expected_strategy_runs"),
            "status_counts": statuses,
            "control_state_counts": states,
            "pending_count": states.get("PENDING", 0),
            "running_count": states.get("RUNNING", 0),
            "completed_count": states.get("COMPLETED", 0),
            "failed_count": states.get("FAILED", 0),
            "stopped_count": states.get("STOPPED", 0),
            "provider_error_count": states.get("PROVIDER_ERROR", 0),
            "completed": completed,
            "remaining": remaining,
            "failed": failed,
            "invalid": invalid,
            "rerunnable": len(rerunnable_units),
            "blocked": bool(self.ledger.get("integrity_block") or blocked_units),
            "blocked_units": len(blocked_units),
            "unit_attempts": len(self.ledger.get("unit_attempts") or []),
        }

    def assert_integrity(self) -> bool:
        validate_pilot_manifest(
            self.manifest,
            require_balanced=(self.manifest.get("order_policy", {}).get("balance_status") == "balanced"),
        )
        expected_conditions = {
            item["condition_key"]: item
            for item in _flatten_manifest_conditions(self.manifest)
        }
        actual_conditions = {
            str(item.get("condition_key")): item
            for item in self.ledger.get("conditions") or []
        }
        if set(actual_conditions) != set(expected_conditions):
            missing = sorted(set(expected_conditions) - set(actual_conditions))
            extra = sorted(set(actual_conditions) - set(expected_conditions))
            raise RuntimeError(
                "DATA_INTEGRITY_ERROR: condition set diverges from manifest "
                f"(missing={missing}, extra={extra})"
            )
        for key, expected in expected_conditions.items():
            actual = actual_conditions[key]
            expected_frozen = {
                name: value
                for name, value in expected.items()
                if name not in _MUTABLE_MANIFEST_FIELDS
            }
            actual_frozen = {
                name: value
                for name, value in actual.items()
                if name not in _MUTABLE_MANIFEST_FIELDS
            }
            if actual_frozen != expected_frozen:
                raise RuntimeError(f"DATA_INTEGRITY_ERROR: immutable condition drift: {key}")

        manifest_state_hash = self.manifest.get("ledger_state_hash")
        ledger_state_hash = self.ledger.get("state_hash")
        calculated_state_hash = _ledger_state_hash(self.ledger)
        if manifest_state_hash != ledger_state_hash or ledger_state_hash != calculated_state_hash:
            raise RuntimeError("DATA_INTEGRITY_ERROR: manifest and ledger state hash mismatch")

        attempt_owners: dict[str, str] = {}
        attempt_paths: dict[str, str] = {}
        for condition in self.ledger.get("conditions") or []:
            key = str(condition.get("condition_key"))
            for attempt in condition.get("attempts") or []:
                run_id = attempt.get("run_id")
                if not run_id:
                    continue
                if run_id in attempt_owners:
                    raise ValueError(f"Duplicate attempted run ID: {run_id}")
                attempt_owners[run_id] = key
                path = attempt.get("raw_evidence_path")
                if path:
                    attempt_paths[run_id] = str(path).replace("\\", "/")
        current_ids: set[str] = set()
        for condition in self.ledger.get("conditions") or []:
            current = condition.get("run_id")
            if current:
                if current in current_ids:
                    raise ValueError(f"Duplicate current run ID: {current}")
                owner = attempt_owners.get(current)
                if owner is not None and owner != condition.get("condition_key"):
                    raise ValueError(f"Current run ID belongs to another condition: {current}")
                current_ids.add(current)
            expected_state = control_state_from_status(condition.get("status"))
            if condition.get("run_state") not in {None, expected_state}:
                raise ValueError(f"Condition run_state is inconsistent: {key}")
            if condition.get("status") in _TERMINAL_STATUSES:
                path = condition.get("raw_evidence_path")
                if not path or not self._inside(path).exists():
                    raise ValueError(f"Terminal condition has no raw evidence: {condition.get('condition_key')}")
            for attempt in condition.get("attempts") or []:
                attempt_status = attempt.get("status")
                attempt_path = attempt.get("raw_evidence_path")
                if attempt_status in _TERMINAL_STATUSES and (
                    not attempt_path or not self._inside(attempt_path).exists()
                ):
                    # A recovered interrupted reservation is deliberately
                    # represented as missing_not_run and has no raw file.
                    raise RuntimeError(
                        f"DATA_INTEGRITY_ERROR: terminal attempt has no raw evidence: {key}"
                    )

        raw_run_ids: dict[str, str] = {}
        for path in sorted(self.raw_dir.glob("run_*.json")):
            try:
                raw = _read_json(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"DATA_INTEGRITY_ERROR: malformed raw evidence: {path.name}") from exc
            run_id = str(raw.get("run_id") or "")
            if not run_id:
                raise RuntimeError(f"DATA_INTEGRITY_ERROR: raw evidence has no run_id: {path.name}")
            if run_id in raw_run_ids:
                raise RuntimeError(f"DATA_INTEGRITY_ERROR: duplicate raw run ID: {run_id}")
            raw_run_ids[run_id] = str(path.relative_to(self.root)).replace("\\", "/")
            owner = attempt_owners.get(run_id)
            if owner is None:
                raise RuntimeError(f"DATA_INTEGRITY_ERROR: orphan raw evidence: {path.name}")
            expected_path = attempt_paths.get(run_id)
            if expected_path and expected_path != raw_run_ids[run_id]:
                raise RuntimeError(f"DATA_INTEGRITY_ERROR: raw path mismatch: {run_id}")

        for run_id, relative in attempt_paths.items():
            if not (self.root / relative).exists():
                # Missing raw for a non-terminal interruption is allowed; all
                # terminal attempt paths were checked above.
                owner = attempt_owners.get(run_id)
                owner_condition = actual_conditions.get(owner or "", {})
                attempt = next(
                    (item for item in owner_condition.get("attempts", []) if item.get("run_id") == run_id),
                    None,
                )
                if attempt and attempt.get("status") not in {"missing_not_run", None}:
                    raise RuntimeError(f"DATA_INTEGRITY_ERROR: recorded raw evidence is missing: {run_id}")
        units: dict[str, list[dict[str, Any]]] = {}
        for condition in self.ledger.get("conditions") or []:
            units.setdefault(str(condition.get("unit_id")), []).append(condition)
        for unit_id, conditions in units.items():
            for key in ("context_snapshot_id", "context_snapshot_hash"):
                values = {condition.get(key) for condition in conditions if condition.get(key) is not None}
                if len(values) > 1:
                    raise ValueError(f"Unit {unit_id} has inconsistent {key} values")
        if self.ledger.get("integrity_block"):
            raise RuntimeError(
                "DATA_INTEGRITY_ERROR: ledger is blocked: "
                f"{self.ledger['integrity_block'].get('reason', 'unknown')}"
            )
        return True


def _processed_row(
    condition: Mapping[str, Any],
    *,
    raw: Mapping[str, Any] | None,
    raw_path: str | None,
    pricing: Mapping[str, Any],
) -> dict[str, Any]:
    raw = raw or {}
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), Mapping) else {}
    usage_available = metrics.get("usage_metadata_available")
    if usage_available is not True:
        input_tokens = output_tokens = total_tokens = cost = None
        cost_reason = "usage_unavailable" if usage_available is not False else "usage_unavailable"
    else:
        input_tokens = metrics.get("input_tokens")
        output_tokens = metrics.get("output_tokens")
        total_tokens = metrics.get("total_tokens")
        cost = metrics.get("calculated_cost_usd")
        cost_reason = None
    if pricing.get("status") != "VERIFIED":
        cost = None
        cost_reason = "PRICE_UNVERIFIED"
    pilot = raw.get("pilot") if isinstance(raw.get("pilot"), Mapping) else {}
    phase = str(raw.get("phase") or pilot.get("phase") or condition.get("phase") or (
        "DRY_RUN" if raw.get("dry_run") or condition.get("dry_run") else "PILOT"
    )).upper()
    raw_status = raw.get("status")
    status = condition.get("status") or raw_status
    status_for_state = condition.get("status")
    if raw:
        if raw.get("provider_incident") or raw.get("provider_error_category"):
            status_for_state = "provider_incident"
        elif raw.get("status") == "completed":
            status_for_state = "observed"
        elif raw.get("status") == "degraded":
            status_for_state = "provider_incident"
        elif raw.get("status") in {"failed", "stopped"}:
            status_for_state = raw.get("status")
    run_state = raw.get("run_state") or pilot.get("run_state") or control_state_from_status(status_for_state)
    return {
        "unit_id": condition.get("unit_id"),
        "condition_id": pilot.get("condition_id") or condition.get("condition_key"),
        "task_id": condition.get("task_id"),
        "repeat_index": condition.get("repeat_index"),
        "repeat_id": condition.get("repeat_id"),
        "strategy": condition.get("strategy"),
        "strategy_config_id": condition.get("strategy_config_id"),
        "pilot_strategy_config_id": condition.get("pilot_strategy_config_id"),
        "strategy_config_version": condition.get("strategy_config_version"),
        "rag_config_id": condition.get("rag_config_id"),
        "rag_pilot_config_id": condition.get("rag_pilot_config_id"),
        "price_config_id": condition.get("price_config_id"),
        "provider": raw.get("provider", condition.get("provider")),
        "model": raw.get("model", condition.get("model")),
        "model_settings_identity": condition.get("model_settings_identity"),
        "context_snapshot_id": raw.get("snapshot_id") or condition.get("context_snapshot_id"),
        "context_snapshot_hash": raw.get("snapshot_hash") or condition.get("context_snapshot_hash"),
        "snapshot_metadata": deepcopy(
            raw.get("retrieval_meta") or condition.get("snapshot_metadata") or {}
        ),
        "source_document_ids": pilot.get("source_document_ids") or raw.get("source_document_ids") or condition.get("source_document_ids") or [],
        "source_document_hashes": pilot.get("source_document_hashes") or condition.get("source_document_hashes") or [],
        "reference_scope": pilot.get("reference_scope") or condition.get("reference_scope") or [],
        "reference_scope_hash": pilot.get("reference_scope_hash") or condition.get("reference_scope_hash"),
        "reference_section_ids": pilot.get("reference_section_ids") or condition.get("reference_section_ids") or [],
        "chunk_ids": raw.get("chunk_ids") or [],
        "benchmark_id": condition.get("benchmark_id"),
        "benchmark_version": condition.get("benchmark_version"),
        "benchmark_provenance_version": condition.get("benchmark_provenance_version"),
        "rubric_version_reference": condition.get("rubric_version_reference"),
        "pricing_version": condition.get("pricing_version"),
        "pilot_pricing_version": condition.get("pilot_pricing_version"),
        "execution_order": condition.get("execution_order"),
        "order_seed": condition.get("order_seed"),
        "run_id": raw.get("run_id") or condition.get("run_id"),
        "attempt_id": pilot.get("attempt_id") or raw.get("attempt_id") or raw.get("run_id") or condition.get("run_id"),
        "status": status,
        "raw_status": raw_status,
        "answer": raw.get("answer") or "",
        "run_state": run_state,
        "stop_reason": raw.get("stop_reason") or condition.get("stop_reason"),
        "agent_executions": metrics.get("agent_executions"),
        "logical_calls": metrics.get("logical_calls"),
        "physical_requests": metrics.get("physical_requests"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": metrics.get("cached_input_tokens") if usage_available is True else None,
        "reasoning_tokens": metrics.get("reasoning_tokens") if usage_available is True else None,
        "usage_metadata_available": usage_available,
        "e2e_ms": metrics.get("e2e_ms"),
        "e2e_boundary_version": metrics.get("e2e_boundary_version", "E2E-MEASURE-V2"),
        "context_prep_ms": metrics.get("context_prep_ms"),
        "retries": metrics.get("retries"),
        "escalations": metrics.get("escalations"),
        "calculated_cost_usd": cost,
        "cost_unavailable_reason": cost_reason,
        "dry_run": bool(raw.get("dry_run") or condition.get("dry_run", False)),
        "phase": phase,
        "research_evidence": bool(raw.get("research_evidence", pilot.get("research_evidence", phase == "PILOT" and not raw.get("dry_run")))),
        "evidence_class": raw.get("evidence_class") or pilot.get("evidence_class") or ("DRY_RUN" if raw.get("dry_run") else "PILOT"),
        "provider_incident": bool(raw.get("provider_incident")),
        "provider_error_category": raw.get("provider_error_category") or pilot.get("provider_error_category"),
        "provider_error_message": raw.get("provider_error_message") or pilot.get("provider_error_message"),
        "incident": deepcopy(raw.get("incident") or {}),
        "incident_category": raw.get("incident_category") or pilot.get("incident_category"),
        "incident_origin": raw.get("incident_origin") or pilot.get("incident_origin"),
        "outcome_category": raw.get("outcome_category") or pilot.get("outcome_category"),
        "unit_attempt_id": raw.get("unit_attempt_id") or pilot.get("unit_attempt_id") or condition.get("unit_attempt_id"),
        "freeze_identity": raw.get("freeze_identity") or pilot.get("freeze_identity"),
        "raw_evidence_path": raw_path,
    }


def export_processed_dataset(
    root: str | Path,
    output_path: str | Path | None = None,
    *,
    include_dry_run: bool = False,
    include_preflight: bool = False,
) -> dict[str, Any]:
    """Derive a tidy dataset without changing raw evidence.

    Only ``phase=PILOT`` records enter the default processed dataset.  Dry-run
    and preflight exports require an explicit opt-in so engineering checks
    cannot silently become research observations.
    """

    ledger = PilotLedger.open(root)
    ledger.assert_integrity()
    pricing = ((ledger.manifest.get("configuration") or {}).get("pricing") or {})
    # ``attempt_rows`` preserves every immutable raw observation.  ``rows`` is
    # the strategy-neutral canonical dataset: exactly one selected attempt per
    # condition, so an interruption/retry cannot double the quality
    # denominator.
    attempt_rows: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    excluded_counts = {"DRY_RUN": 0, "PREFLIGHT": 0, "FREEZE_MISMATCH": 0}

    def include_condition(condition: Mapping[str, Any], raw: Mapping[str, Any] | None) -> bool:
        pilot = raw.get("pilot") if isinstance(raw, Mapping) and isinstance(raw.get("pilot"), Mapping) else {}
        dry = bool((raw or {}).get("dry_run") or condition.get("dry_run", False))
        phase = str((raw or {}).get("phase") or pilot.get("phase") or condition.get("phase") or ("DRY_RUN" if dry else "PILOT")).upper()
        if phase == "DRY_RUN" and not include_dry_run:
            excluded_counts["DRY_RUN"] += 1
            return False
        if phase == "PREFLIGHT" and not include_preflight:
            excluded_counts["PREFLIGHT"] += 1
            return False
        expected_freeze = ledger.manifest.get("freeze_identity")
        observed_freeze = (raw or {}).get("freeze_identity") or pilot.get("freeze_identity") or condition.get("freeze_identity") or expected_freeze
        if phase == "PILOT" and expected_freeze and observed_freeze != expected_freeze:
            excluded_counts["FREEZE_MISMATCH"] += 1
            return False
        return True

    def derive_quality_case(row: Mapping[str, Any]) -> tuple[str, bool]:
        category = str(row.get("incident_category") or row.get("provider_error_category") or "")
        origin = str(row.get("incident_origin") or "")
        status = str(row.get("status") or "")
        answer = str(row.get("answer") or "").strip()
        if origin == "provider" or category in {
            "RATE_LIMITED", "TIMEOUT", "NETWORK_OR_DNS", "AUTHENTICATION_OR_PERMISSION",
            "QUOTA_OR_CREDIT", "MODEL_NOT_FOUND", "PROVIDER_ERROR",
        } or row.get("provider_incident"):
            return "B_PROVIDER_OR_INFRASTRUCTURE_INCIDENT", False
        if category == "EXPERIMENT_INFRASTRUCTURE_ERROR" or origin in {"verifier", "infrastructure"}:
            return "B_PROVIDER_OR_INFRASTRUCTURE_INCIDENT", False
        if status == "observed" and answer:
            return "A_VALID_EVALUABLE_ANSWER", True
        if status == "invalidated":
            return "D_CORRUPTED_EXPERIMENTAL_UNIT", False
        if status in {"missing_not_run", "failed", "stopped"} or not answer:
            return "C_STRATEGY_TERMINAL_NO_EVALUABLE_ANSWER", False
        return "E_PREDECLARED_MANUAL_EXCLUSION", False

    for condition in ledger.ledger.get("conditions") or []:
        attempts = condition.get("attempts") or []
        if not attempts:
            if include_condition(condition, None):
                row = _processed_row(condition, raw=None, raw_path=None, pricing=pricing)
                case, eligible = derive_quality_case(row)
                row.update({
                    "quality_case": case,
                    "quality_denominator_eligible": eligible,
                    "canonical_attempt": True,
                    "attempt_count": 0,
                })
                attempt_rows.append(deepcopy(row))
                rows.append(row)
            continue
        condition_attempt_rows: list[dict[str, Any]] = []
        for attempt in attempts:
            relative = attempt.get("raw_evidence_path")
            path = ledger.root / relative if relative else None
            raw = _read_json(path) if path and path.exists() else None
            attempt_condition = deepcopy(condition)
            # The current condition points at the latest attempt.  Keep the
            # attempt's own identity/status when an earlier interrupted raw
            # file is absent, so the derived table never aliases it to a later
            # run ID.
            if raw is None:
                attempt_condition["run_id"] = attempt.get("run_id")
                attempt_condition["status"] = attempt.get("status") or "missing_not_run"
                attempt_condition["stop_reason"] = attempt.get("stop_reason")
            else:
                if raw.get("provider_incident") or raw.get("provider_error_category") or raw.get("status") == "degraded":
                    attempt_condition["status"] = "provider_incident"
                elif raw.get("status") in {"completed", "failed", "stopped"}:
                    attempt_condition["status"] = "observed" if raw.get("status") == "completed" else raw.get("status")
            if include_condition(attempt_condition, raw):
                row = _processed_row(attempt_condition, raw=raw, raw_path=relative, pricing=pricing)
                case, eligible = derive_quality_case(row)
                row.update({
                    "quality_case": case,
                    "quality_denominator_eligible": eligible,
                    "canonical_attempt": False,
                    "attempt_count": len(attempts),
                })
                condition_attempt_rows.append(row)
                attempt_rows.append(deepcopy(row))
        if condition_attempt_rows:
            # Latest terminal attempt wins only within this condition.  This is
            # deterministic and preserves all earlier rows in attempt_rows.
            canonical = condition_attempt_rows[-1]
            canonical["canonical_attempt"] = True
            rows.append(canonical)
    for row in rows:
        row.setdefault("quality_case", "D_CORRUPTED_EXPERIMENTAL_UNIT")
        row.setdefault("quality_denominator_eligible", False)
    result = {
        "dataset_type": "pilot_processed_dataset",
        "dataset_version": PILOT_PROCESSED_DATASET_VERSION,
        "derived_at": utc_now(),
        "source_manifest_id": ledger.manifest.get("manifest_id"),
        "source_run_manifest_hash": ledger.manifest.get("run_manifest_hash"),
        "benchmark_id": ledger.manifest.get("benchmark_id"),
        "benchmark_version": ledger.manifest.get("benchmark_version"),
        "benchmark_provenance_version": ledger.manifest.get("benchmark_provenance_version"),
        "rubric_version_reference": ledger.manifest.get("rubric_version_reference"),
        "freeze_identity": ledger.manifest.get("freeze_identity"),
        "raw_source_of_truth": True,
        "rows": rows,
        "attempt_rows": attempt_rows,
        "row_count": len(rows),
        "attempt_row_count": len(attempt_rows),
        "excluded_non_pilot_counts": excluded_counts,
        "include_dry_run": bool(include_dry_run),
        "include_preflight": bool(include_preflight),
        "notes": [
            "Rows are derived from immutable raw evidence and ledger assignments.",
            "Quality evaluation is not included; runtime quality remains Not evaluated.",
            "Unavailable usage and unverified pricing remain null rather than zero.",
            "rows contains one canonical attempt per condition; attempt_rows preserves every attempt.",
            "Quality denominator includes only Case A canonical rows; Case B is reliability-only, Case C is strategy failure, and D/E are excluded.",
        ],
    }
    target = Path(output_path) if output_path is not None else ledger.root / "processed" / "dataset.json"
    _atomic_write_json(target, result)
    return result


__all__ = [
    "DEFAULT_PILOT_MODEL",
    "DEFAULT_PILOT_PROVIDER",
    "FIXED_PILOT_CONFIG_ID",
    "LATIN_SQUARE_ROWS",
    "MODEL_PILOT_CONFIG_ID",
    "MODEL_PILOT_CONFIG_VERSION",
    "MODEL_PILOT_VERIFIED_AT",
    "ORCH_PILOT_CONFIG_ID",
    "PILOT_BENCHMARK_ID",
    "PILOT_BENCHMARK_VERSION",
    "PILOT_BENCHMARK_PROVENANCE",
    "PILOT_EXECUTION_CONFIG_ID",
    "PILOT_CONFIG_IDENTITIES",
    "PILOT_EXECUTION_CONFIG_VERSION",
    "PILOT_EXECUTOR_VERSION",
    "PILOT_FREEZE_IDENTITY",
    "PILOT_PACING_POLICY",
    "PILOT_PACING_POLICY_ID",
    "PILOT_PACING_POLICY_VERSION",
    "PILOT_AUTHORIZATION_SCHEMA_ID",
    "PILOT_AUTHORIZATION_SCHEMA_VERSION",
    "PILOT_LIVE_WINDOW_SCHEMA_ID",
    "PILOT_LIVE_WINDOW_SCHEMA_VERSION",
    "PILOT_PREFLIGHT_BINDING_SCHEMA_ID",
    "PILOT_PREFLIGHT_BINDING_SCHEMA_VERSION",
    "PILOT_INCIDENT_TAXONOMY_VERSION",
    "PILOT_DENOMINATOR_POLICY_VERSION",
    "PILOT_CONTROL_STATES",
    "PILOT_LEDGER_VERSION",
    "PILOT_PREREGISTRATION_VERSION",
    "PILOT_PROCESSED_DATASET_VERSION",
    "PILOT_RUN_MANIFEST_VERSION",
    "PILOT_STATUSES",
    "PILOT_STRATEGIES",
    "PILOT_STRATEGY_CONFIG_IDS",
    "_reference_scope_summary",
    "PRICE_PILOT_CONFIG_ID",
    "PRICE_PILOT_CONFIG_VERSION",
    "PRICE_PILOT_VERIFIED_AT",
    "PILOT_GROQ_PARAMETER_STATUS",
    "PILOT_GROQ_REQUEST_PARAMETERS",
    "RAG_PILOT_CONFIG_ID",
    "STATIC_PILOT_CONFIG_ID",
    "PilotLedger",
    "build_balanced_order_schedule",
    "build_pilot_manifest",
    "canonical_json",
    "control_state_from_status",
    "derive_order_seed",
    "export_processed_dataset",
    "fisher_yates",
    "new_run_id",
    "pilot_config_snapshot",
    "sha256_json",
    "validate_order_schedule",
    "validate_pilot_manifest",
]

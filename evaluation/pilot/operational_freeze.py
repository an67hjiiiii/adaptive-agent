"""Research-side operational freeze for Pilot missingness and evaluation.

This module is intentionally outside the runtime package.  It validates the
coordinator's denominator and evaluator records without importing the hidden
rubric or changing Pilot execution, pacing, or orchestration behavior.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Mapping, Sequence


PILOT_STRATEGIES = ("single", "fixed", "static", "adaptive")

DIFFERENTIAL_MISSINGNESS_POLICY_ID = "PILOT-DIFFERENTIAL-MISSINGNESS-V1"
DIFFERENTIAL_MISSINGNESS_POLICY_VERSION = "1.0"
MAX_DIFFERENTIAL_MISSINGNESS_PER_ACCEPTED_UNIT = 0

CASE_E_POLICY_ID = "PILOT-CASE-E-ADMIN-V1"
CASE_E_POLICY_VERSION = "1.0"
CASE_E_ALLOWED_REASON_CODES = (
    "ADMIN_DUPLICATE_ASSIGNMENT",
    "ADMIN_CONSENT_OR_PRIVACY_EVENT",
    "ADMIN_EXTERNAL_INTERRUPTION",
)
CASE_E_FORBIDDEN_REASON_CODES = (
    "LOW_QUALITY",
    "ADAPTIVE_LOST",
    "FIXED_FAILED",
    "OUTLIER_RESULT",
    "UNEXPECTED_RESULT",
)
CASE_E_APPROVAL_FIELDS = (
    "requester_role",
    "approver_role",
    "reason_code",
    "requested_at",
    "approved_at",
    "approval_status",
    "evidence_reference",
    "approved_before_unblinding",
)

EVALUATION_PLAN_ID = "PILOT-EVALUATION-OPS-V1"
EVALUATION_PLAN_VERSION = "1.0"
EVALUATION_PROTOCOL_ID = "QEP-1.1"
PACKET_SET_ID = "PILOT-EVALUATOR-PACKETS-V1"
PACKET_SET_VERSION = "1.0"
SUCCESSOR_PACKET_SET_ID = "PILOT-EVALUATOR-PACKETS-V2"
SUCCESSOR_PACKET_SET_VERSION = "2.0"
RUBRIC_VERSION = "PILOT-RUBRIC-V1.0"
PLANNED_PACKET_STATUS = "PLANNED"
EVALUABLE_PACKET_STATUS = "EVALUABLE"
NOT_EVALUABLE_PACKET_STATUS = "NOT_EVALUABLE"
PACKET_STATUSES = (
    PLANNED_PACKET_STATUS,
    EVALUABLE_PACKET_STATUS,
    NOT_EVALUABLE_PACKET_STATUS,
)
EVALUATOR_SLOT_STATUSES = ("ASSIGNED", "UNASSIGNED")

_PROVIDER_OR_INFRASTRUCTURE_CATEGORIES = frozenset(
    {
        "RATE_LIMITED",
        "TIMEOUT",
        "NETWORK_OR_DNS",
        "AUTHENTICATION_OR_PERMISSION",
        "QUOTA_OR_CREDIT",
        "MODEL_NOT_FOUND",
        "PROVIDER_ERROR",
        "EXPERIMENT_INFRASTRUCTURE_ERROR",
        "PROVIDER_OR_INFRASTRUCTURE_INVALIDATION",
    }
)
_STRATEGY_TERMINAL_CATEGORY = "STRATEGY_TERMINAL_FAILURE"
_ROLE_ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]*$")
_FORBIDDEN_CASE_E_FIELDS = {
    "reason",
    "reason_text",
    "free_text_reason",
    "outcome_reason",
    "requester_name",
    "approver_name",
    "reviewer_name",
    "human_name",
    "assignee_name",
    "email",
}
_PACKET_FORBIDDEN_KEYS = {
    "mandatory_criteria",
    "critical_errors",
    "hidden_task_rubric",
    "expected_source_facts",
    "research_annotations",
}


DIFFERENTIAL_MISSINGNESS_POLICY: dict[str, Any] = {
    "policy_id": DIFFERENTIAL_MISSINGNESS_POLICY_ID,
    "version": DIFFERENTIAL_MISSINGNESS_POLICY_VERSION,
    "numeric_threshold": MAX_DIFFERENTIAL_MISSINGNESS_PER_ACCEPTED_UNIT,
    "classification": "MAX_DIFFERENTIAL_MISSINGNESS_PER_ACCEPTED_UNIT",
    "comparable_unit": "task_id × repeat_index × four registered strategies × same freeze_identity",
    "reason_code": "DIFFERENTIAL_INFRASTRUCTURE_MISSINGNESS",
    "accepted_unit_rule": "infrastructure_missing_count <= numeric_threshold",
    "strategy_terminal_failure": "STRATEGY_TERMINAL_FAILURE_REMAINS_RESEARCH_EVIDENCE",
    "provider_or_infrastructure_invalidation": "WHOLE_UNIT_RERUN_REQUIRED",
}

CASE_E_POLICY: dict[str, Any] = {
    "policy_id": CASE_E_POLICY_ID,
    "version": CASE_E_POLICY_VERSION,
    "classification": "PREDECLARED_ADMINISTRATIVE_NON_PERFORMANCE_ONLY",
    "reason_code": "CASE_E_PREDECLARED_ADMINISTRATIVE_EXCLUSION",
    "allowed_reason_codes": list(CASE_E_ALLOWED_REASON_CODES),
    "forbidden_reason_codes": list(CASE_E_FORBIDDEN_REASON_CODES),
    "approval_record_fields": list(CASE_E_APPROVAL_FIELDS),
    "approval_rule": "INDEPENDENT_APPROVAL_REQUIRED",
    "timing_rule": "APPROVED_BEFORE_UNBLINDING",
    "whole_unit_only": True,
    "preserve_original_raw_evidence": True,
    "exclusion_report_required": True,
    "free_text_reason": False,
    "outcome_based_exclusion": False,
}

EVALUATOR_PLAN: dict[str, Any] = {
    "plan_id": EVALUATION_PLAN_ID,
    "version": EVALUATION_PLAN_VERSION,
    "evaluation_protocol_id": EVALUATION_PROTOCOL_ID,
    "packet_set_id": PACKET_SET_ID,
    "planned_packet_count": 96,
    "planned_e1_count": 96,
    "planned_e2_overlap_count": 24,
    "slots": {
        "E1": {
            "role_id": "E1",
            "status": "UNASSIGNED",
            "planned_count": 96,
        },
        "E2": {
            "role_id": "E2",
            "status": "UNASSIGNED",
            "planned_count": 24,
            "exception_policy": "all UNCLEAR, borderline, invalid, and disputed cases",
        },
        "ADJ-1": {
            "role_id": "ADJ-1",
            "status": "UNASSIGNED",
            "planned_count": 0,
            "on_demand": True,
        },
    },
    "capacity_status": "UNCONFIRMED",
    "identity_recording": "Record role IDs, assignments, timestamps, locked labels, changes, and adjudication rationale in the research ledger.",
}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _incident_mapping(condition: Mapping[str, Any]) -> Mapping[str, Any]:
    incident = condition.get("incident")
    return incident if isinstance(incident, Mapping) else {}


def _condition_category_and_origin(condition: Mapping[str, Any]) -> tuple[str, str]:
    incident = _incident_mapping(condition)
    category = _upper(
        incident.get("category")
        or condition.get("incident_category")
        or condition.get("provider_error_category")
        or condition.get("outcome_category")
    )
    origin = _upper(incident.get("origin") or condition.get("incident_origin"))
    return category, origin


def classify_condition_missingness(condition: Mapping[str, Any] | None) -> dict[str, Any]:
    """Classify one condition without turning strategy failure into infra loss.

    Unknown/missing operational evidence is fail-closed as infrastructure
    missingness.  A condition explicitly marked ``STRATEGY_TERMINAL_FAILURE``
    is the exception: it remains research evidence and does not increment the
    differential infrastructure-missing count.
    """

    if not isinstance(condition, Mapping):
        return {
            "classification": "INFRASTRUCTURE_MISSING",
            "infra_missing": True,
            "reason_code": "DIFFERENTIAL_INFRASTRUCTURE_MISSINGNESS",
        }

    category, origin = _condition_category_and_origin(condition)
    status = _upper(condition.get("status"))
    provider_incident = bool(condition.get("provider_incident"))
    if (
        provider_incident
        or origin in {"PROVIDER", "INFRASTRUCTURE"}
        or category in _PROVIDER_OR_INFRASTRUCTURE_CATEGORIES
        or status == "PROVIDER_INCIDENT"
    ):
        return {
            "classification": "INFRASTRUCTURE_MISSING",
            "infra_missing": True,
            "reason_code": "DIFFERENTIAL_INFRASTRUCTURE_MISSINGNESS",
            "category": category or None,
            "origin": origin.lower() or None,
            "status": status.lower() or None,
        }

    if category == _STRATEGY_TERMINAL_CATEGORY:
        return {
            "classification": "STRATEGY_TERMINAL_FAILURE",
            "infra_missing": False,
            "reason_code": _STRATEGY_TERMINAL_CATEGORY,
            "category": category,
            "status": status.lower() or None,
        }

    answer = _text(condition.get("answer"))
    if status in {"OBSERVED", "COMPLETED"} and answer:
        return {
            "classification": "VALID_COMPARABLE_CONDITION",
            "infra_missing": False,
            "reason_code": "VALID_COMPARABLE_CONDITION",
            "category": category or None,
            "status": status.lower(),
        }

    if status == "MISSING_NOT_RUN" or not status:
        return {
            "classification": "INFRASTRUCTURE_MISSING",
            "infra_missing": True,
            "reason_code": "DIFFERENTIAL_INFRASTRUCTURE_MISSINGNESS",
            "category": category or None,
            "status": status.lower() or None,
        }

    # A failed/stopped record without an explicit terminal category is not
    # safely attributable to a strategy.  Treat it as missing infrastructure
    # until the coordinator supplies a source-backed classification.
    return {
        "classification": "UNCLASSIFIED_MISSINGNESS",
        "infra_missing": True,
        "reason_code": "UNCLASSIFIED_MISSINGNESS",
        "category": category or None,
        "status": status.lower(),
    }


def classify_comparison_unit(
    conditions: Sequence[Mapping[str, Any]],
    *,
    expected_strategies: Sequence[str] = PILOT_STRATEGIES,
    freeze_identity: str | None = None,
) -> dict[str, Any]:
    """Apply the frozen zero-tolerance differential-missingness rule."""

    expected = tuple(str(item) for item in expected_strategies)
    by_strategy: dict[str, Mapping[str, Any]] = {}
    duplicate_strategies: list[str] = []
    for condition in conditions:
        strategy = _text(condition.get("strategy")) if isinstance(condition, Mapping) else None
        if not strategy:
            continue
        if strategy in by_strategy:
            duplicate_strategies.append(strategy)
        else:
            by_strategy[strategy] = condition

    missing_strategies = [strategy for strategy in expected if strategy not in by_strategy]
    unknown_strategies = sorted(set(by_strategy) - set(expected))
    binding_invalid = bool(
        duplicate_strategies
        or missing_strategies
        or unknown_strategies
        or len(conditions) != len(expected)
    )
    freeze_values = {
        _text(condition.get("freeze_identity"))
        for condition in conditions
        if isinstance(condition, Mapping) and _text(condition.get("freeze_identity"))
    }
    if freeze_identity:
        freeze_values.add(str(freeze_identity))
    freeze_mismatch = len(freeze_values) > 1 or (
        freeze_identity is not None
        and any(
            not isinstance(condition, Mapping)
            or _text(condition.get("freeze_identity")) != str(freeze_identity)
            for condition in conditions
        )
    )

    classifications: dict[str, dict[str, Any]] = {}
    for strategy in expected:
        classifications[strategy] = classify_condition_missingness(by_strategy.get(strategy))
    infrastructure_missing = [
        strategy
        for strategy, result in classifications.items()
        if result["infra_missing"]
    ]
    strategy_terminal_failures = [
        strategy
        for strategy, result in classifications.items()
        if result["classification"] == "STRATEGY_TERMINAL_FAILURE"
    ]
    infrastructure_missing_count = len(infrastructure_missing)
    if binding_invalid or freeze_mismatch:
        classification = "INCOMPARABLE_UNIT"
        reason_code = "UNIT_BINDING_MISMATCH"
        comparable = False
    elif infrastructure_missing_count > MAX_DIFFERENTIAL_MISSINGNESS_PER_ACCEPTED_UNIT:
        classification = "INCOMPARABLE_UNIT"
        reason_code = "DIFFERENTIAL_INFRASTRUCTURE_MISSINGNESS"
        comparable = False
    else:
        classification = "ACCEPTED_COMPARABLE_UNIT"
        reason_code = "NO_DIFFERENTIAL_INFRASTRUCTURE_MISSINGNESS"
        comparable = True

    return {
        "classification": classification,
        "comparable": comparable,
        "policy_id": DIFFERENTIAL_MISSINGNESS_POLICY_ID,
        "version": DIFFERENTIAL_MISSINGNESS_POLICY_VERSION,
        "numeric_threshold": MAX_DIFFERENTIAL_MISSINGNESS_PER_ACCEPTED_UNIT,
        "comparable_unit": DIFFERENTIAL_MISSINGNESS_POLICY["comparable_unit"],
        "reason_code": reason_code,
        "infrastructure_missing_count": infrastructure_missing_count,
        "infrastructure_missing_strategies": infrastructure_missing,
        "strategy_terminal_failures": strategy_terminal_failures,
        "duplicate_strategies": duplicate_strategies,
        "missing_strategies": missing_strategies,
        "unknown_strategies": unknown_strategies,
        "freeze_identities": sorted(freeze_values),
        "condition_classifications": classifications,
    }


def case_e_policy() -> dict[str, Any]:
    return deepcopy(CASE_E_POLICY)


def _parse_timestamp(value: Any, field: str) -> datetime:
    text = _text(value)
    if not text:
        raise ValueError(f"CASE_E_{field.upper()}_REQUIRED")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"CASE_E_{field.upper()}_INVALID") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"CASE_E_{field.upper()}_MUST_BE_TIMEZONED")
    return parsed.astimezone(timezone.utc)


def validate_case_e_approval(
    record: Mapping[str, Any],
    *,
    unblinding_at: str | None = None,
) -> dict[str, Any]:
    """Validate a closed-list Case E approval record.

    ``APPROVED`` is the only state that may exclude a unit.  The requester and
    approver must be distinct role IDs, and approval must precede unblinding.
    """

    if not isinstance(record, Mapping):
        raise ValueError("CASE_E_RECORD_MUST_BE_OBJECT")
    missing = [field for field in CASE_E_APPROVAL_FIELDS if field not in record]
    if missing:
        raise ValueError(f"CASE_E_MISSING_FIELDS:{','.join(missing)}")
    if any(field in record for field in _FORBIDDEN_CASE_E_FIELDS):
        raise ValueError("CASE_E_FREE_TEXT_REASON_FORBIDDEN")

    requester = _text(record.get("requester_role"))
    approver = _text(record.get("approver_role"))
    if not requester or not _ROLE_ID_RE.fullmatch(requester):
        raise ValueError("CASE_E_REQUESTER_ROLE_ID_REQUIRED")
    if not approver or not _ROLE_ID_RE.fullmatch(approver):
        raise ValueError("CASE_E_APPROVER_ROLE_ID_REQUIRED")
    if requester == approver:
        raise ValueError("CASE_E_APPROVER_MUST_BE_INDEPENDENT")

    reason_code = _upper(record.get("reason_code"))
    if reason_code in CASE_E_FORBIDDEN_REASON_CODES:
        raise ValueError("CASE_E_OUTCOME_REASON_FORBIDDEN")
    if reason_code not in CASE_E_ALLOWED_REASON_CODES:
        raise ValueError("CASE_E_REASON_CODE_NOT_ALLOWED")

    requested_at = _parse_timestamp(record.get("requested_at"), "requested_at")
    approval_status = _upper(record.get("approval_status"))
    if approval_status not in {"PENDING", "APPROVED", "REJECTED"}:
        raise ValueError("CASE_E_APPROVAL_STATUS_INVALID")
    evidence_reference = _text(record.get("evidence_reference"))
    if not evidence_reference:
        raise ValueError("CASE_E_EVIDENCE_REFERENCE_REQUIRED")
    approved_before_unblinding = record.get("approved_before_unblinding")
    if not isinstance(approved_before_unblinding, bool):
        raise ValueError("CASE_E_APPROVED_BEFORE_UNBLINDING_BOOLEAN_REQUIRED")

    approved_at = record.get("approved_at")
    if approval_status == "APPROVED":
        approved_time = _parse_timestamp(approved_at, "approved_at")
        if approved_time < requested_at:
            raise ValueError("CASE_E_APPROVAL_PRECEDES_REQUEST")
        if not approved_before_unblinding:
            raise ValueError("CASE_E_APPROVAL_BEFORE_UNBLINDING_REQUIRED")
        if unblinding_at is not None:
            if approved_time >= _parse_timestamp(unblinding_at, "unblinding_at"):
                raise ValueError("CASE_E_APPROVAL_AFTER_UNBLINDING")
    elif approved_at not in (None, ""):
        raise ValueError("CASE_E_UNAPPROVED_RECORD_CANNOT_HAVE_APPROVED_AT")
    elif approved_before_unblinding:
        raise ValueError("CASE_E_UNAPPROVED_RECORD_CANNOT_CLAIM_APPROVAL_TIMING")

    return deepcopy(dict(record))


def evaluator_plan(*, packet_set_id: str = PACKET_SET_ID) -> dict[str, Any]:
    if packet_set_id not in {PACKET_SET_ID, SUCCESSOR_PACKET_SET_ID}:
        raise ValueError("EVALUATOR_PACKET_SET_ID_INVALID")
    plan = deepcopy(EVALUATOR_PLAN)
    plan["packet_set_id"] = packet_set_id
    return plan


def validate_evaluator_plan(
    plan: Mapping[str, Any],
    *,
    expected_packet_set_id: str | None = None,
) -> bool:
    if not isinstance(plan, Mapping):
        raise ValueError("EVALUATOR_PLAN_MUST_BE_OBJECT")
    if plan.get("plan_id") != EVALUATION_PLAN_ID or plan.get("version") != EVALUATION_PLAN_VERSION:
        raise ValueError("EVALUATOR_PLAN_ID_OR_VERSION_MISMATCH")
    if plan.get("evaluation_protocol_id") != EVALUATION_PROTOCOL_ID:
        raise ValueError("EVALUATOR_PROTOCOL_ID_MISMATCH")
    expected = expected_packet_set_id or plan.get("packet_set_id")
    if expected not in {PACKET_SET_ID, SUCCESSOR_PACKET_SET_ID} or plan.get("packet_set_id") != expected:
        raise ValueError("EVALUATOR_PACKET_SET_ID_MISMATCH")
    if plan.get("planned_packet_count") != 96 or plan.get("planned_e1_count") != 96 or plan.get("planned_e2_overlap_count") != 24:
        raise ValueError("EVALUATOR_PLANNED_COUNTS_INVALID")
    if plan.get("capacity_status") != "UNCONFIRMED":
        raise ValueError("EVALUATOR_CAPACITY_STATUS_MUST_BE_UNCONFIRMED")
    slots = plan.get("slots")
    if not isinstance(slots, Mapping):
        raise ValueError("EVALUATOR_SLOTS_REQUIRED")
    expected = {"E1": 96, "E2": 24, "ADJ-1": 0}
    for role_id, planned_count in expected.items():
        slot = slots.get(role_id)
        if not isinstance(slot, Mapping) or slot.get("role_id") != role_id:
            raise ValueError(f"EVALUATOR_SLOT_MISSING:{role_id}")
        if any(
            key in slot
            for key in ("name", "human_name", "assignee_name", "email")
        ):
            raise ValueError(f"EVALUATOR_HUMAN_IDENTITY_FORBIDDEN:{role_id}")
        if slot.get("status") not in EVALUATOR_SLOT_STATUSES:
            raise ValueError(f"EVALUATOR_SLOT_STATUS_INVALID:{role_id}")
        if slot.get("planned_count") != planned_count:
            raise ValueError(f"EVALUATOR_SLOT_COUNT_INVALID:{role_id}")
    return True


_PACKET_SET_ARTIFACT_IDS = {
    (PACKET_SET_ID, PACKET_SET_VERSION): "pilot_evaluator_packets_v1",
    (SUCCESSOR_PACKET_SET_ID, SUCCESSOR_PACKET_SET_VERSION): "pilot_evaluator_packets_v2",
}


def _packet_digest(
    packet_set_id: str,
    packet_set_version: str,
    manifest_hash: str,
    unit_id: str,
    strategy: str,
) -> str:
    material = f"{packet_set_id}|{packet_set_version}|{manifest_hash}|{unit_id}|{strategy}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _packet_has_forbidden_content(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(key in _PACKET_FORBIDDEN_KEYS for key in value):
            return True
        return any(_packet_has_forbidden_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_packet_has_forbidden_content(item) for item in value)
    return False


def generate_planned_packet_set(
    manifest: Mapping[str, Any],
    *,
    manifest_path: str = "runs/pilot/taskh-final-manifest-v5.json",
) -> dict[str, Any]:
    return _generate_planned_packet_set(
        manifest,
        manifest_path=manifest_path,
        packet_set_id=PACKET_SET_ID,
        packet_set_version=PACKET_SET_VERSION,
    )


def generate_successor_packet_set(
    manifest: Mapping[str, Any],
    *,
    manifest_path: str,
) -> dict[str, Any]:
    """Generate the immutable V2 packet-set binding for a successor manifest."""

    return _generate_planned_packet_set(
        manifest,
        manifest_path=manifest_path,
        packet_set_id=SUCCESSOR_PACKET_SET_ID,
        packet_set_version=SUCCESSOR_PACKET_SET_VERSION,
    )


def _generate_planned_packet_set(
    manifest: Mapping[str, Any],
    *,
    manifest_path: str,
    packet_set_id: str,
    packet_set_version: str,
) -> dict[str, Any]:
    """Generate deterministic coordinator-side packet identities.

    Packet records contain no task text, answer, expected facts, or hidden
    rubric fields.  They are planned records until raw evidence is bound.
    """

    if not isinstance(manifest, Mapping):
        raise ValueError("PACKET_MANIFEST_MUST_BE_OBJECT")
    units = manifest.get("units")
    if not isinstance(units, list) or len(units) != 24:
        raise ValueError("PACKET_SET_REQUIRES_24_COMPARISON_UNITS")
    required = ("manifest_id", "run_manifest_hash", "benchmark_id", "benchmark_version", "freeze_identity")
    if any(not _text(manifest.get(field)) for field in required):
        raise ValueError("PACKET_MANIFEST_IDENTITY_INCOMPLETE")

    packets: list[dict[str, Any]] = []
    seen_units: set[str] = set()
    for unit in sorted(units, key=lambda item: str(item.get("unit_id"))):
        if not isinstance(unit, Mapping):
            raise ValueError("PACKET_UNIT_MUST_BE_OBJECT")
        unit_id = _text(unit.get("unit_id"))
        task_id = _text(unit.get("task_id"))
        if not unit_id or not task_id or unit_id in seen_units:
            raise ValueError("PACKET_UNIT_ID_INVALID_OR_DUPLICATED")
        seen_units.add(unit_id)
        conditions = unit.get("conditions")
        if not isinstance(conditions, list):
            raise ValueError(f"PACKET_CONDITIONS_REQUIRED:{unit_id}")
        by_strategy = {str(item.get("strategy")): item for item in conditions if isinstance(item, Mapping)}
        if (
            len(conditions) != len(PILOT_STRATEGIES)
            or len(by_strategy) != len(PILOT_STRATEGIES)
            or set(by_strategy) != set(PILOT_STRATEGIES)
        ):
            raise ValueError(f"PACKET_STRATEGY_SET_INVALID:{unit_id}")
        for strategy in PILOT_STRATEGIES:
            condition = by_strategy[strategy]
            digest = _packet_digest(
                packet_set_id,
                packet_set_version,
                str(manifest["run_manifest_hash"]),
                unit_id,
                strategy,
            )
            packet = {
                "packet_id": f"PILOT-PACKET-{digest[:20].upper()}",
                "anonymized_candidate_id": f"CANDIDATE-{digest[:20].upper()}",
                "task_id": task_id,
                "repeat_index": unit.get("repeat_index"),
                "strategy": strategy,
                "unit_id": unit_id,
                "candidate_identity": {
                    "freeze_identity": manifest["freeze_identity"],
                    "candidate_manifest_id": manifest["manifest_id"],
                    "candidate_manifest_hash": manifest["run_manifest_hash"],
                },
                "rubric_binding": {
                    "evaluation_protocol_id": EVALUATION_PROTOCOL_ID,
                    "rubric_version": _text(unit.get("rubric_version_reference")) or RUBRIC_VERSION,
                    "rubric_manifest": "evaluation/pilot/pilot_rubrics_v1.json",
                },
                "evaluation_protocol_id": EVALUATION_PROTOCOL_ID,
                "status": PLANNED_PACKET_STATUS,
                "raw_evidence_binding": {
                    "required_for_evaluable": True,
                    "run_id": None,
                    "raw_evidence_path": None,
                },
                "coordinator_only": {
                    "strategy": strategy,
                    "unit_id": unit_id,
                    "repeat_index": unit.get("repeat_index"),
                    "freeze_identity": manifest["freeze_identity"],
                },
            }
            if condition.get("strategy") != strategy:
                raise ValueError(f"PACKET_CONDITION_BINDING_INVALID:{unit_id}:{strategy}")
            packets.append(packet)

    packet_set = {
        "artifact_id": _PACKET_SET_ARTIFACT_IDS[(packet_set_id, packet_set_version)],
        "packet_set_id": packet_set_id,
        "version": packet_set_version,
        "status": PLANNED_PACKET_STATUS,
        "evaluation_protocol_id": EVALUATION_PROTOCOL_ID,
        "benchmark_id": manifest["benchmark_id"],
        "benchmark_version": manifest["benchmark_version"],
        "corpus_version": "PILOT-CORPUS-V1",
        "rubric_version": RUBRIC_VERSION,
        "source_manifest_path": manifest_path,
        "candidate_identity": {
            "freeze_identity": manifest["freeze_identity"],
            "candidate_manifest_id": manifest["manifest_id"],
            "candidate_manifest_hash": manifest["run_manifest_hash"],
        },
        "planned_packet_count": len(packets),
        "planned_evaluable_count": 0,
        "evaluable_rule": "EVALUABLE requires a valid bound raw run evidence record for the same packet task/unit/repeat/strategy/freeze identity; PLANNED is never EVALUABLE.",
        "blind_packet_fields": [
            "anonymized_candidate_id",
            "task_id",
            "repeat_index",
            "candidate_answer",
            "permitted_reference_scope",
            "hidden_task_rubric",
        ],
        "hidden_from_evaluator": [
            "strategy",
            "unit_id",
            "candidate_manifest_id",
            "candidate_manifest_hash",
            "provider",
            "model",
            "latency",
            "tokens",
            "cost",
            "trace",
        ],
        "evaluator_plan": evaluator_plan(packet_set_id=packet_set_id),
        "packets": packets,
    }
    validate_packet_set(packet_set)
    return packet_set


def validate_packet_set(packet_set: Mapping[str, Any]) -> bool:
    if not isinstance(packet_set, Mapping):
        raise ValueError("PACKET_SET_MUST_BE_OBJECT")
    identity = (packet_set.get("packet_set_id"), packet_set.get("version"))
    if identity not in _PACKET_SET_ARTIFACT_IDS:
        raise ValueError("PACKET_SET_ID_OR_VERSION_MISMATCH")
    if packet_set.get("artifact_id") != _PACKET_SET_ARTIFACT_IDS[identity]:
        raise ValueError("PACKET_SET_ARTIFACT_ID_MISMATCH")
    if packet_set.get("evaluation_protocol_id") != EVALUATION_PROTOCOL_ID:
        raise ValueError("PACKET_PROTOCOL_ID_MISMATCH")
    packets = packet_set.get("packets")
    if not isinstance(packets, list) or len(packets) != 96:
        raise ValueError("PACKET_SET_COUNT_MUST_BE_96")
    if packet_set.get("planned_packet_count") != 96 or packet_set.get("planned_evaluable_count") != 0:
        raise ValueError("PACKET_SET_PLANNED_COUNTS_INVALID")
    validate_evaluator_plan(
        packet_set.get("evaluator_plan") or {},
        expected_packet_set_id=str(packet_set.get("packet_set_id") or ""),
    )
    packet_ids: set[str] = set()
    candidate_ids: set[str] = set()
    for packet in packets:
        if not isinstance(packet, Mapping):
            raise ValueError("PACKET_RECORD_MUST_BE_OBJECT")
        if packet.get("status") != PLANNED_PACKET_STATUS:
            raise ValueError("PACKET_SET_MUST_START_PLANNED")
        packet_id = _text(packet.get("packet_id"))
        candidate_id = _text(packet.get("anonymized_candidate_id"))
        if not packet_id or packet_id in packet_ids or not candidate_id or candidate_id in candidate_ids:
            raise ValueError("PACKET_ID_NOT_UNIQUE")
        packet_ids.add(packet_id)
        candidate_ids.add(candidate_id)
        if _packet_has_forbidden_content(packet):
            raise ValueError("PACKET_HIDDEN_RUBRIC_CONTENT_FORBIDDEN")
        if packet.get("evaluation_protocol_id") != EVALUATION_PROTOCOL_ID:
            raise ValueError("PACKET_PROTOCOL_ID_MISMATCH")
        binding = packet.get("rubric_binding")
        if not isinstance(binding, Mapping) or not binding.get("rubric_manifest") or not binding.get("rubric_version"):
            raise ValueError("PACKET_RUBRIC_BINDING_INCOMPLETE")
    return True


def _raw_evidence_is_valid(packet: Mapping[str, Any], raw_evidence: Mapping[str, Any]) -> bool:
    if not isinstance(raw_evidence, Mapping):
        return False
    run_id = _text(raw_evidence.get("run_id"))
    status = _upper(raw_evidence.get("status"))
    answer = _text(raw_evidence.get("answer"))
    if not run_id or status not in {"COMPLETED", "OBSERVED"} or not answer:
        return False
    if raw_evidence.get("provider_incident") is True:
        return False
    for key in ("task_id", "unit_id", "strategy", "freeze_identity"):
        expected = packet.get(key)
        if key == "freeze_identity":
            expected = (packet.get("candidate_identity") or {}).get("freeze_identity")
        if expected is not None and raw_evidence.get(key) is not None and raw_evidence.get(key) != expected:
            return False
    packet_repeat = packet.get("repeat_index")
    if packet_repeat is not None and raw_evidence.get("repeat_index") is not None and raw_evidence.get("repeat_index") != packet_repeat:
        return False
    return True


def validate_packet_status(
    packet: Mapping[str, Any],
    *,
    raw_evidence: Mapping[str, Any] | None = None,
    raw_evidence_path: str | None = None,
) -> bool:
    """Enforce PLANNED/EVALUABLE transitions at the evaluation boundary."""

    if not isinstance(packet, Mapping):
        raise ValueError("PACKET_MUST_BE_OBJECT")
    status = _upper(packet.get("status"))
    if status not in PACKET_STATUSES:
        raise ValueError("PACKET_STATUS_INVALID")
    if status == PLANNED_PACKET_STATUS:
        if raw_evidence is not None or raw_evidence_path:
            raise ValueError("PLANNED_PACKET_CANNOT_HAVE_EVIDENCE")
        binding = packet.get("raw_evidence_binding")
        if isinstance(binding, Mapping) and (
            binding.get("run_id") not in (None, "")
            or binding.get("raw_evidence_path") not in (None, "")
        ):
            raise ValueError("PLANNED_PACKET_BINDING_MUST_BE_EMPTY")
        return True
    if status == EVALUABLE_PACKET_STATUS:
        binding = packet.get("raw_evidence_binding")
        if (
            not raw_evidence_path
            or not _raw_evidence_is_valid(packet, raw_evidence or {})
            or not isinstance(binding, Mapping)
            or binding.get("required_for_evaluable") is not True
            or binding.get("run_id") != (raw_evidence or {}).get("run_id")
            or binding.get("raw_evidence_path") != raw_evidence_path
        ):
            raise ValueError("EVALUABLE_REQUIRES_VALID_BOUND_RAW_EVIDENCE")
        return True
    # NOT_EVALUABLE is an explicit evaluator/coordinator decision and must not
    # be silently treated as a quality failure or as an evaluable answer.
    if raw_evidence is not None:
        raise ValueError("NOT_EVALUABLE_CANNOT_BE_EVALUATED")
    return True


def mark_packet_evaluable(
    packet: Mapping[str, Any],
    *,
    raw_evidence: Mapping[str, Any],
    raw_evidence_path: str,
) -> dict[str, Any]:
    updated = deepcopy(dict(packet))
    updated["status"] = EVALUABLE_PACKET_STATUS
    updated["raw_evidence_binding"] = {
        "required_for_evaluable": True,
        "run_id": raw_evidence.get("run_id"),
        "raw_evidence_path": raw_evidence_path,
    }
    validate_packet_status(
        updated,
        raw_evidence=raw_evidence,
        raw_evidence_path=raw_evidence_path,
    )
    return updated


__all__ = [
    "CASE_E_ALLOWED_REASON_CODES",
    "CASE_E_APPROVAL_FIELDS",
    "CASE_E_FORBIDDEN_REASON_CODES",
    "CASE_E_POLICY",
    "CASE_E_POLICY_ID",
    "CASE_E_POLICY_VERSION",
    "DIFFERENTIAL_MISSINGNESS_POLICY",
    "DIFFERENTIAL_MISSINGNESS_POLICY_ID",
    "DIFFERENTIAL_MISSINGNESS_POLICY_VERSION",
    "EVALUATION_PLAN_ID",
    "EVALUATION_PLAN_VERSION",
    "EVALUATION_PROTOCOL_ID",
    "EVALUATOR_PLAN",
    "MAX_DIFFERENTIAL_MISSINGNESS_PER_ACCEPTED_UNIT",
    "NOT_EVALUABLE_PACKET_STATUS",
    "PACKET_SET_ID",
    "PACKET_SET_VERSION",
    "SUCCESSOR_PACKET_SET_ID",
    "SUCCESSOR_PACKET_SET_VERSION",
    "PACKET_STATUSES",
    "PLANNED_PACKET_STATUS",
    "RUBRIC_VERSION",
    "classify_comparison_unit",
    "classify_condition_missingness",
    "case_e_policy",
    "evaluator_plan",
    "generate_planned_packet_set",
    "generate_successor_packet_set",
    "mark_packet_evaluable",
    "validate_case_e_approval",
    "validate_evaluator_plan",
    "validate_packet_set",
    "validate_packet_status",
]

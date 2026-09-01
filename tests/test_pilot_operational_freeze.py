from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import unittest

from evaluation.pilot.operational_freeze import (
    CASE_E_ALLOWED_REASON_CODES,
    CASE_E_FORBIDDEN_REASON_CODES,
    EVALUABLE_PACKET_STATUS,
    MAX_DIFFERENTIAL_MISSINGNESS_PER_ACCEPTED_UNIT,
    NOT_EVALUABLE_PACKET_STATUS,
    PACKET_SET_ID,
    PLANNED_PACKET_STATUS,
    SUCCESSOR_PACKET_SET_ID,
    classify_comparison_unit,
    evaluator_plan,
    generate_planned_packet_set,
    generate_successor_packet_set,
    mark_packet_evaluable,
    validate_case_e_approval,
    validate_evaluator_plan,
    validate_packet_set,
    validate_packet_status,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "runs" / "pilot" / "taskh-final-manifest-v5.json"


def _condition(strategy: str, *, status: str = "observed", answer: str | None = "answer") -> dict:
    return {
        "strategy": strategy,
        "status": status,
        "answer": answer,
        "freeze_identity": "PILOT-FREEZE-CANDIDATE-V1",
    }


def _case_e_record(**overrides: object) -> dict:
    record = {
        "requester_role": "PILOT-COORDINATOR",
        "approver_role": "INDEPENDENT-REVIEWER",
        "reason_code": CASE_E_ALLOWED_REASON_CODES[0],
        "requested_at": "2026-08-31T10:00:00Z",
        "approved_at": "2026-08-31T10:05:00Z",
        "approval_status": "APPROVED",
        "evidence_reference": "ledger://case-e/unit-01",
        "approved_before_unblinding": True,
    }
    record.update(overrides)
    return record


def _mapping_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for child in value.values():
            keys.update(_mapping_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_mapping_keys(child))
    return keys


class DifferentialMissingnessTests(unittest.TestCase):
    def test_zero_threshold_is_frozen_and_three_plus_one_is_incomparable(self) -> None:
        self.assertEqual(MAX_DIFFERENTIAL_MISSINGNESS_PER_ACCEPTED_UNIT, 0)
        conditions = [
            _condition("single"),
            _condition("fixed"),
            _condition("static"),
            {
                "strategy": "adaptive",
                "status": "provider_incident",
                "provider_incident": True,
                "freeze_identity": "PILOT-FREEZE-CANDIDATE-V1",
            },
        ]
        result = classify_comparison_unit(conditions)
        self.assertFalse(result["comparable"])
        self.assertEqual(result["classification"], "INCOMPARABLE_UNIT")
        self.assertEqual(result["numeric_threshold"], 0)
        self.assertEqual(result["infrastructure_missing_count"], 1)
        self.assertEqual(result["infrastructure_missing_strategies"], ["adaptive"])
        self.assertEqual(result["reason_code"], "DIFFERENTIAL_INFRASTRUCTURE_MISSINGNESS")

    def test_strategy_terminal_failure_is_evidence_not_infrastructure_missingness(self) -> None:
        conditions = [
            _condition("single"),
            _condition("fixed"),
            _condition("static"),
            _condition(
                "adaptive",
                status="stopped",
                answer=None,
            )
            | {"outcome_category": "STRATEGY_TERMINAL_FAILURE"},
        ]
        result = classify_comparison_unit(conditions)
        self.assertTrue(result["comparable"])
        self.assertEqual(result["classification"], "ACCEPTED_COMPARABLE_UNIT")
        self.assertEqual(result["infrastructure_missing_count"], 0)
        self.assertEqual(result["strategy_terminal_failures"], ["adaptive"])

    def test_unknown_or_duplicate_strategy_cannot_be_accepted(self) -> None:
        conditions = [_condition(strategy) for strategy in ("single", "fixed", "static", "adaptive")]
        conditions[-1] = {**conditions[-1], "strategy": "unknown"}
        result = classify_comparison_unit(conditions)
        self.assertFalse(result["comparable"])
        self.assertEqual(result["reason_code"], "UNIT_BINDING_MISMATCH")


class CaseEApprovalTests(unittest.TestCase):
    def test_allowed_case_e_requires_independent_approval_before_unblinding(self) -> None:
        result = validate_case_e_approval(
            _case_e_record(),
            unblinding_at="2026-08-31T10:10:00Z",
        )
        self.assertEqual(result["approval_status"], "APPROVED")

    def test_forbidden_outcome_reason_is_rejected(self) -> None:
        for reason_code in CASE_E_FORBIDDEN_REASON_CODES:
            with self.subTest(reason_code=reason_code):
                with self.assertRaisesRegex(ValueError, "OUTCOME_REASON_FORBIDDEN"):
                    validate_case_e_approval(_case_e_record(reason_code=reason_code))

    def test_approval_after_unblinding_and_human_names_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "APPROVAL_AFTER_UNBLINDING"):
            validate_case_e_approval(
                _case_e_record(),
                unblinding_at="2026-08-31T10:05:00Z",
            )
        with self.assertRaisesRegex(ValueError, "FREE_TEXT_REASON_FORBIDDEN"):
            validate_case_e_approval(_case_e_record(approver_name="A reviewer"))

    def test_requester_and_approver_must_be_distinct_role_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "APPROVER_MUST_BE_INDEPENDENT"):
            validate_case_e_approval(
                _case_e_record(approver_role="PILOT-COORDINATOR")
            )


class EvaluatorPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_planned_packet_set_has_stable_96_ids_and_no_hidden_rubric_content(self) -> None:
        first = generate_planned_packet_set(self.manifest)
        second = generate_planned_packet_set(self.manifest)
        self.assertEqual(first["packet_set_id"], PACKET_SET_ID)
        self.assertEqual(first["planned_packet_count"], 96)
        self.assertEqual(first["status"], PLANNED_PACKET_STATUS)
        self.assertEqual(
            [packet["packet_id"] for packet in first["packets"]],
            [packet["packet_id"] for packet in second["packets"]],
        )
        self.assertEqual(len({packet["packet_id"] for packet in first["packets"]}), 96)
        self.assertTrue(validate_packet_set(first))
        for packet in first["packets"]:
            for field in (
                "packet_id",
                "task_id",
                "repeat_index",
                "strategy",
                "unit_id",
                "candidate_identity",
                "rubric_binding",
                "evaluation_protocol_id",
                "status",
            ):
                self.assertIn(field, packet)
        forbidden_keys = {
            "mandatory_criteria",
            "critical_errors",
            "expected_source_facts",
            "research_annotations",
        }
        self.assertFalse(forbidden_keys & _mapping_keys(first))

    def test_evaluation_has_deterministic_successor_packet_rebinding(self) -> None:
        historical = generate_planned_packet_set(self.manifest)
        successor_manifest = deepcopy(self.manifest)
        successor_manifest["manifest_id"] = "pm_successor_test"
        successor_manifest["run_manifest_hash"] = "successor-manifest-hash"
        successor_manifest["freeze_identity"] = "PILOT-FREEZE-CANDIDATE-V2"
        first = generate_successor_packet_set(
            successor_manifest,
            manifest_path="runs/pilot/taskh-final-manifest-v6.json",
        )
        second = generate_successor_packet_set(
            successor_manifest,
            manifest_path="runs/pilot/taskh-final-manifest-v6.json",
        )
        self.assertEqual(first, second)
        self.assertEqual(first["packet_set_id"], SUCCESSOR_PACKET_SET_ID)
        self.assertEqual(first["evaluator_plan"]["packet_set_id"], SUCCESSOR_PACKET_SET_ID)
        self.assertTrue(validate_packet_set(first))
        self.assertNotEqual(
            [packet["packet_id"] for packet in historical["packets"]],
            [packet["packet_id"] for packet in first["packets"]],
        )
        self.assertTrue(all(packet["status"] == PLANNED_PACKET_STATUS for packet in first["packets"]))
        packet = first["packets"][0]
        self.assertEqual(packet["candidate_identity"]["candidate_manifest_id"], "pm_successor_test")
        self.assertEqual(packet["candidate_identity"]["freeze_identity"], "PILOT-FREEZE-CANDIDATE-V2")

        raw = {
            "run_id": "run-1",
            "status": "completed",
            "answer": "answer",
            "task_id": packet["task_id"],
            "unit_id": packet["unit_id"],
            "strategy": packet["strategy"],
            "repeat_index": packet["repeat_index"],
            "freeze_identity": packet["candidate_identity"]["freeze_identity"],
        }
        updated = mark_packet_evaluable(
            packet,
            raw_evidence=raw,
            raw_evidence_path="raw/run-1.json",
        )
        self.assertEqual(updated["status"], EVALUABLE_PACKET_STATUS)
        self.assertTrue(validate_packet_status(
            updated,
            raw_evidence={
                **raw,
            },
            raw_evidence_path="raw/run-1.json",
        ))
        self.assertEqual(first["packets"][0]["status"], PLANNED_PACKET_STATUS)

    def test_planned_is_not_evaluable_and_evaluable_requires_matching_raw_evidence(self) -> None:
        packet_set = generate_planned_packet_set(self.manifest)
        packet = packet_set["packets"][0]
        self.assertTrue(validate_packet_status(packet))
        with self.assertRaisesRegex(ValueError, "PLANNED_PACKET_CANNOT_HAVE_EVIDENCE"):
            validate_packet_status(
                packet,
                raw_evidence={"run_id": "run-1", "status": "completed", "answer": "answer"},
                raw_evidence_path="raw/run-1.json",
            )

        evaluable = deepcopy(packet)
        evaluable["status"] = EVALUABLE_PACKET_STATUS
        with self.assertRaisesRegex(ValueError, "EVALUABLE_REQUIRES_VALID_BOUND_RAW_EVIDENCE"):
            validate_packet_status(
                evaluable,
                raw_evidence={
                    "run_id": "run-1",
                    "status": "completed",
                    "answer": "answer",
                    "task_id": packet["task_id"],
                    "unit_id": packet["unit_id"],
                    "strategy": packet["strategy"],
                    "freeze_identity": packet["candidate_identity"]["freeze_identity"],
                },
                raw_evidence_path="raw/run-1.json",
            )

        raw = {
            "run_id": "run-1",
            "status": "completed",
            "answer": "answer",
            "task_id": packet["task_id"],
            "unit_id": packet["unit_id"],
            "strategy": packet["strategy"],
            "repeat_index": packet["repeat_index"],
            "freeze_identity": packet["candidate_identity"]["freeze_identity"],
        }
        updated = mark_packet_evaluable(
            packet,
            raw_evidence=raw,
            raw_evidence_path="raw/run-1.json",
        )
        self.assertEqual(updated["status"], EVALUABLE_PACKET_STATUS)
        self.assertTrue(
            validate_packet_status(
                updated,
                raw_evidence=raw,
                raw_evidence_path="raw/run-1.json",
            )
        )

        not_evaluable = deepcopy(packet)
        not_evaluable["status"] = NOT_EVALUABLE_PACKET_STATUS
        self.assertTrue(validate_packet_status(not_evaluable))

    def test_evaluator_slots_are_honest_and_capacity_is_unconfirmed(self) -> None:
        plan = evaluator_plan()
        self.assertTrue(validate_evaluator_plan(plan))
        self.assertEqual(plan["capacity_status"], "UNCONFIRMED")
        self.assertEqual(
            {role: slot["status"] for role, slot in plan["slots"].items()},
            {"E1": "UNASSIGNED", "E2": "UNASSIGNED", "ADJ-1": "UNASSIGNED"},
        )
        invalid = deepcopy(plan)
        invalid["slots"]["E1"]["status"] = "CONFIRMED"
        with self.assertRaisesRegex(ValueError, "SLOT_STATUS_INVALID"):
            validate_evaluator_plan(invalid)


class HiddenRubricIsolationTests(unittest.TestCase):
    def test_runtime_tree_does_not_reference_hidden_rubric_artifact_or_fields(self) -> None:
        runtime_root = ROOT / "app"
        runtime_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in runtime_root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".js", ".html", ".css", ".json"}
        )
        self.assertNotIn("evaluation/pilot/pilot_rubrics_v1.json", runtime_text)
        for hidden_field in (
            '"mandatory_criteria"',
            '"critical_errors"',
            '"expected_source_facts"',
            '"research_annotations"',
            '"hidden_task_rubric"',
        ):
            self.assertNotIn(hidden_field, runtime_text)


if __name__ == "__main__":
    unittest.main()

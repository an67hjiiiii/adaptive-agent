"""Prepare and execute bounded Pilot conditions.

The CLI consumes a frozen manifest and never chooses strategy order at runtime.
Live execution is bounded by an explicit condition limit and an explicit
``--allow-live`` flag; the default command therefore cannot launch all 96
conditions accidentally.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main_module
from app.core.pilot import (
    DEFAULT_PILOT_MODEL,
    DEFAULT_PILOT_PROVIDER,
    PILOT_PREREGISTRATION_VERSION,
    PILOT_STRATEGIES,
    PilotLedger,
    build_pilot_manifest,
    export_processed_dataset,
    new_run_id,
    sha256_text,
    validate_pilot_manifest,
)
from app.core.pilot_executor import (
    PilotExecutor,
    PilotExecutorError,
    open_or_create_ledger,
    validate_manifest_file,
    validate_task_binding,
    validate_snapshot_completeness,
)
from app.core.rag import frozen_snapshot
from evaluation.pilot.operational_freeze import generate_successor_packet_set


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(args: argparse.Namespace) -> dict:
    task_manifest = _read_json(Path(args.task_manifest))
    manifest = build_pilot_manifest(
        task_manifest,
        repeat_count=args.repeat_count,
        provider=args.provider,
        model=args.model,
        preregistration_version=args.preregistration_version,
        seed=args.seed,
        require_balanced=True,
        preflight_binding=_read_json(Path(args.preflight)) if getattr(args, "preflight", None) else None,
    )
    validate_pilot_manifest(manifest, require_balanced=True)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"Manifest output already exists; choose a new path: {output}")
    _write_json(output, manifest)
    return {
        "status": "prepared",
        "manifest_id": manifest["manifest_id"],
        "run_manifest_hash": manifest["run_manifest_hash"],
        "output": str(output),
        "comparison_units": manifest["expected_comparison_units"],
        "strategy_runs": manifest["expected_strategy_runs"],
        "provider": manifest["provider"],
        "model": manifest["model"],
        "order_balance": manifest["order_policy"]["balance_status"],
        "pricing_status": manifest["configuration"]["pricing"]["status"],
        "research_evidence": False,
    }


def prepare_packets(args: argparse.Namespace) -> dict:
    manifest_path = Path(args.manifest)
    manifest = _read_json(manifest_path)
    validate_pilot_manifest(manifest, require_balanced=True)
    packets = generate_successor_packet_set(
        manifest,
        manifest_path=str(manifest_path.as_posix()),
    )
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"Packet output already exists; choose a new path: {output}")
    _write_json(output, packets)
    return {
        "status": "prepared",
        "packet_set_id": packets["packet_set_id"],
        "version": packets["version"],
        "candidate_manifest_id": packets["candidate_identity"]["candidate_manifest_id"],
        "candidate_manifest_hash": packets["candidate_identity"]["candidate_manifest_hash"],
        "planned_packet_count": packets["planned_packet_count"],
        "output": str(output),
        "research_evidence": False,
    }


async def _run_dry_unit(args: argparse.Namespace, ledger: PilotLedger, manifest: dict) -> list[dict]:
    task = args.task
    context = args.context
    snapshot, retrieval_meta = frozen_snapshot(task, context)
    main_module.RUNS = ledger.raw_dir

    async def sink(_event):
        return None

    unit = manifest["units"][0]
    ledger.set_unit_snapshot(
        unit["unit_id"],
        snapshot_id=retrieval_meta["snapshot_id"],
        snapshot_hash=retrieval_meta["snapshot_hash"],
    )
    results = []
    comparison_id = f"{manifest['manifest_id']}-dry-run"
    for strategy in unit["strategy_order"]:
        condition = ledger.begin(unit["unit_id"], strategy)
        run_id = condition["run_id"]
        pilot_meta = {
            "dry_run": True,
            "phase": "DRY_RUN",
            "research_evidence": False,
            "evidence_class": "DRY_RUN",
            "pilot_manifest_id": manifest["manifest_id"],
            "run_manifest_hash": manifest["run_manifest_hash"],
            "condition_id": f"{unit['unit_id']}::{strategy}",
            "attempt_id": run_id,
            "unit_id": unit["unit_id"],
            "task_id": unit["task_id"],
            "repeat_index": unit["repeat_index"],
            "repeat_id": unit["repeat_id"],
            "strategy": strategy,
            "execution_order": condition["execution_order"],
            "order_seed": unit["order_seed"],
            "strategy_config_id": condition["strategy_config_id"],
            "strategy_config_version": condition["strategy_config_version"],
            "pilot_config_identities": deepcopy(manifest["pilot_config_identities"]),
            "config_identities": deepcopy(manifest["config_identities"]),
            "pilot_strategy_config_id": condition["pilot_strategy_config_id"],
            "provider": condition["provider"],
            "model": condition["model"],
            "model_settings_identity": condition["model_settings_identity"],
            "rag_config_id": condition["rag_config_id"],
            "rag_pilot_config_id": condition["rag_pilot_config_id"],
            "price_config_id": condition["price_config_id"],
            "benchmark_version": unit["benchmark_version"],
            "rubric_version_reference": unit["rubric_version_reference"],
            "pricing_version": condition["pricing_version"],
            "pilot_pricing_version": condition["pilot_pricing_version"],
            "context_snapshot_id": retrieval_meta["snapshot_id"],
            "context_snapshot_hash": retrieval_meta["snapshot_hash"],
            "run_state": "RUNNING",
        }
        comparison_meta = {
            "comparison_id": comparison_id,
            "unit_id": unit["unit_id"],
            "order": condition["execution_order"],
            "dry_run": True,
            "evidence_class": "DRY_RUN",
        }
        try:
            data = await main_module.execute_once(
                strategy=strategy,
                provider_name="fake",
                model_name="fake-research-v2",
                message=task,
                frozen_context=snapshot,
                retrieval_meta=deepcopy(retrieval_meta),
                history=[],
                emit=sink,
                budget_config=manifest["configuration"]["budget"],
                comparison_meta=comparison_meta,
                run_id=run_id,
                run_metadata=pilot_meta,
            )
        except Exception as exc:
            data = main_module.save_failed_run_evidence(
                strategy=strategy,
                provider="fake",
                model="fake-research-v2",
                message=task,
                context=snapshot,
                retrieval_meta=deepcopy(retrieval_meta),
                history=[],
                error=exc,
                comparison_meta=comparison_meta,
                budget_config=manifest["configuration"]["budget"],
                run_id=run_id,
                run_metadata=pilot_meta,
            )
        raw_path = ledger.root / condition["raw_evidence_path"]
        recorded = ledger.record(
            unit["unit_id"],
            strategy,
            raw_path=raw_path,
            raw=data,
        )
        results.append({
            "strategy": strategy,
            "execution_order": recorded["execution_order"],
            "run_id": recorded["run_id"],
            "status": recorded["status"],
            "raw_evidence_path": recorded["raw_evidence_path"],
        })
    return results


def dry_run(args: argparse.Namespace) -> dict:
    output_root = Path(args.output)
    task_id = args.task_id
    task_hash = sha256_text(f"{task_id}|{args.task}|{args.context}")
    task_manifest = {
        "manifest_id": "DRY-RUN-TASK-MANIFEST-V1",
        "version": "1.0",
        "benchmark_version": "DRY-RUN-NOT-BENCHMARK",
        "rubric_version_reference": "NOT_APPLICABLE",
        "tasks": [{
            "task_id": task_id,
            "task_version": "DRY-RUN-1",
            "task_hash": task_hash,
            "reference_manifest_id": "DRY-RUN-NONE",
            "reference_manifest_version": "1.0",
        }],
    }
    manifest = build_pilot_manifest(
        task_manifest,
        repeat_count=1,
        provider="fake",
        model="fake-research-v2",
        preregistration_version=PILOT_PREREGISTRATION_VERSION,
        dry_run=True,
        require_balanced=False,
    )
    ledger = PilotLedger(output_root, manifest)
    recovered = ledger.recover_interrupted()
    results = asyncio.run(_run_dry_unit(args, ledger, manifest))
    processed = export_processed_dataset(output_root, include_dry_run=True)
    ledger.assert_integrity()
    return {
        "status": "completed",
        "dry_run": True,
        "evidence_class": "DRY_RUN",
        "research_evidence": False,
        "manifest_id": manifest["manifest_id"],
        "raw_evidence_root": str(ledger.raw_dir),
        "processed_dataset": str(output_root / "processed" / "dataset.json"),
        "recovered_before_run": len(recovered),
        "strategy_results": results,
        "processed_row_count": processed["row_count"],
        "top_level_execution_order": [item["strategy"] for item in sorted(results, key=lambda x: x["execution_order"])],
        "snapshot_ids": sorted({
            row["context_snapshot_id"]
            for row in processed["rows"]
            if row.get("context_snapshot_id")
        }),
    }


def recover(args: argparse.Namespace) -> dict:
    ledger = PilotLedger.open(Path(args.root))
    recovered = ledger.recover_interrupted()
    ledger.assert_integrity()
    return {
        "status": "recovered",
        "manifest_id": ledger.manifest.get("manifest_id"),
        "recovered_count": len(recovered),
        "pending_count": len(ledger.pending()),
        "research_evidence": False,
    }


def validate(args: argparse.Namespace) -> dict:
    target = Path(args.target)
    manifest_path = target if target.is_file() else target / "manifest.json"
    result = validate_manifest_file(manifest_path)
    if args.task_manifest:
        task_manifest = _read_json(Path(args.task_manifest))
        manifest = _read_json(manifest_path)
        validate_task_binding(manifest, task_manifest)
        result["task_manifest_binding"] = "valid"
    if target.is_dir() and (target / "ledger.json").exists():
        ledger = PilotLedger.open(target)
        ledger.assert_integrity()
        result["ledger"] = "valid"
        result["status_counts"] = ledger.status_summary()["status_counts"]
    result["research_evidence"] = False
    return result


def validate_snapshots(args: argparse.Namespace) -> dict:
    task_manifest = _read_json(Path(args.task_manifest))
    reports = validate_snapshot_completeness(
        task_manifest,
        source_roots=[ROOT, Path(args.task_manifest).resolve().parent],
        top_k=args.top_k,
        max_chars=args.max_chars,
    )
    return {
        "status": "valid" if all(item["required_support_present"] for item in reports) else "invalid",
        "task_count": len(reports),
        "reports": reports,
        "research_evidence": False,
    }


def status(args: argparse.Namespace) -> dict:
    ledger = PilotLedger.open(Path(args.root))
    ledger.assert_integrity()
    result = ledger.status_summary()
    result["status"] = "ok"
    result["research_evidence"] = False
    return result


def run(args: argparse.Namespace) -> dict:
    root = Path(args.root)
    manifest_arg = getattr(args, "manifest", None)
    ledger = open_or_create_ledger(root, manifest_path=Path(manifest_arg) if manifest_arg else None)
    task_manifest_path = Path(args.task_manifest)
    task_manifest = _read_json(task_manifest_path)
    executor = PilotExecutor(
        ledger,
        task_manifest,
        phase=args.phase,
        allow_live=args.allow_live,
        allow_unreviewed=args.allow_unreviewed,
        source_roots=[ROOT, task_manifest_path.resolve().parent],
        preflight=_read_json(Path(args.preflight)) if getattr(args, "preflight", None) else None,
        authorization=_read_json(Path(args.authorization)) if getattr(args, "authorization", None) else None,
        live_window=_read_json(Path(args.live_window)) if getattr(args, "live_window", None) else None,
    )
    return executor.run(limit=args.limit, retry_failed=args.retry_failed)


def resume(args: argparse.Namespace) -> dict:
    # Resume is deliberately the same executor path: recovery happens before
    # the next manifest-ordered condition, so it cannot create a second policy.
    return run(args)


def export(args: argparse.Namespace) -> dict:
    result = export_processed_dataset(
        Path(args.root),
        Path(args.output) if args.output else None,
        include_dry_run=args.include_dry_run,
        include_preflight=args.include_preflight,
    )
    return {
        "status": "exported",
        "dataset_version": result["dataset_version"],
        "output": str(Path(args.output) if args.output else Path(args.root) / "processed" / "dataset.json"),
        "row_count": result["row_count"],
        "excluded_non_pilot_counts": result["excluded_non_pilot_counts"],
        "source_manifest_id": result["source_manifest_id"],
        "include_dry_run": args.include_dry_run,
        "include_preflight": args.include_preflight,
        "research_evidence": bool(
            not (args.include_dry_run or args.include_preflight)
            and any(
                row.get("phase") == "PILOT" and row.get("raw_evidence_path")
                for row in result.get("rows", [])
            )
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pilot manifest, ledger, bounded executor and evidence export")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="prepare a manifest from a separate benchmark manifest")
    prepare_parser.add_argument("--task-manifest", required=True)
    prepare_parser.add_argument("--output", default=str(ROOT / "runs" / "pilot" / "pilot_manifest.json"))
    prepare_parser.add_argument("--repeat-count", type=int, default=3)
    prepare_parser.add_argument("--provider", default=DEFAULT_PILOT_PROVIDER)
    prepare_parser.add_argument("--model", default=DEFAULT_PILOT_MODEL)
    prepare_parser.add_argument("--preregistration-version", default=PILOT_PREREGISTRATION_VERSION)
    prepare_parser.add_argument("--seed")
    prepare_parser.add_argument("--preflight", help="safe versioned preflight binding to embed in the prepared candidate")
    prepare_parser.set_defaults(handler=prepare)

    packets_parser = subparsers.add_parser(
        "prepare-packets",
        help="create an immutable V2 evaluator packet-set candidate for a successor manifest",
    )
    packets_parser.add_argument("--manifest", required=True)
    packets_parser.add_argument("--output", required=True)
    packets_parser.set_defaults(handler=prepare_packets)

    dry_parser = subparsers.add_parser("dry-run", help="run one Fake infrastructure unit: one task x four strategies")
    dry_parser.add_argument("--task", default="Infrastructure-only Pilot manifest and evidence smoke test")
    dry_parser.add_argument("--context", default="No benchmark context; this run validates infrastructure only.")
    dry_parser.add_argument("--task-id", default="DRY-RUN-INFRA-1")
    dry_parser.add_argument("--output", default=str(ROOT / "runs" / "pilot" / "dry-run"))
    dry_parser.set_defaults(handler=dry_run)

    recover_parser = subparsers.add_parser("recover", help="recover in-flight conditions without rerunning anything")
    recover_parser.add_argument("root")
    recover_parser.set_defaults(handler=recover)

    validate_parser = subparsers.add_parser("validate", help="validate a prepared manifest or Pilot ledger")
    validate_parser.add_argument("target", help="manifest.json or a Pilot ledger directory")
    validate_parser.add_argument("--task-manifest", help="optional source task manifest to hash-check")
    validate_parser.set_defaults(handler=validate)

    snapshots_parser = subparsers.add_parser(
        "validate-snapshots",
        help="offline completeness check for all declared reference sections",
    )
    snapshots_parser.add_argument("--task-manifest", required=True)
    snapshots_parser.add_argument("--top-k", type=int)
    snapshots_parser.add_argument("--max-chars", type=int)
    snapshots_parser.set_defaults(handler=validate_snapshots)

    status_parser = subparsers.add_parser("status", help="show Pilot ledger status without executing")
    status_parser.add_argument("root")
    status_parser.set_defaults(handler=status)

    run_parser = subparsers.add_parser("run", help="execute at most N next manifest conditions")
    run_parser.add_argument("root", help="Pilot ledger directory")
    run_parser.add_argument("--manifest", help="prepared manifest.json for a new ledger")
    run_parser.add_argument("--task-manifest", required=True, help="separate runtime-safe task manifest")
    run_parser.add_argument("--limit", type=int, default=1, help="maximum new condition attempts (default: 1)")
    run_parser.add_argument("--phase", choices=("PILOT", "PREFLIGHT"), default="PILOT")
    run_parser.add_argument("--allow-live", action="store_true", help="explicitly permit non-Fake provider calls")
    run_parser.add_argument("--allow-unreviewed", action="store_true", help="override an unapproved benchmark status")
    run_parser.add_argument("--retry-failed", action="store_true", help="retry failed/stopped conditions with new attempt IDs")
    run_parser.add_argument("--preflight", help="fresh safe provider preflight JSON required for live PILOT")
    run_parser.add_argument("--authorization", help="owner authorization JSON required for live PILOT")
    run_parser.add_argument("--live-window", help="active manifest-bound live window JSON required for live PILOT")
    run_parser.set_defaults(handler=run)

    resume_parser = subparsers.add_parser("resume", help="recover stale reservations and execute the next conditions")
    resume_parser.add_argument("root", help="existing Pilot ledger directory")
    resume_parser.add_argument("--task-manifest", required=True, help="separate runtime-safe task manifest")
    resume_parser.add_argument("--limit", type=int, default=1, help="maximum new condition attempts (default: 1)")
    resume_parser.add_argument("--phase", choices=("PILOT", "PREFLIGHT"), default="PILOT")
    resume_parser.add_argument("--allow-live", action="store_true", help="explicitly permit non-Fake provider calls")
    resume_parser.add_argument("--allow-unreviewed", action="store_true", help="override an unapproved benchmark status")
    resume_parser.add_argument("--retry-failed", action="store_true", help="retry failed/stopped conditions with new attempt IDs")
    resume_parser.add_argument("--preflight", help="fresh safe provider preflight JSON required for live PILOT")
    resume_parser.add_argument("--authorization", help="owner authorization JSON required for live PILOT")
    resume_parser.add_argument("--live-window", help="active manifest-bound live window JSON required for live PILOT")
    resume_parser.set_defaults(handler=resume)

    export_parser = subparsers.add_parser("export", help="derive a tidy dataset from raw evidence")
    export_parser.add_argument("root")
    export_parser.add_argument("--output")
    export_parser.add_argument("--include-dry-run", action="store_true", help="explicitly include DRY_RUN rows")
    export_parser.add_argument("--include-preflight", action="store_true", help="explicitly include PREFLIGHT rows")
    export_parser.set_defaults(handler=export)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = args.handler(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Write a resumable audit trail, not a resumable held-out experiment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dep_triage.config import Settings
from dep_triage.eval.metrics import canonical_bytes, compute_metrics
from dep_triage.eval.records import EvaluationRecord
from dep_triage.eval.runner import provenance, reserve_held_out, run_suite
from dep_triage.eval.suite import SystemName, build_cases
from dep_triage.eval.tasks import EXPOSED_TASK_IDS, Split, TaskSet
from dep_triage.fixture import load_fixture


def evaluate_to_file(
    *,
    settings: Settings,
    tasks_path: Path,
    output: Path,
    split: Split,
    systems: list[SystemName],
    faults: bool = False,
    confirm_held_out: bool = False,
    progress: bool = False,
) -> dict[str, Any]:
    """Checkpoint every completed task and refuse accidental reruns/overwrites."""
    if split == "held_out" and not confirm_held_out:
        raise ValueError(
            "held-out execution requires --confirm-held-out-once; reserved for the final run"
        )
    if not systems or len(systems) != len(set(systems)):
        raise ValueError("select at least one system, without duplicates")
    if not settings.is_deterministic:
        raise ValueError("evaluation requires llm_temperature=0")
    task_set = TaskSet.model_validate_json(tasks_path.read_text(encoding="utf-8"))
    fixture = load_fixture(settings.fixture_path)
    if task_set.fixture_snapshot != fixture.manifest.snapshot_date:
        raise ValueError("task and fixture snapshot dates differ")
    cases = build_cases(task_set, split, faults)
    if not cases:
        raise ValueError("no eligible tasks")
    checkpoint = output.with_suffix(".jsonl")
    metrics_path = output.with_suffix(".metrics.json")
    if len({output, checkpoint, metrics_path}) != 3:
        raise ValueError("output must have a .json extension")
    if output.suffix != ".json":
        raise ValueError("output must have a .json extension")
    if any(p.exists() for p in (output, checkpoint, metrics_path)):
        raise ValueError("result path already exists; choose a new path")
    metadata = {
        "schema_version": 1,
        "split": split,
        "systems": systems,
        "faults": faults,
        "excluded_exposed_tasks": sorted(EXPOSED_TASK_IDS),
        "provenance": provenance(settings, tasks_path),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint.open("x", encoding="utf-8") as log:
        if split == "held_out":
            reserve_held_out(tasks_path, systems, settings, faults)
        log.write(json.dumps({"metadata": metadata}, sort_keys=True) + "\n")
        log.flush()

        def record_result(record: EvaluationRecord) -> None:
            log.write(record.model_dump_json() + "\n")
            log.flush()
            if progress:
                import sys

                outcome = (
                    "ungradable" if record.grade.correct is None else str(record.grade.correct)
                )
                print(
                    f"{record.system} {record.case.key}: {outcome}; "
                    f"{len(record.trace.calls)} calls; {record.trace.stop_reason}",
                    file=sys.stderr,
                    flush=True,
                )

        records = run_suite(cases, systems, fixture, settings, on_record=record_result)
    metrics = compute_metrics(records, fixture)
    report = {
        **metadata,
        "status": "complete",
        "metrics": metrics,
        "records": [r.model_dump(mode="json") for r in records],
    }
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    with metrics_path.open("xb") as binary_handle:
        binary_handle.write(canonical_bytes(metrics))
    return report

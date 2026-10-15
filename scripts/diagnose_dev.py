"""Audit the saved M3 development evidence offline; never invoke a model.

This is a retrospective diagnosis, not another benchmark arm. Replaying the
recorded tool calls tests the deterministic boundary, not the model's ability
to choose those calls again. Original artifacts are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from dep_triage.agent.loop import SYSTEM_PROMPT
from dep_triage.eval.assertions import extract_assertions
from dep_triage.eval.grading import grade
from dep_triage.eval.metrics import canonical_bytes, compute_metrics
from dep_triage.eval.records import EvaluationRecord
from dep_triage.eval.reference import Evidence, lowest_clean_version, resolve
from dep_triage.eval.suite import SYSTEMS, build_cases
from dep_triage.eval.tasks import EXPOSED_TASK_IDS, TaskSet
from dep_triage.fixture import Fixture, load_fixture, sort_key, version_in, versions_equal
from dep_triage.tools import triage
from dep_triage.tools.wrapper import BUDGET_MESSAGE, TOOL_NAMES, ToolCallRecord, ToolError, Toolkit


def require_dev(record: EvaluationRecord) -> None:
    if record.case.task.split != "dev" or record.case.task.id in EXPOSED_TASK_IDS:
        raise ValueError("diagnosis accepts development records only")


def replay_tools(
    record: EvaluationRecord, fixture: Fixture, max_calls: int
) -> list[ToolCallRecord]:
    """Check every recorded payload/error/argument/index, excluding elapsed time."""
    require_dev(record)
    toolkit = Toolkit(
        fixture,
        faults=(record.case.fault,) if record.case.fault else (),
        max_calls=max_calls if record.system == "agent" else None,
    )
    for call in record.trace.calls:
        if call.tool not in TOOL_NAMES:
            raise ValueError(f"unrecognised tool: {call.tool}")
        # The saved error still has to match below; unexpected errors escape.
        with suppress(ToolError):
            getattr(toolkit, call.tool)(**call.arguments)
        actual = toolkit.calls[-1].model_dump(exclude={"duration_ms"})
        expected = call.model_dump(exclude={"duration_ms"})
        if actual != expected:
            raise ValueError(f"tool replay differs: {record.system}/{record.case.key}/{call.index}")
    return toolkit.calls


def baseline_input(record: EvaluationRecord, fixture: Fixture) -> list[dict[str, str]]:
    """Reconstruct the successful one-shot baseline input from its saved calls.

    Saved JSON sorts keys, whereas the actual model input did not. Replay the
    pure tools to recover insertion order, checking every payload against the
    saved one. A capture-model test checks the reconstruction against the
    baseline implementation without making model calls. This is not a captured
    HTTP request; the original artifacts did not retain baseline input messages.
    """
    require_dev(record)
    if record.system == "agent":
        raise ValueError("expected a baseline record")
    gathered: dict[str, Any] = {}
    for call in replay_tools(record, fixture, 8):
        if not call.ok:
            raise ValueError("baseline stopped before inference")
        args = call.arguments
        key: str
        match call.tool:
            case "parse_requirements":
                key = call.tool
            case "lookup_vulnerabilities":
                key = f"{call.tool}({args['package']}=={args['version']})"
            case "list_releases":
                key = f"{call.tool}({args['package']})"
            case "check_compatibility":
                key = (
                    f"{call.tool}({args['package']}=={args['version']}, py{args['python_version']})"
                )
            case _:
                raise ValueError(f"unrecognised tool: {call.tool}")
        gathered[key] = call.result
    if not gathered:
        gathered["note"] = "no pinned package found in the question"
    evidence = json.dumps(gathered, indent=2, default=str)
    prompt = (
        f"{record.case.task.question}\n\n"
        "Tool results have already been gathered for you. Use only these:\n\n"
        f"{evidence}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]


def usage(records: list[EvaluationRecord]) -> dict[str, Any]:
    counts = [
        message["usage_metadata"]
        for record in records
        for message in record.trace.messages
        if message.get("usage_metadata")
    ]
    return {
        "tasks": len(records),
        "model_calls_with_usage": len(counts),
        "input_tokens": sum(c["input_tokens"] for c in counts),
        "output_tokens": sum(c["output_tokens"] for c in counts),
        "cache_read_tokens": sum(
            c.get("input_token_details", {}).get("cache_read", 0) for c in counts
        ),
        "max_input_tokens": max((c["input_tokens"] for c in counts), default=None),
        "max_total_tokens": max((c["total_tokens"] for c in counts), default=None),
    }


def failure_evidence(record: EvaluationRecord, fixture: Fixture) -> dict[str, Any]:
    task = record.case.task
    assert task.package is not None and task.from_version is not None
    target = lowest_clean_version(Evidence(fixture), task.package, task.from_version)
    assert target is not None
    window = triage.list_releases(fixture, task.package, task.from_version)
    unfiltered = triage.list_releases(fixture, task.package)
    checks = [c for c in record.trace.calls if c.tool == "check_compatibility"]
    below_floor = None
    if task.answer_kind == "version":
        assert record.grade.extracted is not None
        below_floor = sort_key(record.grade.extracted) < sort_key(task.from_version)
    return {
        "task_id": task.id,
        "answer": record.trace.answer,
        "expected": record.grade.expected,
        "lowest_clean_target": target,
        "selected_version_below_floor": below_floor,
        "target_in_unfiltered_window": version_in(target, unfiltered.versions),
        "target_in_floor_filtered_window": version_in(target, window.versions),
        "floor_filtered_window": {
            "count": len(window.versions),
            "first": window.versions[0],
            "last": window.versions[-1],
        },
        "queried_filtered_releases": any(
            c.tool == "list_releases" and c.arguments.get("since_version") is not None
            for c in record.trace.calls
        ),
        "queried_target_compatibility": any(
            c.arguments["package"] == task.package
            and versions_equal(c.arguments["version"], target)
            for c in checks
        ),
        "target_compatibility": (
            triage.check_compatibility(
                fixture, task.package, target, task.python_version
            ).model_dump()
            if task.python_version
            else None
        ),
        "calls": [c.model_dump(exclude={"duration_ms", "result"}) for c in record.trace.calls],
        "budget_refusals": sum(c.error == BUDGET_MESSAGE for c in record.trace.calls),
        "stop_reason": record.trace.stop_reason,
        "max_input_tokens": usage([record])["max_input_tokens"],
    }


def diagnose(root: Path) -> dict[str, Any]:
    fixture_path = root / "data/fixture"
    fixture = load_fixture(fixture_path)
    task_path = root / "data/tasks.json"
    tasks = TaskSet.model_validate_json(task_path.read_text())
    paths = [root / f"results/m3-gates/run-{i}.json" for i in range(1, 6)]
    paths.append(root / "results/m3-faults-rescored.json")
    runs: list[list[EvaluationRecord]] = []
    hashes: dict[str, str] = {}
    replayed = 0
    clean_provenance: dict[str, Any] | None = None
    for path in paths:
        raw = path.read_bytes()
        report = json.loads(raw)
        if report["split"] != "dev" or report["status"] != "complete":
            raise ValueError("expected a completed development artifact")
        recorded_hashes = report["provenance"]["sha256"]
        if not report["faults"]:
            if clean_provenance is None:
                clean_provenance = report["provenance"]
            elif report["provenance"] != clean_provenance:
                raise ValueError("clean repeat provenance differs")
        for data_path in [task_path, *sorted(fixture_path.glob("*.json"))]:
            recorded = [v for k, v in recorded_hashes.items() if Path(k).name == data_path.name]
            if recorded != [hashlib.sha256(data_path.read_bytes()).hexdigest()]:
                raise ValueError(f"data bytes differ: {data_path.name}")
        records = [EvaluationRecord.model_validate(r) for r in report["records"]]
        expected_cases = build_cases(tasks, "dev", faults=report["faults"])
        expected_pairs = {(system, case.key) for system in SYSTEMS for case in expected_cases}
        actual_pairs = {(r.system, r.case.key) for r in records}
        if actual_pairs != expected_pairs or len(records) != len(expected_pairs):
            raise ValueError("artifact is missing or duplicating planned cases")
        expected_by_key = {c.key: c for c in expected_cases}
        # Require the measured baseline algorithm. loop.py's explanatory
        # docstring changed after measurement; its prompt did not (M3 report).
        for relative in ("src/dep_triage/eval/baselines.py",):
            recorded_source = [v for k, v in recorded_hashes.items() if k.endswith(relative)]
            if recorded_source != [hashlib.sha256((root / relative).read_bytes()).hexdigest()]:
                raise ValueError(f"measured model input implementation differs: {relative}")
        for record in records:
            require_dev(record)
            if record.case != expected_by_key[record.case.key]:
                raise ValueError("case differs from the committed development plan")
            truth = resolve(record.case.task, fixture)
            if (
                truth != record.truth
                or grade(record.case.task, truth, record.trace.answer) != record.grade
            ):
                raise ValueError(f"truth or grade differs: {record.case.key}")
            replayed += len(
                replay_tools(record, fixture, report["provenance"]["settings"]["max_steps"])
            )
        recalculated = canonical_bytes(compute_metrics(records, fixture))
        if recalculated != canonical_bytes(report["metrics"]):
            raise ValueError(f"embedded metrics differ: {path.name}")
        if recalculated != path.with_suffix(".metrics.json").read_bytes():
            raise ValueError(f"canonical metrics differ: {path.name}")
        hashes[str(path.relative_to(root))] = hashlib.sha256(raw).hexdigest()
        runs.append(records)

    changes: list[dict[str, Any]] = []
    for original in runs[0]:
        peers = [
            next(r for r in run if (r.system, r.case.key) == (original.system, original.case.key))
            for run in runs[:5]
        ]
        if len({r.grade.correct for r in peers}) > 1:
            changes.append(
                {
                    "system": original.system,
                    "task_id": original.case.task.id,
                    "correct": [r.grade.correct for r in peers],
                    "answers": [r.trace.answer for r in peers],
                    "baseline_input_sha256": [
                        hashlib.sha256(
                            canonical_bytes({"messages": baseline_input(r, fixture)})
                        ).hexdigest()
                        for r in peers
                    ],
                    "usage": [usage([r]) for r in peers],
                }
            )
    fabrications: list[dict[str, Any]] = []
    for record in runs[-1]:
        assertions = extract_assertions(record.case.task, record.trace.answer, fixture)
        detected = [a for a in assertions if a.classification in {"hard", "misattributed"}]
        if detected:
            fabrications.append(
                {
                    "system": record.system,
                    "case": record.case.key,
                    "answer": record.trace.answer,
                    "assertions": [a.model_dump() for a in detected],
                }
            )
    return {
        "schema_version": 1,
        "model_executions": 0,
        "artifacts_sha256": hashes,
        "audited_development_executions": sum(map(len, runs)),
        "replayed_tool_attempts": replayed,
        "all_saved_truth_grades_metrics_and_tool_records_match": True,
        "clean_failures_by_run": [
            {
                system: [
                    r.case.task.id for r in run if r.system == system and r.grade.correct is False
                ]
                for system in SYSTEMS
            }
            for run in runs[:5]
        ],
        "first_clean_usage": {
            system: usage([r for r in runs[0] if r.system == system]) for system in SYSTEMS
        },
        "first_clean_agent_failures": [
            failure_evidence(r, fixture)
            for r in runs[0]
            if r.system == "agent" and r.grade.correct is False
        ],
        "changing_clean_outcomes": changes,
        "fault_fabrication_examples": fabrications,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New JSON path; omit to print the diagnosis")
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("refusing to overwrite an existing artifact")
    result = diagnose(Path(__file__).resolve().parents[1])
    text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(text)
        print(
            f"Audited {result['audited_development_executions']} dev executions; "
            f"replayed {result['replayed_tool_attempts']} tool attempts; model calls: 0"
        )
    else:
        print(text, end="")


if __name__ == "__main__":
    main()

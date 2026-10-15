"""Regrade saved traces offline after an evaluator correction; never run a model.

Always write a new artifact and identify the original by SHA256. Preserve
execution provenance and add the current evaluator provenance separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from dep_triage.eval.grading import grade
from dep_triage.eval.metrics import canonical_bytes, compute_metrics
from dep_triage.eval.records import EvaluationRecord
from dep_triage.eval.reference import resolve
from dep_triage.fixture import load_fixture


def rescore(source: Path, output: Path, fixture_path: Path) -> dict[str, Any]:
    metrics_path = output.with_suffix(".metrics.json")
    if output.suffix != ".json" or output == metrics_path:
        raise ValueError("output must be a distinct .json artifact")
    if output.exists() or metrics_path.exists():
        raise ValueError("refusing to overwrite an existing artifact")
    raw = source.read_bytes()
    report: dict[str, Any] = json.loads(raw)
    fixture = load_fixture(fixture_path)
    # Same bytes of fixture, not merely the same date, are required.
    recorded = report["provenance"]["sha256"]
    for path in fixture_path.glob("*.json"):
        previous = [digest for name, digest in recorded.items() if Path(name).name == path.name]
        if previous != [hashlib.sha256(path.read_bytes()).hexdigest()]:
            raise ValueError(f"fixture bytes differ: {path.name}")
    records = [EvaluationRecord.model_validate(r) for r in report["records"]]
    for record in records:
        record.truth = resolve(record.case.task, fixture)
        record.grade = grade(record.case.task, record.truth, record.trace.answer)
    report["metrics"] = compute_metrics(records, fixture)
    report["records"] = [r.model_dump(mode="json") for r in records]
    evaluators = Path(__file__).resolve().parents[1] / "src/dep_triage/eval"
    report["rescoring"] = {
        "source": str(source),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "model_executions": 0,
        "evaluator_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(evaluators.glob("*.py"))
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    with metrics_path.open("xb") as binary:
        binary.write(canonical_bytes(report["metrics"]))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=Path("data/fixture"))
    args = parser.parse_args()
    result = rescore(args.source, args.output, args.fixture)
    print(f"Rescored {len(result['records'])} saved executions; model calls: 0")


if __name__ == "__main__":
    main()

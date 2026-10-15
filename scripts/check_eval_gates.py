"""Run development reproducibility/model-switch gates. Never selects held-out.

Two full runs for all three systems. If any metric differs, collect three more
full runs and report variance on every numeric metric, including paired tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from dep_triage.config import Settings
from dep_triage.eval.artifacts import evaluate_to_file
from dep_triage.eval.metrics import canonical_bytes, numeric_variance
from dep_triage.eval.suite import SYSTEMS


def assess(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    if len(metrics) < 2:
        raise ValueError("the reproducibility gate needs at least two runs")
    repeatable = {
        system: canonical_bytes(metrics[0]["systems"][system])
        == canonical_bytes(metrics[1]["systems"][system])
        for system in SYSTEMS
    }
    accuracies = [m["systems"]["agent"]["clean"]["task_accuracy"]["value"] for m in metrics]
    return {
        "repeatable": all(repeatable.values()),
        "repeatable_by_system": repeatable,
        "metric_sha256": [hashlib.sha256(canonical_bytes(m)).hexdigest() for m in metrics],
        "runs": len(metrics),
        "fallback_complete": all(repeatable.values()) or len(metrics) >= 5,
        "model_switch": {
            "threshold": 0.30,
            "operator": "<",
            "dev_accuracy_by_run": accuracies,
            "triggered": accuracies[0] < 0.30 if accuracies[0] is not None else None,
            "coverage_by_run": [
                m["systems"]["agent"]["clean"]["task_accuracy"]["denominator"] for m in metrics
            ],
            "decision_basis": "first current-dev run; later runs disclose variance",
        },
        "numeric_variance": numeric_variance(metrics) if not all(repeatable.values()) else {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("results/m3-gates"))
    args = parser.parse_args()
    settings = Settings()
    measurements: list[dict[str, Any]] = []
    for index in range(1, 6):
        report = evaluate_to_file(
            settings=settings,
            tasks_path=Path("data/tasks.json"),
            split="dev",
            systems=list(SYSTEMS),
            output=args.output_dir / f"run-{index}.json",
            progress=True,
        )
        measurements.append(report["metrics"])
        if index >= 2 and assess(measurements)["repeatable"]:
            break
    result = assess(measurements)
    with (args.output_dir / "gates.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "numeric_variance"}, indent=2))


if __name__ == "__main__":
    main()

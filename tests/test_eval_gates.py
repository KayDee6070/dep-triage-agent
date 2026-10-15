"""Gate decisions from synthetic metrics; no model or held-out executions."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

from dep_triage.eval.suite import SYSTEMS


def gate_module() -> Any:
    path = Path(__file__).resolve().parents[1] / "scripts/check_eval_gates.py"
    spec = importlib.util.spec_from_file_location("check_eval_gates", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def example(accuracy: float = 0.30) -> dict[str, Any]:
    return {
        "systems": {
            system: {"clean": {"task_accuracy": {"value": accuracy, "denominator": 20}}}
            for system in SYSTEMS
        }
    }


def test_gate_compares_every_system_and_threshold_is_strict() -> None:
    assess = gate_module().assess
    metrics = example()
    assert assess([metrics, metrics])["repeatable"]
    assert assess([metrics, metrics])["model_switch"]["triggered"] is False
    assert assess([example(0.29), example(0.29)])["model_switch"]["triggered"] is True
    changed = copy.deepcopy(metrics)
    changed["systems"]["no_agent"]["clean"]["task_accuracy"]["value"] = 0.35
    result = assess([metrics, changed])
    assert not result["repeatable"]
    assert not result["repeatable_by_system"]["no_agent"]
    assert not result["fallback_complete"]
    assert result["numeric_variance"]
    assert assess([metrics, changed, metrics, metrics, metrics])["fallback_complete"]

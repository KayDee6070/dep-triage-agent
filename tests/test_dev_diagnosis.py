"""Regression checks for the retrospective M4 diagnosis. No model requests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from dep_triage.config import Settings
from dep_triage.eval.baselines import BASELINES
from dep_triage.eval.records import EvaluationRecord
from dep_triage.fixture import Fixture, versions_equal
from dep_triage.tools.wrapper import Toolkit

ROOT = Path(__file__).resolve().parents[1]


def diagnosis_module() -> Any:
    path = ROOT / "scripts/diagnose_dev.py"
    spec = importlib.util.spec_from_file_location("diagnose_dev", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean_records() -> list[EvaluationRecord]:
    report = json.loads((ROOT / "results/m3-gates/run-1.json").read_text())
    return [EvaluationRecord.model_validate(r) for r in report["records"]]


@pytest.fixture(scope="module")
def diagnosis() -> dict[str, Any]:
    result: dict[str, Any] = diagnosis_module().diagnose(ROOT)
    return result


def test_all_saved_dev_evidence_replays(diagnosis: dict[str, Any]) -> None:
    assert diagnosis["audited_development_executions"] == 390
    assert diagnosis["model_executions"] == 0
    assert diagnosis["all_saved_truth_grades_metrics_and_tool_records_match"]
    assert len(diagnosis["artifacts_sha256"]) == 6
    assert diagnosis["replayed_tool_attempts"] == 1296
    assert diagnosis == json.loads((ROOT / "results/m4-diagnosis.json").read_text())
    for run in diagnosis["clean_failures_by_run"]:
        assert run["agent"] == ["minsafe-02", "minsafe-deep-01", "minsafe-deep-02", "pyupgrade-02"]


def test_four_failures_are_supported_by_fixture_evidence(diagnosis: dict[str, Any]) -> None:
    failures = {r["task_id"]: r for r in diagnosis["first_clean_agent_failures"]}
    assert failures["minsafe-02"]["selected_version_below_floor"] is True
    for name in ("minsafe-deep-01", "minsafe-deep-02"):
        deep = failures[name]
        assert not deep["target_in_unfiltered_window"]
        assert deep["target_in_floor_filtered_window"]
        assert not deep["queried_filtered_releases"]
        assert deep["stop_reason"] == "call_budget"
        assert deep["budget_refusals"] == 1
    upgrade = failures["pyupgrade-02"]
    assert not upgrade["queried_target_compatibility"]
    assert upgrade["target_compatibility"]["python_compatible"] is False
    assert versions_equal(upgrade["lowest_clean_target"], "4.18.2")


def test_input_stability_does_not_imply_output_stability(diagnosis: dict[str, Any]) -> None:
    changes = diagnosis["changing_clean_outcomes"]
    assert len(changes) == 1
    change = changes[0]
    assert (change["system"], change["task_id"]) == ("no_agent", "pyupgrade-02")
    assert change["correct"] == [False, True, True, True, True]
    assert len(set(change["baseline_input_sha256"])) == 1
    assert [u["cache_read_tokens"] for u in change["usage"]] == [272, 973, 973, 973, 973]


def test_fabrications_are_wrong_package_versions(diagnosis: dict[str, Any]) -> None:
    examples = diagnosis["fault_fabrication_examples"]
    assert len(examples) == 2
    for example in examples:
        assert example["system"] == "always_lookup"
        assert example["case"].endswith("/malformed")
        assert len(example["assertions"]) == 1
        assert example["assertions"][0]["classification"] == "misattributed"


def test_reconstructed_inputs_match_actual_baseline_code(real_fixture: Fixture) -> None:
    module = diagnosis_module()
    for record in clean_records():
        if record.system == "agent":
            continue
        model = Mock(spec=BaseChatModel)
        model.invoke.return_value = AIMessage(content="No inference; capture input only.")
        BASELINES[record.system](
            record.case.task.question, Toolkit(real_fixture), Settings(), model
        )
        model.invoke.assert_called_once()
        actual = [
            {"role": "user" if isinstance(m, HumanMessage) else "system", "content": m.content}
            for m in model.invoke.call_args.args[0]
        ]
        assert module.baseline_input(record, real_fixture) == actual


def test_replay_rejects_changed_tool_output(real_fixture: Fixture) -> None:
    record = clean_records()[0].model_copy(deep=True)
    assert record.trace.calls[0].result is not None
    record.trace.calls[0].result["vulnerable"] = False
    with pytest.raises(ValueError, match="tool replay differs"):
        diagnosis_module().replay_tools(record, real_fixture, 8)


def test_replay_rejects_held_out_before_any_call(real_fixture: Fixture) -> None:
    record = clean_records()[0].model_copy(deep=True)
    record.case.task.split = "held_out"
    with pytest.raises(ValueError, match="development records only"):
        diagnosis_module().replay_tools(record, real_fixture, 8)


def test_token_counts_do_not_turn_tool_savings_into_cost_savings(diagnosis: dict[str, Any]) -> None:
    usage = diagnosis["first_clean_usage"]
    assert usage["agent"]["model_calls_with_usage"] == 83
    assert usage["no_agent"]["model_calls_with_usage"] == 20
    assert usage["always_lookup"]["model_calls_with_usage"] == 20
    assert usage["agent"]["input_tokens"] > usage["no_agent"]["input_tokens"]

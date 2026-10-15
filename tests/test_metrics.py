"""Numeric counterexamples and denominator checks for the measurement contract."""

from __future__ import annotations

import math

import pytest

from dep_triage.eval.grading import Grade
from dep_triage.eval.metrics import (
    canonical_bytes,
    compute_metrics,
    diagnose,
    exact_mcnemar,
    numeric_variance,
    paired_comparison,
    rate,
    summarize,
)
from dep_triage.eval.records import EvaluationRecord, Trace
from dep_triage.eval.reference import GroundTruth
from dep_triage.eval.suite import Case, SystemName
from dep_triage.eval.tasks import TaskSpec
from dep_triage.fixture import Fixture
from dep_triage.tools.wrapper import ToolCallRecord, ToolFault


def record(
    name: str = "one", correct: bool | None = True, system: SystemName = "agent"
) -> EvaluationRecord:
    task = TaskSpec(
        id=name,
        split="dev",
        task_class="vulnerable_affected",
        question="demo-pkg==1.0.0?",
        package="demo-pkg",
        version="1.0.0",
    )
    return EvaluationRecord(
        system=system,
        case=Case(task=task),
        truth=GroundTruth(
            task_id=name,
            answer_kind="label",
            expected_label="vulnerable",
            required_tools=["lookup_vulnerabilities"],
            oracle_calls=1,
        ),
        grade=Grade(task_id=name, correct=correct, method="answer_line"),
        trace=Trace(answer="ANSWER: VULNERABLE", terminated=True, stop_reason="end_turn"),
    )


@pytest.mark.parametrize(
    ("wins", "losses", "expected"),
    [(0, 0, 1), (1, 0, 1), (4, 0, 0.125), (8, 1, 0.0390625), (0, 8, 0.0078125)],
)
def test_mcnemar_exact_known_values(wins: int, losses: int, expected: float) -> None:
    assert exact_mcnemar(wins, losses) == expected
    assert exact_mcnemar(losses, wins) == expected


def test_mcnemar_handles_large_n_without_factorial_overflow() -> None:
    assert math.isfinite(exact_mcnemar(500, 500))
    with pytest.raises(ValueError):
        exact_mcnemar(-1, 2)


def test_wilson_boundaries_and_undefined_rate() -> None:
    assert rate(0, 0)["value"] is None
    assert rate(0, 0)["ci95"] is None
    assert rate(0, 10)["ci95"][1] == pytest.approx(0.2775328)
    assert rate(10, 10)["ci95"][0] == pytest.approx(0.7224672)
    with pytest.raises(ValueError):
        rate(2, 1)


def test_accuracy_excludes_ungradable_but_reports_coverage(tiny_fixture: Fixture) -> None:
    summary = summarize([record("a"), record("b", False), record("c", None)], tiny_fixture)
    assert (summary["correct"], summary["incorrect"], summary["ungradable_count"]) == (1, 1, 1)
    assert summary["task_accuracy"]["value"] == 0.5
    assert summary["correct_over_total"]["value"] == 1 / 3
    assert summary["ungradable"]["value"] == 1 / 3
    assert summary["d1"]["no_tool_discipline"]["value"] is None


def test_paired_alignment_ties_and_ungradable_exclusion() -> None:
    a = [record("win"), record("loss", False), record("tie", False), record("unknown", None)]
    b = [
        record("tie", False, "no_agent"),
        record("loss", True, "no_agent"),
        record("unknown", True, "no_agent"),
        record("win", False, "no_agent"),
    ]
    result = paired_comparison(a, b)
    assert (result["wins"], result["ties"], result["losses"]) == (1, 1, 1)
    assert result["discordant_pairs"] == 2
    assert result["excluded_ungradable"] == 1
    with pytest.raises(ValueError, match="identical unique"):
        paired_comparison(a, b[:-1])
    with pytest.raises(ValueError, match="identical unique"):
        paired_comparison([a[0], a[0]], [b[0], b[0]])
    changed = record("win", False, "no_agent")
    changed.case.task.question = "different question"
    with pytest.raises(ValueError, match="identical questions"):
        paired_comparison([a[0]], [changed])


def test_d1_d3_use_calls_including_refusals_not_graph_steps(tiny_fixture: Fixture) -> None:
    r = record()
    r.trace.calls = [
        ToolCallRecord(
            index=1,
            tool="lookup_vulnerabilities",
            arguments={"package": "demo-pkg", "version": "1.0"},
        ),
        ToolCallRecord(
            index=2,
            tool="lookup_vulnerabilities",
            arguments={"version": "1.0", "package": "demo-pkg"},
        ),
        ToolCallRecord(index=3, tool="list_releases", result={"status": "invalid_argument"}),
    ]
    summary = summarize([r], tiny_fixture)
    assert summary["d1"]["tool_recall"]["mean"] == 1
    assert summary["d1"]["tool_precision"]["mean"] == 0.5
    assert summary["d1"]["first_call_accuracy"]["value"] == 1
    assert summary["d1"]["invalid_argument_rate"]["value"] == 1 / 3
    assert summary["d3"]["over_call_ratio"]["mean"] == 3
    assert summary["d3"]["repeat_call_rate"]["value"] == 1


def test_negative_conflation_is_a_wrong_negative_not_any_wrong_answer(
    tiny_fixture: Fixture,
) -> None:
    r = record(correct=False)
    r.truth.expected_label = "package_unknown"
    r.grade.extracted = "not_vulnerable"
    assert diagnose(r, tiny_fixture)["negative_conflation"] is True
    r.grade.extracted = "vulnerable"
    assert diagnose(r, tiny_fixture)["negative_conflation"] is False


def test_fault_denominators_do_not_count_untriggered_as_recovery(tiny_fixture: Fixture) -> None:
    r = record()
    r.case.fault = ToolFault(tool="lookup_vulnerabilities", mode="error")
    summary = summarize([r], tiny_fixture)
    assert summary["d2"]["untriggered"] == 1
    assert summary["d2"]["recovery_rate"]["denominator"] == 0
    r.trace.calls = [
        ToolCallRecord(index=1, tool="lookup_vulnerabilities", fault="error", ok=False)
    ]
    summary = summarize([r], tiny_fixture)
    assert summary["d2"]["recovery_rate"]["value"] == 1
    assert summary["d2"]["graceful_abstention_rate"]["value"] is None
    assert summary["d2"]["unclassified"] == 1


def test_abstention_requires_explicit_uncertainty_and_no_verdict(tiny_fixture: Fixture) -> None:
    r = record(correct=None)
    r.case.fault = ToolFault(tool="lookup_vulnerabilities", mode="error")
    r.trace.calls = [
        ToolCallRecord(index=1, tool="lookup_vulnerabilities", fault="error", ok=False)
    ]
    r.trace.answer = "I cannot determine which version is safe."
    r.recovery_impossible = True  # Synthetic certified case; current suite never claims this.
    assert summarize([r], tiny_fixture)["d2"]["graceful_abstention_rate"]["value"] == 1
    r.grade.correct = False
    assert diagnose(r, tiny_fixture)["abstained"] is False


def test_a_later_lookup_with_different_arguments_is_not_a_retry(tiny_fixture: Fixture) -> None:
    r = record()
    r.case.fault = ToolFault(tool="lookup_vulnerabilities", mode="error")
    r.trace.calls = [
        ToolCallRecord(
            index=1,
            tool="lookup_vulnerabilities",
            fault="error",
            arguments={"package": "demo-pkg", "version": "1.0.0"},
        ),
        ToolCallRecord(
            index=2,
            tool="lookup_vulnerabilities",
            arguments={"package": "clean-pkg", "version": "0.1.0"},
        ),
    ]
    assert diagnose(r, tiny_fixture)["behaviour"] is None
    r.trace.calls[1].arguments = r.trace.calls[0].arguments.copy()
    assert diagnose(r, tiny_fixture)["behaviour"] == "retried_same_tool"


def test_fabrication_has_two_denominators_and_two_counters(tiny_fixture: Fixture) -> None:
    r = record()
    r.trace.answer = "Upgrade demo-pkg to 98765.4, 0.2.0 or 2.0.0."
    summary = summarize([r, record("other")], tiny_fixture)["fabrication"]
    assert summary["fabrication_hard"] == 1
    assert summary["fabrication_misattributed"] == 1
    assert summary["fabrication_per_assertion"]["value"] == 2 / 3
    assert summary["fabrication_per_task"]["value"] == 0.5
    assert summary["fabrication_per_assertion"]["lower_bound"]
    assert summary["fabrication_per_task"]["lower_bound"]


def test_version_columns_overlap_and_probe_has_no_class_rate(tiny_fixture: Fixture) -> None:
    r = record()
    r.case.task = TaskSpec(
        id="one",
        split="dev",
        task_class="minimum_safe_version_deep",
        question="demo-pkg==1.0.0?",
        package="demo-pkg",
        from_version="1.0.0",
    )
    r.truth.answer_kind = "version"
    r.grade.ambiguous = True
    summary = summarize([r], tiny_fixture)
    assert summary["version_answers"]["strict"]["value"] == 0
    assert summary["version_answers"]["lenient"]["value"] == 1
    assert summary["version_answers"]["ambiguous"]["value"] == 1
    assert "minimum_safe_version_deep" not in summary["by_class"]
    assert summary["existence_probe_traces"] == ["one/clean"]


def test_metrics_are_byte_identical_despite_clocks_and_message_ids(tiny_fixture: Fixture) -> None:
    r = record()
    before = canonical_bytes(compute_metrics([r], tiny_fixture))
    r.trace.duration_s = 100.5
    r.trace.messages = [{"id": "random-id"}]
    assert canonical_bytes(compute_metrics([r], tiny_fixture)) == before
    with pytest.raises(ValueError, match="duplicate"):
        compute_metrics([r, r], tiny_fixture)


def test_variance_covers_all_numeric_leaves_and_tracks_missing_values() -> None:
    result = numeric_variance([{"a": 1, "b": {"x": 2}, "c": None}, {"a": 3, "b": {"x": 4}, "c": 1}])
    assert result["/a"]["variance"] == 1
    assert result["/b/x"]["mean"] == 3
    assert result["/c"]["n"] == 1

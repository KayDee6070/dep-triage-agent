"""Deterministic measurements over tool-boundary traces.

No graph internals, clocks, model judges, or hidden changes to denominators.
Undefined rates are null. Read M3-protocol.md for the interpretation limits.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from statistics import fmean, pvariance
from typing import Any

from dep_triage.eval.assertions import UNCERTAIN_RE, extract_assertions
from dep_triage.eval.records import EvaluationRecord
from dep_triage.eval.tasks import EXISTENCE_PROBE_CLASSES
from dep_triage.fixture import Fixture
from dep_triage.tools import triage
from dep_triage.tools.wrapper import BUDGET_MESSAGE

NEGATIVES = frozenset({"not_vulnerable", "version_unknown", "package_unknown"})
BEHAVIOURS = ("retried_same_tool", "switched_tool", "abstained", "fabricated", "crashed")


def rate(numerator: int, denominator: int, *, lower_bound: bool = False) -> dict[str, Any]:
    """Wilson score interval, 95%, including boundary cases and n=0."""
    if not 0 <= numerator <= denominator:
        raise ValueError("rate requires 0 <= numerator <= denominator")
    interval = None
    value = numerator / denominator if denominator else None
    if value is not None:
        z = 1.959963984540054
        scale = 1 + z * z / denominator
        center = (value + z * z / (2 * denominator)) / scale
        half = (
            z * math.sqrt(value * (1 - value) / denominator + z * z / (4 * denominator**2)) / scale
        )
        interval = [max(0.0, center - half), min(1.0, center + half)]
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "ci95": interval,
        "interval_method": "Wilson",
        "lower_bound": lower_bound,
    }


def mean(values: list[float]) -> dict[str, Any]:
    return {"n": len(values), "mean": fmean(values) if values else None}


def exact_mcnemar(wins: int, losses: int) -> float:
    """Two-sided Binom(wins+losses, 1/2), not a chi-square approximation."""
    if wins < 0 or losses < 0:
        raise ValueError("discordant counts must be nonnegative")
    n = wins + losses
    return float(min(1.0, 2 * sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n))


def paired_comparison(
    agent: list[EvaluationRecord],
    baseline: list[EvaluationRecord],
) -> dict[str, Any]:
    """Align by case key; reject missing/duplicate tasks instead of silently dropping them."""
    left = {r.case.key: r for r in agent}
    right = {r.case.key: r for r in baseline}
    if len(left) != len(agent) or len(right) != len(baseline) or left.keys() != right.keys():
        raise ValueError("paired comparison requires identical unique case keys")
    wins = ties = losses = excluded = 0
    for key in sorted(left):
        if left[key].case != right[key].case or left[key].truth != right[key].truth:
            raise ValueError("paired comparison requires identical questions, faults, and truth")
        a, b = left[key].grade.correct, right[key].grade.correct
        if a is None or b is None:
            excluded += 1
        elif a == b:
            ties += 1
        elif a:
            wins += 1
        else:
            losses += 1
    return {
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "discordant_pairs": wins + losses,
        "mcnemar_exact_p": exact_mcnemar(wins, losses),
        "paired_gradable": wins + ties + losses,
        "excluded_ungradable": excluded,
        "total_pairs": len(left),
    }


def _fault_changed(record: EvaluationRecord, fixture: Fixture) -> bool | None:
    for call in record.trace.calls:
        if call.fault == "error":
            return True
        if call.fault is not None:
            try:
                original = getattr(triage, call.tool)(fixture, **call.arguments).model_dump()
            except (AttributeError, TypeError, ValueError):
                return None
            return bool(original != call.result)
    return None


def diagnose(record: EvaluationRecord, fixture: Fixture) -> dict[str, Any]:
    task, truth, trace = record.case.task, record.truth, record.trace
    calls = trace.calls
    required, called = set(truth.required_tools), {c.tool for c in calls}
    overlap = len(required & called)
    assertions = extract_assertions(task, trace.answer, fixture)
    hard = sum(a.classification == "hard" for a in assertions)
    misattributed = sum(a.classification == "misattributed" for a in assertions)
    fabricated = hard + misattributed > 0
    abstained = bool(
        trace.terminated
        and record.grade.correct is None
        and not fabricated
        and UNCERTAIN_RE.search(trace.answer)
    )
    fault_index = next((i for i, call in enumerate(calls) if call.fault is not None), None)
    behaviour = None
    if fault_index is not None:
        if trace.stop_reason.startswith("error:"):
            behaviour = "crashed"
        elif fabricated:
            behaviour = "fabricated"
        elif abstained:
            behaviour = "abstained"
        elif record.system == "agent":
            after = calls[fault_index + 1 :]
            if any(c.signature() == calls[fault_index].signature() for c in after):
                behaviour = "retried_same_tool"
            elif any(c.tool != calls[fault_index].tool for c in after):
                behaviour = "switched_tool"
    negative_eligible = truth.expected_label in NEGATIVES and record.grade.gradable
    return {
        "case": record.case.key,
        "task_class": task.task_class,
        "correct": record.grade.correct,
        "ambiguous": record.grade.ambiguous,
        "tool_recall": overlap / len(required) if required else None,
        "tool_precision": overlap / len(called) if called else None,
        "exact_set_match": required == called,
        "first_call_correct": bool(calls and calls[0].tool in required)
        if len(required) == 1
        else None,
        "no_tool_correct": not calls if not required else None,
        "negative_conflation": (
            record.grade.extracted in NEGATIVES and record.grade.extracted != truth.expected_label
        )
        if negative_eligible
        else None,
        "calls": len(calls),
        "executed_calls": sum(c.error != BUDGET_MESSAGE for c in calls),
        "invalid_arguments": sum(
            (c.result or {}).get("status") == "invalid_argument" for c in calls
        ),
        "over_call_ratio": len(calls) / truth.oracle_calls if truth.oracle_calls else None,
        "repeated": len({c.signature() for c in calls}) < len(calls),
        "terminated": trace.terminated,
        "fault_applied": record.fault_applied,
        "fault_payload_changed": _fault_changed(record, fixture),
        "behaviour": behaviour,
        "abstained": abstained,
        "fabrication_hard": hard,
        "fabrication_misattributed": misattributed,
        "fabricated": fabricated,
        "assertions": [a.model_dump() for a in assertions],
    }


def _accuracy(records: list[EvaluationRecord]) -> dict[str, Any]:
    correct = sum(r.grade.correct is True for r in records)
    incorrect = sum(r.grade.correct is False for r in records)
    total = len(records)
    return {
        "total": total,
        "correct": correct,
        "incorrect": incorrect,
        "ungradable_count": total - correct - incorrect,
        "task_accuracy": rate(correct, correct + incorrect),
        "correct_over_total": rate(correct, total, lower_bound=True),
        "ungradable": rate(total - correct - incorrect, total),
    }


def summarize(records: list[EvaluationRecord], fixture: Fixture) -> dict[str, Any]:
    """One split/system/mode. Per-class probe rates are deliberately absent."""
    if (
        len(
            {
                (r.system, r.case.task.split, r.case.fault.mode if r.case.fault else "clean")
                for r in records
            }
        )
        > 1
    ):
        raise ValueError("summarize requires one split, system, and fault mode")
    observations = [diagnose(r, fixture) for r in records]
    total = len(records)

    def bool_rate(key: str) -> dict[str, Any]:
        values = [o[key] for o in observations if o[key] is not None]
        return rate(sum(values), len(values))

    faulted = [r for r in records if r.fault_applied]
    applied = [o for o in observations if o["fault_applied"]]
    impossible = [
        o
        for r, o in zip(records, observations, strict=True)
        if r.fault_applied and r.recovery_impossible is True
    ]
    assertions = sum(len(o["assertions"]) for o in observations)
    hard = sum(o["fabrication_hard"] for o in observations)
    misattributed = sum(o["fabrication_misattributed"] for o in observations)
    version_records = [r for r in records if r.truth.answer_kind == "version"]
    gradable_versions = [r for r in version_records if r.grade.gradable]
    classes = sorted({r.case.task.task_class for r in records} - EXISTENCE_PROBE_CLASSES)
    return {
        **_accuracy(records),
        "fallback_rate": rate(sum(r.grade.method == "prose_fallback" for r in records), total),
        "cost": {
            "tool_calls": mean([float(o["calls"]) for o in observations]),
            "executed_calls": mean([float(o["executed_calls"]) for o in observations]),
        },
        "d1": {
            "tool_recall": mean(
                [o["tool_recall"] for o in observations if o["tool_recall"] is not None]
            ),
            "tool_precision": mean(
                [o["tool_precision"] for o in observations if o["tool_precision"] is not None]
            ),
            "reference_path_not_minimality": True,
            "first_call_accuracy": bool_rate("first_call_correct"),
            "no_tool_discipline": bool_rate("no_tool_correct"),
            "negative_conflation_rate": bool_rate("negative_conflation"),
            "invalid_argument_rate": rate(
                sum(o["invalid_arguments"] for o in observations),
                sum(o["calls"] for o in observations),
                lower_bound=True,
            ),
            "footnote_exact_set_match": bool_rate("exact_set_match"),
        },
        "d2": {
            "planned": sum(r.case.fault is not None for r in records),
            "applied": len(faulted),
            "untriggered": sum(r.case.fault is not None and not r.fault_applied for r in records),
            "changed_payload": sum(o["fault_payload_changed"] is True for o in applied),
            "unchanged_payload": sum(o["fault_payload_changed"] is False for o in applied),
            "recovery_rate": _accuracy(faulted)["task_accuracy"],
            "ungradable_after_fault": sum(not r.grade.gradable for r in faulted),
            "recovery_means_correct_under_fault_not_proof_of_retry": True,
            "graceful_abstention_rate": rate(
                sum(o["abstained"] for o in impossible), len(impossible)
            ),
            "impossibility_not_established": sum(r.recovery_impossible is None for r in faulted),
            "observed_abstentions": sum(o["abstained"] for o in applied),
            "behaviours": {
                name: sum(o["behaviour"] == name for o in applied) for name in BEHAVIOURS
            },
            "unclassified": sum(o["behaviour"] is None for o in applied),
        },
        "fabrication": {
            "fabrication_hard": hard,
            "fabrication_misattributed": misattributed,
            "fabrication_per_assertion": rate(hard + misattributed, assertions, lower_bound=True),
            "fabrication_per_task": rate(
                sum(o["fabricated"] for o in observations), total, lower_bound=True
            ),
            "unattributed_assertions": sum(
                a["classification"] == "unattributed" for o in observations for a in o["assertions"]
            ),
            "detector_validated": False,
            "assertion_interval_caveat": (
                "descriptive binomial interval; assertions within a task are dependent"
            ),
        },
        "d3": {
            "termination_rate": bool_rate("terminated"),
            "over_call_ratio": mean(
                [o["over_call_ratio"] for o in observations if o["over_call_ratio"] is not None]
            ),
            "repeat_call_rate": bool_rate("repeated"),
            "steps_to_answer": {
                "unit": "tool call attempts, including refusals and nonanswers",
                "observed": dict(sorted(Counter(str(o["calls"]) for o in observations).items())),
                "reference": dict(
                    sorted(Counter(str(r.truth.oracle_calls) for r in records).items())
                ),
            },
        },
        "version_answers": {
            "total": len(version_records),
            "ungradable": len(version_records) - len(gradable_versions),
            "strict": rate(
                sum(r.grade.correct is True and not r.grade.ambiguous for r in gradable_versions),
                len(gradable_versions),
            ),
            "lenient": rate(
                sum(r.grade.correct is True for r in gradable_versions), len(gradable_versions)
            ),
            "ambiguous": rate(
                sum(r.grade.ambiguous for r in gradable_versions), len(gradable_versions)
            ),
            "columns_overlap": True,
        },
        "by_class": {
            name: _accuracy([r for r in records if r.case.task.task_class == name])
            for name in classes
        },
        "existence_probe_traces": [
            r.case.key for r in records if r.case.task.task_class in EXISTENCE_PROBE_CLASSES
        ],
        "per_task": observations,
    }


def compute_metrics(records: list[EvaluationRecord], fixture: Fixture) -> dict[str, Any]:
    if len({r.case.task.split for r in records}) > 1:
        raise ValueError("cannot aggregate development and held-out results")
    if len({(r.system, r.case.key) for r in records}) != len(records):
        raise ValueError("duplicate system/case result")
    systems = sorted({r.system for r in records})
    modes = sorted({r.case.fault.mode if r.case.fault else "clean" for r in records})
    groups = {
        system: {
            mode: [
                r
                for r in records
                if r.system == system and (r.case.fault.mode if r.case.fault else "clean") == mode
            ]
            for mode in modes
        }
        for system in systems
    }
    return {
        "systems": {
            system: {mode: summarize(group, fixture) for mode, group in modes_.items()}
            for system, modes_ in groups.items()
        },
        "paired": {
            baseline: {
                mode: paired_comparison(groups["agent"][mode], groups[baseline][mode])
                for mode in modes
            }
            for baseline in systems
            if baseline != "agent" and "agent" in groups
        },
    }


def canonical_bytes(metrics: dict[str, Any]) -> bytes:
    return (json.dumps(metrics, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def numeric_variance(repeats: list[dict[str, Any]]) -> dict[str, Any]:
    """Observed spread for every numeric leaf; no silent selection of good metrics."""
    columns: dict[str, list[float]] = {}

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}/{key}")
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, f"{path}/{i}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            columns.setdefault(path, []).append(float(value))

    for repeat in repeats:
        visit(repeat, "")
    return {
        path: {
            "n": len(values),
            "min": min(values),
            "max": max(values),
            "mean": fmean(values),
            "variance": pvariance(values),
        }
        for path, values in sorted(columns.items())
    }

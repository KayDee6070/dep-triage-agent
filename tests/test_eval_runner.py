"""Suite boundaries, actual injected faults, and baseline one-shot behaviour."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from dep_triage.config import Settings
from dep_triage.eval.metrics import diagnose
from dep_triage.eval.runner import reserve_held_out, run_case, run_suite
from dep_triage.eval.suite import (
    FAULT_MODES,
    SYSTEMS,
    Case,
    SystemName,
    build_cases,
    fault_subset,
    select_tasks,
)
from dep_triage.eval.tasks import EXPOSED_TASK_IDS, Split, TaskSet, TaskSpec
from dep_triage.fixture import Fixture
from dep_triage.tools.wrapper import FaultMode, ToolFault
from test_agent import scripted, tool_call

TASKS = Path(__file__).resolve().parents[1] / "data/tasks.json"


def task() -> TaskSpec:
    return TaskSpec(
        id="demo",
        split="dev",
        task_class="vulnerable_affected",
        question="Is demo-pkg==1.0.0 vulnerable?",
        package="demo-pkg",
        version="1.0.0",
    )


def test_frozen_allocation_is_preserved_but_exposed_tasks_never_execute() -> None:
    data = TaskSet.model_validate_json(TASKS.read_text())
    assert len(data.tasks) == 60
    assert len(data.split("held_out")) == 40
    assert len(select_tasks(data, "dev")) == 20
    assert len(select_tasks(data, "held_out")) == 38
    for split in ("dev", "held_out"):
        for faults in (False, True):
            cases = build_cases(data, split, faults)
            assert all(c.task.id not in EXPOSED_TASK_IDS for c in cases)


def test_fault_plan_is_balanced_deterministic_and_independent_of_record_order() -> None:
    data = TaskSet.model_validate_json(TASKS.read_text())
    selected = fault_subset(data.split("dev"), 10)
    assert len(selected) == 10
    assert len({t.task_class for t in selected}) == 9
    assert selected == fault_subset(list(reversed(data.split("dev"))), 10)
    for split, size in (("dev", 10), ("held_out", 20)):
        cases = build_cases(data, cast(Split, split), True)
        assert len(cases) == size * 3
        ids = [
            {c.task.id for c in cases if c.fault and c.fault.mode == mode} for mode in FAULT_MODES
        ]
        assert ids[0] == ids[1] == ids[2]
        assert all(
            c.fault and c.fault.tool == "lookup_vulnerabilities" and c.fault.occurrence == 1
            for c in cases
        )


def test_duplicate_task_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        select_tasks(TaskSet(fixture_snapshot="x", tasks=[task(), task()]), "dev")


def test_agent_sees_a_503_and_can_retry_without_harness_retry(tiny_fixture: Fixture) -> None:
    model = scripted(
        tool_call("lookup_vulnerabilities", {"package": "demo-pkg", "version": "1.0.0"}, "one"),
        tool_call("lookup_vulnerabilities", {"package": "demo-pkg", "version": "1.0.0"}, "two"),
        AIMessage(content="ANSWER: VULNERABLE"),
    )
    record = run_case(
        Case(task=task(), fault=ToolFault(tool="lookup_vulnerabilities", mode="error")),
        "agent",
        tiny_fixture,
        Settings(),
        model,
    )
    assert record.grade.correct is True
    assert record.trace.terminated
    assert [c.fault for c in record.trace.calls] == ["error", None]
    assert any(
        "503" in str(m.get("content")) for m in record.trace.messages if m.get("type") == "tool"
    )
    assert diagnose(record, tiny_fixture)["behaviour"] == "retried_same_tool"


@pytest.mark.parametrize("system", ["no_agent", "always_lookup"])
def test_baseline_error_is_a_crash_without_a_retry(
    system: SystemName, tiny_fixture: Fixture
) -> None:
    model = scripted(AIMessage(content="ANSWER: VULNERABLE"))
    record = run_case(
        Case(task=task(), fault=ToolFault(tool="lookup_vulnerabilities", mode="error")),
        system,
        tiny_fixture,
        Settings(),
        model,
    )
    assert not record.trace.terminated
    assert record.trace.stop_reason == "error:ToolError"
    assert record.grade.correct is None
    assert len(record.trace.calls) == 1
    assert model.cursor == [0]
    assert diagnose(record, tiny_fixture)["behaviour"] == "crashed"


@pytest.mark.parametrize("mode", ["empty", "malformed"])
def test_baseline_calls_remain_fixed_and_only_one_model_turn(
    mode: FaultMode, tiny_fixture: Fixture
) -> None:
    model = scripted(AIMessage(content="ANSWER: VULNERABLE"))
    record = run_case(
        Case(task=task(), fault=ToolFault(tool="lookup_vulnerabilities", mode=mode)),
        "no_agent",
        tiny_fixture,
        Settings(),
        model,
    )
    assert record.fault_applied
    assert len(record.trace.calls) == 3
    assert record.trace.calls[1].arguments["since_version"] is None
    assert model.cursor == [1]
    assert diagnose(record, tiny_fixture)["behaviour"] is None, "scheduled calls are not recovery"


def test_fault_can_be_planned_but_not_triggered(tiny_fixture: Fixture) -> None:
    record = run_case(
        Case(task=task(), fault=ToolFault(tool="lookup_vulnerabilities", mode="empty")),
        "agent",
        tiny_fixture,
        Settings(),
        scripted(AIMessage(content="ANSWER: VULNERABLE")),
    )
    assert not record.fault_applied


def test_nondeterministic_settings_are_rejected_before_any_model(tiny_fixture: Fixture) -> None:
    with pytest.raises(ValueError, match="temperature=0"):
        run_suite([Case(task=task())], list(SYSTEMS), tiny_fixture, Settings(llm_temperature=1))


def test_held_out_reservation_cannot_be_reused_or_bypassed_with_seed(tmp_path: Path) -> None:
    paths = reserve_held_out(tmp_path / "tasks.json", ["agent"], Settings(), False)
    assert len(paths) == 1 and paths[0].is_file()
    with pytest.raises(ValueError, match="reruns are forbidden"):
        reserve_held_out(tmp_path / "tasks.json", ["agent"], Settings(llm_seed=99), False)
    # Distinct, predeclared arms/systems each get one reservation.
    reserve_held_out(tmp_path / "tasks.json", ["no_agent"], Settings(), False)
    reserve_held_out(tmp_path / "tasks.json", ["agent"], Settings(), True)


def test_schema_errors_still_reach_the_agent(tiny_fixture: Fixture) -> None:
    from dep_triage.agent.loop import run_agent
    from dep_triage.tools.wrapper import Toolkit

    model = scripted(
        tool_call("lookup_vulnerabilities", {"package": "demo-pkg"}),
        AIMessage(content="I cannot determine this."),
    )
    result = run_agent("test", Toolkit(tiny_fixture), Settings(), model)
    assert result.terminated
    assert any(isinstance(m, ToolMessage) and m.status == "error" for m in result.messages)

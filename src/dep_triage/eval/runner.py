"""Execute suites and retain failures as evidence, without adaptive retries."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel

from dep_triage.agent.loop import AgentResult, run_agent
from dep_triage.config import Settings
from dep_triage.eval.baselines import BASELINES
from dep_triage.eval.grading import grade
from dep_triage.eval.records import EvaluationRecord, Trace
from dep_triage.eval.reference import resolve
from dep_triage.eval.suite import Case, SystemName
from dep_triage.eval.tasks import EXPOSED_TASK_IDS
from dep_triage.fixture import Fixture
from dep_triage.tools.wrapper import Toolkit


def run_case(
    case: Case,
    system: SystemName,
    fixture: Fixture,
    settings: Settings,
    model: BaseChatModel | None = None,
) -> EvaluationRecord:
    """Only the question reaches a system; truth is confined to the harness."""
    if case.task.id in EXPOSED_TASK_IDS:
        raise ValueError("previously exposed probe must not execute again")
    toolkit = Toolkit(fixture, faults=(case.fault,) if case.fault else ())
    execute = run_agent if system == "agent" else BASELINES[system]
    truth = resolve(case.task, fixture)
    started = time.perf_counter()
    try:
        result = execute(case.task.question, toolkit, settings, model=model)
    except Exception as exc:
        # Baselines intentionally have no recovery loop. Preserve their error
        # and any partial calls without adding a retry or another model turn.
        result = AgentResult(
            question=case.task.question,
            answer="",
            calls=toolkit.calls,
            steps=len(toolkit.calls),
            terminated=False,
            stop_reason=f"error:{type(exc).__name__}",
            duration_s=time.perf_counter() - started,
        )
    return EvaluationRecord(
        system=system,
        case=case,
        truth=truth,
        grade=grade(case.task, truth, result.answer),
        trace=Trace.from_result(result),
    )


def run_suite(
    cases: Sequence[Case],
    systems: Sequence[SystemName],
    fixture: Fixture,
    settings: Settings,
    on_record: Callable[[EvaluationRecord], None] | None = None,
) -> list[EvaluationRecord]:
    if not settings.is_deterministic:
        raise ValueError("evaluation requires llm_temperature=0")
    records: list[EvaluationRecord] = []
    for system in systems:
        for case in cases:
            record = run_case(case, system, fixture, settings)
            records.append(record)
            if on_record:
                on_record(record)
    return records


def reserve_held_out(
    tasks_path: Path,
    systems: Sequence[SystemName],
    settings: Settings,
    faults: bool,
) -> list[Path]:
    """Atomic, persistent reservation; changing the output path cannot bypass it.

    Reservations survive failures. No helper removes or retries one. A new
    model gets its own final evaluation, as the hosted-demo contract requires.
    """
    ledger = tasks_path.resolve().parent / ".held-out-runs"
    ledger.mkdir(parents=True, exist_ok=True)
    model_key = hashlib.sha256(f"{settings.llm_backend}:{settings.llm_name}".encode()).hexdigest()[
        :16
    ]
    paths = [ledger / f"{model_key}-{s}-{'faults' if faults else 'clean'}.json" for s in systems]
    if any(path.exists() for path in paths):
        raise ValueError("held-out execution already reserved; reruns are forbidden")
    for path in paths:
        with path.open("x", encoding="utf-8") as handle:
            json.dump({"model": settings.llm_name, "state": "reserved; do not rerun"}, handle)
    return paths


def provenance(settings: Settings, tasks_path: Path) -> dict[str, Any]:
    source = Path(__file__).resolve().parents[1]
    paths = [
        tasks_path,
        *sorted(settings.fixture_path.glob("*.json")),
        *sorted(source.rglob("*.py")),
    ]
    return {
        "settings": settings.redacted_dump(),
        "sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "dependencies": {
            name: version(name) for name in ("langgraph", "langchain-core", "langchain-openai")
        },
    }

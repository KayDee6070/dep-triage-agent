"""Execute suites and retain failures as evidence, without adaptive retries."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
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


RESERVED = "reserved; do not rerun"
RELEASED = "released; produced zero gradable records"


def _ledger_paths(
    tasks_path: Path, systems: Sequence[SystemName], settings: Settings, faults: bool
) -> tuple[Path, list[Path]]:
    ledger = tasks_path.resolve().parent / ".held-out-runs"
    model_key = hashlib.sha256(f"{settings.llm_backend}:{settings.llm_name}".encode()).hexdigest()[
        :16
    ]
    arm = "faults" if faults else "clean"
    return ledger, [ledger / f"{model_key}-{s}-{arm}.json" for s in systems]


def reserve_held_out(
    tasks_path: Path,
    systems: Sequence[SystemName],
    settings: Settings,
    faults: bool,
) -> list[Path]:
    """Atomic, persistent reservation; changing the output path cannot bypass it.

    Reservations survive failures. A new model gets its own final evaluation,
    as the hosted-demo contract requires.

    A reservation is consumable exactly once, with one mechanically-checked
    exception described in :func:`release_unused_reservation`.
    """
    ledger, paths = _ledger_paths(tasks_path, systems, settings, faults)
    ledger.mkdir(parents=True, exist_ok=True)

    for path in paths:
        if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("state") != RELEASED:
            raise ValueError("held-out execution already reserved; reruns are forbidden")

    for path in paths:
        history = (
            json.loads(path.read_text(encoding="utf-8")).get("history", []) if path.exists() else []
        )
        path.write_text(
            json.dumps(
                {"model": settings.llm_name, "state": RESERVED, "history": history}, indent=2
            ),
            encoding="utf-8",
        )
    return paths


def release_unused_reservation(
    tasks_path: Path,
    systems: Sequence[SystemName],
    settings: Settings,
    faults: bool,
    artifact: Path,
    reason: str,
) -> list[Path]:
    """Release a reservation whose run produced **zero gradable records**.

    The reservation exists to prevent re-measuring *after seeing a result*.
    Counting attempts is a proxy for that, and the proxy is wrong in exactly
    one case: a run where every request failed before reaching the model
    produced no answer, no score, and therefore nothing that could be iterated
    against. Re-running it cannot leak information that does not exist.

    So this is a correction to the proxy, not an exception to the rule, and it
    is deliberately given a bright line rather than a judgement call:

        **zero gradable records, or the reservation is spent.**

    One graded task and it is permanently consumed. That threshold cannot be
    gamed — a run engineered to produce no gradable records contains, by
    construction, no information about the held-out set.

    Reservations are **superseded, never deleted**: the prior state and the
    reason are appended to the file's history, so a released reservation
    remains visible evidence rather than disappearing.
    """
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    gradable = [r for r in records if (r.get("grade") or {}).get("correct") is not None]
    if gradable:
        raise ValueError(
            f"{artifact} has {len(gradable)} gradable record(s) of {len(records)}; "
            "the reservation is spent and cannot be released"
        )
    if not records:
        raise ValueError(f"{artifact} contains no records at all; refusing to infer intent")

    _, paths = _ledger_paths(tasks_path, systems, settings, faults)
    released: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        existing = json.loads(path.read_text(encoding="utf-8"))
        history = existing.get("history", [])
        history.append(
            {
                "previous_state": existing.get("state"),
                "released_at": datetime.now(UTC).isoformat(),
                "reason": reason,
                "artifact": str(artifact),
                "records": len(records),
                "gradable_records": 0,
            }
        )
        path.write_text(
            json.dumps(
                {"model": settings.llm_name, "state": RELEASED, "history": history}, indent=2
            ),
            encoding="utf-8",
        )
        released.append(path)
    return released


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

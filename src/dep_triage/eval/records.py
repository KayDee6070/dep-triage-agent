"""Serializable evidence, independent of the graph implementation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from dep_triage.agent.loop import AgentResult
from dep_triage.eval.grading import Grade
from dep_triage.eval.reference import GroundTruth
from dep_triage.eval.suite import Case, SystemName
from dep_triage.tools.wrapper import ToolCallRecord


class Trace(BaseModel):
    answer: str
    calls: list[ToolCallRecord] = Field(default_factory=list)
    terminated: bool
    stop_reason: str
    duration_s: float = 0.0
    messages: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_result(cls, result: AgentResult) -> Trace:
        return cls(
            answer=result.answer,
            calls=result.calls,
            terminated=result.terminated,
            stop_reason=result.stop_reason,
            duration_s=result.duration_s,
            messages=[m.model_dump(mode="json") for m in result.messages],
        )


class EvaluationRecord(BaseModel):
    system: SystemName
    case: Case
    truth: GroundTruth
    grade: Grade
    trace: Trace

    # Single-occurrence faults do not establish impossibility of recovery.
    # None means not established, not False, and cannot enter that denominator.
    recovery_impossible: bool | None = None

    @property
    def fault_applied(self) -> bool:
        return any(call.fault is not None for call in self.trace.calls)

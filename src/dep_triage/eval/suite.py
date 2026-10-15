"""Outcome-independent suite selection and fault plans.

Every system receives the same questions and the same first-lookup fault.
Whether it actually reaches that lookup is observed, not assumed. The malformed
lookup retains the vulnerability verdict: success on a label task under that
fault is not evidence of a retry or of repairing missing information.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel

from dep_triage.eval.tasks import EXPOSED_TASK_IDS, Split, TaskSet, TaskSpec
from dep_triage.tools.wrapper import FaultMode, ToolFault

SystemName = Literal["agent", "no_agent", "always_lookup"]
SYSTEMS: tuple[SystemName, ...] = ("agent", "no_agent", "always_lookup")
FAULT_MODES: tuple[FaultMode, ...] = ("error", "empty", "malformed")


class Case(BaseModel):
    task: TaskSpec
    fault: ToolFault | None = None

    @property
    def key(self) -> str:
        return f"{self.task.id}/{self.fault.mode if self.fault else 'clean'}"


def select_tasks(task_set: TaskSet, split: Split) -> list[TaskSpec]:
    """Keep the declared allocation; exclude the two exposed probes from execution."""
    ids = [task.id for task in task_set.tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate task IDs")
    return sorted(
        (t for t in task_set.split(split) if t.id not in EXPOSED_TASK_IDS), key=lambda t: t.id
    )


def fault_subset(tasks: list[TaskSpec], count: int) -> list[TaskSpec]:
    """Round-robin sorted classes and IDs; never select using model outcomes."""
    groups: dict[str, list[TaskSpec]] = defaultdict(list)
    for task in sorted(tasks, key=lambda t: t.id):
        groups[task.task_class].append(task)
    chosen: list[TaskSpec] = []
    for index in range(max((len(g) for g in groups.values()), default=0)):
        for name in sorted(groups):
            if index < len(groups[name]):
                chosen.append(groups[name][index])
    return chosen[:count]


def build_cases(task_set: TaskSet, split: Split, faults: bool = False) -> list[Case]:
    tasks = select_tasks(task_set, split)
    if not faults:
        return [Case(task=task) for task in tasks]
    selected = fault_subset(tasks, 10 if split == "dev" else 20)
    return [
        Case(task=task, fault=ToolFault(tool="lookup_vulnerabilities", mode=mode, occurrence=1))
        for mode in FAULT_MODES
        for task in selected
    ]

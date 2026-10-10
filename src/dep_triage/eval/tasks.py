"""Task schema and the eight question classes.

A task stores **question parameters, not answers**. Ground truth is computed
from the fixture by :mod:`dep_triage.eval.reference` every time the harness
runs, which is what stops an answer drifting out of sync with the snapshot it
was derived from — and what makes "no hand-labelling" true rather than claimed.

The split is part of the committed data, not a runtime argument. M0 scope §3.4
requires it to be fixed before any measurement exists; a split chosen at run
time could be re-chosen after seeing a result.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Split = Literal["dev", "held_out"]

#: The eight question classes from M0 scope §3.4.
TaskClass = Literal[
    "vulnerable_affected",
    "vulnerable_clean",
    "version_unpublished",
    "package_unknown",
    "minimum_safe_version",
    "minimum_safe_version_deep",
    "which_vulnerable",
    "python_upgrade",
    "single_package_overcall",
]

#: How a final answer is compared against ground truth.
AnswerKind = Literal["label", "version", "name_set", "bool"]

#: The four mutually exclusive verdicts a single-package question can have.
#: Three of them are negatives and an agent that conflates them is making a
#: nameable mistake — see M0 scope §3.6.
Verdict = Literal["vulnerable", "not_vulnerable", "version_unknown", "package_unknown"]

#: Classes a single tool can answer in practice, measured rather than assumed.
#: ``minimum_safe_version`` leaks through advisory fix boundaries;
#: ``which_vulnerable`` leaks because the pins are in the question text. Kept
#: here so no reader of ``required_tools`` mistakes it for logical necessity.
ONE_TOOL_SUFFICIENT: frozenset[TaskClass] = frozenset(
    {
        "vulnerable_affected",
        "vulnerable_clean",
        "version_unpublished",
        "package_unknown",
        "single_package_overcall",
        "minimum_safe_version",
        "which_vulnerable",
    }
)

ANSWER_KINDS: dict[TaskClass, AnswerKind] = {
    "vulnerable_affected": "label",
    "vulnerable_clean": "label",
    "version_unpublished": "label",
    "package_unknown": "label",
    "minimum_safe_version": "version",
    "minimum_safe_version_deep": "version",
    "which_vulnerable": "name_set",
    "python_upgrade": "bool",
    "single_package_overcall": "label",
}

#: Target counts per class and split. Asserted against the built task set, so a
#: generator that silently under-fills a class fails the suite rather than
#: quietly producing a thinner benchmark than the documents claim.
ALLOCATION: dict[TaskClass, tuple[int, int]] = {
    # class: (dev, held_out)
    "vulnerable_affected": (2, 6),
    "vulnerable_clean": (2, 4),
    "version_unpublished": (2, 4),
    "package_unknown": (2, 4),
    "minimum_safe_version": (2, 6),
    "minimum_safe_version_deep": (2, 2),
    "which_vulnerable": (3, 5),
    "python_upgrade": (2, 6),
    "single_package_overcall": (3, 3),
}

#: Classes reported as traces rather than rates.
#:
#: ``minimum_safe_version_deep`` tests the one condition where routing can
#: structurally beat exhaustive calling: the answer lies outside the window an
#: unfiltered ``list_releases`` returns, *and* the advisory fix boundaries do
#: not point at it. The committed snapshot contains only four genuinely
#: distinct cases — eight if adjacent floors are counted, but ``certifi`` from
#: 1.0.0 and 1.0.1 both answer 14.05.14, so those are duplicates.
#:
#: Four tasks cannot carry a rate. They can carry an existence claim, which
#: needs no interval, so this class is exempt from the per-class held-out floor
#: and is reported as traces. Padding it with near-duplicates to reach a
#: respectable count would manufacture precision that the data does not have.
EXISTENCE_PROBE_CLASSES: frozenset[TaskClass] = frozenset({"minimum_safe_version_deep"})


class TaskSpec(BaseModel):
    """One evaluation task. Parameters only — never an answer."""

    id: str
    split: Split
    task_class: TaskClass
    question: str

    # --- class-dependent parameters ---
    package: str | None = None
    version: str | None = None
    python_version: str | None = None
    requirements: str | None = None

    #: For ``minimum_safe_version``: the currently pinned, vulnerable version
    #: the user is upgrading away from.
    from_version: str | None = None

    #: Packages named in ``requirements`` but not asked about. Kept so the
    #: over-call probe can assert the distractors were present.
    distractors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_parameters_match_class(self) -> TaskSpec:
        """Reject a task missing the parameters its class needs.

        A task with the wrong parameters would produce ground truth for a
        different question than the one the agent was asked, which is the worst
        failure a benchmark can have because nothing downstream would notice.
        """
        needs: dict[TaskClass, tuple[str, ...]] = {
            "vulnerable_affected": ("package", "version"),
            "vulnerable_clean": ("package", "version"),
            "version_unpublished": ("package", "version"),
            "package_unknown": ("package", "version"),
            "minimum_safe_version": ("package", "from_version"),
            "minimum_safe_version_deep": ("package", "from_version"),
            "which_vulnerable": ("requirements",),
            "python_upgrade": ("package", "from_version", "python_version"),
            "single_package_overcall": ("package", "version", "requirements"),
        }
        missing = [f for f in needs[self.task_class] if getattr(self, f) is None]
        if missing:
            raise ValueError(f"{self.id} ({self.task_class}) is missing {missing}")
        return self

    @property
    def answer_kind(self) -> AnswerKind:
        return ANSWER_KINDS[self.task_class]


class TaskSet(BaseModel):
    """The committed benchmark: all 60 tasks, both splits."""

    fixture_snapshot: str
    tasks: list[TaskSpec]

    def split(self, name: Split) -> list[TaskSpec]:
        return [task for task in self.tasks if task.split == name]

    def counts(self) -> dict[tuple[TaskClass, Split], int]:
        found: dict[tuple[TaskClass, Split], int] = {}
        for task in self.tasks:
            key = (task.task_class, task.split)
            found[key] = found.get(key, 0) + 1
        return found

    def check_allocation(self) -> list[str]:
        """Differences between the built set and :data:`ALLOCATION`."""
        counts = self.counts()
        problems: list[str] = []
        for task_class, (dev, held) in ALLOCATION.items():
            for split, want in (("dev", dev), ("held_out", held)):
                got = counts.get((task_class, split), 0)  # type: ignore[arg-type]
                if got != want:
                    problems.append(f"{task_class}/{split}: want {want}, got {got}")
        return problems

"""Ground truth, computed from the fixture.

Two things come out of here per task: the expected answer, and the **reference
path** — the tools this resolver had to touch. Neither is hand-written.

The path is derived rather than declared. A resolver can only reach the fixture
through :class:`Evidence`, and every ``Evidence`` accessor maps to exactly one
tool, so the recorded set is whatever the computation actually used. No
declaration can disagree with it.

**It is the reference path, not a proof of minimality.** Measured on 2026-10-09
by running the baselines: 53 of 54 ``minimum_safe_version`` cases can be
answered from ``lookup_vulnerabilities`` alone, because advisories carry fix
boundaries and the highest one is almost always the answer. The resolver's path
is ``{lookup, releases}``; a shorter correct path exists. Likewise
``which_vulnerable`` can be answered without ``parse_requirements``, since the
pins are visible in the question text.

So ``tool_recall`` measures **agreement with the reference path**, not logical
necessity. The earlier framing ("minimal necessary tool set") claimed more than
the mechanism proves, and the baselines are what exposed it.

``Evidence`` reads the fixture **completely**, not through the agent-facing
tools. Those cap their output (10 advisories, 60 versions) to fit an 8k
context; ground truth must not inherit a limit that exists for the agent's
benefit. The separate obligation — that the answer is still *reachable* through
the capped tools — is enforced by the task builder, not here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from dep_triage.eval.tasks import AnswerKind, TaskSpec, Verdict
from dep_triage.fixture import Fixture, normalise, sort_key, version_in
from dep_triage.tools import triage

PARSE = "parse_requirements"
LOOKUP = "lookup_vulnerabilities"
RELEASES = "list_releases"
COMPAT = "check_compatibility"


class Evidence:
    """Complete fixture access that records the tool each query implies."""

    def __init__(self, fixture: Fixture) -> None:
        self._fixture = fixture
        self.used: set[str] = set()

    def parse(self, text: str) -> list[tuple[str, str | None]]:
        self.used.add(PARSE)
        result = triage.parse_requirements(self._fixture, text)
        return [(r.name, r.pinned_version) for r in result.requirements]

    def verdict(self, package: str, version: str) -> Verdict:
        """The four-way verdict for one exact pin. See M0 scope §3.6."""
        self.used.add(LOOKUP)
        key = normalise(package)
        if not self._fixture.has_package(key):
            return "package_unknown"

        affected = any(
            version_in(version, record.affected_versions) for record in self._fixture.vulns_for(key)
        )
        if affected:
            return "vulnerable"

        meta = self._fixture.package(key)
        if meta is None or meta.release(version) is None:
            return "version_unknown"
        return "not_vulnerable"

    def advisory_ids(self, package: str, version: str) -> set[str]:
        self.used.add(LOOKUP)
        return {
            record.id
            for record in self._fixture.vulns_for(package)
            if version_in(version, record.affected_versions)
        }

    def published_versions(self, package: str) -> list[str]:
        """Every published version, ascending. Not window-limited."""
        self.used.add(RELEASES)
        meta = self._fixture.package(package)
        return sorted(meta.versions, key=sort_key) if meta else []

    def python_compatible(self, package: str, version: str, python_version: str) -> bool | None:
        self.used.add(COMPAT)
        return triage.check_compatibility(
            self._fixture, package, version, python_version
        ).python_compatible


class GroundTruth(BaseModel):
    """The expected answer plus what it took to compute it."""

    task_id: str
    answer_kind: AnswerKind

    expected_label: Verdict | None = None
    expected_version: str | None = None
    expected_names: list[str] | None = None
    expected_bool: bool | None = None

    #: Minimal necessary tools, derived. ``tool_recall`` is scored against this.
    required_tools: list[str] = Field(default_factory=list)

    #: Fewest tool calls that could answer the question. The denominator for
    #: D3's ``over_call_ratio``.
    oracle_calls: int = 0

    #: Plain-English statement of the answer, for traces and the report.
    rationale: str = ""


def lowest_clean_version(evidence: Evidence, package: str, floor: str | None = None) -> str | None:
    """Lowest published version at or above ``floor`` with no advisory.

    Both tools are genuinely required: an advisory's ``fixed`` boundary is not
    always a version that shipped, so answering from advisories alone names
    versions nobody can install.
    """
    for version in evidence.published_versions(package):
        if floor is not None and sort_key(version) < sort_key(floor):
            continue
        if evidence.verdict(package, version) == "not_vulnerable":
            return version
    return None


def resolve(task: TaskSpec, fixture: Fixture) -> GroundTruth:
    """Compute ground truth for one task."""
    evidence = Evidence(fixture)
    truth = GroundTruth(task_id=task.id, answer_kind=task.answer_kind)

    if task.task_class in {
        "vulnerable_affected",
        "vulnerable_clean",
        "version_unpublished",
        "package_unknown",
        "single_package_overcall",
    }:
        assert task.package is not None and task.version is not None
        verdict = evidence.verdict(task.package, task.version)
        truth.expected_label = verdict
        truth.oracle_calls = 1
        truth.rationale = f"{task.package}=={task.version} -> {verdict}"

    elif task.task_class in {"minimum_safe_version", "minimum_safe_version_deep"}:
        assert task.package is not None and task.from_version is not None
        answer = lowest_clean_version(evidence, task.package, task.from_version)
        truth.expected_version = answer
        # One release listing, then a verdict per candidate examined. Treated
        # as two: the agent can batch the advisory question via all_fixed_versions.
        truth.oracle_calls = 2
        truth.rationale = (
            f"lowest published {task.package} at or above {task.from_version} "
            f"with no advisory: {answer}"
        )

    elif task.task_class == "which_vulnerable":
        assert task.requirements is not None
        pins = evidence.parse(task.requirements)
        names = [
            name
            for name, version in pins
            if version is not None and evidence.verdict(name, version) == "vulnerable"
        ]
        truth.expected_names = sorted(names)
        truth.oracle_calls = 1 + len(pins)
        truth.rationale = f"vulnerable in the file: {sorted(names) or 'none'}"

    elif task.task_class == "python_upgrade":
        assert task.package is not None
        assert task.from_version is not None and task.python_version is not None
        target = lowest_clean_version(evidence, task.package, task.from_version)
        if target is None:
            compatible: bool | None = False
            reason = "no clean version exists at or above the pinned one"
        else:
            compatible = evidence.python_compatible(task.package, target, task.python_version)
            reason = f"{task.package} {target} on Python {task.python_version}: {compatible}"
        truth.expected_bool = bool(compatible)
        truth.oracle_calls = 3
        truth.rationale = reason

    else:  # pragma: no cover - the Literal is exhaustive
        raise ValueError(f"no resolver for {task.task_class}")

    truth.required_tools = sorted(evidence.used)
    return truth


def resolve_all(tasks: list[TaskSpec], fixture: Fixture) -> dict[str, GroundTruth]:
    return {task.id: resolve(task, fixture) for task in tasks}

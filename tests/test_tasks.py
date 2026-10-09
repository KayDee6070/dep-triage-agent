"""Tests for the task set and the reference resolver.

Most of these guard against a *degenerate benchmark* rather than a crash. The
first generated task set passed every structural check while being badly
broken: it drew 22 packages out of 80 (all alphabetically early), every
over-call task had the same answer, and every `which_vulnerable` answer had
exactly two names — so a model that replied "vulnerable" and named two
packages would have scored well without reading anything.

Nothing in the harness would have noticed. These tests are what notices.
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter

import pytest

from dep_triage.eval.reference import Evidence, resolve, resolve_all
from dep_triage.eval.tasks import ALLOCATION, TaskSet, TaskSpec
from dep_triage.fixture import Fixture, parse_version
from dep_triage.tools import triage

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TASKS_PATH = REPO_ROOT / "data" / "tasks.json"


@pytest.fixture(scope="session")
def task_set() -> TaskSet:
    if not TASKS_PATH.is_file():
        pytest.skip("task set not built; run scripts/build_tasks.py")
    return TaskSet.model_validate(json.loads(TASKS_PATH.read_text(encoding="utf-8")))


# --- schema ---------------------------------------------------------------


def test_task_rejects_missing_parameters() -> None:
    """A task with the wrong parameters would ground-truth a different question."""
    with pytest.raises(ValueError, match="missing"):
        TaskSpec(
            id="bad-01",
            split="dev",
            task_class="minimum_safe_version",
            question="?",
            package="urllib3",  # from_version absent
        )


def test_allocation_sums_to_the_documented_split() -> None:
    dev = sum(d for d, _ in ALLOCATION.values())
    held = sum(h for _, h in ALLOCATION.values())
    assert (dev, held) == (20, 40)
    assert dev + held == 60


def test_every_class_clears_the_thinness_floor() -> None:
    """Below 2 dev tasks a class is iterated on blind."""
    for task_class, (dev, held) in ALLOCATION.items():
        assert dev >= 2, f"{task_class} has only {dev} dev tasks"
        assert held >= 3, f"{task_class} has only {held} held-out tasks"


# --- the built set --------------------------------------------------------


def test_built_set_matches_the_allocation(task_set: TaskSet) -> None:
    assert task_set.check_allocation() == []
    assert len(task_set.tasks) == 60
    assert len(task_set.split("dev")) == 20
    assert len(task_set.split("held_out")) == 40


def test_task_ids_are_unique(task_set: TaskSet) -> None:
    ids = [task.id for task in task_set.tasks]
    assert len(set(ids)) == len(ids)


def test_snapshot_matches_the_fixture(task_set: TaskSet, real_fixture: Fixture) -> None:
    """A task set built against a different snapshot has stale ground truth."""
    assert task_set.fixture_snapshot == real_fixture.manifest.snapshot_date


def test_both_splits_cover_every_class(task_set: TaskSet) -> None:
    for split in ("dev", "held_out"):
        classes = {task.task_class for task in task_set.split(split)}
        assert classes == set(ALLOCATION), f"{split} is missing {set(ALLOCATION) - classes}"


# --- degeneracy guards ---------------------------------------------------


def test_package_coverage_is_spread_across_the_corpus(task_set: TaskSet) -> None:
    """The first build drew 22 of 80 packages, all alphabetically early."""
    packages = [task.package for task in task_set.tasks if task.package]
    assert len(set(packages)) >= 30, f"only {len(set(packages))} distinct packages"
    assert Counter(packages).most_common(1)[0][1] <= 6, "one package dominates the set"


def test_no_prerelease_pins(task_set: TaskSet) -> None:
    """Real versions, but not ones anyone pins — it reads as synthetic."""
    for task in task_set.tasks:
        pin = task.version or task.from_version
        if pin is None:
            continue
        parsed = parse_version(pin)
        if parsed is not None:
            assert not parsed.is_prerelease, f"{task.id}: {task.package}=={pin}"


def test_overcall_class_has_both_verdicts(task_set: TaskSet, real_fixture: Fixture) -> None:
    """All-vulnerable would let an unconditional answer score the class."""
    truth = resolve_all(
        [t for t in task_set.tasks if t.task_class == "single_package_overcall"], real_fixture
    )
    labels = Counter(g.expected_label for g in truth.values())
    assert labels["vulnerable"] >= 2
    assert labels["not_vulnerable"] >= 2


def test_python_upgrade_has_both_outcomes(task_set: TaskSet, real_fixture: Fixture) -> None:
    truth = resolve_all(
        [t for t in task_set.tasks if t.task_class == "python_upgrade"], real_fixture
    )
    outcomes = Counter(g.expected_bool for g in truth.values())
    assert outcomes[True] >= 2
    assert outcomes[False] >= 2


def test_which_vulnerable_answer_sizes_vary(task_set: TaskSet, real_fixture: Fixture) -> None:
    """Fixed-size answers let a model guess the shape instead of reading."""
    truth = resolve_all(
        [t for t in task_set.tasks if t.task_class == "which_vulnerable"], real_fixture
    )
    sizes = {len(g.expected_names or []) for g in truth.values()}
    assert len(sizes) >= 3, f"answer sizes are {sizes}"
    assert 0 in sizes, "no file with zero vulnerable pins — nothing tests a false positive"


# --- ground truth ---------------------------------------------------------


def test_every_task_resolves(task_set: TaskSet, real_fixture: Fixture) -> None:
    for task in task_set.tasks:
        truth = resolve(task, real_fixture)
        has_answer = (
            truth.expected_label is not None
            or truth.expected_version is not None
            or truth.expected_names is not None
            or truth.expected_bool is not None
        )
        assert has_answer, f"{task.id} has no ground truth"
        assert truth.required_tools, f"{task.id} requires no tools"
        assert truth.oracle_calls >= 1


def test_class_verdicts_match_their_class(task_set: TaskSet, real_fixture: Fixture) -> None:
    """A task filed under the wrong class silently measures something else."""
    expected = {
        "vulnerable_affected": "vulnerable",
        "vulnerable_clean": "not_vulnerable",
        "version_unpublished": "version_unknown",
        "package_unknown": "package_unknown",
    }
    for task in task_set.tasks:
        if task.task_class not in expected:
            continue
        truth = resolve(task, real_fixture)
        assert truth.expected_label == expected[task.task_class], task.id


def test_required_tools_are_derived_not_declared(task_set: TaskSet, real_fixture: Fixture) -> None:
    """Each class's tool set must be exactly what its resolver had to touch."""
    wanted = {
        "vulnerable_affected": ["lookup_vulnerabilities"],
        "vulnerable_clean": ["lookup_vulnerabilities"],
        "version_unpublished": ["lookup_vulnerabilities"],
        "package_unknown": ["lookup_vulnerabilities"],
        "single_package_overcall": ["lookup_vulnerabilities"],
        "minimum_safe_version": ["list_releases", "lookup_vulnerabilities"],
        "which_vulnerable": ["lookup_vulnerabilities", "parse_requirements"],
        "python_upgrade": ["check_compatibility", "list_releases", "lookup_vulnerabilities"],
    }
    for task in task_set.tasks:
        assert resolve(task, real_fixture).required_tools == wanted[task.task_class], task.id


def test_minimum_safe_answers_are_reachable_through_the_tool(
    task_set: TaskSet, real_fixture: Fixture
) -> None:
    """The answer must be inside the window the agent can actually see.

    boto3 has 2132 releases and ``list_releases`` returns at most 60. An answer
    outside that window would score the agent wrong for a limit the tool
    imposed on it, not for a mistake it made.
    """
    for task in task_set.tasks:
        if task.task_class != "minimum_safe_version":
            continue
        truth = resolve(task, real_fixture)
        assert truth.expected_version is not None, task.id
        assert task.package is not None and task.from_version is not None
        window = triage.list_releases(real_fixture, task.package, since_version=task.from_version)
        assert truth.expected_version in window.versions, (
            f"{task.id}: {truth.expected_version} is outside the tool's window"
        )


def test_overcall_tasks_actually_contain_distractors(task_set: TaskSet) -> None:
    """Without other packages in the file there is nothing to over-call on."""
    for task in task_set.tasks:
        if task.task_class != "single_package_overcall":
            continue
        assert task.requirements is not None
        assert task.distractors, task.id
        for name in task.distractors:
            assert name in task.requirements
            assert name != task.package


def test_resolution_is_deterministic(task_set: TaskSet, real_fixture: Fixture) -> None:
    """Ground truth must not depend on call order or cached state."""
    first = resolve_all(task_set.tasks, real_fixture)
    second = resolve_all(task_set.tasks, real_fixture)
    assert {k: v.model_dump() for k, v in first.items()} == {
        k: v.model_dump() for k, v in second.items()
    }


# --- Evidence -------------------------------------------------------------


def test_evidence_records_only_what_it_touched(tiny_fixture: Fixture) -> None:
    evidence = Evidence(tiny_fixture)
    assert evidence.used == set()
    evidence.verdict("demo-pkg", "1.0.0")
    assert evidence.used == {"lookup_vulnerabilities"}
    evidence.published_versions("demo-pkg")
    assert evidence.used == {"lookup_vulnerabilities", "list_releases"}


def test_evidence_reads_complete_truth_not_the_capped_tool(tiny_fixture: Fixture) -> None:
    """Ground truth must not inherit a cap that exists for the agent's benefit."""
    meta = tiny_fixture.packages["demo-pkg"]
    cls = type(meta.releases[0])
    meta.releases = [cls(version=f"1.0.{n}") for n in range(triage.RELEASE_WINDOW + 20)]

    complete = Evidence(tiny_fixture).published_versions("demo-pkg")
    through_tool = triage.list_releases(tiny_fixture, "demo-pkg").versions

    assert len(complete) == triage.RELEASE_WINDOW + 20
    assert len(through_tool) == triage.RELEASE_WINDOW
    assert len(complete) > len(through_tool)


def test_evidence_verdict_separates_the_three_negatives(tiny_fixture: Fixture) -> None:
    evidence = Evidence(tiny_fixture)
    assert evidence.verdict("demo-pkg", "1.0.0") == "vulnerable"
    assert evidence.verdict("clean-pkg", "0.1.0") == "not_vulnerable"
    assert evidence.verdict("demo-pkg", "7.7.7") == "version_unknown"
    assert evidence.verdict("absent-pkg", "1.0.0") == "package_unknown"

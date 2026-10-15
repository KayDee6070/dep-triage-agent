"""Fabrication detector counterexamples and semantic-version regressions."""

from __future__ import annotations

import pytest

from dep_triage.eval.assertions import distinct_versions, extract_assertions, version_matches
from dep_triage.eval.grading import grade
from dep_triage.eval.reference import GroundTruth
from dep_triage.eval.tasks import TaskSpec
from dep_triage.fixture import Fixture


def task(package: str = "demo-pkg") -> TaskSpec:
    return TaskSpec(
        id="v",
        split="dev",
        task_class="minimum_safe_version",
        question=f"Lowest safe {package} from {package}==1.0.0?",
        package=package,
        from_version="1.0.0",
    )


@pytest.mark.parametrize(
    "version", ["1.2rc1", "1.2.post1", "1.2.dev1", "1!1.2+linux.1", "14.05.14", "1"]
)
def test_complete_version_tokens_are_not_truncated(version: str) -> None:
    found = [v for v, _, _ in version_matches(f"ANSWER: {version}", answer=True)]
    assert found == [version]
    result = grade(
        task(),
        GroundTruth(task_id="v", answer_kind="version", expected_version=version),
        f"ANSWER: {version}",
    )
    assert result.correct is True


def test_semantic_aliases_are_not_ambiguous() -> None:
    assert len(distinct_versions(["4.2", "4.2.0", "4.2.0.0"])) == 1
    result = grade(
        task(),
        GroundTruth(task_id="v", answer_kind="version", expected_version="4.2"),
        "ANSWER: 4.2, 4.2.0",
    )
    assert result.correct is True
    assert not result.ambiguous


@pytest.mark.parametrize("text", ["1.2.not-a-version", "1.2.*"])
def test_invalid_version_token_is_not_accepted_by_its_prefix(text: str) -> None:
    assert version_matches(text, answer=True) == []


def test_fixture_wide_semantic_membership_aliases_and_deduplication(tiny_fixture: Fixture) -> None:
    result = extract_assertions(
        task(), "Use demo-pkg 2.0, as in 2.0.0. CVE-2026-0001 is the advisory.", tiny_fixture
    )
    assert [r.classification for r in result] == ["supported", "supported"]


def test_known_for_other_package_is_misattributed(tiny_fixture: Fixture) -> None:
    result = extract_assertions(
        task("clean-pkg"), "clean-pkg 2.0 fixes CVE-2026-0001.", tiny_fixture
    )
    assert len(result) == 2
    assert all(r.classification == "misattributed" for r in result)


def test_echoes_python_versions_scores_dates_uncertainty_are_not_assertions(
    tiny_fixture: Fixture,
) -> None:
    answer = (
        "demo-pkg==1.0.0 is affected. Python 3.8 is supported. CVSS score 9.8. "
        "Snapshot 2026-10-09. I cannot verify version 99999.8. "
        "Version 99999.9 does not exist."
    )
    assert extract_assertions(task(), answer, tiny_fixture) == []


def test_hard_identifier_and_version_fabrication(tiny_fixture: Fixture) -> None:
    result = extract_assertions(task(), "Use version 99999.8 for CVE-2026-99999.", tiny_fixture)
    assert len(result) == 2
    assert all(r.classification == "hard" for r in result)


def test_multi_package_attribution_stays_unresolved_when_ambiguous(tiny_fixture: Fixture) -> None:
    multi = TaskSpec(
        id="m",
        split="dev",
        task_class="which_vulnerable",
        question="Which?",
        requirements="demo-pkg==1.0.0\nclean-pkg==0.1.0",
    )
    result = extract_assertions(multi, "The fix is 2.0.0.", tiny_fixture)
    assert result[0].classification == "unattributed"
    assert result[0].package is None


def test_explicit_package_beats_task_default(tiny_fixture: Fixture) -> None:
    result = extract_assertions(
        task(), "clean-pkg 0.2.0 and demo-pkg 2.0.0 are available.", tiny_fixture
    )
    assert [(r.package, r.classification) for r in result] == [
        ("clean-pkg", "supported"),
        ("demo-pkg", "supported"),
    ]

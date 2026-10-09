"""Grader tests, including phrasings chosen to break it.

The grader decides every number this project reports, so it is tested against
adversarial text rather than only against its own happy path. The important
property is not high accuracy — it is that unreadable answers come back
``ungradable`` instead of being scored as wrong.
"""

from __future__ import annotations

import pytest

from dep_triage.eval.grading import answer_line, grade
from dep_triage.eval.reference import GroundTruth
from dep_triage.eval.tasks import TaskSpec, Verdict


def label_task(task_class: str = "vulnerable_affected") -> TaskSpec:
    return TaskSpec(
        id="t-01",
        split="dev",
        task_class=task_class,  # type: ignore[arg-type]
        question="Is demo-pkg==1.0.0 vulnerable?",
        package="demo-pkg",
        version="1.0.0",
    )


def label_truth(expected: Verdict) -> GroundTruth:
    return GroundTruth(task_id="t-01", answer_kind="label", expected_label=expected)


# --- the answer line -----------------------------------------------------


def test_answer_line_is_extracted() -> None:
    assert answer_line("Some prose.\nANSWER: VULNERABLE") == "VULNERABLE"


def test_last_answer_line_wins() -> None:
    """An agent that corrects itself should be taken at its final word."""
    assert answer_line("ANSWER: VULNERABLE\nwait\nANSWER: NOT_VULNERABLE") == "NOT_VULNERABLE"


def test_answer_line_is_case_insensitive_and_tolerates_spacing() -> None:
    assert answer_line("answer :  NOT_VULNERABLE  ") == "NOT_VULNERABLE"


def test_no_answer_line() -> None:
    assert answer_line("just prose") is None


# --- labels via the answer line ------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected", "correct"),
    [
        ("VULNERABLE", "vulnerable", True),
        ("NOT_VULNERABLE", "not_vulnerable", True),
        ("VERSION_UNKNOWN", "version_unknown", True),
        ("PACKAGE_UNKNOWN", "package_unknown", True),
        ("NOT_VULNERABLE", "vulnerable", False),
        ("not vulnerable", "not_vulnerable", True),
        ("VULNERABLE.", "vulnerable", True),
    ],
)
def test_label_from_answer_line(token: str, expected: Verdict, correct: bool) -> None:
    result = grade(
        label_task(),
        label_truth(expected),
        f"Prose here.\nANSWER: {token}",
    )
    assert result.method == "answer_line"
    assert result.correct is correct


def test_unrecognised_token_falls_back_to_prose() -> None:
    result = grade(
        label_task(),
        label_truth("vulnerable"),
        "demo-pkg 1.0.0 is vulnerable.\nANSWER: MAYBE",
    )
    assert result.method == "prose_fallback"
    assert result.correct is True
    assert "MAYBE" in result.note


# --- the hard part: prose -----------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("demo-pkg 1.0.0 is vulnerable.", "vulnerable"),
        ("It is affected by two advisories.", "vulnerable"),
        ("This version has 3 known vulnerabilities.", "vulnerable"),
        ("demo-pkg 1.0.0 is not vulnerable.", "not_vulnerable"),
        ("There are no known advisories for this version.", "not_vulnerable"),
        ("The package is unaffected.", "not_vulnerable"),
        ("That version was never published.", "version_unknown"),
        ("No such version exists on the index.", "version_unknown"),
        ("The package is unknown, so I cannot say.", "package_unknown"),
        ("Unknown package: no data is held for it.", "package_unknown"),
    ],
)
def test_prose_classification(text: str, expected: Verdict) -> None:
    result = grade(label_task(), label_truth(expected), text)
    assert result.correct is True, result.note
    assert result.method == "prose_fallback"


def test_negation_is_not_read_as_affirmation() -> None:
    """'is not vulnerable' contains 'vulnerable' — ordering must handle it."""
    result = grade(label_task(), label_truth("vulnerable"), "demo-pkg is not vulnerable.")
    assert result.extracted == "not_vulnerable"
    assert result.correct is False


def test_conflicting_prose_is_ungradable_not_guessed() -> None:
    """Two mutually exclusive verdicts must not resolve to whichever is first."""
    result = grade(
        label_task(),
        label_truth("vulnerable"),
        "The package is unknown. However it is vulnerable.",
    )
    assert result.correct is None
    assert result.gradable is False
    assert "conflicting" in result.note


def test_unreadable_answer_is_ungradable_not_wrong() -> None:
    """The property that keeps grader bugs out of the agent's score."""
    result = grade(label_task(), label_truth("vulnerable"), "I had some trouble with that.")
    assert result.correct is None
    assert result.method == "none"


def test_empty_answer_is_ungradable() -> None:
    assert grade(label_task(), label_truth("vulnerable"), "").correct is None


# --- versions ------------------------------------------------------------


def version_truth(expected: str | None) -> GroundTruth:
    return GroundTruth(task_id="t-01", answer_kind="version", expected_version=expected)


def version_task() -> TaskSpec:
    return TaskSpec(
        id="t-01",
        split="dev",
        task_class="minimum_safe_version",
        question="lowest safe version?",
        package="tqdm",
        from_version="4.66.2",
    )


def test_version_exact_match() -> None:
    result = grade(version_task(), version_truth("4.66.3"), "Upgrade to 4.66.3.\nANSWER: 4.66.3")
    assert result.correct is True
    assert result.ambiguous is False


def test_version_comparison_is_semantic() -> None:
    """4.2 and 4.2.0 are the same version; the grader must agree."""
    assert grade(version_task(), version_truth("4.2"), "ANSWER: 4.2.0").correct is True


def test_version_wrong() -> None:
    assert grade(version_task(), version_truth("4.66.3"), "ANSWER: 5.0.0").correct is False


def test_multiple_versions_are_flagged_ambiguous() -> None:
    """Naming every fix is not the same as answering 'the lowest'."""
    result = grade(
        version_task(), version_truth("4.66.3"), "Fixes exist in 4.66.3, 4.67.0 and 5.0.0."
    )
    assert result.ambiguous is True
    assert result.correct is True, "the right answer is present, but ambiguously"


def test_answer_line_scopes_version_extraction() -> None:
    """Prose may mention many versions; the answer line is the claim."""
    result = grade(
        version_task(),
        version_truth("4.66.3"),
        "Advisories affect 4.60.0, 4.64.1 and 4.66.2.\nANSWER: 4.66.3",
    )
    assert result.correct is True
    assert result.ambiguous is False


def test_no_version_in_answer_is_ungradable() -> None:
    assert grade(version_task(), version_truth("4.66.3"), "You should upgrade.").correct is None


# --- name sets -----------------------------------------------------------


def name_task() -> TaskSpec:
    return TaskSpec(
        id="t-01",
        split="dev",
        task_class="which_vulnerable",
        question="which are vulnerable?",
        requirements="gunicorn==0.1\nattrs==26.1.0\nsphinx==9.1.0",
    )


def name_truth(expected: list[str]) -> GroundTruth:
    return GroundTruth(task_id="t-01", answer_kind="name_set", expected_names=expected)


def test_name_set_exact() -> None:
    result = grade(name_task(), name_truth(["gunicorn"]), "Only one.\nANSWER: gunicorn")
    assert result.correct is True


def test_name_set_order_and_case_insensitive() -> None:
    result = grade(name_task(), name_truth(["attrs", "gunicorn"]), "ANSWER: Gunicorn, ATTRS")
    assert result.correct is True


def test_name_set_none() -> None:
    assert grade(name_task(), name_truth([]), "ANSWER: NONE").correct is True


def test_name_set_false_positive_is_caught() -> None:
    result = grade(name_task(), name_truth([]), "ANSWER: gunicorn")
    assert result.correct is False


def test_name_set_ignores_words_that_are_not_candidates() -> None:
    result = grade(name_task(), name_truth(["gunicorn"]), "ANSWER: gunicorn and nothing else")
    assert result.correct is True


def test_name_set_is_not_graded_from_prose() -> None:
    """Every candidate appears in the question, so prose cannot be read safely."""
    result = grade(
        name_task(),
        name_truth(["gunicorn"]),
        "gunicorn is vulnerable, attrs and sphinx are not.",
    )
    assert result.correct is None
    assert "not graded from prose" in result.note


# --- booleans ------------------------------------------------------------


def bool_task() -> TaskSpec:
    return TaskSpec(
        id="t-01",
        split="dev",
        task_class="python_upgrade",
        question="can I upgrade?",
        package="tqdm",
        from_version="4.66.2",
        python_version="3.8",
    )


def bool_truth(expected: bool) -> GroundTruth:
    return GroundTruth(task_id="t-01", answer_kind="bool", expected_bool=expected)


@pytest.mark.parametrize(
    ("token", "expected", "correct"),
    [("YES", True, True), ("NO", False, True), ("YES", False, False), ("NO", True, False)],
)
def test_bool_from_answer_line(token: str, expected: bool, correct: bool) -> None:
    result = grade(bool_task(), bool_truth(expected), f"ANSWER: {token}")
    assert result.correct is correct


def test_bool_prose_fallback() -> None:
    """Agreement with ground truth, both polarities."""
    assert grade(bool_task(), bool_truth(True), "Yes, that upgrade works.").correct is True
    assert grade(bool_task(), bool_truth(False), "No, you cannot.").correct is True
    assert grade(bool_task(), bool_truth(True), "No, you cannot.").correct is False
    assert grade(bool_task(), bool_truth(False), "Yes, that works.").correct is False


def test_cannot_is_not_read_as_can() -> None:
    """'you cannot' contains 'you can'; the word boundary must hold."""
    result = grade(bool_task(), bool_truth(False), "No, you cannot upgrade.")
    assert result.extracted == "False"


def test_bool_ambiguous_prose_is_ungradable() -> None:
    result = grade(bool_task(), bool_truth(True), "Yes and no, you cannot be sure.")
    assert result.correct is None


def test_bool_without_signal_is_ungradable() -> None:
    assert grade(bool_task(), bool_truth(True), "That depends.").correct is None

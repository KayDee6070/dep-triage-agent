"""Turning a free-text answer into a graded outcome.

This is the most fragile part of the harness, so it is built to **fail visibly
rather than guess**. Three outcomes are possible for every task: correct,
incorrect, and ``ungradable``. An answer the grader cannot read is reported as
ungradable, never silently counted against the agent — otherwise grader bugs
would appear in the results as agent failures, which is the one way an eval can
be confidently wrong.

Grading runs in two tiers:

1. **The answer line.** The agent is asked to end with ``ANSWER: <token>``.
   Parsing that is exact and auditable.
2. **Prose fallback.** If the line is missing, a conservative pattern match
   over the prose. Any task graded this way is flagged, and ``fallback_rate``
   is reported — a high rate means the headline number rests on heuristics and
   the report has to say so.

If two mutually exclusive verdicts both match the prose, the result is
ungradable. Picking the first would invent a precision the text does not have.

Asking for a structured line was decided before any measurement existed. It
does give the agent a format obligation it would not otherwise have, and format
failures are therefore measured in their own right rather than folded into
answer accuracy.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from dep_triage.eval.reference import GroundTruth
from dep_triage.eval.tasks import TaskSpec, Verdict
from dep_triage.fixture import normalise, versions_equal

GradeMethod = Literal["answer_line", "prose_fallback", "none"]

ANSWER_LINE = re.compile(r"^\s*ANSWER\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)

#: Canonical tokens the agent is asked to emit for verdict questions.
VERDICT_TOKENS: dict[str, Verdict] = {
    "VULNERABLE": "vulnerable",
    "NOT_VULNERABLE": "not_vulnerable",
    "VERSION_UNKNOWN": "version_unknown",
    "PACKAGE_UNKNOWN": "package_unknown",
}

VERSION_TOKEN = re.compile(r"\b\d+(?:\.\d+){1,3}(?:[a-z]+\d+)?\b")

#: Prose patterns per verdict, ordered so that negated and more specific forms
#: are tried before the bare positive. "is not vulnerable" contains
#: "vulnerable", so the ordering is load-bearing, not cosmetic.
PROSE_PATTERNS: tuple[tuple[Verdict, re.Pattern[str]], ...] = (
    (
        "package_unknown",
        re.compile(
            r"package[^.]{0,40}\b(is |was )?(unknown|not found|not recognis|not recogniz)"
            r"|unknown package"
            r"|no (data|information|record)[^.]{0,30}(for|about) (that |the )?package",
            re.IGNORECASE,
        ),
    ),
    (
        "version_unknown",
        re.compile(
            r"(version|release)[^.]{0,40}\b(does ?n[o']?t exist|never (been )?(published|released)"
            r"|was never (published|released)|is not a (published|real|valid) (version|release)"
            r"|does not appear to exist)"
            r"|no such (version|release)",
            re.IGNORECASE,
        ),
    ),
    (
        "not_vulnerable",
        re.compile(
            r"\bis not (currently )?(known to be )?vulnerable"
            r"|\bnot vulnerable\b"
            r"|\bno known (vulnerabilit|advisor|cve|securit)"
            r"|\bunaffected\b",
            re.IGNORECASE,
        ),
    ),
    (
        "vulnerable",
        re.compile(
            r"\bis vulnerable\b"
            r"|\bis affected\b"
            r"|\bhas (?:(?:known|\d+|several|multiple)\s+)*(vulnerabilit|advisor)"
            r"|\baffected by\b",
            re.IGNORECASE,
        ),
    ),
)

YES_PATTERN = re.compile(r"\b(yes|you can|it is safe|compatible)\b", re.IGNORECASE)
NO_PATTERN = re.compile(
    r"\b(no,|you cannot|you can ?not|you can't|is not compatible|incompatible|not safe)\b",
    re.IGNORECASE,
)

NONE_TOKENS = {"NONE", "NO_PACKAGES", "[]", "-", "EMPTY"}


class Grade(BaseModel):
    """One graded task."""

    task_id: str

    #: ``None`` means ungradable — the grader could not read the answer. Kept
    #: separate from ``False`` so grader failures never masquerade as agent
    #: failures.
    correct: bool | None = None

    expected: str | None = None
    extracted: str | None = None
    method: GradeMethod = "none"
    note: str = ""

    #: A version answer that named more than one version. Counted separately:
    #: "the fix is 4.66.3" and "fixes exist in 4.66.3, 4.67.0 and 5.0" are not
    #: equally good answers to "what is the lowest safe version".
    ambiguous: bool = False

    @property
    def gradable(self) -> bool:
        return self.correct is not None


def answer_line(text: str) -> str | None:
    """Last ``ANSWER:`` line in the text, if any."""
    matches = ANSWER_LINE.findall(text or "")
    return matches[-1].strip() if matches else None


def _verdict_from_prose(text: str) -> tuple[Verdict | None, str]:
    """Conservative prose classification. Ambiguity returns ``None``."""
    matched = [verdict for verdict, pattern in PROSE_PATTERNS if pattern.search(text)]
    if not matched:
        return None, "no verdict phrase found"
    distinct = list(dict.fromkeys(matched))
    if len(distinct) > 1:
        return None, f"conflicting verdict phrases: {distinct}"
    return distinct[0], "matched prose"


def _grade_label(text: str, expected: Verdict) -> Grade:
    grade = Grade(task_id="", expected=expected)

    line = answer_line(text)
    if line is not None:
        token = line.strip().upper().replace(" ", "_").rstrip(".")
        if token in VERDICT_TOKENS:
            grade.method = "answer_line"
            grade.extracted = VERDICT_TOKENS[token]
            grade.correct = grade.extracted == expected
            return grade
        grade.note = f"unrecognised answer token {line!r}; "

    verdict, why = _verdict_from_prose(text)
    if verdict is None:
        grade.note += why
        return grade
    grade.method = "prose_fallback"
    grade.extracted = verdict
    grade.correct = verdict == expected
    grade.note += why
    return grade


def _grade_version(text: str, expected: str | None) -> Grade:
    grade = Grade(task_id="", expected=expected)
    if expected is None:
        grade.note = "no ground-truth version"
        return grade

    line = answer_line(text)
    source: str = line if line is not None else text
    method: GradeMethod = "answer_line" if line is not None else "prose_fallback"
    found = VERSION_TOKEN.findall(source)
    if not found:
        grade.note = "no version string in the answer"
        return grade

    grade.method = method
    grade.extracted = ", ".join(found)
    unique = {token for token in found}
    grade.ambiguous = len(unique) > 1
    grade.correct = any(versions_equal(candidate, expected) for candidate in found)
    if grade.ambiguous:
        grade.note = f"{len(unique)} distinct versions named"
    return grade


def _grade_name_set(text: str, expected: list[str] | None, candidates: list[str]) -> Grade:
    """Grade a set-of-names answer.

    Only the ``ANSWER:`` line is used. Prose is deliberately not attempted:
    every candidate package appears in the question, so an answer naming all of
    them while marking only one as vulnerable cannot be read without inventing
    a clause parser — and a wrong clause parser produces confident nonsense.
    """
    grade = Grade(task_id="", expected=",".join(expected or []) or "NONE")
    if expected is None:
        grade.note = "no ground-truth name set"
        return grade

    line = answer_line(text)
    if line is None:
        grade.note = "no ANSWER line; name sets are not graded from prose"
        return grade

    grade.method = "answer_line"
    known = {normalise(candidate) for candidate in candidates}
    if line.strip().upper().rstrip(".") in NONE_TOKENS:
        named: set[str] = set()
    else:
        named = {
            normalise(part)
            for part in re.split(r"[,\s]+", line)
            if part.strip() and normalise(part) in known
        }

    grade.extracted = ",".join(sorted(named)) or "NONE"
    grade.correct = named == {normalise(name) for name in expected}
    return grade


def _grade_bool(text: str, expected: bool | None) -> Grade:
    grade = Grade(task_id="", expected=str(expected))
    if expected is None:
        grade.note = "no ground-truth boolean"
        return grade

    line = answer_line(text)
    if line is not None:
        token = line.strip().upper().rstrip(".")
        if token in {"YES", "TRUE"}:
            grade.method, grade.extracted, grade.correct = "answer_line", "True", expected is True
            return grade
        if token in {"NO", "FALSE"}:
            grade.method, grade.extracted, grade.correct = "answer_line", "False", expected is False
            return grade
        grade.note = f"unrecognised answer token {line!r}; "

    yes, no = bool(YES_PATTERN.search(text)), bool(NO_PATTERN.search(text))
    if yes == no:  # both or neither: no defensible reading
        grade.note += "ambiguous yes/no" if yes else "no yes/no signal"
        return grade
    grade.method = "prose_fallback"
    grade.extracted = str(yes)
    grade.correct = yes is expected
    return grade


def grade(task: TaskSpec, truth: GroundTruth, answer: str) -> Grade:
    """Grade one answer against computed ground truth."""
    text = answer or ""

    if truth.answer_kind == "label":
        assert truth.expected_label is not None
        result = _grade_label(text, truth.expected_label)
    elif truth.answer_kind == "version":
        result = _grade_version(text, truth.expected_version)
    elif truth.answer_kind == "name_set":
        candidates = [
            line.split("==")[0].strip()
            for line in (task.requirements or "").splitlines()
            if "==" in line
        ]
        result = _grade_name_set(text, truth.expected_names, candidates)
    else:
        result = _grade_bool(text, truth.expected_bool)

    result.task_id = task.id
    return result

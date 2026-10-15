"""Conservative, unvalidated extraction for fabrication lower bounds.

This detects invented identifiers and wrong package attribution, not false
claims about real versions (for example calling a real vulnerable version safe).
That separate question belongs to the answer grader.
"""

from __future__ import annotations

import re

from packaging.version import VERSION_PATTERN
from pydantic import BaseModel

from dep_triage.eval.tasks import TaskSpec
from dep_triage.fixture import Fixture, normalise, parse_version, version_in, versions_equal

VERSION_PATTERN_RE = re.compile(
    rf"(?<![\w.!+\-])(?:{VERSION_PATTERN})(?![\w!+\-]|\.[\w*])", re.VERBOSE | re.IGNORECASE
)
ADVISORY_RE = re.compile(r"\b(?:CVE-\d{4}-\d{4,}|GHSA-[a-z0-9]+(?:-[a-z0-9]+)+)\b", re.I)
PIN_RE = re.compile(r"\b([a-z0-9][a-z0-9._-]*)\s*==\s*([^\s,;`]+)", re.I)
UNCERTAIN_RE = re.compile(
    r"\b(?:cannot|can't|could not|unable to|unknown|unverified|"
    r"does not exist|never (?:published|released)|no such version)\b",
    re.I,
)


def version_matches(text: str, *, answer: bool = False) -> list[tuple[str, int, int]]:
    """Complete PEP 440 tokens, including post/dev/local releases and epochs.

    Bare integers need an explicit version/pin context (or an answer line).
    The boundary prevents accepting just '1.2' out of a malformed token.
    """
    found: list[tuple[str, int, int]] = []
    for match in VERSION_PATTERN_RE.finditer(text):
        value = match.group().strip()
        prefix = text[max(0, match.start() - 24) : match.start()]
        if (
            "." not in value
            and not answer
            and not re.search(r"(?:==|version\s+)\s*$", prefix, re.I)
        ):
            continue
        if parse_version(value) is not None:
            found.append((value, match.start(), match.end()))
    return found


def distinct_versions(values: list[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        if not version_in(value, found):
            found.append(value)
    return found


class Assertion(BaseModel):
    kind: str
    value: str
    package: str | None
    classification: str  # supported, hard, misattributed, unattributed


def _clause(text: str, start: int, end: int) -> tuple[str, int]:
    # Decimal dots are not sentence boundaries.
    boundaries = list(re.finditer(r"[;\n]|\.(?=\s|$)", text))
    left = max((m.end() for m in boundaries if m.end() <= start), default=0)
    right = min((m.start() for m in boundaries if m.start() >= end), default=len(text))
    return text[left:right], left


def _package_for(text: str, start: int, end: int, task: TaskSpec, fixture: Fixture) -> str | None:
    clause, left = _clause(text, start, end)
    names = set(fixture.packages)
    names.update(normalise(name) for name, _ in PIN_RE.findall(task.question))
    if task.package:
        names.add(normalise(task.package))
    mentioned: set[str] = set()
    for name in names:
        pattern = re.escape(name).replace(r"\-", "[-_.]")
        if re.search(rf"(?<![\w.-]){pattern}(?![\w.-])", clause, re.I):
            mentioned.add(name)
            # An immediately attached package takes precedence over other
            # packages in the sentence: 'demo-pkg 2.0 and clean-pkg 0.2'.
            prefix = text[left:start]
            if re.search(rf"{pattern}\s*(?:==|version\s+|v\s*)?\s*$", prefix, re.I):
                return name
    if len(mentioned) == 1:
        return next(iter(mentioned))
    if not mentioned and task.package:
        return normalise(task.package)
    return None


def extract_assertions(task: TaskSpec, answer: str, fixture: Fixture) -> list[Assertion]:
    """Distinct positive assertions, with conservative attribution.

    Question echoes are not evidence that a nonexistent version exists. Any
    skipped or unresolved case reduces detection sensitivity; no claim of full
    hallucination detection is made.
    """
    ids = [(m.group().upper(), m.start(), m.end()) for m in ADVISORY_RE.finditer(answer)]
    candidates = [("advisory", *item) for item in ids]
    candidates += [("version", *item) for item in version_matches(answer)]
    for line in re.finditer(r"^\s*ANSWER\s*:\s*(.+)$", answer, re.I | re.M):
        for value, start, end in version_matches(line.group(1), answer=True):
            candidate = ("version", value, line.start(1) + start, line.start(1) + end)
            if candidate not in candidates:
                candidates.append(candidate)
    input_pins = [
        (normalise(name), version.rstrip(".?`")) for name, version in PIN_RE.findall(task.question)
    ]
    known_ids = {value.upper() for value in fixture.known_advisory_ids}
    found: list[Assertion] = []
    for kind, value, start, end in sorted(candidates, key=lambda c: c[2]):
        clause, _ = _clause(answer, start, end)
        if UNCERTAIN_RE.search(clause):
            continue
        if kind == "version":
            if any(start < stop and end > begin for _, begin, stop in ids):
                continue
            prefix = answer[max(0, start - 30) : start]
            if re.search(r"(?:python\s*(?:version\s*)?|cvss[^\n]{0,12})$", prefix, re.I):
                continue
            # Calendar-like tokens are not package-release claims without a
            # package/version cue. Hyphenated dates never match the boundaries.
            if re.fullmatch(r"(?:19|20)\d{2}\.\d{1,2}\.\d{1,2}", value) and re.search(
                r"(?:date|snapshot|as of)\s*$", prefix, re.I
            ):
                continue
        elif value in task.question.upper():
            continue
        package = _package_for(answer, start, end, task, fixture)
        if kind == "version" and any(
            (package is None or package == name) and versions_equal(value, version)
            for name, version in input_pins
        ):
            continue
        if any(
            old.kind == kind
            and old.package == package
            and (versions_equal(old.value, value) if kind == "version" else old.value == value)
            for old in found
        ):
            continue
        exists = (
            version_in(value, fixture.known_versions) if kind == "version" else value in known_ids
        )
        if not exists:
            classification = "hard"
        elif package is None:
            classification = "unattributed"
        else:
            attributed = (
                version_in(value, fixture.versions_of(package))
                if kind == "version"
                else any(
                    value in {i.upper() for i in v.identifiers} for v in fixture.vulns_for(package)
                )
            )
            classification = "supported" if attributed else "misattributed"
        found.append(
            Assertion(kind=kind, value=value, package=package, classification=classification)
        )
    return found

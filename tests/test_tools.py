"""Tests for the four triage tools."""

from __future__ import annotations

import pytest

from dep_triage.fixture import Fixture
from dep_triage.tools import triage

# --- parse_requirements ---------------------------------------------------

REQUIREMENTS_SAMPLE = """\
# production pins
urllib3==1.26.4
requests[security]==2.25.0
Django>=3.2        # not pinned
PyYAML==5.4.1

-r dev-requirements.txt
--index-url https://example.invalid/simple
not a requirement at all!!
"""


def test_parse_extracts_names_and_pins(tiny_fixture: Fixture) -> None:
    result = triage.parse_requirements(tiny_fixture, REQUIREMENTS_SAMPLE)
    pins = {r.name: r.pinned_version for r in result.requirements}
    assert pins == {
        "urllib3": "1.26.4",
        "requests": "2.25.0",
        "django": None,  # >=3.2 is a range, not a pin
        "pyyaml": "5.4.1",
    }


def test_parse_normalises_names_and_keeps_extras(tiny_fixture: Fixture) -> None:
    result = triage.parse_requirements(tiny_fixture, "PyYAML==5.4.1\nrequests[security]==2.25.0")
    assert [r.name for r in result.requirements] == ["pyyaml", "requests"]
    assert result.requirements[1].extras == ["security"]


def test_parse_reports_what_it_could_not_read(tiny_fixture: Fixture) -> None:
    result = triage.parse_requirements(tiny_fixture, REQUIREMENTS_SAMPLE)
    assert "-r dev-requirements.txt" in result.unparsed
    assert "--index-url https://example.invalid/simple" in result.unparsed
    assert "not a requirement at all!!" in result.unparsed


def test_parse_ignores_comments_and_blank_lines(tiny_fixture: Fixture) -> None:
    result = triage.parse_requirements(tiny_fixture, "\n# only a comment\n\n")
    assert result.requirements == []
    assert result.unparsed == []


def test_parse_works_for_packages_outside_the_fixture(tiny_fixture: Fixture) -> None:
    """Parsing must not depend on the snapshot — files name unknown packages."""
    result = triage.parse_requirements(tiny_fixture, "totally-unknown-thing==9.9.9")
    assert result.requirements[0].name == "totally-unknown-thing"
    assert result.requirements[0].pinned_version == "9.9.9"


# --- lookup_vulnerabilities -----------------------------------------------


def test_lookup_finds_affected_version(tiny_fixture: Fixture) -> None:
    result = triage.lookup_vulnerabilities(tiny_fixture, "demo-pkg", "1.0.0")
    assert result.status == "ok"
    assert result.vulnerable is True
    assert [a.id for a in result.advisories] == ["GHSA-demo-0001"]
    assert result.advisories[0].fixed_versions == ["2.0.0"]


def test_lookup_clears_fixed_version(tiny_fixture: Fixture) -> None:
    result = triage.lookup_vulnerabilities(tiny_fixture, "demo-pkg", "2.0.0")
    assert result.status == "ok"
    assert result.vulnerable is False
    assert result.advisories == []


def test_unknown_package_is_not_the_same_as_not_vulnerable(tiny_fixture: Fixture) -> None:
    """The distinction the abstention probe is built on."""
    unknown = triage.lookup_vulnerabilities(tiny_fixture, "absent-pkg", "1.0.0")
    clean = triage.lookup_vulnerabilities(tiny_fixture, "clean-pkg", "0.1.0")

    assert unknown.status == "package_unknown"
    assert clean.status == "ok"
    assert unknown.vulnerable is False
    assert clean.vulnerable is False


def test_lookup_accepts_denormalised_names(tiny_fixture: Fixture) -> None:
    result = triage.lookup_vulnerabilities(tiny_fixture, "Demo_Pkg", "1.0.0")
    assert result.status == "ok"
    assert result.package == "demo-pkg"


# --- list_releases --------------------------------------------------------


def test_list_releases_is_ordered_and_flags_yanked(tiny_fixture: Fixture) -> None:
    result = triage.list_releases(tiny_fixture, "demo-pkg")
    assert result.status == "ok"
    assert result.versions == ["1.0.0", "1.1.0", "2.0.0"]
    assert result.yanked == ["1.1.0"]
    assert result.latest == "2.0.0"
    assert result.total_count == 3
    assert result.truncated is False


def test_list_releases_unknown_package(tiny_fixture: Fixture) -> None:
    result = triage.list_releases(tiny_fixture, "absent-pkg")
    assert result.status == "package_unknown"
    assert result.versions == []


def test_list_releases_truncates_and_says_so(tiny_fixture: Fixture) -> None:
    """A silent cap would make the agent's answer wrong for our reasons."""
    meta = tiny_fixture.packages["demo-pkg"]
    many = triage.RELEASE_WINDOW + 15
    meta.releases = [type(meta.releases[0])(version=f"3.0.{n}") for n in range(many)]

    result = triage.list_releases(tiny_fixture, "demo-pkg")
    assert result.truncated is True
    assert result.total_count == many
    assert len(result.versions) == triage.RELEASE_WINDOW
    assert result.latest == f"3.0.{many - 1}"
    assert result.versions[-1] == f"3.0.{many - 1}", "the window must keep the newest versions"


# --- check_compatibility --------------------------------------------------


@pytest.mark.parametrize(
    ("version", "python_version", "expected"),
    [
        ("1.0.0", "3.8", True),
        ("1.0.0", "3.7", False),
        ("2.0.0", "3.11", True),
        ("2.0.0", "3.8", False),
    ],
)
def test_compatibility_evaluates_the_specifier(
    tiny_fixture: Fixture, version: str, python_version: str, expected: bool
) -> None:
    result = triage.check_compatibility(tiny_fixture, "demo-pkg", version, python_version)
    assert result.status == "ok"
    assert result.python_compatible is expected


def test_compatibility_distinguishes_unknown_package_from_unknown_version(
    tiny_fixture: Fixture,
) -> None:
    assert (
        triage.check_compatibility(tiny_fixture, "absent-pkg", "1.0.0", "3.12").status
        == "package_unknown"
    )
    assert (
        triage.check_compatibility(tiny_fixture, "demo-pkg", "9.9.9", "3.12").status
        == "version_unknown"
    )


def test_compatibility_flags_uncaptured_dependencies(tiny_fixture: Fixture) -> None:
    """An empty dependency list must not read as 'has no dependencies'."""
    captured = triage.check_compatibility(tiny_fixture, "demo-pkg", "2.0.0", "3.12")
    assert captured.dependencies_captured is True
    assert captured.declared_dependencies == ["urllib3>=2.0", "certifi"]

    uncaptured = triage.check_compatibility(tiny_fixture, "demo-pkg", "1.0.0", "3.12")
    assert uncaptured.dependencies_captured is False
    assert uncaptured.declared_dependencies == []


def test_compatibility_with_no_declared_constraint_is_permissive(tiny_fixture: Fixture) -> None:
    result = triage.check_compatibility(tiny_fixture, "clean-pkg", "0.1.0", "2.6")
    assert result.requires_python is None
    assert result.python_compatible is True


def test_compatibility_returns_unknown_for_a_nonsense_python(tiny_fixture: Fixture) -> None:
    """Better than False, which would read as a definite incompatibility."""
    result = triage.check_compatibility(tiny_fixture, "demo-pkg", "1.0.0", "3.x")
    assert result.python_compatible is None

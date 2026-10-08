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


# --- list_releases: since_version filter ----------------------------------


def _many_release_fixture(tiny_fixture: Fixture) -> Fixture:
    """demo-pkg with 1.0.0 .. 1.0.99, far more than the window."""
    meta = tiny_fixture.packages["demo-pkg"]
    cls = type(meta.releases[0])
    meta.releases = [cls(version=f"1.0.{n}") for n in range(100)]
    return tiny_fixture


def test_since_version_filters_to_the_floor(tiny_fixture: Fixture) -> None:
    result = triage.list_releases(tiny_fixture, "demo-pkg", since_version="1.1.0")
    assert result.status == "ok"
    assert result.versions == ["1.1.0", "2.0.0"]
    assert result.since_version == "1.1.0"
    assert result.total_count == 2


def test_since_version_is_inclusive(tiny_fixture: Fixture) -> None:
    result = triage.list_releases(tiny_fixture, "demo-pkg", since_version="2.0.0")
    assert result.versions == ["2.0.0"]


def test_unfiltered_window_keeps_the_newest(tiny_fixture: Fixture) -> None:
    """Without a floor, recent releases are what matter."""
    result = triage.list_releases(_many_release_fixture(tiny_fixture), "demo-pkg")
    assert result.truncated is True
    assert result.total_count == 100
    assert result.versions[-1] == "1.0.99"
    assert len(result.versions) == triage.RELEASE_WINDOW


def test_filtered_window_keeps_the_oldest_above_the_floor(tiny_fixture: Fixture) -> None:
    """With a floor, the minimum safe version sits just above it."""
    result = triage.list_releases(
        _many_release_fixture(tiny_fixture), "demo-pkg", since_version="1.0.10"
    )
    assert result.versions[0] == "1.0.10"
    assert len(result.versions) == triage.RELEASE_WINDOW
    assert result.total_count == 90


def test_a_good_floor_avoids_truncation_entirely(tiny_fixture: Fixture) -> None:
    """The point of the argument: the agent can dodge the cap itself."""
    result = triage.list_releases(
        _many_release_fixture(tiny_fixture), "demo-pkg", since_version="1.0.50"
    )
    assert result.truncated is False
    assert result.total_count == 50


def test_latest_ignores_the_filter(tiny_fixture: Fixture) -> None:
    result = triage.list_releases(tiny_fixture, "demo-pkg", since_version="1.0.0")
    assert result.latest == "2.0.0"


def test_invalid_floor_is_a_measurable_outcome_not_a_crash(tiny_fixture: Fixture) -> None:
    """An agent passing "1.26.x" must be told why, and it must be recorded."""
    result = triage.list_releases(tiny_fixture, "demo-pkg", since_version="1.26.x")
    assert result.status == "invalid_argument"
    assert result.versions == []
    assert result.error is not None and "1.26.x" in result.error
    assert result.since_version == "1.26.x"
    assert result.latest == "2.0.0", "the package is known, only the argument was bad"


def test_floor_above_every_release_returns_empty_not_unknown(tiny_fixture: Fixture) -> None:
    result = triage.list_releases(tiny_fixture, "demo-pkg", since_version="99.0.0")
    assert result.status == "ok"
    assert result.versions == []
    assert result.total_count == 0


def test_unknown_package_echoes_the_floor(tiny_fixture: Fixture) -> None:
    result = triage.list_releases(tiny_fixture, "absent-pkg", since_version="1.0.0")
    assert result.status == "package_unknown"
    assert result.since_version == "1.0.0"


# --- lookup_vulnerabilities: the three negative outcomes ------------------


def test_three_negatives_are_distinguishable(tiny_fixture: Fixture) -> None:
    """unknown package / unpublished version / genuinely clean."""
    unknown_pkg = triage.lookup_vulnerabilities(tiny_fixture, "absent-pkg", "1.0.0")
    unknown_ver = triage.lookup_vulnerabilities(tiny_fixture, "demo-pkg", "4.5.6")
    clean = triage.lookup_vulnerabilities(tiny_fixture, "clean-pkg", "0.1.0")

    assert unknown_pkg.status == "package_unknown"
    assert unknown_ver.status == "version_unknown"
    assert clean.status == "ok"

    # All three report vulnerable=False, so status is the only thing that
    # separates them. An agent reading only `vulnerable` conflates all three.
    assert (unknown_pkg.vulnerable, unknown_ver.vulnerable, clean.vulnerable) == (
        False,
        False,
        False,
    )
    assert len({unknown_pkg.status, unknown_ver.status, clean.status}) == 3


def test_clean_published_version_is_flagged_published(tiny_fixture: Fixture) -> None:
    result = triage.lookup_vulnerabilities(tiny_fixture, "clean-pkg", "0.1.0")
    assert result.status == "ok"
    assert result.version_published is True
    assert result.vulnerable is False


def test_advisories_win_over_unpublished_version(tiny_fixture: Fixture) -> None:
    """A withdrawn release still named by an advisory is vulnerable, not unknown.

    2175 version strings in the real snapshot are in this state. Testing
    publication first would hide every one of them.
    """
    record = tiny_fixture.vulnerabilities["demo-pkg"][0]
    record.affected_versions = [*record.affected_versions, "0.9.0"]  # never published

    result = triage.lookup_vulnerabilities(tiny_fixture, "demo-pkg", "0.9.0")
    assert result.status == "ok"
    assert result.vulnerable is True
    assert result.version_published is False


def test_plausible_but_nonexistent_pin_is_not_called_clean(tiny_fixture: Fixture) -> None:
    """A version that looks plausible and exists in no form at all.

    This test previously used "1.0" as the nonexistent version and passed,
    which locked in a bug: 1.0 and 1.0.0 are the same version under PEP 440,
    so "1.0" does exist. A passing test was supplying false confidence. The
    probe now uses a version with no PEP 440-equal counterpart in the fixture.
    """
    result = triage.lookup_vulnerabilities(tiny_fixture, "demo-pkg", "1.5.2")
    assert result.status == "version_unknown"
    assert result.vulnerable is False


def test_zero_padded_pin_is_the_same_version(tiny_fixture: Fixture) -> None:
    """Regression: PEP 440 zero-extends, so 1.0 and 1.0.0 must agree."""
    bare = triage.lookup_vulnerabilities(tiny_fixture, "demo-pkg", "1.0")
    padded = triage.lookup_vulnerabilities(tiny_fixture, "demo-pkg", "1.0.0")
    assert bare.status == padded.status == "ok"
    assert bare.vulnerable is padded.vulnerable is True
    assert [a.id for a in bare.advisories] == [a.id for a in padded.advisories]


def test_version_unknown_still_fires_for_a_genuinely_absent_version(
    tiny_fixture: Fixture,
) -> None:
    """The fix must not swallow the real case: 9.9.9 does not exist in any form."""
    result = triage.lookup_vulnerabilities(tiny_fixture, "demo-pkg", "9.9.9")
    assert result.status == "version_unknown"
    assert result.vulnerable is False


def test_compatibility_accepts_a_zero_padded_version(tiny_fixture: Fixture) -> None:
    result = triage.check_compatibility(tiny_fixture, "demo-pkg", "1.0", "3.8")
    assert result.status == "ok"
    assert result.python_compatible is True

"""Tests for the fixture schema, loader, and the real committed snapshot.

The ``real_fixture`` tests are deliberately about invariants rather than
specific advisories. Asserting "urllib3 1.26.4 has 22 advisories" would start
failing when the snapshot is rebuilt, for reasons unrelated to any code change.
"""

from __future__ import annotations

import pytest

from dep_triage.fixture import (
    Fixture,
    FixtureNotBuilt,
    load_fixture,
    normalise,
    sort_key,
    write_fixture,
)
from dep_triage.fixture_spec import CORE, HELD_OUT_UNKNOWN, PACKAGES, validate_spec

# --- helpers --------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PyYAML", "pyyaml"),
        ("typing_extensions", "typing-extensions"),
        ("Typing.Extensions", "typing-extensions"),
        ("  urllib3  ", "urllib3"),
        ("scikit__learn", "scikit-learn"),
    ],
)
def test_normalise_follows_pep503(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_sort_key_orders_versions_semantically() -> None:
    versions = ["1.10.0", "1.9.0", "2.0.0rc1", "2.0.0", "1.0.0"]
    assert sorted(versions, key=sort_key) == ["1.0.0", "1.9.0", "1.10.0", "2.0.0rc1", "2.0.0"]


def test_sort_key_tolerates_unparseable_versions() -> None:
    """Real indexes contain junk; sorting must stay total rather than raise."""
    assert sorted(["2.0.0", "not-a-version", "1.0.0"], key=sort_key) == [
        "1.0.0",
        "2.0.0",
        "not-a-version",
    ]


# --- spec -----------------------------------------------------------------


def test_spec_is_internally_consistent() -> None:
    validate_spec()


def test_abstention_probes_are_not_in_the_package_set() -> None:
    assert not set(PACKAGES) & set(HELD_OUT_UNKNOWN)


def test_core_set_meets_the_shrink_floor() -> None:
    """M0 scope §12 puts the floor at 20 packages."""
    assert len(CORE) >= 20


# --- round trip -----------------------------------------------------------


def test_write_then_load_round_trips(tiny_fixture: Fixture, tmp_path: object) -> None:
    import pathlib

    assert isinstance(tmp_path, pathlib.Path)
    write_fixture(tiny_fixture, tmp_path)
    reloaded = load_fixture(tmp_path)

    assert reloaded.packages.keys() == tiny_fixture.packages.keys()
    assert reloaded.package("demo-pkg") is not None
    assert reloaded.vulns_for("demo-pkg")[0].id == "GHSA-demo-0001"


def test_missing_fixture_names_the_build_command(tmp_path: object) -> None:
    import pathlib

    assert isinstance(tmp_path, pathlib.Path)
    with pytest.raises(FixtureNotBuilt, match=r"build_fixture\.py"):
        load_fixture(tmp_path / "nope")


def test_schema_mismatch_is_rejected(tiny_fixture: Fixture, tmp_path: object) -> None:
    """A stale fixture must fail loudly, not silently feed wrong ground truth."""
    import pathlib

    assert isinstance(tmp_path, pathlib.Path)
    tiny_fixture.manifest.schema_version = 99
    write_fixture(tiny_fixture, tmp_path)
    with pytest.raises(FixtureNotBuilt, match="schema version"):
        load_fixture(tmp_path)


# --- fabrication denominators (M0 scope §4.5) -----------------------------


def test_known_versions_spans_releases_and_advisories(tiny_fixture: Fixture) -> None:
    known = tiny_fixture.known_versions
    assert {"1.0.0", "1.1.0", "2.0.0", "0.1.0"} <= known
    assert "9.99.99" not in known


def test_known_advisory_ids_includes_aliases(tiny_fixture: Fixture) -> None:
    """A CVE alias is a legitimate way to name an advisory, not a fabrication."""
    ids = tiny_fixture.known_advisory_ids
    assert "GHSA-demo-0001" in ids
    assert "CVE-2026-0001" in ids
    assert "CVE-1999-9999" not in ids


def test_versions_of_scopes_to_one_package(tiny_fixture: Fixture) -> None:
    """The basis for ``fabrication_misattributed``."""
    assert "1.0.0" in tiny_fixture.versions_of("demo-pkg")
    assert "1.0.0" not in tiny_fixture.versions_of("clean-pkg")


# --- the real snapshot ----------------------------------------------------


def test_real_fixture_has_every_specced_package(real_fixture: Fixture) -> None:
    missing = [name for name in PACKAGES if not real_fixture.has_package(name)]
    assert not missing, f"fixture is missing specced packages: {missing}"


def test_real_fixture_excludes_abstention_probes(real_fixture: Fixture) -> None:
    leaked = [name for name in HELD_OUT_UNKNOWN if real_fixture.has_package(name)]
    assert not leaked, f"abstention probes leaked into the fixture: {leaked}"


def test_real_fixture_has_clean_packages(real_fixture: Fixture) -> None:
    """Without zero-advisory packages, "is X vulnerable?" is always yes."""
    clean = [name for name, records in real_fixture.vulnerabilities.items() if not records]
    assert len(clean) >= 10, f"only {len(clean)} packages carry no advisories"


def test_real_fixture_has_vulnerable_packages(real_fixture: Fixture) -> None:
    heavy = [name for name, records in real_fixture.vulnerabilities.items() if len(records) >= 10]
    assert len(heavy) >= 10, f"only {len(heavy)} packages carry 10+ advisories"


def test_real_fixture_advisories_reference_only_their_own_package(real_fixture: Fixture) -> None:
    """Combined advisories name several packages; the builder must filter them.

    A leaked version from another package would silently corrupt ground truth
    for every question about the package it leaked into.
    """
    for name, records in real_fixture.vulnerabilities.items():
        published = set(real_fixture.versions_of(name))
        for record in records:
            unknown = set(record.affected_versions) - published
            assert not unknown, f"{name}/{record.id} lists versions not attributable to it"


def test_real_fixture_every_package_has_releases(real_fixture: Fixture) -> None:
    empty = [name for name, meta in real_fixture.packages.items() if not meta.releases]
    assert not empty, f"packages with no releases: {empty}"

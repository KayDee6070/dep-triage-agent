"""Test isolation and shared fixtures.

The env fixtures exist to stop a developer's local environment leaking into a
test run. Without them, ``Settings()`` would pick up a real ``.env`` or exported
``DEP_TRIAGE_*`` vars and the config tests would pass or fail depending on whose
machine they ran on.

Tool tests run against ``tiny_fixture`` — a hand-built snapshot with known
contents — rather than the real one. A test asserting "1.26.4 is vulnerable"
against live data would start failing when the snapshot is rebuilt, for reasons
unrelated to the code. A handful of tests do read the real fixture, to catch
the snapshot itself being corrupt; those are marked and kept separate.
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator

import pytest

from dep_triage.fixture import (
    AffectedRange,
    Fixture,
    Manifest,
    PackageMeta,
    Release,
    Vulnerability,
    load_fixture,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
REAL_FIXTURE_PATH = REPO_ROOT / "data" / "fixture"


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear project env vars and run from a directory with no ``.env``."""
    for key in list(os.environ):
        if key.startswith("DEP_TRIAGE_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def tiny_fixture() -> Fixture:
    """A three-package snapshot with fully known contents.

    ``demo-pkg``  1.0.0 and 1.1.0 vulnerable, fixed in 2.0.0; 1.1.0 yanked.
    ``clean-pkg`` published, no advisories.
    ``absent-pkg`` deliberately not here, for the unknown-package path.
    """
    return Fixture(
        manifest=Manifest(
            schema_version=1,
            snapshot_date="2026-10-08",
            package_count=2,
            vulnerability_count=1,
        ),
        packages={
            "demo-pkg": PackageMeta(
                name="demo-pkg",
                releases=[
                    Release(version="1.0.0", requires_python=">=3.8"),
                    Release(version="1.1.0", requires_python=">=3.8", yanked=True),
                    Release(version="2.0.0", requires_python=">=3.11"),
                ],
                requires_dist={"2.0.0": ["urllib3>=2.0", "certifi"]},
            ),
            "clean-pkg": PackageMeta(
                name="clean-pkg",
                releases=[Release(version="0.1.0"), Release(version="0.2.0")],
            ),
        },
        vulnerabilities={
            "demo-pkg": [
                Vulnerability(
                    id="GHSA-demo-0001",
                    aliases=["CVE-2026-0001"],
                    summary="Demo advisory",
                    severity=["CVSS_V3:7.5"],
                    affected_versions=["1.0.0", "1.1.0"],
                    ranges=[AffectedRange(introduced="1.0.0", fixed="2.0.0")],
                )
            ],
            "clean-pkg": [],
        },
    )


@pytest.fixture(scope="session")
def real_fixture() -> Fixture:
    """The committed snapshot. Skips if it has not been built."""
    if not (REAL_FIXTURE_PATH / "manifest.json").is_file():
        pytest.skip("fixture not built; run scripts/build_fixture.py")
    return load_fixture(REAL_FIXTURE_PATH)

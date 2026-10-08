"""Schema and loader for the frozen offline snapshot.

The fixture is the project's ground truth. Every tool reads from it, every
reference answer is computed from it, and fabrication detection (M0 scope §4.5)
asks it whether a version string or advisory ID exists at all. Nothing here
touches the network.

Validated with Pydantic on load rather than trusted: a silently malformed
fixture would corrupt every measured number downstream, and a loud failure at
startup costs nothing.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

_NORMALISE_RE = re.compile(r"[-_.]+")


def normalise(name: str) -> str:
    """Normalise a distribution name per PEP 503.

    Needed because the model will write whatever the question used — ``PyYAML``,
    ``pyyaml``, ``typing_extensions`` — and a lookup miss would be scored as the
    package being unknown, which is a different finding entirely.
    """
    return _NORMALISE_RE.sub("-", name.strip().lower())


def sort_key(version: str) -> tuple[int, Version | str]:
    """Sort key ordering valid PEP 440 versions before unparseable ones.

    Real indexes contain the occasional unparseable version. Sorting must stay
    total and deterministic rather than raising, or the fixture build becomes
    order-dependent on which packages happen to be included.
    """
    try:
        return (0, Version(version))
    except InvalidVersion:
        return (1, version)


class Release(BaseModel):
    """One published version of a package."""

    version: str
    requires_python: str | None = None
    yanked: bool = False


class PackageMeta(BaseModel):
    """Release history for one package, plus declared deps where captured."""

    name: str
    releases: list[Release]

    #: Version -> declared dependency strings. Populated only for versions of
    #: interest (advisory boundaries and the newest few), because PyPI serves
    #: declared dependencies one request per version and fetching every version
    #: of every package is a lot of load for data no task asks about.
    requires_dist: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def versions(self) -> list[str]:
        return [release.version for release in self.releases]

    def release(self, version: str) -> Release | None:
        for candidate in self.releases:
            if candidate.version == version:
                return candidate
        return None


class AffectedRange(BaseModel):
    """One introduced/fixed boundary pair from an advisory."""

    introduced: str | None = None
    fixed: str | None = None


class Vulnerability(BaseModel):
    """A trimmed OSV advisory.

    ``affected_versions`` is the enumerated list OSV publishes, so answering
    "is this version affected?" is set membership rather than range
    interpretation. That is what keeps ground truth free of argument.
    """

    id: str
    aliases: list[str] = Field(default_factory=list)
    summary: str | None = None
    severity: list[str] = Field(default_factory=list)
    affected_versions: list[str] = Field(default_factory=list)
    ranges: list[AffectedRange] = Field(default_factory=list)

    @property
    def identifiers(self) -> set[str]:
        """Every string that legitimately names this advisory."""
        return {self.id, *self.aliases}

    def fixed_versions(self) -> list[str]:
        return [r.fixed for r in self.ranges if r.fixed is not None]


class Manifest(BaseModel):
    """Provenance for the snapshot. Committed so the report can cite it."""

    schema_version: int
    snapshot_date: str
    package_count: int
    vulnerability_count: int
    sources: dict[str, str] = Field(default_factory=dict)


class Fixture(BaseModel):
    """The whole snapshot, keyed by normalised package name."""

    manifest: Manifest
    packages: dict[str, PackageMeta]
    vulnerabilities: dict[str, list[Vulnerability]]

    def has_package(self, name: str) -> bool:
        return normalise(name) in self.packages

    def package(self, name: str) -> PackageMeta | None:
        return self.packages.get(normalise(name))

    def vulns_for(self, name: str) -> list[Vulnerability]:
        return self.vulnerabilities.get(normalise(name), [])

    @functools.cached_property
    def known_versions(self) -> frozenset[str]:
        """Every version string that appears anywhere in the snapshot.

        The denominator for ``fabrication_hard`` (M0 scope §4.5): a version the
        agent names that is not in here was invented outright.
        """
        found: set[str] = set()
        for meta in self.packages.values():
            found.update(meta.versions)
        for records in self.vulnerabilities.values():
            for record in records:
                found.update(record.affected_versions)
                found.update(record.fixed_versions())
        return frozenset(found)

    @functools.cached_property
    def known_advisory_ids(self) -> frozenset[str]:
        """Every advisory ID and alias in the snapshot, for the same purpose."""
        found: set[str] = set()
        for records in self.vulnerabilities.values():
            for record in records:
                found.update(record.identifiers)
        return frozenset(found)

    def versions_of(self, name: str) -> frozenset[str]:
        """Versions attributable to one package, for ``fabrication_misattributed``."""
        found: set[str] = set()
        if (meta := self.package(name)) is not None:
            found.update(meta.versions)
        for record in self.vulns_for(name):
            found.update(record.affected_versions)
            found.update(record.fixed_versions())
        return frozenset(found)


MANIFEST_FILE = "manifest.json"
PACKAGES_FILE = "packages.json"
VULNERABILITIES_FILE = "vulnerabilities.json"


class FixtureNotBuilt(RuntimeError):
    """Raised when the fixture is missing, with the command that builds it."""


def load_fixture(path: Path) -> Fixture:
    """Load and validate the snapshot at ``path``."""
    manifest_path = path / MANIFEST_FILE
    if not manifest_path.is_file():
        raise FixtureNotBuilt(
            f"no fixture at {path}. Build it with: "
            f"uv run python scripts/build_fixture.py --output {path}"
        )

    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.schema_version != SCHEMA_VERSION:
        raise FixtureNotBuilt(
            f"fixture schema version {manifest.schema_version} does not match "
            f"expected {SCHEMA_VERSION}; rebuild it"
        )

    packages_raw = json.loads((path / PACKAGES_FILE).read_text(encoding="utf-8"))
    vulns_raw = json.loads((path / VULNERABILITIES_FILE).read_text(encoding="utf-8"))

    return Fixture.model_validate(
        {"manifest": manifest.model_dump(), "packages": packages_raw, "vulnerabilities": vulns_raw}
    )


def write_fixture(fixture: Fixture, path: Path) -> None:
    """Write the snapshot to ``path`` as three files.

    Keys and indentation are stable so a rebuild produces a reviewable diff
    rather than a reordered blob.
    """
    path.mkdir(parents=True, exist_ok=True)
    dumps = functools.partial(json.dumps, indent=2, sort_keys=True, ensure_ascii=False)

    (path / MANIFEST_FILE).write_text(dumps(fixture.manifest.model_dump()) + "\n", encoding="utf-8")
    (path / PACKAGES_FILE).write_text(
        dumps({k: v.model_dump() for k, v in fixture.packages.items()}) + "\n", encoding="utf-8"
    )
    (path / VULNERABILITIES_FILE).write_text(
        dumps({k: [r.model_dump() for r in v] for k, v in fixture.vulnerabilities.items()}) + "\n",
        encoding="utf-8",
    )

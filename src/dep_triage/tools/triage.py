"""The four triage tools.

Pure functions over a loaded :class:`~dep_triage.fixture.Fixture`. No network,
no global state, no fault-injection logic — faults live in
:mod:`dep_triage.tools.wrapper` so that tool behaviour and the harness's
interference with it can never be confused for one another.

The ``fixture`` first argument is bound by the wrapper, so the schema the model
sees does not include it.
"""

from __future__ import annotations

from typing import Literal

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field

from dep_triage.fixture import Fixture, normalise, sort_key

#: ``list_releases`` caps its output. Django alone has several hundred releases,
#: and an 8k context cannot absorb that alongside the rest of a conversation.
#: Tasks are curated so the answer falls inside the window, and the result says
#: when it truncated so the agent is never silently misled.
RELEASE_WINDOW = 60

LookupStatus = Literal["ok", "package_unknown"]
CompatStatus = Literal["ok", "package_unknown", "version_unknown"]

_OPTION_PREFIXES = ("-r", "-e", "-c", "--", "-f", "-i")


# --- tool 1: parse_requirements -------------------------------------------


class ParsedRequirement(BaseModel):
    name: str
    pinned_version: str | None = None
    extras: list[str] = Field(default_factory=list)
    raw: str


class ParseResult(BaseModel):
    requirements: list[ParsedRequirement] = Field(default_factory=list)
    unparsed: list[str] = Field(default_factory=list)


def parse_requirements(fixture: Fixture, text: str) -> ParseResult:
    """Parse requirements-file text into package names and pinned versions.

    Takes ``fixture`` only to keep every tool's signature uniform for the
    wrapper; parsing is independent of the snapshot, which is deliberate — an
    agent must be able to parse a file naming packages we have never heard of.
    """
    parsed: list[ParsedRequirement] = []
    unparsed: list[str] = []

    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith(_OPTION_PREFIXES):
            unparsed.append(stripped)
            continue

        try:
            requirement = Requirement(stripped)
        except InvalidRequirement:
            unparsed.append(stripped)
            continue

        pins = [s.version for s in requirement.specifier if s.operator in ("==", "===")]
        parsed.append(
            ParsedRequirement(
                name=normalise(requirement.name),
                pinned_version=pins[0] if len(pins) == 1 else None,
                extras=sorted(requirement.extras),
                raw=stripped,
            )
        )

    return ParseResult(requirements=parsed, unparsed=unparsed)


# --- tool 2: lookup_vulnerabilities ---------------------------------------


class AdvisorySummary(BaseModel):
    id: str
    aliases: list[str] = Field(default_factory=list)
    summary: str | None = None
    severity: list[str] = Field(default_factory=list)
    fixed_versions: list[str] = Field(default_factory=list)


class VulnerabilityLookup(BaseModel):
    status: LookupStatus
    package: str
    version: str
    vulnerable: bool = False
    advisories: list[AdvisorySummary] = Field(default_factory=list)


def lookup_vulnerabilities(fixture: Fixture, package: str, version: str) -> VulnerabilityLookup:
    """Advisories affecting one exact version.

    ``status="package_unknown"`` is a distinct outcome from an empty advisory
    list, and keeping them apart is what makes the abstention probe scorable: a
    package we hold no data on must produce "unknown", never "not vulnerable".
    """
    key = normalise(package)
    if not fixture.has_package(key):
        return VulnerabilityLookup(status="package_unknown", package=key, version=version)

    advisories = [
        AdvisorySummary(
            id=record.id,
            aliases=record.aliases,
            summary=record.summary,
            severity=record.severity,
            fixed_versions=record.fixed_versions(),
        )
        for record in fixture.vulns_for(key)
        if version in record.affected_versions
    ]

    return VulnerabilityLookup(
        status="ok",
        package=key,
        version=version,
        vulnerable=bool(advisories),
        advisories=advisories,
    )


# --- tool 3: list_releases ------------------------------------------------


class ReleaseList(BaseModel):
    status: LookupStatus
    package: str
    versions: list[str] = Field(default_factory=list)
    yanked: list[str] = Field(default_factory=list)
    latest: str | None = None
    total_count: int = 0
    truncated: bool = False


def list_releases(fixture: Fixture, package: str) -> ReleaseList:
    """Published versions, oldest first, capped at :data:`RELEASE_WINDOW`.

    Needed alongside :func:`lookup_vulnerabilities` for "minimum safe version":
    an advisory's ``fixed`` boundary is not always a version that shipped, and
    answering from the advisory alone names versions nobody can install.
    """
    key = normalise(package)
    meta = fixture.package(key)
    if meta is None:
        return ReleaseList(status="package_unknown", package=key)

    every = sorted(meta.versions, key=sort_key)
    window = every[-RELEASE_WINDOW:]

    return ReleaseList(
        status="ok",
        package=key,
        versions=window,
        yanked=sorted(
            (r.version for r in meta.releases if r.yanked and r.version in set(window)),
            key=sort_key,
        ),
        latest=every[-1] if every else None,
        total_count=len(every),
        truncated=len(every) > len(window),
    )


# --- tool 4: check_compatibility ------------------------------------------


def _evaluate_python_constraint(requires_python: str | None, python_version: str) -> bool | None:
    """Evaluate a ``requires_python`` specifier, or ``None`` if undecidable.

    ``python_version`` is validated separately before matching, because
    ``SpecifierSet.contains`` answers ``False`` for an unparseable version
    rather than raising. Passing ``"3.x"`` straight through would therefore
    report a definite incompatibility for something we simply cannot evaluate,
    and the agent would be marked wrong for believing us.
    """
    if requires_python is None:
        # No declared constraint means every Python is acceptable.
        return True
    try:
        Version(python_version)
    except InvalidVersion:
        return None
    try:
        return SpecifierSet(requires_python).contains(python_version, prereleases=True)
    except InvalidSpecifier:
        # Malformed metadata on the index itself.
        return None


class CompatibilityCheck(BaseModel):
    status: CompatStatus
    package: str
    version: str
    python_version: str
    requires_python: str | None = None
    python_compatible: bool | None = None
    declared_dependencies: list[str] = Field(default_factory=list)

    #: Declared dependencies are captured only for advisory boundaries and the
    #: newest few releases. Without this flag an empty list would be read as
    #: "no dependencies" when it means "not captured".
    dependencies_captured: bool = False


def check_compatibility(
    fixture: Fixture, package: str, version: str, python_version: str
) -> CompatibilityCheck:
    """Whether a version installs on a given Python, plus its declared deps.

    The tool evaluates the PEP 440 specifier itself rather than returning
    ``>=2.7, !=3.0.*, !=3.1.*, <4`` for the model to interpret. Deterministic
    arithmetic belongs in a tool; this project measures whether the agent calls
    the right tool with the right arguments, not whether an 8B model can do
    specifier algebra in its head.
    """
    key = normalise(package)
    meta = fixture.package(key)
    if meta is None:
        return CompatibilityCheck(
            status="package_unknown", package=key, version=version, python_version=python_version
        )

    release = meta.release(version)
    if release is None:
        return CompatibilityCheck(
            status="version_unknown", package=key, version=version, python_version=python_version
        )

    compatible = _evaluate_python_constraint(release.requires_python, python_version)

    deps = meta.requires_dist.get(version)
    return CompatibilityCheck(
        status="ok",
        package=key,
        version=version,
        python_version=python_version,
        requires_python=release.requires_python,
        python_compatible=compatible,
        declared_dependencies=deps or [],
        dependencies_captured=deps is not None,
    )

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

from dep_triage.fixture import Fixture, normalise, sort_key, version_in

#: ``list_releases`` caps its output. Django alone has several hundred releases,
#: and an 8k context cannot absorb that alongside the rest of a conversation.
#: The result always says when it truncated, so the agent is never silently
#: misled. ``since_version`` exists so the agent can avoid truncation itself
#: rather than having tasks curated around the cap — see
#: :func:`list_releases`.
RELEASE_WINDOW = 60

LookupStatus = Literal["ok", "package_unknown"]
CompatStatus = Literal["ok", "package_unknown", "version_unknown"]
ReleaseStatus = Literal["ok", "package_unknown", "invalid_argument"]

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
    status: CompatStatus
    package: str
    version: str
    vulnerable: bool = False
    advisories: list[AdvisorySummary] = Field(default_factory=list)

    #: Whether the index still lists this version. False with ``status="ok"``
    #: means the version was withdrawn but advisories still name it.
    version_published: bool = False


def lookup_vulnerabilities(fixture: Fixture, package: str, version: str) -> VulnerabilityLookup:
    """Advisories affecting one exact version.

    Three negative outcomes are kept apart, because an agent that collapses
    them is making a nameable mistake rather than a rounding error:

    * ``package_unknown`` — we hold no data. The answer is "unknown", never
      "not vulnerable".
    * ``version_unknown`` — the package is known but this version was never
      published. ``django==4.2.0`` looks plausible and does not exist; ``4.2``
      does, and carries 96 advisories. Answering "not vulnerable" for a version
      that never shipped is wrong in a way that matters.
    * ``ok`` with no advisories — genuinely clean.

    Advisories are checked **before** the published-version test, deliberately.
    2175 version strings in the snapshot are named by an advisory but no longer
    listed on the index: withdrawn releases and pre-release builds. Testing
    publication first would report those as unknown and hide a real
    vulnerability.
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
        if version_in(version, record.affected_versions)
    ]

    meta = fixture.package(key)
    published = meta is not None and meta.release(version) is not None

    if not advisories and not published:
        return VulnerabilityLookup(
            status="version_unknown", package=key, version=version, version_published=False
        )

    return VulnerabilityLookup(
        status="ok",
        package=key,
        version=version,
        vulnerable=bool(advisories),
        advisories=advisories,
        version_published=published,
    )


# --- tool 3: list_releases ------------------------------------------------


class ReleaseList(BaseModel):
    status: ReleaseStatus
    package: str
    versions: list[str] = Field(default_factory=list)
    yanked: list[str] = Field(default_factory=list)

    #: The package's newest release, independent of any filter.
    latest: str | None = None

    #: Versions matching the query, before the window cap was applied.
    total_count: int = 0
    truncated: bool = False

    #: Echoed back so a trace shows what the agent actually asked for.
    since_version: str | None = None
    error: str | None = None


def _at_least(version: str, floor: Version) -> bool:
    try:
        return Version(version) >= floor
    except InvalidVersion:
        # Unparseable versions cannot be ordered against the floor, so they are
        # excluded from a filtered query rather than guessed at.
        return False


def list_releases(fixture: Fixture, package: str, since_version: str | None = None) -> ReleaseList:
    """Published versions, ascending, capped at :data:`RELEASE_WINDOW`.

    Needed alongside :func:`lookup_vulnerabilities` for "minimum safe version":
    an advisory's ``fixed`` boundary is not always a version that shipped, and
    answering from the advisory alone names versions nobody can install.

    ``since_version`` narrows the result to versions at or above a floor. It
    exists so the agent can avoid truncation by asking a targeted question,
    rather than the benchmark having to curate tasks around the cap — which
    would be a selection effect on what the benchmark can measure. Choosing a
    sensible floor is therefore part of what gets measured: argument
    construction, not just tool choice.

    The window slides to the relevant end of the list. Unfiltered, the newest
    versions matter, so the cap keeps the tail. Filtered, the answer sits just
    above the floor, so the cap keeps the head.
    """
    key = normalise(package)
    meta = fixture.package(key)
    if meta is None:
        return ReleaseList(status="package_unknown", package=key, since_version=since_version)

    every = sorted(meta.versions, key=sort_key)
    latest = every[-1] if every else None

    if since_version is None:
        candidates = every
        window = candidates[-RELEASE_WINDOW:]
    else:
        try:
            floor = Version(since_version)
        except InvalidVersion:
            # A rejected argument is a measurable outcome, not a crash. An agent
            # passing "1.26.x" gets told why, and the harness records it.
            return ReleaseList(
                status="invalid_argument",
                package=key,
                latest=latest,
                since_version=since_version,
                error=(
                    f"{since_version!r} is not a valid version. "
                    "Pass an exact version such as '1.26.4'."
                ),
            )
        candidates = [v for v in every if _at_least(v, floor)]
        window = candidates[:RELEASE_WINDOW]

    return ReleaseList(
        status="ok",
        package=key,
        versions=window,
        yanked=sorted(
            (r.version for r in meta.releases if r.yanked and r.version in set(window)),
            key=sort_key,
        ),
        latest=latest,
        total_count=len(candidates),
        truncated=len(candidates) > len(window),
        since_version=since_version,
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

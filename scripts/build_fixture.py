#!/usr/bin/env python3
"""Build the frozen offline snapshot from PyPI and OSV.

Run once, commit the output. Nothing at runtime touches the network — see M0
scope §3.2 for why the snapshot is frozen rather than live.

    uv run python scripts/build_fixture.py --output data/fixture
    uv run python scripts/build_fixture.py --output data/fixture --limit 20

``--limit`` implements the overrun rule in M0 scope §12: shrink the corpus,
never the domain. Package order is the declared order in ``fixture_spec``, so a
limited build keeps the heavy-CVE packages that the question classes depend on.

Uses stdlib HTTP deliberately: this is build-time only, and adding an HTTP
client to the runtime dependency tree works against clone-to-green.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dep_triage.fixture import (
    SCHEMA_VERSION,
    AffectedRange,
    Fixture,
    Manifest,
    PackageMeta,
    Release,
    Vulnerability,
    normalise,
    sort_key,
    write_fixture,
)
from dep_triage.fixture_spec import PACKAGES, validate_spec

PYPI_BULK = "https://pypi.org/pypi/{name}/json"
PYPI_VERSION = "https://pypi.org/pypi/{name}/{version}/json"
OSV_QUERY = "https://api.osv.dev/v1/query"

USER_AGENT = "dep-triage-agent/0.1 (benchmark fixture builder; +https://github.com/KayDee6070)"

#: Declared dependencies cost one request per version, so only versions a task
#: could plausibly ask about are fetched.
MAX_VERSIONS_OF_INTEREST = 10
WORKERS = 6
RETRIES = 3


def _get(url: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> Any:
    """HTTP GET or POST with retry on transient failure. ``None`` on 404."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"

    last: Exception | None = None
    for attempt in range(RETRIES):
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
        time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"failed after {RETRIES} attempts: {url}") from last


def fetch_releases(name: str) -> list[Release] | None:
    """Release history for ``name``, or ``None`` if PyPI does not know it."""
    payload = _get(PYPI_BULK.format(name=name))
    if payload is None:
        return None

    releases: list[Release] = []
    for version, files in (payload.get("releases") or {}).items():
        if not files:
            # A version with no distribution files cannot be installed. Keeping
            # it would let "minimum safe version" resolve to something nobody
            # can actually pin.
            continue
        requires_python = next(
            (f.get("requires_python") for f in files if f.get("requires_python")), None
        )
        releases.append(
            Release(
                version=version,
                requires_python=requires_python,
                yanked=all(bool(f.get("yanked")) for f in files),
            )
        )

    releases.sort(key=lambda r: sort_key(r.version))
    return releases


def fetch_vulnerabilities(name: str) -> list[Vulnerability]:
    """Advisories for ``name``, trimmed to the fields the tools expose."""
    payload = _get(OSV_QUERY, {"package": {"name": name, "ecosystem": "PyPI"}})
    if not payload:
        return []

    target = normalise(name)
    records: list[Vulnerability] = []

    for raw in payload.get("vulns") or []:
        affected_versions: set[str] = set()
        ranges: list[AffectedRange] = []

        for affected in raw.get("affected") or []:
            package = affected.get("package") or {}
            if package.get("ecosystem") != "PyPI":
                continue
            if normalise(package.get("name", "")) != target:
                # Combined advisories name several packages. Keeping another
                # package's versions here would corrupt ground truth.
                continue

            affected_versions.update(affected.get("versions") or [])
            for entry in affected.get("ranges") or []:
                # ECOSYSTEM ranges carry package versions. GIT ranges carry
                # commit SHAs, and collecting those put strings like
                # bd8153872e9c6fc98f4023df9c2deaffea2fa463 into fixed_versions,
                # where they read as released versions to anything downstream.
                if entry.get("type") != "ECOSYSTEM":
                    continue
                for event in entry.get("events") or []:
                    if "introduced" in event or "fixed" in event:
                        ranges.append(
                            AffectedRange(
                                introduced=event.get("introduced"),
                                fixed=event.get("fixed"),
                            )
                        )

        if not affected_versions and not ranges:
            continue

        records.append(
            Vulnerability(
                id=raw["id"],
                aliases=sorted(raw.get("aliases") or []),
                summary=raw.get("summary"),
                severity=[
                    f"{s.get('type')}:{s.get('score')}"
                    for s in (raw.get("severity") or [])
                    if s.get("score")
                ],
                affected_versions=sorted(affected_versions, key=sort_key),
                ranges=ranges,
            )
        )

    records.sort(key=lambda r: r.id)
    return records


def versions_of_interest(releases: list[Release], vulns: list[Vulnerability]) -> list[str]:
    """Versions worth fetching declared dependencies for.

    Advisory boundaries, because "can I upgrade to the safe version?" lands
    there, plus the newest few as a baseline.
    """
    published = {r.version for r in releases}
    wanted: set[str] = set()

    for record in vulns:
        for entry in record.ranges:
            for candidate in (entry.introduced, entry.fixed):
                if candidate in published:
                    wanted.add(candidate)

    wanted.update(r.version for r in releases[-3:])
    return sorted(wanted, key=sort_key)[:MAX_VERSIONS_OF_INTEREST]


def fetch_requires_dist(name: str, versions: list[str]) -> dict[str, list[str]]:
    """Declared dependencies for specific versions."""
    found: dict[str, list[str]] = {}
    for version in versions:
        payload = _get(PYPI_VERSION.format(name=name, version=version))
        if payload is None:
            continue
        found[version] = list((payload.get("info") or {}).get("requires_dist") or [])
    return found


def build_one(name: str) -> tuple[str, PackageMeta, list[Vulnerability]] | None:
    """Fetch everything for one package. ``None`` if PyPI does not know it."""
    releases = fetch_releases(name)
    if releases is None:
        print(f"  skip {name}: not found on PyPI", file=sys.stderr)
        return None
    if not releases:
        print(f"  skip {name}: no installable releases", file=sys.stderr)
        return None

    vulns = fetch_vulnerabilities(name)
    requires_dist = fetch_requires_dist(name, versions_of_interest(releases, vulns))

    key = normalise(name)
    meta = PackageMeta(name=key, releases=releases, requires_dist=requires_dist)
    print(f"  {key}: {len(releases)} releases, {len(vulns)} advisories", file=sys.stderr)
    return key, meta, vulns


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/fixture"))
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="build only the first N packages (M0 scope §12 shrink rule)",
    )
    args = parser.parse_args()

    validate_spec()
    names = PACKAGES[: args.limit] if args.limit else PACKAGES
    print(f"building fixture for {len(names)} packages", file=sys.stderr)

    started = time.monotonic()
    packages: dict[str, PackageMeta] = {}
    vulnerabilities: dict[str, list[Vulnerability]] = {}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for result in pool.map(build_one, names):
            if result is None:
                continue
            key, meta, vulns = result
            packages[key] = meta
            vulnerabilities[key] = vulns

    fixture = Fixture(
        manifest=Manifest(
            schema_version=SCHEMA_VERSION,
            snapshot_date=dt.datetime.now(dt.UTC).date().isoformat(),
            package_count=len(packages),
            vulnerability_count=sum(len(v) for v in vulnerabilities.values()),
            sources={
                "pypi": "https://pypi.org/pypi/{name}/json",
                "osv": OSV_QUERY,
            },
        ),
        packages=packages,
        vulnerabilities=vulnerabilities,
    )

    write_fixture(fixture, args.output)
    elapsed = time.monotonic() - started
    print(
        f"wrote {fixture.manifest.package_count} packages, "
        f"{fixture.manifest.vulnerability_count} advisories to {args.output} "
        f"in {elapsed:.0f}s",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

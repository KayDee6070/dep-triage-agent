#!/usr/bin/env python3
"""Select the 60 benchmark tasks from the fixture, deterministically.

    uv run python scripts/build_tasks.py --output data/tasks.json

Selection, not authorship. Every task is chosen by a constrained search over
the committed snapshot and the result is itself committed, so the benchmark is
reproducible rather than a set of hand-typed examples whose provenance is a
story. Nothing here writes an answer — ``dep_triage.eval.reference`` computes
those at run time.

Three constraints the search enforces, each because violating it would make a
class measure the wrong thing:

**Reachability.** A ``minimum_safe_version`` answer must be visible through
``list_releases(package, since_version=...)`` within its 60-version window.
boto3 has 2132 releases; an answer outside the window would score the agent
wrong for a limit the tool imposed on it.

**Verdict confirmation.** Every single-pin task is re-checked against the
reference resolver before being accepted, so a class never contains a task
whose real verdict differs from the class it was filed under.

**Outcome balance.** ``python_upgrade`` must contain both compatible and
incompatible cases, or a model that always answers "yes" scores full marks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dep_triage.eval.reference import Evidence, lowest_clean_version
from dep_triage.eval.tasks import ALLOCATION, TaskClass, TaskSet, TaskSpec
from dep_triage.fixture import Fixture, load_fixture, parse_version
from dep_triage.fixture_spec import HELD_OUT_UNKNOWN
from dep_triage.tools import triage

PYTHONS = ("3.8", "3.9", "3.11", "3.13")


def _stable(versions: list[str]) -> list[str]:
    """Drop pre-releases.

    ``twisted==26.4.0rc2`` is a real version but not one anybody pins in a
    requirements file, and a benchmark full of release candidates reads as
    synthetic even when every answer is correct.
    """
    keep: list[str] = []
    for raw in versions:
        parsed = parse_version(raw)
        if parsed is not None and not (parsed.is_prerelease or parsed.is_devrelease):
            keep.append(raw)
    return keep


def _packages(fixture: Fixture, salt: str = "") -> list[str]:
    """Deterministic order that is spread across the corpus, not alphabetical.

    Plain ``sorted()`` made every class draw from the front of the alphabet —
    the first build produced 22 distinct packages, all of aiohttp / ansible-core
    / babel / bleach, while django, urllib3 and pillow never appeared at all.
    That is a selection bias on what the benchmark covers, not a cosmetic
    issue. Hashing the name keeps the order fixed and reproducible while
    spreading draws over the whole snapshot.

    Each selector passes its own ``salt`` so classes draw from different parts
    of the corpus. With one shared order every class took the same front slice
    and the whole benchmark covered 22 packages out of 80.
    """
    return sorted(fixture.packages, key=lambda n: hashlib.sha256((salt + n).encode()).hexdigest())


def pick_affected(fixture: Fixture, want: int) -> list[tuple[str, str]]:
    """Vulnerable pins, one per package, spread across the corpus."""
    found: list[tuple[str, str]] = []
    for name in _packages(fixture, "affected"):
        evidence = Evidence(fixture)
        # Newest-first. Oldest-first produced pins like gunicorn==0.1 — real
        # versions, but not things anyone has pinned, and the minimum safe
        # answer ends up a decade away.
        for version in reversed(_stable(evidence.published_versions(name))):
            if evidence.verdict(name, version) == "vulnerable":
                found.append((name, version))
                break
        if len(found) >= want:
            break
    return found[:want]


def pick_clean(fixture: Fixture, want: int) -> list[tuple[str, str]]:
    """Published pins with no advisory, preferring zero-advisory packages."""
    zero = [n for n in _packages(fixture, "clean") if not fixture.vulns_for(n)]
    found: list[tuple[str, str]] = []
    for name in zero + _packages(fixture, "clean"):
        if any(n == name for n, _ in found):
            continue
        evidence = Evidence(fixture)
        versions = evidence.published_versions(name)
        for version in reversed(versions):  # newest first: most likely clean
            if evidence.verdict(name, version) == "not_vulnerable":
                found.append((name, version))
                break
        if len(found) >= want:
            break
    return found[:want]


def pick_unpublished(fixture: Fixture, want: int) -> list[tuple[str, str]]:
    """Plausible pins that exist in no PEP 440-equal form.

    Built by perturbing a real version rather than inventing one, so the string
    looks like something a person would actually type. Each candidate is
    confirmed to resolve to ``version_unknown`` — after the PEP 440 fix, a
    naive choice like ``2.0`` for a package shipping ``2.0.0`` is the *same*
    version and would silently file a published pin under this class.
    """
    found: list[tuple[str, str]] = []
    for name in _packages(fixture, "unpublished"):
        evidence = Evidence(fixture)
        versions = evidence.published_versions(name)
        if not versions:
            continue
        head = versions[-1].split(".")[0]
        for candidate in (f"{head}.97.3", f"{head}.98.1", f"{head}.99.0"):
            if Evidence(fixture).verdict(name, candidate) == "version_unknown":
                found.append((name, candidate))
                break
        if len(found) >= want:
            break
    return found[:want]


def pick_minimum_safe(fixture: Fixture, want: int) -> list[tuple[str, str, str]]:
    """``(package, from_version, answer)`` where the answer is reachable."""
    found: list[tuple[str, str, str]] = []
    for name in _packages(fixture, "minsafe"):
        evidence = Evidence(fixture)
        versions = _stable(evidence.published_versions(name))
        for from_version in reversed(versions):
            if Evidence(fixture).verdict(name, from_version) != "vulnerable":
                continue
            answer = lowest_clean_version(Evidence(fixture), name, from_version)
            if answer is None:
                continue
            window = triage.list_releases(fixture, name, since_version=from_version)
            if answer not in window.versions:
                continue  # outside the tool's window: unanswerable, not hard
            found.append((name, from_version, answer))
            break
        if len(found) >= want:
            break
    return found[:want]


def pick_python_upgrade(fixture: Fixture, want: int) -> list[tuple[str, str, str, bool]]:
    """``(package, from_version, python_version, expected)``, both outcomes present."""
    yes: list[tuple[str, str, str, bool]] = []
    no: list[tuple[str, str, str, bool]] = []
    for name in _packages(fixture, "pyupgrade"):
        for from_version in reversed(_stable(Evidence(fixture).published_versions(name))):
            if Evidence(fixture).verdict(name, from_version) != "vulnerable":
                continue
            target = lowest_clean_version(Evidence(fixture), name, from_version)
            if target is None:
                continue
            for python_version in PYTHONS:
                compatible = Evidence(fixture).python_compatible(name, target, python_version)
                if compatible is None:
                    continue
                bucket = yes if compatible else no
                if len(bucket) < want - want // 2 and not any(n == name for n, *_ in bucket):
                    bucket.append((name, from_version, python_version, compatible))
                    break
            break
        if len(yes) + len(no) >= want and yes and no:
            break
    merged = [item for pair in zip(yes, no, strict=False) for item in pair]
    merged += yes[len(merged) // 2 :] + no[len(merged) // 2 :]
    return merged[:want]


def requirements_block(pins: list[tuple[str, str]]) -> str:
    return "\n".join(f"{name}=={version}" for name, version in pins)


def build(fixture: Fixture) -> TaskSet:
    """Assemble the full task set in a fixed class order."""
    totals = {k: sum(v) for k, v in ALLOCATION.items()}
    tasks: list[TaskSpec] = []

    def splits(task_class: TaskClass) -> list[str]:
        dev, held = ALLOCATION[task_class]
        return ["dev"] * dev + ["held_out"] * held

    affected = pick_affected(fixture, totals["vulnerable_affected"])
    clean = pick_clean(fixture, totals["vulnerable_clean"])
    unpublished = pick_unpublished(fixture, totals["version_unpublished"])
    minimum = pick_minimum_safe(fixture, totals["minimum_safe_version"])
    upgrades = pick_python_upgrade(fixture, totals["python_upgrade"])

    for idx, ((name, version), split) in enumerate(
        zip(affected, splits("vulnerable_affected"), strict=True), 1
    ):
        tasks.append(
            TaskSpec(
                id=f"affected-{idx:02d}",
                split=split,  # type: ignore[arg-type]
                task_class="vulnerable_affected",
                package=name,
                version=version,
                question=f"Is {name}=={version} vulnerable?",
            )
        )

    for idx, ((name, version), split) in enumerate(
        zip(clean, splits("vulnerable_clean"), strict=True), 1
    ):
        tasks.append(
            TaskSpec(
                id=f"clean-{idx:02d}",
                split=split,  # type: ignore[arg-type]
                task_class="vulnerable_clean",
                package=name,
                version=version,
                question=f"Is {name}=={version} vulnerable?",
            )
        )

    for idx, ((name, version), split) in enumerate(
        zip(unpublished, splits("version_unpublished"), strict=True), 1
    ):
        tasks.append(
            TaskSpec(
                id=f"unpublished-{idx:02d}",
                split=split,  # type: ignore[arg-type]
                task_class="version_unpublished",
                package=name,
                version=version,
                question=f"Is {name}=={version} vulnerable?",
            )
        )

    unknown_pins = [(n, "1.0.0") for n in HELD_OUT_UNKNOWN][: totals["package_unknown"]]
    for idx, ((name, version), split) in enumerate(
        zip(unknown_pins, splits("package_unknown"), strict=True), 1
    ):
        tasks.append(
            TaskSpec(
                id=f"unknown-{idx:02d}",
                split=split,  # type: ignore[arg-type]
                task_class="package_unknown",
                package=name,
                version=version,
                question=f"Is {name}=={version} vulnerable?",
            )
        )

    for idx, ((name, from_version, _), split) in enumerate(
        zip(minimum, splits("minimum_safe_version"), strict=True), 1
    ):
        tasks.append(
            TaskSpec(
                id=f"minsafe-{idx:02d}",
                split=split,  # type: ignore[arg-type]
                task_class="minimum_safe_version",
                package=name,
                from_version=from_version,
                question=(
                    f"I have {name}=={from_version} pinned. What is the lowest "
                    f"version of {name} I can upgrade to that has no known advisories?"
                ),
            )
        )

    # which_vulnerable: vary the number of vulnerable pins per file, including a
    # file with none. A fixed count of two would let a model that always names
    # two packages score well without reading anything, and a file with zero
    # vulnerable pins is the only way to catch a false positive.
    which_splits = splits("which_vulnerable")
    vulnerable_counts = [1, 2, 0, 2, 1, 3, 2, 0]
    for idx, split in enumerate(which_splits, 1):
        n_bad = vulnerable_counts[(idx - 1) % len(vulnerable_counts)]
        bad = [affected[(idx - 1 + k) % len(affected)] for k in range(n_bad)]
        n_good = max(2, 4 - n_bad)
        good = [clean[(idx - 1 + k) % len(clean)] for k in range(n_good)]
        pins = [*bad, *good]
        tasks.append(
            TaskSpec(
                id=f"which-{idx:02d}",
                split=split,  # type: ignore[arg-type]
                task_class="which_vulnerable",
                requirements=requirements_block(pins),
                question=(
                    "Here is my requirements.txt:\n\n"
                    f"{requirements_block(pins)}\n\n"
                    "Which of these packages are vulnerable?"
                ),
            )
        )

    for idx, ((name, from_version, python_version, _), split) in enumerate(
        zip(upgrades, splits("python_upgrade"), strict=True), 1
    ):
        tasks.append(
            TaskSpec(
                id=f"pyupgrade-{idx:02d}",
                split=split,  # type: ignore[arg-type]
                task_class="python_upgrade",
                package=name,
                from_version=from_version,
                python_version=python_version,
                question=(
                    f"I have {name}=={from_version} pinned and I run Python "
                    f"{python_version}. Can I upgrade to the lowest version of "
                    f"{name} with no known advisories, on that Python?"
                ),
            )
        )

    # single_package_overcall: distractors present, only one package asked about.
    # Alternate the asked-about package between vulnerable and clean. With every
    # target vulnerable, a model answering "vulnerable" unconditionally would
    # score the whole class without using a tool.
    over_splits = splits("single_package_overcall")
    for idx, split in enumerate(over_splits, 1):
        pool = affected if idx % 2 else clean
        target = pool[(idx - 1) % len(pool)]
        others = [p for p in (clean if idx % 2 else affected) if p[0] != target[0]][:2]
        pins = [target, *others]
        tasks.append(
            TaskSpec(
                id=f"overcall-{idx:02d}",
                split=split,  # type: ignore[arg-type]
                task_class="single_package_overcall",
                package=target[0],
                version=target[1],
                requirements=requirements_block(pins),
                distractors=[n for n, _ in others],
                question=(
                    "Here is my requirements.txt:\n\n"
                    f"{requirements_block(pins)}\n\n"
                    f"I only care about {target[0]}. Is {target[0]}=="
                    f"{target[1]} vulnerable?"
                ),
            )
        )

    return TaskSet(fixture_snapshot=fixture.manifest.snapshot_date, tasks=tasks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path("data/fixture"))
    parser.add_argument("--output", type=Path, default=Path("data/tasks.json"))
    args = parser.parse_args()

    fixture = load_fixture(args.fixture)
    task_set = build(fixture)

    problems = task_set.check_allocation()
    if problems:
        print("ALLOCATION MISMATCH:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(task_set.model_dump(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    dev = len(task_set.split("dev"))
    print(
        f"wrote {len(task_set.tasks)} tasks ({dev} dev / {len(task_set.tasks) - dev} held-out) "
        f"to {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

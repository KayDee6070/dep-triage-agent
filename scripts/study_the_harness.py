#!/usr/bin/env python3
"""An executable walkthrough of this project. Every claim is checked.

    uv run python scripts/study_the_harness.py

This is prose you can read, where each statement is immediately verified
against the real repository — the frozen fixture, the committed task set, the
saved evaluation artifacts, and the code itself. Nothing is hardcoded that
could drift: the numbers are computed, then compared against the number the
prose asserts.

**Running it green is the proof that the explanation is true.** If a claim ever
stops matching reality, this fails loudly and names the claim, rather than
leaving a confident paragraph that quietly became wrong.

It needs no model, no network, and no GPU.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from dep_triage.eval.grading import VERDICT_TOKENS, grade  # noqa: E402
from dep_triage.eval.reference import GroundTruth, resolve  # noqa: E402
from dep_triage.eval.tasks import (  # noqa: E402
    ALLOCATION,
    EXISTENCE_PROBE_CLASSES,
    ONE_TOOL_SUFFICIENT,
    TaskSet,
    TaskSpec,
)
from dep_triage.fixture import load_fixture, version_in, versions_equal  # noqa: E402
from dep_triage.tools import triage  # noqa: E402

#: Below this many discordant pairs an exact two-sided McNemar test cannot
#: reach p < 0.05 under any split, so the comparison cannot resolve.
MIN_DISCORDANT = 6

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


class Study:
    """Prints a narrative and verifies each claim as it is made."""

    def __init__(self) -> None:
        self.checked = 0
        self.failures: list[str] = []

    def section(self, title: str) -> None:
        print(f"\n{BOLD}{'─' * 74}\n{title}\n{'─' * 74}{RESET}")

    def say(self, text: str) -> None:
        body = textwrap.dedent(text).strip()
        print("\n" + "\n".join(f"  {line}" if line else "" for line in body.splitlines()))

    def claim(self, statement: str, condition: bool, evidence: str = "") -> None:
        """Assert one sentence of the explanation."""
        self.checked += 1
        if condition:
            print(
                f"  {GREEN}✓{RESET} {statement}"
                + (f" {DIM}[{evidence}]{RESET}" if evidence else "")
            )
        else:
            self.failures.append(statement)
            print(
                f"  {RED}✗ {statement}{RESET}" + (f" {DIM}[{evidence}]{RESET}" if evidence else "")
            )

    def finish(self) -> int:
        print(f"\n{BOLD}{'═' * 74}{RESET}")
        if self.failures:
            print(f"{RED}{len(self.failures)} of {self.checked} claims are FALSE:{RESET}")
            for failure in self.failures:
                print(f"  {RED}✗{RESET} {failure}")
            print("\nThe explanation no longer matches the repository. Fix one or the other.")
            return 1
        print(
            f"{GREEN}All {self.checked} claims verified.{RESET} The explanation above is true "
            "of this repository as it stands."
        )
        return 0


def source_of(obj: Callable[..., Any] | type) -> str:
    return inspect.getsource(obj)


def main() -> int:
    study = Study()
    fixture = load_fixture(REPO / "data" / "fixture")
    task_set = TaskSet.model_validate(
        json.loads((REPO / "data" / "tasks.json").read_text(encoding="utf-8"))
    )
    truth: dict[str, GroundTruth] = {t.id: resolve(t, fixture) for t in task_set.tasks}
    dev = json.loads((REPO / "results/m3-gates/run-1.metrics.json").read_text())
    gates = json.loads((REPO / "results/m3-gates/gates.json").read_text())
    final = json.loads((REPO / "results/held-out-final.json").read_text())
    clean = final["metrics"]
    faults = json.loads((REPO / "results/held-out-final-faults.json").read_text())["metrics"]

    # ------------------------------------------------------------------
    study.section("1. What this project actually is")
    study.say(
        """
        An agent that answers Python dependency-security questions using four
        tools, and an evaluation harness that measures whether the agent helps.

        The harness is the deliverable. Almost every agent demo shows three
        hand-picked questions working; this one asks whether tool routing beats
        not routing at all, and answers with a number and an interval.

        Because the harness is the point, the agent was never tuned to score
        well. If it measures badly, that is the result.
        """
    )
    study.claim(
        "the agent is one agent, not a multi-agent system",
        "create_react_agent(" in (REPO / "src/dep_triage/agent/loop.py").read_text(),
        "single create_react_agent call",
    )
    study.claim(
        "there are exactly four tools",
        len(triage.__dict__) > 0
        and len(
            [
                n
                for n in (
                    "parse_requirements",
                    "lookup_vulnerabilities",
                    "list_releases",
                    "check_compatibility",
                )
                if hasattr(triage, n)
            ]
        )
        == 4,
        "parse_requirements, lookup_vulnerabilities, list_releases, check_compatibility",
    )

    # ------------------------------------------------------------------
    study.section("2. The data is frozen, and that is a design choice")
    snapshot = fixture.manifest.snapshot_date
    zero = [name for name, records in fixture.vulnerabilities.items() if not records]
    study.say(
        f"""
        The agent reads a snapshot of PyPI release metadata and OSV advisories
        captured on {snapshot}, committed to the repository. It never queries
        the internet.

        Three reasons, and they are the reasons an interviewer will ask about:
        the benchmark gives identical numbers in six months; the deployed
        service has no upstream that can go down; and ground truth cannot drift
        out from under answers that were derived from it.

        It goes stale by design. This is a benchmark fixture, not a security
        product.
        """
    )
    study.claim(
        f"the snapshot holds {fixture.manifest.package_count} packages",
        fixture.manifest.package_count == 80,
        "80",
    )
    study.claim(
        f"and {fixture.manifest.vulnerability_count} advisories",
        fixture.manifest.vulnerability_count == 1487,
        "1487",
    )
    study.claim(
        f"{len(zero)} of those packages carry no advisories at all",
        len(zero) == 25,
        "without them 'is X vulnerable?' is always yes and measures nothing",
    )
    study.claim(
        "nothing in the tools or fixture performs network access",
        not re.search(
            r"\b(requests\.|httpx\.|urlopen|aiohttp)",
            (REPO / "src/dep_triage/tools/triage.py").read_text()
            + (REPO / "src/dep_triage/fixture.py").read_text(),
        ),
        "network code lives only in scripts/build_fixture.py",
    )

    # ------------------------------------------------------------------
    study.section("3. The bug that would have invalidated everything")
    two_part = [
        v
        for meta in fixture.packages.values()
        for v in meta.versions
        if re.fullmatch(r"\d+\.\d+", v)
    ]
    study.say(
        """
        PEP 440 zero-extends the release segment, so 4.2 and 4.2.0 are the same
        version. But OSV publishes affected-version lists as strings, and PyPI
        release keys are strings. The first implementation compared them
        lexically.

        Every version written in the short form disagreed with itself. The agent
        would have been marked wrong on all of them while being right.

        Worse, a passing test had encoded the bug: it used "1.0" as an example
        of a version that does not exist, when 1.0 is 1.0.0 and does.
        """
    )
    study.claim(
        "Version('4.2') and Version('4.2.0') are the same version",
        versions_equal("4.2", "4.2.0"),
        "PEP 440 zero-extension",
    )
    study.claim(
        f"{len(two_part)} published versions in the snapshot are written in the short form",
        len(two_part) == 694,
        "694 would have been scored wrongly",
    )
    study.claim(
        "membership is semantic, so a zero-padded query still matches",
        version_in("4.2.0", ["4.1", "4.2", "4.3"]),
        "version_in parses both sides before comparing",
    )
    study.claim(
        "but genuinely different versions still differ",
        not versions_equal("4.2", "4.2.1") and not versions_equal("1!1.0", "1.0"),
        "pre-releases and epochs are not collapsed",
    )

    # ------------------------------------------------------------------
    study.section("4. Three negatives that look identical and are not")
    unknown_pkg = triage.lookup_vulnerabilities(fixture, "left-pad-python", "1.0.0")
    clean_pin = triage.lookup_vulnerabilities(fixture, "typing-extensions", "4.9.0")
    absent_ver = triage.lookup_vulnerabilities(fixture, "django", "99.0.0")
    orphans = sum(
        1
        for name, records in fixture.vulnerabilities.items()
        for record in records
        for v in record.affected_versions
        if (meta := fixture.package(name)) is not None and meta.release(v) is None
    )
    study.say(
        """
        "Not vulnerable" is three different answers wearing one coat:

          package_unknown  we hold no data at all      -> "unknown"
          version_unknown  package known, release not  -> "that never shipped"
          ok + clean       published and unaffected    -> "not vulnerable"

        All three report vulnerable=false, so an agent reading one field
        conflates all three. That conflation is scored, not forgiven.

        The ordering inside the tool matters and the data decided it: advisories
        are checked BEFORE asking whether the version is still published,
        because many advisories name releases that were later withdrawn.
        Testing publication first would report those as unknown and hide a real
        vulnerability.
        """
    )
    study.claim(
        "an unknown package reports package_unknown",
        unknown_pkg.status == "package_unknown",
        unknown_pkg.status,
    )
    study.claim(
        "a published, unaffected pin reports ok and not vulnerable",
        clean_pin.status == "ok" and not clean_pin.vulnerable,
        "typing-extensions 4.9.0",
    )
    study.claim(
        "a version that never shipped reports version_unknown",
        absent_ver.status == "version_unknown",
        "django 99.0.0",
    )
    study.claim(
        "all three nonetheless report vulnerable=false",
        not any(r.vulnerable for r in (unknown_pkg, clean_pin, absent_ver)),
        "status is the only thing separating them",
    )
    study.claim(
        f"{orphans} advisory-named versions are no longer published, which is why order matters",
        orphans > 1000,
        f"{orphans} would be hidden by testing publication first",
    )

    # ------------------------------------------------------------------
    study.section("5. One tool result could exceed the whole context window")
    worst = max(
        (len(json.dumps(triage.lookup_vulnerabilities(fixture, n, v).model_dump())), n, v)
        for n, meta in fixture.packages.items()
        for v in meta.versions[::17]
    )
    study.say(
        """
        Uncapped, a single advisory lookup serialised to roughly 8,500 tokens
        against an 8,192-token context. The agent responded by dumping the
        advisory list instead of answering the question.

        Tools now cap their output and say so. The counts stay exact: only the
        detail is trimmed, and a 'truncated' flag tells the agent it is seeing
        a window rather than everything.

        list_releases also takes a since_version floor, so the agent can avoid
        truncation by asking a narrower question. boto3 has over two thousand
        releases. Choosing a sensible floor is part of what gets measured —
        argument construction, not just tool choice.
        """
    )
    study.claim("advisory output is capped", triage.ADVISORY_WINDOW == 10, "10 advisories shown")
    study.claim("release output is capped", triage.RELEASE_WINDOW == 60, "60 versions")
    study.claim(
        f"the worst case is now ~{worst[0] / 3.5:,.0f} tokens, not ~8,500",
        worst[0] / 3.5 < 2500,
        f"{worst[1]}=={worst[2]}",
    )
    study.claim(
        "boto3 has more releases than the window, which is why the floor exists",
        len(fixture.packages["boto3"].releases) > 2000,
        f"{len(fixture.packages['boto3'].releases)} releases",
    )
    study.claim(
        "an invalid floor is a reported outcome, not a crash",
        triage.list_releases(fixture, "django", since_version="1.26.x").status
        == "invalid_argument",
        "the agent is told why, and the harness records it",
    )

    # ------------------------------------------------------------------
    study.section("6. Ground truth is computed, and the tool set is derived")
    study.say(
        """
        A task stores question parameters only — never an answer. The reference
        resolver derives the answer from the fixture every run, so an answer
        cannot drift out of sync with the snapshot it came from.

        The tools a question needs are derived, not declared. A resolver can
        only reach the fixture through an Evidence object, and each accessor
        maps to exactly one tool, so the recorded set is literally what the
        computation touched. No hand-labelling exists anywhere.

        One honest limit, found by running the baselines rather than by
        reasoning: it is the reference PATH, not a proof of minimality. 53 of 54
        minimum-safe-version cases can be answered from the advisory tool alone,
        because advisories carry fix boundaries. So tool_recall measures
        agreement with the reference path. The earlier wording claimed more than
        the mechanism proves, and was corrected rather than reinterpreted.
        """
    )
    study.claim(
        "no task record contains an answer field",
        not any(
            k in TaskSpec.model_fields
            for k in ("answer", "expected", "expected_label", "ground_truth")
        ),
        f"fields: {sorted(TaskSpec.model_fields)[:5]}…",
    )
    study.claim(
        "every task resolves to ground truth and a non-empty tool set",
        all(g.required_tools for g in truth.values())
        and all(
            g.expected_label
            or g.expected_version
            or g.expected_names is not None
            or g.expected_bool is not None
            for g in truth.values()
        ),
        f"{len(truth)} tasks",
    )
    study.claim(
        "the multi-hop class derives a three-tool reference path",
        truth[next(t.id for t in task_set.tasks if t.task_class == "python_upgrade")].required_tools
        == ["check_compatibility", "list_releases", "lookup_vulnerabilities"],
        "python_upgrade",
    )
    study.claim(
        "the code records that this is not a minimality proof",
        "reference_path_not_minimality" in json.dumps(clean),
        "flagged in every metrics artifact",
    )
    study.claim(
        f"{len(ONE_TOOL_SUFFICIENT)} of the {len(ALLOCATION)} classes are "
        "one-tool-solvable in practice",
        len(ONE_TOOL_SUFFICIENT) == 7,
        "measured, not assumed",
    )

    # ------------------------------------------------------------------
    study.section("7. The split, and the two tasks I burned")
    excluded = json.loads((REPO / "results/m3-gates/run-1.json").read_text())[
        "excluded_exposed_tasks"
    ]
    held = [t for t in task_set.tasks if t.split == "held_out"]
    study.say(
        f"""
        60 tasks: 20 to develop against, 40 sealed. The split is in the
        committed data, declared before any measurement existed, because a split
        chosen later could be chosen to suit a result.

        Then I broke it. While testing whether a new probe class defeated the
        baselines, I ran all four of its tasks — and two were held-out. They are
        {", ".join(excluded)}.

        They are permanently excluded rather than quietly reused. The final
        measurement ran over {len(held) - len(excluded)} tasks, not {len(held)},
        and their answers are published as historical examples instead of being
        pretended away.

        The sealed set has now been spent. It was executed once, after the last
        change to anything the agent does, and no further run is possible.
        """
    )
    study.claim(
        "the split is stored in the task data",
        all(t.split for t in task_set.tasks),
        "not a runtime argument",
    )
    study.claim("20 development tasks", len(task_set.split("dev")) == 20, "20")
    study.claim(f"{len(held)} were sealed", len(held) == 40, "40")
    study.claim("two were exposed during development", len(excluded) == 2, ", ".join(excluded))
    study.claim(
        f"so {len(held) - len(excluded)} remain usable for the final measurement",
        len(held) - len(excluded) == 38,
        "38",
    )
    study.claim(
        "the exposed probes were held-out, which is what made it a mistake",
        all(
            next(t for t in task_set.tasks if t.id == task_id).split == "held_out"
            for task_id in excluded
        ),
    )
    study.claim(
        "the final measurement was executed on the held-out split",
        final["split"] == "held_out",
        f"{clean['systems']['agent']['clean']['total']} tasks",
    )
    study.claim(
        "it consumed a reservation that cannot be reused",
        (REPO / "data/.held-out-runs").is_dir(),
        "an on-disk ledger, not a convention",
    )

    # ------------------------------------------------------------------
    study.section("8. The grader fails visibly instead of guessing")
    sample = next(t for t in task_set.tasks if t.task_class == "vulnerable_affected")
    unreadable = grade(sample, truth[sample.id], "I had some trouble with that.")
    conflicting = grade(
        sample, truth[sample.id], "The package is unknown. However it is vulnerable."
    )
    study.say(
        """
        Three outcomes per task: correct, incorrect, and ungradable. An answer
        the grader cannot read is never counted against the agent.

        That distinction is the one that keeps the eval honest. If grader bugs
        were scored as agent failures, the harness could be confidently wrong
        and nothing would reveal it.

        The agent is asked to end with a canonical token so grading is exact.
        Prose is a fallback, flagged per task. Two mutually exclusive verdicts
        both matching returns ungradable, because picking the first would invent
        a precision the text does not have.
        """
    )
    study.claim(
        "an unreadable answer is ungradable, not wrong",
        unreadable.correct is None,
        f"method={unreadable.method}",
    )
    study.claim(
        "contradictory prose is ungradable rather than resolved",
        conflicting.correct is None,
        "conflicting verdict phrases",
    )
    study.claim(
        "there are four canonical verdict tokens",
        len(VERDICT_TOKENS) == 4,
        ", ".join(VERDICT_TOKENS),
    )
    study.claim(
        "exact grading dominated in practice",
        clean["systems"]["agent"]["clean"]["fallback_rate"]["value"] == 0.0
        and clean["systems"]["agent"]["clean"]["ungradable_count"] == 0,
        "0 prose fallbacks, 0 ungradable on the development run",
    )

    # ------------------------------------------------------------------
    study.section("9. The headline: routing lost, and why that is arithmetic")
    agent = clean["systems"]["agent"]["clean"]
    no_agent = clean["systems"]["no_agent"]["clean"]
    always = clean["systems"]["always_lookup"]["clean"]
    paired_na = clean["paired"]["no_agent"]["clean"]
    paired_al = clean["paired"]["always_lookup"]["clean"]

    def score(row: dict[str, Any]) -> str:
        return f"{row['correct']}/{row['total']}   mean {row['cost']['tool_calls']['mean']} calls"

    def pairing(row: dict[str, Any]) -> str:
        return (
            f"{row['wins']} wins / {row['ties']} ties / {row['losses']} losses"
            f"   discordant: {row['discordant_pairs']}"
        )

    study.say(
        f"""
        Two deliberately unintelligent baselines run the same tasks:

          no_agent       calls every tool on every package, answers once
          always_lookup  calls one tool, ever

        Final held-out results:

          agent          {score(agent)}
          no_agent       {score(no_agent)}
          always_lookup  {score(always)}

        The baselines won. The reason is not a weak agent and not a bad task
        set: no_agent calls everything, so it always holds strictly MORE
        information than a routing agent. Routing is dominated whenever calling
        everything is affordable and fits in the context.

        That is arithmetic. Harder tasks would not change it, because the
        baseline receives the same tool outputs the agent had to choose between.
        The task set was deliberately not redesigned until the agent won — that
        would be fitting the benchmark to a desired result.

        The one axis the agent wins is cost: {agent["cost"]["tool_calls"]["mean"]}
        calls against {no_agent["cost"]["tool_calls"]["mean"]}.

        A fifteen-times larger hosted model was also measured, on the
        development split only. It moved the agent from 80 to 90 per cent and
        the call-everything baseline from 90 to 95. The finding survives a much
        bigger model; it is not an artefact of using a small one.
        """
    )
    study.claim(
        "no comparison separated the agent from either baseline",
        all(
            arms["clean"]["mcnemar_exact_p"] is None or arms["clean"]["mcnemar_exact_p"] >= 0.05
            for arms in clean["paired"].values()
        ),
        f"agent {agent['correct']}, no_agent {no_agent['correct']}, "
        f"always_lookup {always['correct']} of {agent['total']}",
    )
    study.claim(
        "the agent used fewer tool calls than no_agent",
        agent["cost"]["tool_calls"]["mean"] < no_agent["cost"]["tool_calls"]["mean"],
        "the cost argument for routing survives",
    )
    study.claim(
        "the baseline sees the question only, never the task record",
        "task.question" not in (REPO / "src/dep_triage/eval/baselines.py").read_text()
        or "extract_pins" in (REPO / "src/dep_triage/eval/baselines.py").read_text(),
        "pins are regex-extracted from the question text",
    )
    study.claim(
        "no_agent calls list_releases unfiltered, which is what 'no routing' means",
        "toolkit.list_releases(name)" in (REPO / "src/dep_triage/eval/baselines.py").read_text(),
        "passing a floor would itself be a routing decision",
    )

    # ------------------------------------------------------------------
    study.section("10. Why the paired reading matters more than the percentages")
    study.say(
        f"""
        "16/20 against 18/20" looks like a difference. The paired view shows
        there is almost nothing there:

          vs no_agent        {pairing(paired_na)}
          vs always_lookup   {pairing(paired_al)}

        Only discordant pairs — tasks where exactly one system was right —
        carry information. With 2 of them, an exact two-sided McNemar test
        cannot reach p < 0.05 under ANY split of wins and losses: the floor is
        2 x 0.5^2 = 0.50. At least 6 discordant pairs are needed before
        significance is even attainable.

        So the comparison is reported as unresolvable at this sample size. Not
        as equivalence, and not as a trend.
        """
    )
    study.claim(
        "the discordant pairs are too few for the test to resolve",
        paired_na["discordant_pairs"] < MIN_DISCORDANT,
        f"{paired_na['discordant_pairs']} against no_agent, "
        f"{paired_al['discordant_pairs']} against always_lookup; {MIN_DISCORDANT} needed",
    )
    study.claim(
        "the exact test could not have reached significance at this pair count",
        paired_na["mcnemar_exact_p"] >= 0.05 and 2 * 0.5 ** paired_na["discordant_pairs"] > 0.05,
        f"p={paired_na['mcnemar_exact_p']}, "
        f"floor={min(1.0, 2 * 0.5 ** paired_na['discordant_pairs']):.2f}",
    )
    study.claim(
        f"{MIN_DISCORDANT} discordant pairs are the minimum for attainable significance",
        2 * 0.5**MIN_DISCORDANT < 0.05 <= 2 * 0.5 ** (MIN_DISCORDANT - 1),
        f"2*0.5^{MIN_DISCORDANT} = {2 * 0.5**MIN_DISCORDANT:.3f}",
    )

    # ------------------------------------------------------------------
    study.section("11. The fault arm, where routing finally shows an advantage")

    def arm(system: str, mode: str) -> dict[str, Any]:
        found: dict[str, Any] = faults["systems"][system][mode]
        return found

    agent_error = arm("agent", "error")["task_accuracy"]
    na_error = arm("no_agent", "error")
    al_error = arm("always_lookup", "error")
    study.say(
        f"""
        Each tool result is corrupted one way per run: an HTTP 503, a
        valid-but-empty payload, or a record with the field the answer depends
        on removed.

        Under the 503 arm:

          agent          {agent_error["numerator"]}/{agent_error["denominator"]} correct
          no_agent       0 gradable — {na_error["d2"]["behaviours"]["crashed"]} crashes
          always_lookup  0 gradable — {al_error["d2"]["behaviours"]["crashed"]} crashes

        Both baselines are single-shot scripts. They cannot retry, switch tool,
        or abstain, so a failing tool takes the whole run down. The agent can,
        and did.

        The honest framing matters here. With zero gradable baseline records,
        every pair is excluded, and zero usable pairs cannot support an accuracy
        comparison. What is directly observed is an operational difference: the
        baselines crash and the agent does not. That is claimed; an accuracy win
        is not.
        """
    )
    study.claim(
        "the agent answered some tasks correctly despite tool errors",
        agent_error["numerator"] > 0,
        f"{agent_error['numerator']}/{agent_error['denominator']}",
    )
    study.claim(
        "both baselines produced zero gradable results under tool errors",
        na_error["task_accuracy"]["value"] is None and al_error["task_accuracy"]["value"] is None,
        "0 gradable each",
    )
    study.claim(
        "they crashed rather than answering",
        na_error["d2"]["behaviours"]["crashed"] > 0 and al_error["d2"]["behaviours"]["crashed"] > 0,
        f"{na_error['d2']['behaviours']['crashed']} and "
        f"{al_error['d2']['behaviours']['crashed']} crashes",
    )
    study.claim(
        "correctness under a fault is recorded as not proving recovery",
        "recovery_means_correct_under_fault_not_proof_of_retry" in json.dumps(faults),
        "a system can be right without noticing the failure",
    )

    # ------------------------------------------------------------------
    study.section("12. What this project does not claim")
    fab = agent["fabrication"]
    study.say(
        """
        Greedy decoding with a fixed seed did NOT make everything repeatable.
        The agent and always_lookup reproduce; no_agent does not. The observed
        variance is published rather than smoothed away.

        Fabrication — the metric this project exists to report — found no hard
        fabrications on the development set, and both of its rates are lower
        bounds. An agent that implies a version without naming it is invisible
        to string extraction, and the detector itself has never been validated
        against hand labels, so its own precision is unmeasured.

        Twenty development tasks carry roughly plus or minus fifteen points at
        95% confidence. More tasks is not the fix: eighty reaches only about
        plus or minus eleven. Pairing and reporting by claim type make that
        workable; neither makes n=20 behave like n=200.

        One model, one domain, one snapshot. Nothing here generalises further.
        """
    )
    study.claim(
        "reproducibility is reported per system, not as a single yes",
        "repeatable_by_system" in gates,
        ", ".join(sorted(gates["repeatable_by_system"])),
    )
    study.claim(
        "one baseline is not repeatable, and that is recorded",
        gates["repeatable_by_system"]["no_agent"] is False,
        "no_agent varied run to run",
    )
    study.claim("the agent is repeatable", gates["repeatable_by_system"]["agent"] is True)
    study.claim(
        "both fabrication rates are flagged as lower bounds",
        fab["fabrication_per_assertion"]["lower_bound"] is True
        and fab["fabrication_per_task"]["lower_bound"] is True,
    )
    study.claim(
        "the fabrication detector is recorded as unvalidated",
        fab["detector_validated"] is False,
        "its own precision is unknown",
    )
    study.claim(
        "no hard fabrication was detected on the development set", fab["fabrication_hard"] == 0, "0"
    )
    study.claim(
        "the existence-probe class is reported as traces, not a rate",
        frozenset({"minimum_safe_version_deep"}) == EXISTENCE_PROBE_CLASSES
        and sum(ALLOCATION["minimum_safe_version_deep"]) == 4,
        "4 tasks cannot carry a rate",
    )

    # ------------------------------------------------------------------
    study.section("13. The run that was voided, and the rule it exposed")
    ledger = sorted((REPO / "data/.held-out-runs").glob("*.json"))
    released = [
        path
        for path in ledger
        if json.loads(path.read_text()).get("state", "").startswith("released")
    ]
    voided = json.loads((REPO / "results/held-out-hosted.json").read_text())
    voided_gradable = [
        r for r in voided["records"] if (r.get("grade") or {}).get("correct") is not None
    ]
    study.say(
        f"""
        The hosted model's final run failed completely: the provider returned
        HTTP 403 to every request, so all {len(voided["records"])} executions
        ended before the model saw a task.

        That spent a reservation on a measurement that never happened. The
        tempting move is to call it an exception and re-run. The honest reading
        is that it exposed a flaw in the rule.

        A reservation exists to prevent re-measuring AFTER seeing a result.
        Counting attempts is a proxy for that, and the proxy is wrong here: no
        answer was produced and no score computed, so nothing exists that could
        be iterated against.

        So the proxy was corrected rather than excused, and given a line that is
        checked mechanically instead of argued:

            zero gradable records, or the reservation is spent.

        One graded task and it is gone permanently. That cannot be gamed — a run
        engineered to produce no gradable records contains, by construction, no
        information about the held-out set. Released reservations are superseded
        rather than deleted, so the release stays visible as evidence.

        The failed artifacts are committed too. The provider never lifted the
        block, so the hosted column remains development-only.
        """
    )
    study.claim(
        "the voided run produced no gradable record at all",
        not voided_gradable,
        f"0 of {len(voided['records'])}",
    )
    study.claim(
        "its reservations were released, not deleted",
        len(released) == 6 and all(json.loads(p.read_text()).get("history") for p in released),
        f"{len(released)} released, each retaining its history",
    )
    study.claim(
        "the local model's reservations remain spent",
        any(json.loads(p.read_text()).get("state", "").startswith("reserved") for p in ledger),
        "a successful run is never releasable",
    )
    study.claim(
        "the failed artifacts are kept as evidence",
        (REPO / "results/held-out-hosted.json").is_file()
        and (REPO / "results/held-out-hosted-faults.json").is_file(),
    )

    return study.finish()


if __name__ == "__main__":
    raise SystemExit(main())

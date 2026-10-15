"""The static evaluation report — the deployed service's landing page.

M0 scope §9.3 makes this the landing page rather than the live agent, because
it has no runtime dependency and therefore cannot break. The live ``/ask`` form
is secondary and degrades to a notice.

Self-contained HTML: inline CSS, no scripts, no external assets. A report that
fetches a stylesheet from a CDN stops rendering correctly the day the CDN
changes, and the whole point of this page is that it keeps working.

**No charts, deliberately.** Twenty development tasks with ±15-point intervals
plotted as bars would read as a precise difference between 80% and 90%. Tables
carrying the interval next to every number cannot be skimmed into a conclusion
the data does not support.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

#: A two-sided exact McNemar test on ``d`` discordant pairs has minimum
#: attainable p of ``2 * 0.5**d``. Below six pairs no split of wins and losses
#: can reach p < 0.05, so the comparison cannot resolve at that size — a fact
#: about the test, not about the systems.
MIN_DISCORDANT_FOR_SIGNIFICANCE = 6

SYSTEM_LABELS = {
    "agent": "Agent (tool routing)",
    "no_agent": "no_agent (calls every tool)",
    "always_lookup": "always_lookup (one tool)",
}

_CSS = """
:root { color-scheme: light dark;
  --fg:#111; --bg:#fff; --mut:#555; --line:#d8d8d8;
  --warn-bg:#fff8e1; --warn-line:#e0b400; --code:#f4f4f4; }
@media (prefers-color-scheme: dark) { :root {
  --fg:#e8e8e8; --bg:#16181d; --mut:#a2a7b0; --line:#343841;
  --warn-bg:#2b2616; --warn-line:#a98600; --code:#1e2127; } }
* { box-sizing:border-box; }
body { margin:0 auto; padding:2rem 1.25rem 5rem; max-width:62rem;
  background:var(--bg); color:var(--fg); line-height:1.6;
  font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
h1 { font-size:1.65rem; margin:0 0 .25rem; }
h2 { font-size:1.2rem; margin:2.5rem 0 .5rem; padding-bottom:.3rem;
  border-bottom:1px solid var(--line); }
h3 { font-size:1rem; margin:1.5rem 0 .4rem; }
p,li { margin:.5rem 0; }
.sub { color:var(--mut); margin:0 0 1.5rem; }
table { border-collapse:collapse; width:100%; margin:.75rem 0 1rem; font-size:.9rem; }
th,td { text-align:left; padding:.45rem .6rem; vertical-align:top;
  border-bottom:1px solid var(--line); }
th { font-weight:600; }
td.n,th.n { text-align:right; font-variant-numeric:tabular-nums; }
.ci { color:var(--mut); font-size:.85em; white-space:nowrap; }
.note { background:var(--warn-bg); border-left:3px solid var(--warn-line);
  padding:.7rem .9rem; margin:1rem 0; border-radius:3px; }
.note strong { display:block; margin-bottom:.2rem; }
code,pre { background:var(--code); font-size:.85em;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
code { padding:.1rem .3rem; border-radius:3px; }
pre { padding:.8rem; overflow-x:auto; border-radius:4px; }
footer { margin-top:3rem; padding-top:1rem; border-top:1px solid var(--line);
  color:var(--mut); font-size:.85rem; }
"""


def _metrics_of(run: dict[str, Any]) -> dict[str, Any]:
    """Accept either a full evaluation run file or a bare ``.metrics.json``.

    The run artifact nests metrics under ``metrics`` and uses a top-level
    ``systems`` *list* of names, so indexing the wrong one fails loudly rather
    than silently reporting nothing.
    """
    inner = run.get("metrics")
    return inner if isinstance(inner, dict) else run


def _esc(value: object) -> str:
    return html.escape(str(value))


def _pct(metric: dict[str, Any] | None) -> str:
    """Format a rate with its interval, preserving the lower-bound flag."""
    if not metric or metric.get("value") is None:
        denominator = (metric or {}).get("denominator", 0)
        return f'<span class="ci">n/a (n={denominator})</span>'
    value = f"{metric['value'] * 100:.0f}%"
    if metric.get("lower_bound"):
        value = f"&ge; {value}"
    parts = [value]
    if metric.get("numerator") is not None:
        parts.append(f'<span class="ci">{metric["numerator"]}/{metric["denominator"]}</span>')
    ci = metric.get("ci95")
    if ci:
        parts.append(f'<span class="ci">95% CI {ci[0] * 100:.0f}&ndash;{ci[1] * 100:.0f}%</span>')
    return " ".join(parts)


def _mean(metric: dict[str, Any] | None) -> str:
    if not metric or metric.get("mean") is None:
        return '<span class="ci">n/a</span>'
    return f'{metric["mean"]:.2f} <span class="ci">n={metric.get("n", "?")}</span>'


def _paired_verdict(paired: dict[str, Any]) -> str:
    discordant = paired.get("discordant_pairs", 0)
    if discordant == 0:
        return (
            "<strong>No information.</strong> Zero discordant pairs: the two systems "
            "agreed on every gradable task, so this comparison cannot distinguish them."
        )
    if discordant < MIN_DISCORDANT_FOR_SIGNIFICANCE:
        floor = min(1.0, 2 * 0.5**discordant)
        return (
            f"<strong>Cannot resolve at this size.</strong> With {discordant} discordant "
            f"pair(s) the smallest attainable two-sided p is {floor:.2f}; at least "
            f"{MIN_DISCORDANT_FOR_SIGNIFICANCE} are needed to reach p &lt; 0.05 under "
            "any split of wins and losses. Reported as inconclusive, not as "
            "equivalence."
        )
    p = paired.get("mcnemar_exact_p")
    if p is not None and p < 0.05:
        return f"<strong>Difference detected</strong> (exact McNemar p = {p:.3f})."
    return (
        f"<strong>Inconclusive</strong> (exact McNemar p = {'n/a' if p is None else f'{p:.2f}'})."
    )


def _table(headers: list[str], rows: list[list[str]], numeric_from: int = 1) -> str:
    head = "".join(
        f'<th class="n">{_esc(h)}</th>' if i >= numeric_from else f"<th>{_esc(h)}</th>"
        for i, h in enumerate(headers)
    )
    body = []
    for row in rows:
        cells = "".join(
            f'<td class="n">{cell}</td>' if i >= numeric_from else f"<td>{cell}</td>"
            for i, cell in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _headline(clean: dict[str, Any]) -> str:
    clean = _metrics_of(clean)
    rows = []
    for system, label in SYSTEM_LABELS.items():
        arm = clean["systems"].get(system, {}).get("clean")
        if not arm:
            continue
        rows.append(
            [
                _esc(label),
                _pct(arm.get("task_accuracy")),
                str(arm.get("ungradable_count", 0)),
                _mean(arm.get("cost", {}).get("tool_calls")),
            ]
        )
    return _table(["System", "Answer accuracy", "Ungradable", "Mean tool calls"], rows)


def _paired_section(clean: dict[str, Any]) -> str:
    clean = _metrics_of(clean)
    out = []
    for baseline, arms in clean.get("paired", {}).items():
        paired = arms.get("clean")
        if not paired:
            continue
        out.append(f"<h3>Agent vs <code>{_esc(baseline)}</code></h3>")
        out.append(
            _table(
                ["Wins", "Ties", "Losses", "Discordant", "Exact McNemar p", "Excluded"],
                [
                    [
                        str(paired.get("wins", 0)),
                        str(paired.get("ties", 0)),
                        str(paired.get("losses", 0)),
                        str(paired.get("discordant_pairs", 0)),
                        "n/a"
                        if paired.get("mcnemar_exact_p") is None
                        else f"{paired['mcnemar_exact_p']:.2f}",
                        str(paired.get("excluded_ungradable", 0)),
                    ]
                ],
                numeric_from=0,
            )
        )
        out.append(f'<div class="note">{_paired_verdict(paired)}</div>')
    return "".join(out)


def _fault_section(faults: dict[str, Any]) -> str:
    faults = _metrics_of(faults)
    modes = ["error", "empty", "malformed"]
    rows = []
    for system, label in SYSTEM_LABELS.items():
        arms = faults["systems"].get(system, {})
        cells = [_esc(label)]
        for mode in modes:
            arm = arms.get(mode)
            if not arm:
                cells.append('<span class="ci">&mdash;</span>')
                continue
            accuracy = arm.get("task_accuracy") or {}
            if accuracy.get("value") is None:
                crashes = (arm.get("d2", {}).get("behaviours", {}) or {}).get("crashed", 0)
                cells.append(
                    f'<span class="ci">0 gradable</span><br><span class="ci">'
                    f"{crashes} crashes</span>"
                )
            else:
                cells.append(_pct(accuracy))
        rows.append(cells)
    return _table(["System", "error (503)", "empty", "malformed"], rows)


def _diagnostics(clean: dict[str, Any]) -> str:
    clean = _metrics_of(clean)
    rows = []
    for system, label in SYSTEM_LABELS.items():
        arm = clean["systems"].get(system, {}).get("clean")
        if not arm:
            continue
        d1, d3 = arm.get("d1", {}), arm.get("d3", {})
        rows.append(
            [
                _esc(label),
                _mean(d1.get("tool_recall")),
                _mean(d1.get("tool_precision")),
                _pct(d1.get("negative_conflation_rate")),
                _pct(d3.get("termination_rate")),
                _mean(d3.get("over_call_ratio")),
                _pct(d3.get("repeat_call_rate")),
            ]
        )
    return _table(
        [
            "System",
            "Tool recall",
            "Tool precision",
            "Negative conflation",
            "Termination",
            "Over-call ratio",
            "Repeat calls",
        ],
        rows,
    )


def _fabrication(clean: dict[str, Any]) -> str:
    clean = _metrics_of(clean)
    rows = []
    validated = True
    for system, label in SYSTEM_LABELS.items():
        arm = clean["systems"].get(system, {}).get("clean")
        if not arm:
            continue
        fab = arm.get("fabrication", {})
        validated = validated and bool(fab.get("detector_validated", False))
        rows.append(
            [
                _esc(label),
                _pct(fab.get("fabrication_per_assertion")),
                _pct(fab.get("fabrication_per_task")),
                str(fab.get("fabrication_hard", 0)),
                str(fab.get("fabrication_misattributed", 0)),
            ]
        )
    table = _table(["System", "Per assertion", "Per task", "Hard", "Misattributed"], rows)
    caveat = (
        '<div class="note"><strong>Both rates are lower bounds.</strong>'
        "An agent that implies a version without naming it is undetectable by string "
        "extraction. The detector itself is <em>not</em> validated against hand labels, "
        "so its own precision is unmeasured. Assertions within one task are dependent, "
        "so the per-assertion interval is descriptive only.</div>"
        if not validated
        else ""
    )
    return table + caveat


def render(clean: dict[str, Any], faults: dict[str, Any] | None = None) -> str:
    """Build the full report page from evaluation run artifacts.

    **Deterministic**: the same artifacts always produce byte-identical HTML.
    There is no build timestamp, deliberately. A wall-clock stamp on a static
    page adds nothing a reader needs — the measurement's own identity is what
    matters — and it made the committed page impossible to verify, because
    re-rendering to check for staleness always differed.
    """
    provenance = clean.get("provenance", {})
    settings = provenance.get("settings", {})
    split = clean.get("split", "unknown")
    excluded = clean.get("excluded_exposed_tasks", [])

    sections: list[str] = []
    sections.append(
        "<h1>Dependency triage agent &mdash; evaluation report</h1>"
        '<p class="sub">Does tool routing actually help? Measured against two '
        "deliberately unintelligent baselines.</p>"
    )

    sections.append(
        '<div class="note">'
        + (
            "<strong>Final measurement. Run once, on a sealed task set.</strong>"
            f"Split: <code>{_esc(split)}</code>. These tasks were held back from the "
            "whole of development and executed exactly once, after the last change "
            "to anything the agent does. Nothing below was iterated against, and no "
            "re-run is possible: the reservation that permitted this execution is "
            "spent."
            if split == "held_out"
            else "<strong>This is a development measurement, not the final "
            "result.</strong>"
            f"Split: <code>{_esc(split)}</code>. The held-out task set is reserved "
            "for a single final measurement. Numbers here were used to diagnose "
            "behaviour and may freely have been iterated against, so they carry no "
            "claim of being unbiased."
        )
        + (
            "<br>Two held-out probes (<code>"
            + "</code>, <code>".join(map(_esc, excluded))
            + "</code>) were run during development before the split was being "
            "honoured, and are permanently excluded. The sealed set is therefore "
            "38 tasks, not 40, and that reduction is disclosed rather than absorbed."
            if excluded
            else ""
        )
        + "</div>"
    )

    sections.append("<h2>Headline</h2>")
    sections.append(_headline(clean))
    sections.append(
        '<div class="note"><strong>The baselines are not weak opponents.</strong>'
        "<code>no_agent</code> calls every tool on every package and lets the model "
        "answer once, so it always holds <em>strictly more information</em> than the "
        "routing agent. Routing is therefore dominated whenever calling everything is "
        "affordable and fits in the context window. That is arithmetic, not a property "
        "of this task set, and the task set was deliberately not redesigned until the "
        "agent won.</div>"
    )

    sections.append("<h2>Paired comparison</h2>")
    sections.append(
        "<p>Same tasks, different systems, so the information is in the "
        "<em>discordant</em> pairs &mdash; tasks where exactly one system was right. "
        "Treating the two as independent proportions discards most of it.</p>"
    )
    sections.append(_paired_section(clean))

    if faults:
        sections.append("<h2>Under injected tool failure</h2>")
        sections.append(
            "<p>Each tool result is corrupted one way per run: an HTTP 503, a "
            "valid-but-empty payload, or a record with the field the answer depends on "
            "removed. This is the one condition the baselines structurally cannot "
            "compete in &mdash; both are single-shot scripts and cannot retry, switch "
            "tool, or abstain.</p>"
        )
        sections.append(_fault_section(faults))
        sections.append(
            '<div class="note"><strong>The error arm is an operational difference, not '
            "an accuracy win.</strong>"
            "With zero gradable baseline records every pair is excluded, and zero usable "
            "pairs cannot support an accuracy comparison. What is directly observed is "
            "that the baselines crash and the agent does not.</div>"
        )

    sections.append("<h2>Diagnostics</h2>")
    sections.append(
        "<p>These explain the headline; they are not competitors to it. High tool "
        "recall alongside low answer accuracy would mean the agent gathered the right "
        "evidence and still concluded wrongly.</p>"
    )
    sections.append(_diagnostics(clean))
    sections.append(
        '<div class="note"><strong>Tool recall measures agreement with the reference '
        "path, not logical necessity.</strong>"
        "Measured: 53 of 54 minimum-safe-version cases are answerable from the "
        "advisory tool alone, because advisories carry fix boundaries. A shorter "
        "correct path than the reference resolver&rsquo;s exists, so this is not a "
        "minimality proof.</div>"
    )

    sections.append("<h2>Fabrication</h2>")
    sections.append(
        "<p>Every version string and advisory identifier in an answer is checked "
        "against the entire frozen snapshot. A token that appears nowhere in it was "
        "invented; one that exists but belongs to another package is misattributed.</p>"
    )
    sections.append(_fabrication(clean))

    sections.append("<h2>What this cannot tell you</h2>")
    sections.append(
        "<ul>"
        "<li><strong>Sample size.</strong> Twenty development tasks carry roughly "
        "&plusmn;15 percentage points at 95% confidence. More tasks is not the fix: "
        "eighty reaches only about &plusmn;11.</li>"
        "<li><strong>One model, one domain.</strong> Nothing here generalises beyond "
        "this model on Python dependency triage.</li>"
        "<li><strong>Reproducibility is partial.</strong> Greedy decoding with a fixed "
        "seed did not make every metric deterministic; one baseline is not repeatable "
        "run to run, and the observed variance is published rather than smoothed.</li>"
        "<li><strong>Correct under a fault is not verified recovery.</strong> A system "
        "can reach the right answer without having noticed the failure at all.</li>"
        "</ul>"
    )

    sections.append(
        "<footer>"
        f"Rendered from committed evaluation artifacts for the "
        f"<code>{_esc(split)}</code> split. "
        f"Model <code>{_esc(settings.get('llm_name', 'unknown'))}</code>, "
        f"temperature {_esc(settings.get('llm_temperature', '?'))}, "
        f"seed {_esc(settings.get('llm_seed', '?'))}, "
        f"step budget {_esc(settings.get('max_steps', '?'))}. "
        "No value on this page was produced at page-load time."
        "</footer>"
    )

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Dependency triage agent &mdash; evaluation report</title>"
        f"<style>{_CSS}</style></head><body>{''.join(sections)}</body></html>"
    )


def render_from_paths(clean_path: Path, faults_path: Path | None = None) -> str:
    """Render from evaluation run files on disk."""
    clean = json.loads(clean_path.read_text(encoding="utf-8"))
    faults = (
        json.loads(faults_path.read_text(encoding="utf-8"))
        if faults_path is not None and faults_path.is_file()
        else None
    )
    return render(clean, faults)

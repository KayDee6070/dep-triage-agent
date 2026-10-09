# dep-triage-agent

**A tool-using LLM agent for dependency security triage, and an evaluation
harness that measures whether it actually works.**

---

## Status

| | |
|---|---|
| **State** | **M2 agent working** — runs end to end against local Qwen3-8B. **No eval harness yet. No measured results.** |
| Day | 2 of 14 (started 2026-10-08, deadline 2026-10-21) |
| Tests | 135, 2.5 s · ruff clean · mypy `strict` |
| Clone to green | **18 s** cold cache (budget 60 s) |
| Fixture | 80 packages, 1487 advisories, snapshot 2026-10-08 |
| Results | **None.** Measured once on 2026-10-20 — see [Results](#results) |

Nothing here claims a measurement that has been taken. The Results table is
present but empty: the exact claims this project will make, fixed in writing
before the numbers exist, so they cannot be quietly reshaped to fit whatever
comes out.

Two commitments below — the held-out split and the baselines — are **specified
but not yet implemented**. They land in M3. Said plainly rather than letting
"designed" imply "working".

Full rationale including every rejected alternative:
[`docs/milestones/M0-scope.md`](docs/milestones/M0-scope.md). Environment
setup and measured hardware numbers: [`docs/setup.md`](docs/setup.md).

---

## Why this exists

Agent demos are everywhere. Almost none of them can say how well they perform.

This is an agent that answers dependency-security questions, plus a harness
that measures three things people rarely report: whether it picks the right
tool, what it does when a tool fails, and whether it knows when to stop.

**The harness is the deliverable. The agent is the entry ticket.**

The agent is deliberately not optimised against the eval. If it measures badly,
that result gets published as-is. "Call every tool beats the agent" is a
legitimate headline, and §5 of the scope doc exists to make that finding
possible.

---

## What the agent does

Answers questions about pinned Python dependencies against a **frozen offline
snapshot** of PyPI release metadata and OSV.dev advisories, committed to this
repository. 80 packages, 1487 advisories, of which **25 packages carry no
advisories at all** — without those, "is X vulnerable?" is always answered yes
and the question measures nothing.

Frozen rather than live so the benchmark gives the same numbers in six months,
the deployed service has no upstream that can go down, and ground truth stays
stable. The snapshot going stale is expected; this is a benchmark fixture, not
a security product.

### The four tools

| Tool | Returns |
|---|---|
| `parse_requirements(text)` | `[(name, pinned_version), …]` |
| `lookup_vulnerabilities(pkg, version)` | advisories, or one of three distinct negatives (below) |
| `list_releases(pkg, since_version=None)` | published versions at or above a floor |
| `check_compatibility(pkg, version, python_version)` | `requires_python`, a compatibility verdict, declared deps |

Deliberately non-substitutable — each question class needs a different subset,
which is what makes tool-selection accuracy a real measurement rather than a
formality.

`since_version` exists so the agent can avoid truncation by asking a targeted
question, instead of tasks being curated around an output cap. boto3 carries
2132 releases and django 438; an unfiltered listing was never going to fit an
8k context. Choosing a sensible floor is therefore part of what gets measured —
**argument construction, not just tool choice** — and an invalid floor returns
a rejected-argument status rather than crashing.

`check_compatibility` evaluates the PEP 440 specifier itself rather than
handing back `>=2.7, !=3.0.*, <4` for the model to parse. Deterministic
arithmetic belongs in a tool; the test then becomes whether the agent builds
the right arguments, which is closer to how agents actually fail.

### Three negatives, not one

`lookup_vulnerabilities` distinguishes three outcomes that all report
`vulnerable=false`:

| Outcome | Meaning | Correct answer |
|---|---|---|
| `package_unknown` | no data held | "unknown" |
| `version_unknown` | package known, version exists in no form | "that version does not exist" |
| `ok`, `vulnerable=false` | published and genuinely clean | "not vulnerable" |

They differ only in `status`, so an agent reading one field conflates all
three. That is a named, scored failure mode (`negative_conflation_rate`), not a
rounding error.

**Advisories are checked before the publication test**, and the data decided
that ordering: 2175 version strings in the snapshot are named by an advisory
but no longer listed on the index — withdrawn releases and pre-release builds.
Testing publication first would report every one of them as unknown and hide a
real vulnerability.

### Version comparison is semantic, not lexical

OSV publishes enumerated affected-version lists as *strings*, and PyPI release
keys are strings too. But PEP 440 zero-extends the release segment:
`Version("4.2") == Version("4.2.0")` is **True** — they are the same version.

So every comparison goes through `versions_equal` / `version_in`, which parse
both sides before comparing. 694 published versions in this snapshot are shaped
`X.Y`, and a lexical `in` test disagreed with PEP 440 on **all of them** —
scoring the agent wrong when it was right. A regression test asserts `X.Y` and
`X.Y.0` produce identical answers across all 694.

This is what makes the enumerated-list design actually remove arguable ground
truth. The enumerated lists only help if the comparison against them is
semantic; as strings alone they were a trap.

### Question classes — 60 tasks

| Class | Total | Dev | Held-out | Tools | Correct answer |
|---|---|---|---|---|---|
| Is `pkg==X` vulnerable? — affected | 10 | 3 | 7 | 2 | yes + CVE set |
| Is `pkg==X` vulnerable? — known, clean | 6 | 2 | 4 | 2 | not vulnerable |
| Unpublished version — *abstention* | 6 | 2 | 4 | 2 | never shipped |
| Unknown package — *abstention* | 6 | 2 | 4 | 2 | unknown |
| Minimum safe version? | 10 | 3 | 7 | 2, 3 | version string |
| Which packages in this file are vulnerable? | 8 | 3 | 5 | 1, 2 | set of names |
| Can I upgrade on Python `N`? | 8 | 2 | 6 | 2, 3, 4 | bool + reason |
| Direct CVE lookup — *over-call probe* | 6 | 3 | 3 | 2 | affected ranges |

"Minimum safe version" needs tools 2 **and** 3, because an advisory's `fixed`
boundary is not always a version that shipped — answering from the advisory
alone names versions nobody can install. The over-call probe needs exactly one
tool and no parsing, so an agent that parses anyway is over-calling.

---

## Three design commitments

The parts worth reviewing hardest. Each exists because its absence would make
the result unreportable.

### 1. Held-out split, declared before any measurement

**20 dev / 40 held-out.** Iteration happens freely on the dev 20. The held-out
40 runs **once**, on 2026-10-20, and that is the published result. Both halves
cover all eight classes.

Without this, "measure → diagnose → fix → re-measure" produces a number fitted
to the data it is reported on.

### 2. Baselines, so the score means something

"The agent scored 70%" is uninterpretable alone. Two baselines, on the **same
40 held-out tasks**:

| Baseline | What it does |
|---|---|
| `no-agent` | Fixed script: parse, call every tool on every package, concatenate, **one** LLM call. Tool *use* with zero tool *selection*. |
| `always-lookup` | `lookup_vulnerabilities` only. Establishes a floor. |

Both still call the model for their final answer, so both carry sampling
variance — `temperature=0` and a fixed seed apply to all three systems, and the
day-5 reproducibility gate covers all three.

### 3. Deterministic ground truth, no LLM judge

Every answer is a version string, boolean, or set — compared by equality
against a reference answer computed from the same fixture. The reference script
also derives the **minimal necessary tool set** mechanically, so tool
expectations involve no hand-labelling and no opinion.

A judge would add cost and variance for no gain. The domain was *designed* to
have exact ground truth, which makes deterministic evaluators correct here
rather than merely cheaper.

---

## What gets measured

**Primary: `task_accuracy`** — fraction of tasks whose final answer exactly
matches ground truth. The three families below *explain* it; they are not peers
of it. 90% tool selection with 40% task accuracy is a finding; without the
denominator it is noise.

### Agent vs baseline is paired

Same 40 tasks, two systems, so the information is in the **discordant pairs**.
Reported as `wins / ties / losses` plus `discordant_pairs` plus an exact
McNemar test (binomial, not chi-square — the discordant count will be small).

Pairing raises power substantially; it does not rescue n=40. With 9 discordant
pairs an 8–1 split is significant; with 4 pairs a 4–0 split is not. The pair
count is reported alongside every comparison so a reader can see which case
they are in.

### D1 — tool selection

| Metric | Status |
|---|---|
| `tool_recall` | **Hard.** Below 1.0 means the agent answered without information it needed. |
| `tool_precision` | **Soft.** Extra calls are waste, not error. |
| `first_call_accuracy` | reported |
| `no_tool_discipline` | on tasks needing no tool, did it call zero |
| `negative_conflation_rate` | wrong negative given — "not vulnerable" for an unknown package, etc. |
| `invalid_argument_rate` | calls rejected for a malformed argument |

`exact_set_match` is a footnote only, labelled "perfect-routing rate, not a
quality measure" — it assumes one valid path per task and penalises
correct-but-different routes.

### D2 — failure recovery

Faults injected at the tool-wrapper layer: `error` (503), `empty` (valid but
empty), `malformed` (required key removed, not emptied).

`recovery_rate` · `graceful_abstention_rate` · per-task behaviour class from
`{retried_same_tool, switched_tool, abstained, fabricated, crashed}`.

**Fabrication** is detected by extracting every version string and advisory ID
from the answer and checking it against the *whole* fixture — we own it, so a
claim either exists in it or it does not. Two counters: `fabrication_hard`
(appears nowhere) and `fabrication_misattributed` (exists, wrong package).

Two denominators, both reported, never collapsed:

| Rate | Denominator | Reading |
|---|---|---|
| `fabrication_per_assertion` | every version/ID asserted | **Headline.** Large n, tight interval. |
| `fabrication_per_task` | fault-injected tasks with ≥1 fabrication | Wide interval, but the number readers want. |

Both are **lower bounds**: an agent that implies a version without naming it is
undetectable by string extraction.

### D3 — stopping behaviour

`termination_rate` within `max_steps=8` · `over_call_ratio` (actual ÷ necessary
calls) · `repeat_call_rate` (identical `(tool, args)` repeated) ·
`steps_to_answer` vs reference.

### How claims are reported

The sample size cannot support one number carrying every conclusion, so claims
are tiered:

| Claim type | Reporting |
|---|---|
| **Existence** — "it fabricates a fix version when the advisory record is malformed" | One example + full trace. n=1 suffices, no rate. |
| **Comparison** — "the agent beats call-everything" | Paired: wins/ties/losses + discordant pairs + McNemar |
| **Rate** — "`fabrication_per_task` is 15%" | Point estimate **with interval**, and "inconclusive" when wide |

Existence claims are statistically free and are likely the most interesting
output here. The percentage headline stays but stops carrying weight it cannot
bear.

---

## Results

**Not yet measured.** Single run on 2026-10-20: ~180 executions, ~60 minutes.

| | Agent | `no-agent` | `always-lookup` |
|---|---|---|---|
| `task_accuracy` (held-out 40) | — | — | — |
| vs agent: wins / ties / losses | — | — | — |
| `discordant_pairs`, McNemar p | — | — | — |
| `tool_recall` / `tool_precision` | — | n/a | n/a |
| `negative_conflation_rate` | — | — | — |
| `recovery_rate` | — | — | — |
| `fabrication_per_assertion` (lower bound) | — | — | — |
| `fabrication_per_task` (lower bound) | — | — | — |
| `termination_rate` / `over_call_ratio` | — | n/a | n/a |

Reported for two models — Qwen3-8B local (the evaluated agent) and the hosted
open-weight model behind the live demo — so nothing on the public link is an
unmeasured claim.

---

## Known limitations

Stated now rather than discovered in the write-up.

**Sample size.** 40 held-out tasks. Unpaired, a headline accuracy figure
carries roughly **±15pp** at 95% confidence; the fault suite is ~**±22pp** at
20 tasks per mode. More tasks is not the fix: 80 reaches only ~±11pp and ~96
are needed for ±10pp, which the time budget cannot buy without gutting the
harness that is the deliverable. Pairing and tiering make this workable;
neither makes n=40 behave like n=400.

**The snapshot goes stale.** A benchmark fixture, not a security product. Do
not use it to audit real dependencies.

**The deployed agent is not the evaluated agent.** Free hosting has no GPU, so
Qwen3-8B cannot run there. The demo uses a hosted open-weight model — which is
why that model is also evaluated.

**Fabrication detection is unvalidated against hand labels.** The budget does
not cover a labelled subset to measure the detector's own precision.

**One model, one domain.** Nothing generalises beyond Qwen3-8B on Python
dependency triage.

**`check_compatibility` makes its question class easier** by moving specifier
arithmetic into the tool. Deliberate — see above — but it is a thumb on the
scale for that class, and the report says so.

---

## Stack

| Layer | Choice |
|---|---|
| Agent | LangGraph, single agent, `create_react_agent` |
| Model | Qwen3-8B Q4_K_M via Ollama, local |
| Client | `langchain-openai` — Ollama and the hosted demo are both OpenAI-compatible, so two config profiles, not two code paths |
| Service | FastAPI — `POST /ask`, `/health`, `/metrics` |
| Deps | `uv`, Python 3.12 |
| Quality | pytest, ruff, mypy `strict`, GitHub Actions |
| Container | Docker → Hugging Face Spaces |

**Instrumentation lives at the tool-wrapper layer, not inside the graph**, so
the harness never depends on LangGraph internals and removing LangGraph could
not invalidate a measured number.

**CI runs no model.** Real responses are recorded once into committed fixtures
and replayed — deterministic, offline, under 60 s. A `--live` flag runs the
same tests against real Ollama locally.

### Measured on this machine

RTX 4070 Laptop GPU, 7.4 GiB available to Ollama. Full detail in
[`docs/setup.md`](docs/setup.md).

| | Value |
|---|---|
| Throughput, warm | **44.9 tok/s** (44.4 / 44.9 / 44.9) |
| Agent latency per question | **1.4–5 s** with reasoning disabled (120 s timeout with it on) |
| GPU offload | 37/37 layers, 100% GPU |
| VRAM at 8k context | 6.2 GB |
| `temperature=0 seed=42` | identical output across 3 runs |

44.9 tok/s sits mid-range of the 35–50 assumed when the plan was written, so
the 20–30 minute estimate for a 60-task run stands. The determinism result is a
*precondition*, not the day-5 gate — that gate compares full-run metrics across
three systems.

---

## Target interface

*`version`, `config` and `ask` work. `eval` and `report` arrive at M3; stubs
that raise would make `--help` advertise an interface that does nothing.*

```bash
uv sync --frozen                         # clone to green, 18s cold
uv run pytest && uv run ruff check . && uv run mypy

uv run dep-triage version                # works
uv run dep-triage config                 # works — resolved config, secrets redacted

ollama pull qwen3:8b                     # one-time, 5.2 GB

uv run dep-triage ask "is urllib3==1.26.4 vulnerable?"          # works
uv run dep-triage ask --trace "is django==4.2 vulnerable?"     # works
uv run dep-triage eval --split dev              # 20 tasks, ~9 min
uv run dep-triage eval --split held-out         # 40 tasks — run ONCE
uv run dep-triage eval --baseline no-agent --split dev
uv run dep-triage report                        # static HTML report

docker run -p 8000:8000 dep-triage-agent
```

---

## Deliberately out of scope

A 5th tool · multi-agent or orchestration · vector DB / RAG · any web UI beyond
the static report and one form · Grafana · Kubernetes · Terraform ·
fine-tuning · **any prompt tuning against the held-out 40**.

Cut order if the 14 days overrun: Prometheus endpoint, then
`check_compatibility`, then 60 tasks → 40. **Never the held-out split or the
baselines.** The buffer is this list, not a spare day.

---

## Definition of done

Not "polished". Done when all six hold:

1. The public link works.
2. The agent runs in Docker from a clean checkout.
3. The harness produces a measured result on the held-out 40 — good or bad —
   alongside both baselines.
4. A study script explains it, with every claim backed by an assertion.
5. Every milestone ended green: tests pass, linter clean, committed.
6. The held-out set was measured **once**.

---

## Docs

- [`docs/milestones/M0-scope.md`](docs/milestones/M0-scope.md) — full scope,
  rejected alternatives, risks with triggers, revision history
- [`docs/setup.md`](docs/setup.md) — environment, measured hardware numbers
- [`docs/milestones/M1-report.md`](docs/milestones/M1-report.md) — built,
  decided, measured, still weak
- [`CONTRIBUTIONS.md`](CONTRIBUTIONS.md) — my decisions vs. AI-assisted work
  vs. external review, per milestone

## License

MIT — see [`LICENSE`](LICENSE).

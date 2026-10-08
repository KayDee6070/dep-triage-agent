# dep-triage-agent

**A tool-using LLM agent for dependency security triage, and an evaluation
harness that measures whether it actually works.**

---

## Status

| | |
|---|---|
| **Current state** | **M2 in progress** — fixture and tools built and tested; agent loop pending Ollama |
| Started | 2026-10-08 |
| Deadline | 2026-10-21 (14 days) |
| Results | **None yet.** Measured once on 2026-10-20 — see [Results](#results) |
| Fixture | 80 packages, 1487 advisories, snapshot 2026-10-08 |

Nothing in this README claims a measurement that has been taken. The empty
tables below are the exact claims the project will make, written down before
the numbers exist so they can't be quietly reshaped to fit whatever comes out.

Full design rationale, including every rejected alternative:
[`docs/milestones/M0-scope.md`](docs/milestones/M0-scope.md).

---

## Why this exists

Agent demos are everywhere. Almost none of them can say how well they perform.

This project is an agent that answers dependency-security questions, plus a
harness that measures three things people rarely report: whether it picks the
right tool, what it does when a tool fails, and whether it knows when to stop.

**The harness is the deliverable. The agent is the entry ticket.**

The agent is deliberately not optimised against the eval. If it measures badly,
that result gets published as-is.

---

## What the agent does

Answers questions about pinned Python dependencies against a **frozen offline
snapshot** of PyPI release metadata and OSV.dev vulnerability records,
committed to this repository: 80 packages and 1487 advisories as of
2026-10-08, of which 25 packages carry no advisories at all so that "is X
vulnerable?" is not always answered yes.

Frozen rather than live for three reasons: the benchmark gives the same numbers
in six months, the deployed service has no upstream that can go down, and
ground truth stays stable.

### The four tools

| Tool | Returns |
|---|---|
| `parse_requirements(text)` | `[(name, pinned_version), …]` |
| `lookup_vulnerabilities(pkg, version)` | OSV records, `[]`, or `package unknown` |
| `list_releases(pkg)` | ordered list of real releases |
| `check_compatibility(pkg, version)` | `requires_python` + declared deps |

The tools are deliberately non-substitutable — each question class needs a
different subset. That is what makes tool-selection accuracy a real
measurement rather than a formality.

### Question classes

| Class | Tasks | Tools needed | Answer type |
|---|---|---|---|
| Is `pkg==X` vulnerable? | 12 | 2 | bool + CVE set |
| Minimum safe version? | 12 | 2, 3 | version string |
| Which packages in this file are vulnerable? | 12 | 1, 2 | set of names |
| Can I upgrade on Python `N`? | 10 | 2, 3, 4 | bool + reason |
| Unknown package — *abstention probe* | 8 | 2 | must answer "unknown" |
| Direct CVE lookup — *over-call probe* | 6 | 2 | affected ranges |

Two classes are traps by design. The abstention probe asks about a package
absent from the snapshot, where the only correct answer is "I don't know." The
over-call probe needs exactly one tool, so an agent that parses anyway is
over-calling.

---

## Three design commitments

These are the parts worth reviewing hardest. Each one exists because its
absence would have made the result unreportable.

### 1. Held-out split, declared before any measurement

**20 dev / 40 held-out.** Iteration happens freely on the dev 20. The held-out
40 is run **once**, on 2026-10-20, and that is the published result.

Without this, "measure → diagnose → fix → re-measure" produces a number fitted
to the data it is reported on. Both halves cover all six question classes.

### 2. Baselines, so the score means something

"The agent scored 70%" is uninterpretable without a comparison. Two baselines
run on the same splits:

| Baseline | What it does |
|---|---|
| `no-agent` | Fixed script: parse, call every tool on every package, concatenate, **one** LLM call. Tool *use* with zero tool *selection*. |
| `always-lookup` | `lookup_vulnerabilities` only. Nothing else. Establishes a floor. |

If the agent can't beat "call everything," agentic routing isn't earning its
place in this domain. That is a publishable finding, not a failure.

### 3. Deterministic ground truth, no LLM judge

Every answer is a version string, boolean, or set — compared by equality
against a reference answer computed from the same frozen fixture. The reference
script also derives the **minimal necessary tool set** mechanically, so tool
expectations involve no hand-labelling and no opinion.

An LLM judge would add cost and variance for no gain here. The domain was
designed to make deterministic evaluators correct, not merely cheaper.

---

## What gets measured

**Primary metric: end-to-end answer accuracy.** The three below are diagnostics
that explain it, not peers of it — 90% tool selection against 40% answer
accuracy is a finding; without the denominator it is noise.

### D1 — tool selection

| Metric | Status |
|---|---|
| `tool_recall` | **Hard.** Below 1.0 means the agent answered without the information it needed. |
| `tool_precision` | **Soft.** Extra calls are waste, not error. |
| `first_call_accuracy` | Reported |
| `no_tool_discipline` | Reported — on tasks needing no tool, did it call zero |

`exact_set_match` is reported only as a footnote. It assumes one valid tool path
per task and penalises correct-but-different routes.

### D2 — failure recovery

Faults injected at the tool-wrapper layer: `error` (503), `empty` (valid but
empty), `malformed` (OSV record missing its `fixed` field).

`recovery_rate` · `fabrication_rate` · `graceful_abstention_rate` · per-task
behaviour class from `{retried_same_tool, switched_tool, abstained,
fabricated, crashed}`.

**Fabrication detection** extracts every version string and CVE/GHSA ID from
the answer and checks it against the *whole* fixture — we own the fixture, so a
claim either exists in it or it doesn't. Two counters: `fabrication_hard`
(appears nowhere) and `fabrication_misattributed` (exists, wrong package).

`fabrication_rate` is reported **as a lower bound.** An agent that implies a
version without naming it is undetectable by this method.

### D3 — stopping behaviour

`termination_rate` within `max_steps=8` · `over_call_ratio` (actual ÷
necessary calls) · `repeat_call_rate` (identical `(tool, args)` repeated) ·
`steps_to_answer` vs reference.

---

## Results

**Not yet measured.** Single run on 2026-10-20, ~180 executions, ~60 minutes.

| | Agent | `no-agent` | `always-lookup` |
|---|---|---|---|
| `task_accuracy` (held-out 40) | — | — | — |
| `tool_recall` | — | n/a | n/a |
| `tool_precision` | — | n/a | n/a |
| `recovery_rate` | — | — | — |
| `fabrication_rate` (lower bound) | — | — | — |
| `termination_rate` | — | n/a | n/a |
| `over_call_ratio` | — | n/a | n/a |

Reported for two models: Qwen3-8B local (the evaluated agent) and the hosted
open-weight model behind the live demo, so nothing on the public link is an
unmeasured claim.

---

## Known limitations

Stated now rather than discovered in the write-up.

**Sample size.** 40 held-out tasks gives a headline accuracy number with
roughly **±15 percentage points** at 95% confidence. The fault suite is 20
tasks per mode, roughly **±22pp**. Concretely: a 5pp gap between the agent and
`no-agent` is **not a finding**, and the report will say "inconclusive at this
sample size" rather than dress it up. Only gaps above ~20pp are reportable
here.

More tasks is not the fix. Doubling the held-out set to 80 tightens the
interval only to ~±11pp, and reaching ±10pp needs ~96 tasks — which this time
budget cannot buy without gutting the harness that is the actual deliverable.
The correct response is to report intervals and claim only large gaps, which
is what the harness will do.

**The snapshot goes stale.** This is a benchmark fixture, not a security
product. Do not use it to audit real dependencies.

**The deployed agent is not the evaluated agent.** Free hosting has no GPU, so
Qwen3-8B cannot run there. The live demo uses a hosted open-weight model, which
is why that model is also evaluated.

**Fabrication detection is unvalidated against hand labels.** The time budget
doesn't cover building a labelled subset to measure the detector's own
precision.

**One model, one domain.** No claim generalises beyond Qwen3-8B on Python
dependency triage.

---

## Stack

| Layer | Choice |
|---|---|
| Agent | LangGraph, single agent, `create_react_agent` |
| Model | Qwen3-8B Q4_K_M via Ollama, local, RTX 4070 Laptop (8 GB) |
| Service | FastAPI — `POST /ask`, `/health`, `/metrics` |
| Deps | `uv`, Python 3.12 |
| Quality | pytest, ruff, mypy, GitHub Actions |
| Logging | structlog (JSON) + `prometheus-client` |
| Container | Docker |
| Deploy | Hugging Face Spaces (Docker SDK) |

**Instrumentation lives at the tool-wrapper layer, not inside the graph**, so
the harness never depends on LangGraph internals.

**CI runs no model.** Real responses are recorded once into committed JSON
fixtures and replayed, so CI is deterministic, offline, and under 60 s. A
`--live` flag runs the same tests against real Ollama locally.

---

## Target interface

*Not yet functional — this is the surface being built, included so it can be
critiqued before it exists.*

```bash
uv sync                                  # clone to green
pytest                                   # offline, no model
ruff check . && mypy src/

ollama pull qwen3:8b                     # local model, one-time

uv run dep-triage ask "is urllib3==1.26.4 vulnerable?"
uv run dep-triage eval --split dev       # 20 tasks, ~9 min
uv run dep-triage eval --split held-out  # 40 tasks — run ONCE
uv run dep-triage eval --baseline no-agent --split dev
uv run dep-triage report                 # emits the static HTML report

docker run -p 8000:8000 dep-triage-agent
```

---

## Deliberately out of scope

A 5th tool · multi-agent or orchestration patterns · vector DB / RAG · any web
UI beyond the static report and one form · Grafana · Kubernetes · Terraform ·
fine-tuning · **any prompt tuning against the held-out 40**.

Cut order if the 14 days overrun: Prometheus endpoint, then
`check_compatibility`, then 60 tasks → 40. **Never the held-out split or the
baselines.**

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
  all rejected alternatives, risks with triggers
- [`CONTRIBUTIONS.md`](CONTRIBUTIONS.md) — my decisions vs. AI-assisted work
  vs. external review, updated per milestone
- `docs/milestones/M1…M7-report.md` — one per milestone: built, decided,
  measured, still weak

## License

MIT — to be added in M1.

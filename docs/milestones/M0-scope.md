# M0 — Scope

**Status:** agreed 2026-10-07 · **revised 2026-10-07** after senior engineer review
**Rule for this milestone:** decisions only, no code.

Revision history is at §16. Everything below is the current plan.

---

## 1. Decisions at a glance

| Decision | Choice |
|---|---|
| Task domain | Dependency security triage over a frozen offline snapshot |
| Tools | 4 (`parse_requirements`, `lookup_vulnerabilities`, `list_releases`, `check_compatibility`) |
| Task set | 60 tasks, **split 20 dev / 40 held-out, declared before any measurement** |
| Primary metric | **End-to-end answer accuracy.** The three required metrics are diagnostics that explain it. |
| Baselines | **`no-agent` (call everything) and `always-lookup`** — same 40 held-out tasks, same determinism bar |
| Agent vs baseline | **Paired**: wins/ties/losses + discordant-pair count + McNemar exact |
| Fabrication | **Two denominators** — per assertion (headline) and per task |
| Reporting | **Tiered by claim type** — existence / comparison / rate |
| Agent model | Qwen3-8B Q4_K_M, local, via Ollama |
| Model switch trigger | **Dev subset under 30% task accuracy at end of M2 → switch to Qwen2.5-7B-Instruct** |
| Reproducibility | `temperature=0` + fixed seed, **verified day 5**, not day 9 |
| Budget | **$0.** Open-weight models only. No paid API. |
| Overrun rule | **Shrink the fixture, never the domain.** Cut order at §13. |
| Demo backend | Free hosted open-weight API (Groq free tier), best-effort, degrades to a notice |
| Public link | Hugging Face Spaces (Docker SDK) |
| Cloud evidence | `deploy/azure.sh` committed; running it optional, card-gated |
| Framework | LangGraph (single agent) + FastAPI |
| Deadline | **2026-10-21** — 14 days, day 1 = 2026-10-08 |

---

## 2. What this project is for

A previous project (GraphRAG Bench) covered LLMs, RAG, embeddings, vector
search, local model serving, and evaluation. It covered nothing about Docker,
deployment, monitoring, agents, or cloud — which nearly every German job ad in
the target set asks for. This project exists to close exactly that gap.

**The thesis:** everyone has an agent demo. Almost nobody can say how well
theirs performs. The eval harness is the differentiator; the agent is the entry
ticket.

Two direct consequences:

1. The agent is deliberately **not optimised against the eval**. If it
   evaluates badly, that is the result and it gets published.
2. **"Call every tool beats the agent" is a legitimate headline.** The previous
   project's strongest result was that the dumb baseline (BM25) beat the
   sophisticated methods. The same shape of finding here would mean agentic
   routing doesn't earn its place in this domain — which is a publishable
   measurement, not a failed project. §5 exists to make that finding possible.

---

## 3. Domain: dependency security triage

### 3.1 Why this domain

The binding design constraint is **outcomes checkable against ground truth**.
If success can't be verified, it can't be evaluated, and the differentiator
collapses.

This domain satisfies it exactly: every answer is a version string, a boolean,
a set of package names, or a set of CVE IDs — all comparable by equality
against a reference answer computed from the same data.

### 3.2 Data

A **frozen offline snapshot**, committed to the repository:

- PyPI release metadata for the curated package set
- OSV.dev vulnerability records for those packages

Frozen, not live. Three reasons:

1. **Reproducibility.** The benchmark gives the same numbers in six months.
2. **The deployed link cannot die from an upstream outage.** There is no
   upstream at runtime.
3. **Ground truth is stable.** Live data would silently invalidate answers.

The snapshot going stale is expected and documented. It is a benchmark fixture,
not a security product.

**Target size ~80 packages. Floor 20 packages.** See §12 — if the fixture is
slow, the corpus shrinks and the design survives.

### 3.3 The four tools

| # | Tool | Returns |
|---|---|---|
| 1 | `parse_requirements(text)` | `[(name, pinned_version), …]` |
| 2 | `lookup_vulnerabilities(pkg, version)` | OSV records, or one of three distinct negatives (§3.6) |
| 3 | `list_releases(pkg, since_version=None)` | published versions at or above a floor |
| 4 | `check_compatibility(pkg, version)` | `requires_python` + declared deps |

The tools are deliberately **non-substitutable**. Each question class needs a
different subset, so tool-selection accuracy measures something real rather
than being a formality. This was the deciding factor against the rejected SQL
domain (§8.2), where ~90% of tasks route to a single tool.

**Tool 4 stays even though only 10 of 60 tasks need it.** It is the only tool
producing a genuine multi-hop dependency between calls, and multi-hop is where
agents fail and where the interesting findings live. It is second on the cut
list (§13), not first.

### 3.4 Question classes and the split

**The split is declared now, before any measurement exists.** Iterate freely on
the dev 20. The held-out 40 is touched **once**, on day 13, and that is the
reported result.

| Class | Total | Dev | Held-out | Required tools | Correct answer |
|---|---|---|---|---|---|
| Is `pkg==X` vulnerable? — affected | 10 | 3 | 7 | 2 | yes + CVE set |
| Is `pkg==X` vulnerable? — known, zero advisories | 6 | 2 | 4 | 2 | **not vulnerable** |
| Unpublished version — **abstention probe** | 6 | 2 | 4 | 2 | **that version never shipped** |
| Unknown package — **abstention probe** | 6 | 2 | 4 | 2 | **unknown** |
| Minimum safe version? | 10 | 3 | 7 | 2, 3 | version string |
| Which packages in this file are vulnerable? | 8 | 3 | 5 | 1, 2 | set of names |
| Can I upgrade on Python `N`? | 8 | 2 | 6 | 2, 3, 4 | bool + reason |
| Direct CVE lookup — **over-call probe** | 6 | 3 | 3 | 2 | affected ranges |
| **Total** | **60** | **20** | **40** | | |

Both halves cover all six classes, so the dev subset is representative and the
held-out set isn't measuring something the dev set never saw.

Four classes exist to catch specific failures rather than to measure general
competence:

- **Known, zero advisories.** 25 of the 80 packages carry no advisories at all.
  The correct answer is "not vulnerable" — a positive claim, distinct from
  "unknown".
- **Unpublished version.** The package is known; the version never shipped.
  `django==4.2.0` looks entirely plausible and does not exist, while `4.2` does
  and carries 96 advisories. See §3.6.
- **Unknown package.** No data at all. The only correct answer is "unknown".
- **Over-call probe.** The question needs exactly one tool and no parsing. An
  agent that calls `parse_requirements` here is over-calling, which feeds D3.

The first three share `vulnerable=False` and differ only in `status`, so an
agent reading one field conflates all three. That conflation is a named,
scored failure mode — `negative_conflation_rate` in §4.2 — not a rounding
error.

"Minimum safe version" requires tools 2 **and** 3 because the fix version must
be one that actually exists on PyPI. An agent answering from the OSV record
alone will name versions that were never released — a specific, checkable
failure mode.

### 3.5 Ground truth

Computed once by a reference script reading the same frozen snapshot, stored
alongside each task. Scoring is exact comparison (string, bool, or set
equality). No LLM judge — see §10.2.

**The reference script also derives the minimal necessary tool set, for free.**
Whichever fixture tables the script had to read to produce the answer determine
which tools are necessary. No hand-labelling, and no opinion involved.

### 3.6 Three negatives, not one

`lookup_vulnerabilities` distinguishes three outcomes that all report
`vulnerable=false`:

| Outcome | Meaning | Correct answer |
|---|---|---|
| `package_unknown` | no data held | "unknown" |
| `version_unknown` | package known, version exists in no PEP 440-equal form | "that version does not exist" |
| `ok`, `vulnerable=false` | published and genuinely clean | "not vulnerable" |

**Advisories are checked before the publication test.** 2175 version strings in
the snapshot are named by an advisory but no longer listed on the index —
withdrawn releases and pre-release builds. Testing publication first would
report every one of them as unknown and hide a real vulnerability.

### 3.7 Version comparison is semantic, not lexical

OSV publishes enumerated affected-version lists as strings and PyPI release
keys are strings, but PEP 440 zero-extends the release segment:
`Version("4.2") == Version("4.2.0")` is **True**.

Every comparison therefore goes through `versions_equal` / `version_in`, which
parse both sides first. 694 published versions in this snapshot are shaped
`X.Y`, and the original lexical implementation disagreed with PEP 440 on **all
694** — it would have scored the agent wrong when it was right. A regression
test asserts `X.Y` and `X.Y.0` agree across all of them.

The enumerated-list property in §3.5 is what removes arguable ground truth from
this project, but **only if the comparison against those lists is semantic**.
As raw strings they were a trap, not an asset.

---

## 4. Metrics

### 4.1 Primary metric

**`task_accuracy`** — fraction of tasks whose final answer exactly matches
ground truth.

This is the headline. The three diagnostic families below **explain** it; they
are not peers of it. 90% tool selection with 40% task accuracy is a
fascinating finding; without the denominator it is noise.

Reported for the agent and both baselines (§5), on the same splits.

**The agent-vs-baseline comparison is paired, not two independent
proportions.** Same 40 tasks, same ground truth, two systems — so the
information lives in the **discordant pairs**, and treating them as
independent throws most of it away.

| Reported | Definition |
|---|---|
| `wins` | agent correct, baseline wrong |
| `losses` | baseline correct, agent wrong |
| `ties` | both correct, or both wrong |
| `discordant_pairs` | `wins + losses` |
| McNemar exact | two-sided binomial on the discordant pairs, p = 2·P(X ≤ min(wins, losses)) under Binom(n_discordant, ½) |

Exact binomial, not the chi-square approximation, because the discordant count
will be small.

**Pairing improves power substantially; it does not rescue n=40.** With 9
discordant pairs an 8–1 split is significant; with 4 pairs a 4–0 split is not.
`discordant_pairs` is therefore reported alongside every comparison so a reader
can see which case they are looking at, rather than having to infer it.

### 4.2 D1 — tool selection

Scored against the **minimal necessary** set derived in §3.5.

| Metric | Definition | Status |
|---|---|---|
| `tool_recall` | \|called ∩ necessary\| / \|necessary\| | **Hard requirement.** Below 1.0 means the agent answered without the information it needed — it guessed. |
| `tool_precision` | \|called ∩ necessary\| / \|called\| | **Soft.** Extra calls are waste, not error. |
| `first_call_accuracy` | fraction where the first tool called is the expected one (determinate tasks only) | Reported |
| `no_tool_discipline` | on tasks needing no tool, fraction calling zero tools | Reported |

Two additions beyond tool choice:

| Metric | Definition |
|---|---|
| `negative_conflation_rate` | fraction of §3.6 tasks where the agent gave the wrong negative — "not vulnerable" for an unknown package, "unknown" for a clean one, and so on |
| `invalid_argument_rate` | fraction of calls rejected for a malformed argument, e.g. `since_version="1.26.x"` |

`invalid_argument_rate` exists because `list_releases` now takes a floor
(§3.3), which makes **argument construction** measurable rather than just tool
choice. That is closer to how agents actually fail.

`exact_set_match` is **demoted to a footnote**, labelled "perfect-routing rate
— reported for interest, not a quality measure." It assumes a single valid tool
path per task and penalises correct-but-different routes. Over-calling is
already scored in D3; penalising it here too would double-count it.

### 4.3 D2 — failure recovery

Faults injected at the tool-wrapper layer:

- `error` — tool returns HTTP 503
- `empty` — tool returns a valid but empty result
- `malformed` — tool returns an OSV record missing its `fixed` field

| Metric | Definition |
|---|---|
| `recovery_rate` | fraction reaching the correct final answer despite the fault |
| `fabrication_rate` | see §4.5 |
| `graceful_abstention_rate` | where recovery was impossible, fraction that said so instead of answering |
| behaviour class | one of `retried_same_tool`, `switched_tool`, `abstained`, `fabricated`, `crashed` |

### 4.4 D3 — stopping behaviour

| Metric | Definition |
|---|---|
| `termination_rate` | fraction finishing within `max_steps` (8) |
| `over_call_ratio` | mean of actual tool calls ÷ necessary tool calls |
| `repeat_call_rate` | fraction of tasks with ≥1 identical `(tool, args)` call repeated |
| `steps_to_answer` | distribution, compared against the reference step count |

### 4.5 Fabrication detection

**Checked against the whole frozen fixture, not against what one call
returned.** We own the fixture and it is complete, so a version string or
vulnerability ID either exists in it or it does not.

Extract every version string and CVE/GHSA ID from the agent's final answer,
then:

| Counter | Definition |
|---|---|
| `fabrication_hard` | the token appears **nowhere** in the fixture → invented outright |
| `fabrication_misattributed` | the token exists in the fixture but not for the package under discussion → wrong attribution |

**Two denominators, both reported, never collapsed.** They answer different
questions and have very different precision:

| Rate | Denominator | Reading |
|---|---|---|
| `fabrication_per_assertion` | every version string and advisory ID asserted | **The headline.** Large n, tight interval. |
| `fabrication_per_task` | fault-injected tasks producing ≥1 fabrication | Wide interval at n=20–60, but it is the number a reader intuitively wants. |

A single task can assert a dozen versions, so the per-assertion rate has far
more statistical weight while the per-task rate is the one people reason about.
Reporting only one would either hide the precision or answer the wrong
question.

**Both are explicitly lower bounds.** An agent that implies a version without
naming it is undetectable by string extraction. The report states that rather
than letting the numbers read as complete.

This is the metric the project exists to publish. It is also the most fragile
one, which is why it carries its own caveat in the report.

### 4.6 Suite sizes and wall times

Planning number: ~25 s/task on Qwen3-8B at ~35–50 tok/s.

| Suite | Size | Wall time | When |
|---|---|---|---|
| **Dev** | 20 tasks | ~8–10 min | freely, all of M4 |
| **Dev fault suite** | 10 × 3 modes = 30 runs | ~13 min | freely |
| **Held-out** | 40 tasks | ~17–20 min | **once, day 13** |
| **Held-out fault suite** | 20 × 3 modes = 60 runs | ~25 min | **once, day 13** |
| `no-agent` baseline | 40 tasks | ~7 min | once, day 13 |
| `always-lookup` baseline | 40 tasks | ~8 min | once, day 13 |
| **Final held-out run, total** | **~180 executions** | **~60 min** | **one shot** |

The final run is a single ~1 h job. Everything in it is touched once.

### 4.7 Report structure — by claim type

The sample size (§4.8) cannot support one headline number carrying every
conclusion. So claims are reported in three tiers, each with the treatment it
can actually sustain:

| Claim type | Example | How it is reported |
|---|---|---|
| **Existence** | "the agent fabricates a fix version when the advisory tool returns a malformed record" | One example plus its full trace. **n=1 suffices; no rate.** |
| **Comparison** | "the agent beats call-everything" | Paired: wins / ties / losses + `discordant_pairs` + McNemar (§4.1) |
| **Rate** | "`fabrication_per_task` is 15%" | Point estimate **with interval**, and the word "inconclusive" when the interval is wide |

Existence claims are statistically free and are likely the most interesting
output of this project — a reproducible trace of a named failure mode needs no
confidence interval. The percentage headline stays, but it stops being asked to
carry weight it cannot bear.

### 4.8 What the sample size can and cannot support

40 held-out tasks. Unpaired, a headline accuracy figure carries roughly
**±15 percentage points** at 95% confidence; the fault suite is ~**±22pp** at
20 tasks per mode.

More tasks is not the fix. 80 held-out reaches only ~±11pp and ~96 are needed
for ±10pp, which this time budget cannot buy without gutting the harness that
is the deliverable.

Two things make this workable rather than fatal:

1. **Pairing** (§4.1) moves the agent-vs-baseline comparison off independent
   proportions and onto discordant pairs, which is far more powerful at this n.
2. **Tiering** (§4.7) stops the percentage from carrying claims it cannot
   support, and routes the most interesting findings to existence claims that
   need no interval at all.

Neither makes n=40 behave like n=400. The report says so.

---

## 5. Baselines

Without these, "the agent scored 70%" is unanswerable — 70% against what?
Both are cheap, deterministic, and measured on the same splits as the agent.

### 5.1 `no-agent` — call everything

A fixed script, no routing decision by the model:

1. Run `parse_requirements` on any requirements-like text in the question;
   otherwise regex-extract the package name.
2. For every package found, call tools 2, 3, and 4.
3. Concatenate all results into one prompt. **One** LLM call. Answer.

This is tool *use* without tool *selection*. It is the control that asks
whether agentic routing earns its place at all.

### 5.2 `always-lookup` — one tool, always

Call `lookup_vulnerabilities` on the regex-extracted package(s). Nothing else.
One LLM call.

Expected to fail the "minimum safe version" class (needs real releases) and the
Python-compatibility class. That is the point: it establishes a floor and shows
which question classes genuinely need routing.

### 5.3 What the comparison means

| Outcome | Reading |
|---|---|
| Agent > `no-agent` | routing earns its place; report the margin |
| Agent ≈ `no-agent` | routing costs tokens and latency for nothing — **publish that** |
| Agent < `no-agent` | routing actively hurts; the most interesting result available |
| `always-lookup` ≈ agent | the task set is too easy; say so |

### 5.4 Both baselines run on the held-out 40

Not a subset, not a different sample — **the same 40 tasks as the agent**. The
paired comparison in §4.1 is invalid otherwise: wins and losses are only
defined per task, against the same task.

### 5.5 Baselines are held to the same determinism bar

`no-agent` still calls the model once for its final answer, so it carries
sampling variance exactly as the agent does. `always-lookup` likewise.

`temperature=0` and a fixed seed apply to **every** system under measurement,
and the day-5 reproducibility gate (§6) covers the agent *and* both baselines.
A baseline that wobbles between runs would make the paired comparison
unreproducible even if the agent were perfectly stable.

**Baselines are never cut.** See §13.

---

## 6. Reproducibility — verified day 5

`temperature=0` and a fixed seed, then **run the dev subset twice at end of M2
and confirm the metrics are byte-identical — for the agent and for both
baselines.**

All three are measured systems, and all three call the model. Checking only the
agent would leave the paired comparison (§4.1) resting on an unverified
assumption about the baselines.

Checked on day 5, not day 9, because it is cheap now and expensive later.

**If it fails** — Ollama determinism is not guaranteed across batching and GPU
scheduling even at `temperature=0` — the fallback is 3 repeats with variance
reported on every metric, and the report says `repeatable: False` with the
observed spread. That is a worse result, not a blocker, and it has to be known
before M3 builds the harness around a single-run assumption.

---

## 7. Model: Qwen3-8B, local

**Chosen:** Qwen3-8B Q4_K_M (~5.0 GB) served by Ollama on an RTX 4070 Laptop
(8188 MiB). An 8k context adds ~0.5 GB KV cache, total ~5.5 GB against ~7.2 GB
usable. Fits.

**Fallback:** Qwen2.5-7B-Instruct Q4_K_M (~4.7 GB) — older, but its Ollama
tool-calling path is very well trodden.

### 7.1 Switch trigger — declared before seeing any number

> **If the dev subset scores under 30% `task_accuracy` at end of M2, switch to
> Qwen2.5-7B-Instruct.**

A threshold set in advance is the difference between a decision and a
rationalisation.

### 7.2 Why local, and why a small model

1. **Budget is $0.** This is the binding constraint and it forecloses every
   paid API.
2. **A weak model produces a usable failure distribution.** A frontier model
   would score ~95% and the harness would have nothing to report. An instrument
   that only outputs "it works" is a weak artifact. This is a property of the
   choice, not a consolation.
3. **Fully offline and reproducible** — no key, no quota, no rate limit, no
   silent model drift.

### 7.3 What this costs

Not money — **time.** A full 60-task run is 20–30 min against ~90 s on a hosted
API. That caps iteration at ~6–8 full runs per day, which is why the dev subset
in §4.6 exists.

**Residual risk:** the model may be too weak to produce *any* successful
trajectories, and an all-failures result is as uninformative as an all-passes
one. The §7.1 trigger and the hosted-model comparison column (§9.3) are the
partial cover. It remains a real risk.

### 7.4 Rejected

| Option | Why not |
|---|---|
| Claude Haiku 4.5 | ~$66 for the project. Budget is $0. |
| Any frontier model | Cost, plus it would flatten the result (§7.2) |
| Qwen3-4B | Fits easily, too weak to produce an interesting agent |
| Qwen3-1.7B | Only considered for CPU deployment; see §9.2 |

---

## 8. Rejected domains

### 8.1 Incident triage over synthetic telemetry

Tools would be `search_logs`, `query_metric`, `get_service_graph`,
`get_deploy_history`; ground truth perfect by construction.

**Rejected on cost.** A telemetry generator is a full day of a 14-day budget,
spent before any agent exists. Secondary objection: the data is admittedly
synthetic.

### 8.2 SQL data analyst over a fixed SQLite database

Tools `get_schema`, `run_sql`, `compute`, `lookup_glossary`; ground truth is a
reference SQL query per question. Fastest to build (~2 h) and verification is
bulletproof.

**Rejected because it breaks D1.** Roughly 90% of tasks route to `run_sql`, so
tool-selection accuracy would be near-constant and would measure nothing. It is
also the most common agent demo in existence.

**It is not the overrun fallback.** An earlier draft of this document listed
SQL as the day-3 fallback while simultaneously documenting that SQL destroys
D1 — a contradiction. Switching to it would trade a late project for a
pointless one. See §12 for the actual rule.

---

## 9. Deployment

### 9.1 The constraint

The link must still work in six months. A dead demo link is worse than no link.
That ranks survivability above every other property.

### 9.2 The GPU problem

HF Spaces free tier is 2 vCPU / 16 GB RAM / **no GPU**. Qwen3-8B cannot run
there, so the deployed agent cannot be the evaluated agent.

The fully self-contained alternative was measured rather than assumed:
Qwen3-1.7B Q4 on 2 cores runs ~6–10 tok/s generation with slow prompt
processing — roughly 65 s per agent call, **5+ minutes per query** — and
tool-calling at 1.7B is poor. Immortal, but a demo that visibly fails.
Rejected.

### 9.3 The resolution

The Space serves three things, in descending order of durability:

1. **Landing page: the generated eval report.** Static HTML emitted by the
   harness. Zero runtime dependencies. Cannot break.
2. **Live `/ask` form**, backed by a free hosted open-weight model (Groq free
   tier — no card; terms verified at signup). Best-effort.
3. `/health`, `/metrics`, `/docs`.

**Graceful degradation is a requirement, not a nicety.** When the hosted path
is unreachable the form renders *"Live agent temporarily unavailable — the full
evaluation report is below"* and the report still loads. A demo that says that
reads as competent; one that throws a stack trace reads as broken.

**The demo model is also evaluated.** The report carries two columns — Qwen3-8B
local and the hosted model — so nothing on the public link is an unmeasured
claim. Close to free: Ollama and Groq are both OpenAI-compatible, so it is two
config profiles, not two code paths.

### 9.4 Rejected hosts

| Host | Why not |
|---|---|
| Railway | No free tier; trial credit then the link dies |
| Render free | Spins down at 15 min; free tier repeatedly restricted |
| Fly.io | Card required; billing-surprise risk |
| Azure Container Apps (live) | Free grant still requires a card on file |

**Azure as evidence, not as hosting.** `deploy/azure.sh` is committed and
documented. Running it is optional and card-gated, decided at M6. An unrun
script is weak evidence and the README says so rather than implying otherwise.

---

## 10. Stack

| Layer | Choice | Reason |
|---|---|---|
| Agent | LangGraph, single agent, `create_react_agent` | ~40 lines, stable API, named in target job ads |
| Instrumentation | **tool-wrapper layer, not inside the graph** | the harness must never depend on LangGraph internals |
| Service | FastAPI — `POST /ask`, `/health`, `/metrics` | named in target job ads; needed for deploy |
| Deps | `uv` | fast, reproducible, CI-friendly |
| Quality | pytest, ruff, mypy (light), GitHub Actions | |
| Observability | structlog JSON + `prometheus-client` | Prometheus is first on the cut list (§13) |

**LangGraph is in the plan for job-ad reasons, which is a career argument and
not an engineering one.** A hand-rolled loop would be clearer with no version
churn. The accepted obligation: during M2, walk through exactly what loop
`create_react_agent` generates — the state graph, the tool-call node, the
condition that routes back, and where the step limit is enforced — and record
it in the M2 report. The risk here is not technical, it is being unable to
answer "what does that actually do" in an interview.

### 10.1 CI runs no model

No GPU on free runners, and pulling 5 GB per run is absurd. Real Qwen3
responses are recorded once into committed JSON fixtures; CI replays them —
lint, mypy, unit tests, and a full agent-loop test, all deterministic. A
`--live` flag runs the same tests against real Ollama, locally only.

Clone-to-green stays under 60 s and costs nothing. Sound practice independent
of budget, not a compromise forced by it.

### 10.2 Deterministic evaluators, no LLM judge

Ground truth is exact, so a judge would add variance and cost for no gain.
Target ads name "LLM-as-judge, deterministic evaluators" — the defensible
answer is that the domain was *designed* to have exact ground truth, which
makes deterministic evaluators correct here rather than merely cheaper.

---

## 11. Scope boundary

Written down in advance so it can be pointed at when pressure arrives,
including pressure from the repository owner.

**Excluded, no exceptions:**

- A 5th tool
- Multi-agent, supervisor, or orchestration patterns
- Vector DB or RAG (already proven in the previous project)
- Any web UI beyond the static report and one form
- Grafana
- Kubernetes, Terraform
- Fine-tuning
- **Prompt tuning against the held-out 40**

---

## 12. Risks and triggers

| Risk | Trigger / mitigation |
|---|---|
| Fixture build overruns | **Shrink the fixture, not the domain.** Floor is 20 packages, which still supports all six task classes. The eval design survives; only the corpus shrinks. |
| Qwen3 tool-call parsing fights Ollama | Fall back to Qwen2.5-7B-Instruct |
| Model too weak to produce signal | §7.1 trigger: <30% dev `task_accuracy` at end of M2 → switch |
| Runs non-deterministic | §6: detected day 5 → 3 repeats + variance reporting |
| 20–30 min runs slow M4 | Dev subset (20 tasks, ~9 min) for all iteration |
| Groq free tier changes or disappears | Report is static and primary; form degrades to a notice (§9.3) |
| Docker not yet installed | **Day 1 task**, not day 10 |
| Fabrication detector unvalidated | Reported as a lower bound with the limitation stated (§4.5) |
| M3 underestimated | **Budgeted at 3 days, not 2** — curating unambiguous tasks is slower than it looks |
| Scope growth | §11, enforced |

---

## 13. Cut order, if the project overruns

Decided now so it isn't decided under pressure.

1. **Prometheus / `/metrics`.** Monitoring on HF Spaces is decorative — nothing
   scrapes it. Keep structlog JSON logging, drop the metrics endpoint.
2. **The 4th tool** (`check_compatibility`), if M2 runs long. Costs the
   multi-hop question class.
3. **60 tasks → 40** (13 dev / 27 held-out), preserving all six classes.

**Never cut:**

- The **held-out split** (§3.4)
- The **baselines** (§5)

Those two are the differentiator. Everything else is replaceable.

**The buffer is this list, not a spare day.** The timeline below has none.

---

## 14. Timeline

Day 1 is **2026-10-08**. Deadline **2026-10-21**.

| Day | Date | Work |
|---|---|---|
| 1 | Wed 08 Oct | Install Docker + Ollama · pull Qwen3-8B · M1 repo hygiene, CI green |
| 2–3 | Thu 09 – Fri 10 | Frozen fixture + 4 tools — shrink the corpus if slow (§12) |
| 4–5 | Sat 11 – Sun 12 | M2 agent working locally · **day 5 gates: reproducibility check (§6) + model-switch decision (§7.1) + `create_react_agent` walkthrough (§10)** |
| 6–8 | Mon 13 – Wed 15 | M3 harness · 60 tasks with ground truth · split declared · both baselines |
| 9–10 | Thu 16 – Fri 17 | M4 measure on **dev 20 only** · diagnose · fix · re-measure on dev |
| 11 | Sat 18 Oct | M5 Dockerise |
| 12 | Sun 19 Oct | M6 deploy + monitoring, report built from dev numbers |
| 13 | Mon 20 Oct | **Held-out run — one shot, ~60 min (§4.6)** · regenerate report · redeploy |
| 14 | Tue 21 Oct | M7 docs · `scripts/study_*.py` · README · CONTRIBUTIONS.md |

Deploy comes before the held-out run deliberately: by day 13 the deploy
pipeline is already proven, so publishing the final numbers is a rebuild and a
push, not a first attempt.

No buffer day. If day 13 slips, §13 activates.

**The two-day cushion earned on day 1 is not spare capacity.** Scaffolding and
a data fetcher went fast; that says nothing about curating 60 unambiguous tasks
with ground truth. M3 keeps its full three days, and the cushion is not
available for added scope — see §11.

---

## 15. Definition of done for the project

Not "polished". Done when all six hold:

1. The public link works.
2. The agent runs in Docker from a clean checkout.
3. The harness produces a measured result on the **held-out 40** — good or bad
   — alongside both baselines.
4. A study script explains it, with every claim backed by an assertion.
5. Every milestone ended green: tests pass, linter clean, committed.
6. The held-out set was measured **once**.

---

## 16. Revision history

### 2026-10-08 — senior engineer review, round 3

One item, and it was a real ground-truth bug rather than a design preference.

Version comparison was **lexical**, not semantic. PEP 440 zero-extends the
release segment, so `4.2` and `4.2.0` are the same version, but OSV's
enumerated affected-version lists and PyPI's release keys are both strings. A
naive `in` test disagreed with PEP 440 on all 694 `X.Y`-shaped published
versions in the snapshot. `lookup_vulnerabilities` and `check_compatibility`
were both affected; `list_releases` was already correct because its
`since_version` filter compared `Version` objects.

Worse than the bug: the round-2 notes and the README presented the
`django==4.2` / `django==4.2.0` contrast as *evidence* that the ground truth
was unarguable. It was evidence of the opposite. §3.6 and the README have been
corrected, and §3.7 added.

Worse still: a test — `test_plausible_but_nonexistent_pin_is_not_called_clean`
— asserted the buggy behaviour and passed, supplying false confidence. It now
uses a version with no PEP 440-equal counterpart, and carries a comment saying
what it used to assert.

Fixed in the fixture layer so all four tools inherit it. `Version` hashes
consistently with its equality, so membership stayed O(1).

### 2026-10-08 — senior engineer review, round 2

Day-1 work approved. Six changes before M3 locks the task set.

| # | Change | Where |
|---|---|---|
| 1 | Agent-vs-baseline analysed as a **paired** comparison — wins/ties/losses, discordant-pair count, exact McNemar. Pairing raises power at n=40; it does not rescue it, so the pair count is always reported. | §4.1 |
| 2 | `fabrication_rate` split into **two denominators** — per assertion (headline, tight) and per task (wide, but what readers want). Never collapsed. | §4.5 |
| 3 | **Report tiered by claim type** — existence (n=1 + trace, no rate), comparison (paired), rate (interval, or "inconclusive"). | §4.7 |
| 4 | Baselines run on the **same held-out 40** and are held to the **same determinism bar**; the day-5 gate covers all three systems, not just the agent. | §5.4, §5.5, §6 |
| 5 | **Unknown package separated from known-but-clean**, scored as `negative_conflation_rate`. | §3.4, §3.6, §4.2 |
| 6 | **60-version cap reconsidered.** `list_releases` now takes `since_version`, so the agent can avoid truncation itself instead of tasks being curated around the cap. Argument construction becomes measurable; `invalid_argument_rate` added. | §3.3, §4.2 |

Item 6 removed a selection effect on the benchmark: the cap previously
constrained which tasks could be written at all. It also turned out to be
necessary rather than cosmetic — boto3 carries 2132 releases and django 438,
so an unfiltered listing was never going to fit an 8k context.

Working item 5 surfaced a third negative outcome the review did not name, found
in the built data rather than the plan: a package can be known while the
*version* was never published. `django==4.2.0` looks plausible and does not
exist; `4.2` does and carries 96 advisories. See §3.6.

### 2026-10-07 — senior engineer review

Twelve items applied. Three were structural and could not have been retrofitted
later:

| # | Change | Where |
|---|---|---|
| 1 | **Held-out split added** — 20 dev / 40 held-out, declared before measurement. Without it, M4's "fix and re-measure" would have produced a fitted number reported as clean. | §3.4, §4.6, §15 |
| 2 | **Baselines added** — `no-agent` and `always-lookup`. The eval previously compared against nothing, making any score uninterpretable. | §5 |
| 3 | **Day-3 fallback corrected** — shrink the fixture, not switch domains. The old rule contradicted §8.2 in the same document. | §12 |

Nine refinements:

| # | Change | Where |
|---|---|---|
| 4 | Metric hierarchy restructured — `task_accuracy` is primary, the three required metrics are diagnostics | §4.1 |
| 5 | `exact_set_match` demoted to a footnote; recall hard, precision soft, against a minimal necessary set derived mechanically | §4.2, §3.5 |
| 6 | Fabrication checked against the whole fixture, and reported as a lower bound | §4.5 |
| 7 | Model switch given an advance threshold | §7.1 |
| 8 | Reproducibility verified day 5 | §6 |
| 9 | `create_react_agent` walkthrough required in M2 | §10 |
| 10 | Cut order fixed in advance; M3 rebudgeted 2 → 3 days | §13, §14 |
| 11 | 4th tool retained — the only multi-hop path | §3.3 |
| 12 | Live demo graceful degradation made a requirement | §9.3 |

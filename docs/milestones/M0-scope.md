# M0 — Scope

**Status:** agreed, 2026-10-07
**Rule for this milestone:** decisions only, no code.

---

## 1. Decisions at a glance

| Decision | Choice |
|---|---|
| Task domain | Dependency security triage over a frozen offline snapshot |
| Tools | 4 (`parse_requirements`, `lookup_vulnerabilities`, `list_releases`, `check_compatibility`) |
| Agent model | Qwen3-8B Q4_K_M, local, via Ollama |
| Fallback model | Qwen2.5-7B-Instruct Q4_K_M (decide day 4) |
| Budget | **$0.** Open-weight models only. No paid API. |
| Demo backend | Free hosted open-weight API (Groq free tier), best-effort |
| Public link | Hugging Face Spaces (Docker SDK) |
| Cloud evidence | `deploy/azure.sh` committed; running it is optional, card-gated |
| Framework | LangGraph (single agent) + FastAPI |
| Deadline | 14 days from 2026-10-07 |

---

## 2. What this project is for

A previous project (GraphRAG Bench) covered LLMs, RAG, embeddings, vector
search, local model serving, and evaluation. It covered nothing about Docker,
deployment, monitoring, agents, or cloud — which nearly every German job ad in
the target set asks for. This project exists to close exactly that gap, and
nothing else.

**The thesis:** everyone has an agent demo. Almost nobody can say how well
theirs performs. The eval harness is the differentiator; the agent is the
entry ticket.

Direct consequence: the agent is deliberately *not* optimised. If it evaluates
badly, that is the result and it gets published. No tuning against the eval
set.

---

## 3. Domain: dependency security triage

### 3.1 Why this domain

The project's hard design constraint is **outcomes checkable against ground
truth**. If success can't be verified, it can't be evaluated, and the
differentiator collapses.

This domain satisfies it exactly: every answer is a version string, a boolean,
a set of package names, or a set of CVE IDs — all comparable by equality
against a reference answer computed from the same data.

### 3.2 Data

A **frozen offline snapshot**, committed to the repository:

- PyPI release metadata for ~80 curated packages
- OSV.dev vulnerability records for those packages

Frozen, not live. Three reasons:

1. **Reproducibility.** The benchmark gives the same numbers in six months.
2. **The deployed link cannot die from an upstream outage.** There is no
   upstream at runtime.
3. **Ground truth is stable.** Live data would silently invalidate answers.

The snapshot going stale is expected and documented. It is a benchmark
fixture, not a security product.

### 3.3 The four tools

| # | Tool | Returns |
|---|---|---|
| 1 | `parse_requirements(text)` | `[(name, pinned_version), …]` |
| 2 | `lookup_vulnerabilities(pkg, version)` | OSV records, `[]`, or `package unknown` |
| 3 | `list_releases(pkg)` | ordered list of real releases |
| 4 | `check_compatibility(pkg, version)` | `requires_python` + declared deps |

The tools are deliberately **non-substitutable**. Each question class needs a
different subset, so tool-selection accuracy measures something real rather
than being a formality. This was the deciding factor against the rejected SQL
domain (§6.2), where ~90% of tasks route to a single tool.

### 3.4 Question classes and the 60-task set

| Class | n | Required tools | Answer type |
|---|---|---|---|
| Is `pkg==X` vulnerable? | 12 | 2 | bool + CVE set |
| Minimum safe version? | 12 | 2, 3 | version string |
| Which packages in this file are vulnerable? | 12 | 1, 2 | set of names |
| Can I upgrade on Python `N`? | 10 | 2, 3, 4 | bool + reason |
| Unknown package — **abstention probe** | 8 | 2 | must answer "unknown" |
| Direct CVE lookup — **over-call probe** | 6 | 2 | affected ranges |
| **Total** | **60** | | |

Two probe classes earn their place:

- **Abstention probe.** The package is absent from the snapshot. The only
  correct answer is "I don't know." Anything specific is a fabrication, and we
  know it is, because we know what the tool returned.
- **Over-call probe.** The question needs exactly one tool and no parsing. An
  agent that calls `parse_requirements` here is over-calling, which feeds
  metric 3.

"Minimum safe version" requires tools 2 **and** 3 because the fix version must
be one that actually exists on PyPI. An agent that answers from the OSV record
alone will name versions that were never released — a specific, checkable
failure mode.

### 3.5 Ground truth

Computed once by a reference script reading the same frozen snapshot, stored
alongside each task. Scoring is exact comparison (string, bool, or set
equality). No LLM judge — see §7.3.

---

## 4. The three metrics

Defined precisely here so M3 has nothing left to interpret.

### 4.1 Tool-selection accuracy

| Metric | Definition |
|---|---|
| `exact_set_match` | fraction of tasks where {tools called} == {tools required} |
| `tool_precision` | \|called ∩ required\| / \|called\| |
| `tool_recall` | \|called ∩ required\| / \|required\| |
| `first_call_accuracy` | fraction where the first tool called is the expected one (tasks with a determinate first tool only) |
| `no_tool_discipline` | on tasks needing no tool, fraction where zero tools were called |

### 4.2 Failure recovery

Measured on fault-injected runs. Three injected fault modes, applied at the
tool-wrapper layer:

- `error` — tool returns HTTP 503
- `empty` — tool returns a valid but empty result
- `malformed` — tool returns an OSV record missing its `fixed` field

| Metric | Definition |
|---|---|
| `recovery_rate` | fraction reaching the correct final answer despite the fault |
| `fabrication_rate` | fraction asserting a specific version or CVE ID the tool never returned |
| `graceful_abstention_rate` | where recovery was impossible, fraction that said so instead of answering |
| behaviour class | one of `retried_same_tool`, `switched_tool`, `abstained`, `fabricated`, `crashed` |

`fabrication_rate` is the metric this project exists to report. It is almost
never measured, and it is only checkable because the harness knows exactly what
each tool returned.

### 4.3 Stopping behaviour

| Metric | Definition |
|---|---|
| `termination_rate` | fraction finishing within `max_steps` (8) |
| `over_call_ratio` | mean of actual tool calls ÷ oracle tool calls |
| `repeat_call_rate` | fraction of tasks with ≥1 identical `(tool, args)` call repeated |
| `steps_to_answer` | distribution, compared against the oracle step count |

### 4.4 Suite sizes and run times

| Suite | Size | Wall time |
|---|---|---|
| Fast subset (iteration only) | 15 tasks | ~6 min |
| Full set (reported numbers only) | 60 tasks | ~20–30 min |
| Fault suite | 30 tasks × 3 modes = 90 runs | ~45 min |

---

## 5. Model: Qwen3-8B, local

**Chosen:** Qwen3-8B Q4_K_M (~5.0 GB) served by Ollama on an RTX 4070 Laptop
(8188 MiB). With an 8k context the KV cache adds ~0.5 GB, total ~5.5 GB against
~7.2 GB usable. Fits.

**Fallback:** Qwen2.5-7B-Instruct Q4_K_M (~4.7 GB) if Qwen3 tool-call parsing
proves awkward under Ollama. Decided on day 4, not now.

### 5.1 Why local, and why a small model

1. **Budget is $0.** This is the binding constraint and it forecloses every
   paid API.
2. **A weak model produces a usable failure distribution.** A frontier model
   would score ~95% and the harness would have nothing to report. An
   instrument that only outputs "it works" is a weak artifact. This is a
   feature of the choice, not a consolation.
3. **Fully offline and reproducible** — the same discipline as the previous
   project. No key, no quota, no rate limit, no drift.

### 5.2 What this costs

Not money — **time**. At ~35–50 tok/s, a full 60-task run takes 20–30 minutes
against ~90 seconds for a hosted API. That caps iteration at roughly 6–8 full
runs per day and is why the fast subset in §4.4 exists.

### 5.3 Rejected

| Option | Why not |
|---|---|
| Claude Haiku 4.5 | ~$66 for the project. Budget is $0. |
| Any frontier model | Cost, plus it would flatten the eval result (§5.1) |
| Qwen3-4B | Fits easily but too weak to produce an interesting agent at all |
| Qwen3-1.7B | Only considered for CPU deployment; see §7.2 |

---

## 6. Rejected domains

### 6.1 Incident triage over synthetic telemetry

Tools would be `search_logs`, `query_metric`, `get_service_graph`,
`get_deploy_history`; ground truth perfect by construction, since the root
cause is injected.

**Rejected on cost.** A telemetry generator is a full day of a 14-day budget,
spent before any agent exists. Secondary objection: the data is admittedly
synthetic, which is answerable but is still an objection the chosen domain
doesn't have to field.

### 6.2 SQL data analyst over a fixed SQLite database

Tools `get_schema`, `run_sql`, `compute`, `lookup_glossary`; ground truth is a
reference SQL query per question. Fastest to build (~2 h on a public dataset)
and verification is bulletproof.

**Rejected because it breaks metric 1.** Roughly 90% of tasks route to
`run_sql`, so tool-selection accuracy would be near-constant and would measure
nothing. It is also the single most common agent demo in existence.

**Retained as the fallback.** If the frozen fixture is not finished by end of
day 3, the project switches to this domain. That trigger is a hard date, not a
judgement call.

---

## 7. Deployment

### 7.1 The constraint

The stated requirement is that the link still works in six months. A dead demo
link is worse than no link. That ranks survivability above every other
property.

### 7.2 The GPU problem

HF Spaces free tier is 2 vCPU / 16 GB RAM / **no GPU**. Qwen3-8B cannot run
there, so the deployed agent cannot be the evaluated agent.

The fully self-contained alternative was measured rather than assumed: Qwen3-1.7B
Q4 on 2 cores runs ~6–10 tok/s generation with slow prompt processing — roughly
65 s per agent call, **5+ minutes per query** — and tool-calling at 1.7B is
poor. Immortal, but a demo that visibly fails. Rejected.

### 7.3 The resolution

The Space serves three things, in descending order of durability:

1. **Landing page: the generated eval report.** Static HTML emitted by the
   harness. Zero runtime dependencies. Cannot break.
2. **Live `/ask` form**, backed by a free hosted open-weight model (Groq free
   tier — no card; terms to be verified at signup). Best-effort. If that tier
   changes or disappears, the form degrades to a notice and the report still
   loads.
3. `/health`, `/metrics`, `/docs`.

**The demo model is also evaluated.** The report carries two columns —
Qwen3-8B local and the hosted model — so nothing on the public link is an
unmeasured claim. This is close to free: Ollama and Groq are both
OpenAI-compatible, so it is two config profiles, not two code paths.

### 7.4 Rejected hosts

| Host | Why not |
|---|---|
| Railway | No free tier; trial credit then the link dies |
| Render free | Spins down at 15 min; free tier repeatedly restricted |
| Fly.io | Card required; billing-surprise risk |
| Azure Container Apps (live) | Free grant still requires a card on file |

**Azure as evidence, not as hosting.** `deploy/azure.sh` is committed and
documented. Running it is optional and card-gated, decided at M6. An unrun
script is weak evidence and the README will say so rather than imply otherwise.

---

## 8. Stack

| Layer | Choice | Reason |
|---|---|---|
| Agent | LangGraph, single agent, `create_react_agent` | ~40 lines, stable API, named in target job ads |
| Instrumentation | **tool-wrapper layer, not inside the graph** | the harness must never depend on LangGraph internals |
| Service | FastAPI — `POST /ask`, `GET /health`, `GET /metrics` | named in target job ads; needed for deploy |
| Deps | `uv` | fast, reproducible, CI-friendly |
| Quality | pytest, ruff, mypy (light), GitHub Actions | |
| Observability | structlog JSON logs + `prometheus-client` | |

### 8.1 CI runs no model

No GPU on free runners, and pulling 5 GB per run is absurd. Instead: real
Qwen3 responses are recorded once into committed JSON fixtures, and CI replays
them — lint, mypy, unit tests, and a full agent-loop test, all deterministic. A
`--live` flag runs the same tests against real Ollama, locally only.

Clone-to-green stays under a minute and costs nothing. This is sound practice
independent of budget, not a compromise forced by it.

### 8.2 Deterministic evaluators, no LLM judge

Ground truth is exact, so an LLM judge would add variance and cost for no gain.
Target ads name "LLM-as-judge, deterministic evaluators" — the defensible
answer is that the domain was *designed* to have exact ground truth, which
makes deterministic evaluators correct here rather than merely cheaper.

---

## 9. Scope boundary

Written down in advance so it can be pointed at when pressure arrives,
including pressure from the repository owner.

**Excluded, no exceptions:**

- A 5th tool
- Multi-agent, supervisor, or orchestration patterns
- Vector DB or RAG (already proven in the previous project)
- Any web UI beyond the static report and one form
- Grafana, unless M6 finishes a day early
- Kubernetes, Terraform
- Fine-tuning
- **Prompt tuning against the eval set**

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Fixture build overruns | **Hard cap end of day 3**, then switch to domain B (§6.2) |
| Qwen3 tool-call parsing fights Ollama | Fall back to Qwen2.5-7B-Instruct; decided day 4 |
| 20–30 min eval runs slow M4 to a crawl | Fast 15-task subset for all iteration; full set only for reported numbers |
| Groq free tier changes or disappears | Report is static and primary; live form degrades to a notice |
| Docker not yet installed on the dev machine | **Day 1 task**, not day 10 |
| Scope growth | §9, enforced |

---

## 11. Timeline

| Days | Milestone |
|---|---|
| 1 | M0 sign-off · install Docker · install Ollama · pull Qwen3-8B · M1 repo hygiene, CI green |
| 2–3 | Frozen fixture + 4 tools — **hard cap, see §10** |
| 4–5 | M2 agent working locally |
| 6–7 | M3 eval harness + 60 tasks with ground truth |
| 8–9 | M4 measure, diagnose, fix what's worth fixing, re-measure |
| 10 | M5 Dockerise |
| 11 | M6 deploy + monitoring |
| 12–13 | M7 docs, `scripts/study_*.py`, CONTRIBUTIONS.md |
| 14 | Buffer |

---

## 12. Definition of done for the project

Not "polished". Done when all five hold:

1. The public link works.
2. The agent runs in Docker from a clean checkout.
3. The eval harness produces a measured result — good or bad.
4. A study script explains it, with every claim backed by an assertion.
5. Every milestone ended green: tests pass, linter clean, committed.

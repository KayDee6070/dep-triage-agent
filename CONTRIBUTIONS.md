# Contributions

This repository was built with AI assistance (Claude Opus 5, via Claude Code).
This file separates the decisions I made from the work that was AI-assisted and
from external review, so that nothing in the repository is ambiguous about its
origin.

It is updated at the end of every milestone, not retrofitted at the end.

---

## M0 — Scope

### My decisions

| Decision | Choice | Notes |
|---|---|---|
| Project purpose | Close the gap left by GraphRAG Bench: Docker, deployment, monitoring, agents, cloud | My read of real German job ads I researched myself |
| Task domain | Dependency security triage | Chosen from three proposals |
| Budget | **$0 — open-weight models only** | Overrode an initial API-model recommendation |
| Public link host | HF Spaces + committed-but-optional Azure script | |
| Demo backend | Static eval report primary, live form best-effort | |
| Hard limits | 14 days · one agent · 4 tools max · no Kubernetes | Set before any proposal was made |
| Publication rule | A bad eval result gets published as-is; no tuning against the eval set | Set before any proposal was made |
| **Sought external review before writing code** | Took the M0 brief to a senior engineer | Caught three structural errors (below) |

### AI-assisted

- Drafted the three candidate task domains, with tool decomposition and
  question classes for each.
- Checked the dev machine (GPU, Ollama, Docker, toolchain) and surfaced that
  Docker and Ollama were not installed.
- Costed the rejected API option (~$66 at Haiku 4.5 rates) from a token-level
  estimate.
- Worked out the VRAM arithmetic for Qwen3-8B Q4_K_M on 8 GB, and the CPU
  throughput estimate that killed the self-contained deployment option.
- Surveyed deployment hosts against the six-month-survival requirement.
- Wrote the metric definitions, the task-class breakdown, and the scope
  document itself.
- Produced the self-assessed weakness list that went into the review brief.
  Three of its items were confirmed by the reviewer: the multiple-valid-paths
  problem in metric 1, the fragility of fabrication detection, and the missing
  end-to-end accuracy metric.

### External review — senior engineer, 2026-10-07

Twelve items, all applied. Three were structural and could not have been
retrofitted later:

1. **Held-out split.** The plan had 60 tasks, iterated on a 15-task subset, and
   an M4 of "measure, diagnose, fix, re-measure" — with nothing sealing the
   rest. As written it would have produced a partly-fitted number reported as
   clean. Now 20 dev / 40 held-out, declared before any measurement, held-out
   touched once.
2. **Baselines.** The eval compared against nothing, so no score would have
   been interpretable. Added `no-agent` (call every tool, one LLM call) and
   `always-lookup`.
3. **The day-3 fallback was self-defeating.** See below.

Nine refinements: metric hierarchy (answer accuracy primary, the three required
metrics demoted to diagnostics); `exact_set_match` demoted to a footnote with
recall hard / precision soft; fabrication checked against the whole fixture and
reported as a lower bound; an advance threshold for the model switch;
reproducibility verified day 5; a `create_react_agent` walkthrough required in
M2; a fixed cut order with M3 rebudgeted 2 → 3 days; the 4th tool retained as
the only multi-hop path; graceful degradation made a requirement for the live
demo.

### Errors found and corrected

- **AI error, caught by review.** The M0 draft named the SQL domain as the
  day-3 overrun fallback while, in the same document, rejecting SQL on the
  grounds that it routes ~90% of tasks to one tool and therefore destroys the
  tool-selection metric. Those two statements contradict each other and the
  contradiction went unnoticed. Corrected: if the fixture is slow, **shrink the
  fixture, not the domain** — the floor is 20 packages, which still supports all
  six task classes.
- **My correction to AI output.** The initial recommendation was Claude Haiku
  4.5 with a $100 ceiling. I have no budget, so I rejected it and required
  open-weight models throughout. The plan was reworked around a local Qwen3-8B.

---

## M1 — Repo hygiene

Full report: [`docs/milestones/M1-report.md`](docs/milestones/M1-report.md).

### My decisions

| Decision | Choice |
|---|---|
| Definition of done for M1 | The seven criteria in the M1 report, set before any code was written |
| Milestone ordering | M1 before the sudo installs, because neither Docker nor Ollama blocks repo hygiene |

### AI-assisted

- Package layout, `pyproject.toml`, ruff/mypy/pytest configuration, CI
  workflow, `.gitignore`, `.env.example`, LICENSE.
- The config layer (`src/dep_triage/config.py`) and the CLI.
- All 27 tests.
- Measured clone-to-green against a real clean clone with a cold `uv` cache
  (10 s) rather than timing the working tree, and ran a secret scan before the
  first commit.

### Errors found and corrected

- **A test caught a real bug in the config layer.**
  `test_unknown_env_var_is_rejected` asserted that a mistyped
  `DEP_TRIAGE_MAX_STEP` would fail loudly. It did not: `extra="forbid"` does
  not apply to environment variables, because pydantic-settings only looks up
  variables it already has fields for. In a deployed container that means a
  setting you believe you configured having no effect, with nothing in the
  logs. Fixed with a validator that scans `os.environ` and raises on unknown
  `DEP_TRIAGE_*` keys.

### Deviations from the stated plan

- **mypy runs `strict`, where the M1 definition of done said "light".** A
  deliberate upgrade: strict typing is cheap to adopt across 200 lines and
  expensive across a grown codebase. Recorded rather than quietly changed.
- **License set to MIT without confirmation.** Flagged in the M1 report as
  unconfirmed; one commit to change.

---

## M2 (part 1) — fixture, tools, fault injection

### My decisions

| Decision | Choice |
|---|---|
| Sought a second review before M3 locked the task set | Day-1 update taken to the same senior engineer |
| Accepted all six review items | Including the two with code consequences, applied before any task curation |

### AI-assisted

- Curated the 80-package set across heavy-CVE / moderate / expected-clean
  groups, plus 8 reserved nonexistent names for the abstention probe.
- Built the fixture builder, the schema and loader, the four tools, and the
  fault-injection wrapper. 102 tests.
- Measured the environment rather than assuming it: 44.9 tok/s, 37/37 layers on
  GPU, 6.2 GB VRAM at 8k context.
- Installed Ollama user-local without sudo, with a `systemctl --user` unit.

### External review — senior engineer, round 2, 2026-10-08

Six items, all applied. Two had code consequences and were done before task
curation, which was the point of reviewing at this moment:

- **Paired analysis.** Agent-vs-baseline is the same 40 tasks through two
  systems, so it is reported as wins/ties/losses with a discordant-pair count
  and an exact McNemar test. The reviewer was explicit that this raises power
  but does not rescue n=40, so the pair count is always reported alongside.
- **Two fabrication denominators**, per assertion and per task, never
  collapsed.
- **Report tiered by claim type** — existence claims need no rate at all, which
  makes the most interesting findings statistically free.
- **Baselines on the same held-out 40, same determinism bar**, with the day-5
  gate extended to cover all three systems.
- **Unknown package separated from known-but-clean**, scored.
- **The 60-version cap reconsidered** — `list_releases` gained `since_version`.

### Errors found and corrected

- **A real gap found while implementing item 5, in the data rather than the
  plan.** Version-string format varies by package: `django==4.2` exists with 96
  advisories, `django==4.2.0` never shipped. `lookup_vulnerabilities` was
  answering "not vulnerable" for versions that never existed — conflating
  *absent* with *clean*. It now returns a third negative, `version_unknown`.
  Advisories are checked first, because 2175 version strings in the snapshot
  are named by an advisory but no longer listed on the index; testing
  publication first would have hidden every one of them.
- **Two self-inflicted shell mistakes.** `pgrep -f` / `pkill -f` match the
  agent's own command line and killed the session twice. `pgrep -x` is the
  correct form; recorded in memory.

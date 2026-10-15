# Contributions

This repository was built with AI assistance (initial work with Claude Opus 5
via Claude Code; M3 completion, M4 diagnosis, and M5 Docker with Codex).
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
  **Later correction:** the Django example above was wrong: 4.2 and 4.2.0
  are semantically equal under PEP 440. The implementation was repaired before
  M3 measurement; M4 also removed the surviving incorrect internal docstring.
- **Two self-inflicted shell mistakes.** `pgrep -f` / `pkill -f` match the
  agent's own command line and killed the session twice. `pgrep -x` is the
  correct form; recorded in memory.

---

## 2026-10-15 — deadline withdrawn

### My decision

| Decision | Choice |
|---|---|
| Schedule | **Deadline withdrawn.** Functional and good quality over hitting a date. |

### AI-assisted

- Flagged that the deadline was my own guard against over-polishing — named in
  the original brief — and that deleting it without a replacement would remove
  the stopping line I had asked for.
- Proposed and recorded the replacement: the six-point definition of done
  becomes the stopping line, and the scope exclusions hold regardless of
  available time.

---

## M3 completion — 2026-10-15

### My decisions

- Approved the exposure correction after the audit found that two current
  held-out probes already had published model results. Keep all 60 records,
  never rerun those two, and evaluate the remaining 38 once. Do not manufacture
  replacement tasks.
- Reaffirmed that quality takes priority over schedule, that the harness is
  the deliverable, and that weak or negative results must be reported.

### AI-assisted

- Implemented deterministic suite selection, injected fault runs, JSON traces
  and checkpoints, accuracy and D1/D2/D3 metrics, exact paired McNemar tests,
  fabrication lower bounds, version-answer columns, and a guarded eval CLI.
- Added an executable three-system reproducibility/model-switch gate and
  offline regression tests. Ran the development and fault suites locally.
- Wrote the measurement protocol before live runs and completed the overdue
  M2/M3 reports. Inspected the installed LangGraph source for the walkthrough.
- Corrected claims that exhaustive fixed calls necessarily provide a strict
  information superset, that zero discordances prove equivalence, and that
  the historical 18/20 score describes the current development allocation.

### Errors found and corrected

- **Prior AI/reporting error:** `minsafe-deep-03` and `minsafe-deep-04` were
  already measured despite being described as untouched held-out data. The
  result table and commit message supplied the evidence. The correction was
  escalated to Kuntal before changing the measurement contract.
- **Framework integration error:** the assumed ToolNode exception handling
  did not match the pinned version. An offline retry test first failed with
  `error:ToolError`; an explicit handler now surfaces injected failures without
  changing the prompt, tool data, or baseline algorithms.
- **Instrumentation race:** an offline parallel-call test executed seven
  calls with a budget of two. Atomic bookkeeping now enforces the budget and
  unique trace indices. Unexpected implementation errors are recorded too.
- **Grader bug:** semantic version aliases were treated as distinct answers,
  and the regex truncated post/dev/local releases. Complete PEP 440 extraction
  and semantic deduplication repair those cases without tuning model outputs.
- **Grader bug:** filtering unknown names out of a structured set answer could
  turn an invented package into a correct empty set. Explicit extra names now
  fail the set comparison; unreadable prose is ungradable. All five saved clean
  runs were regraded offline and their metric bytes remained identical.
- **My assistant's M3 classifier error:** the initial retry classification
  counted later calls with different arguments as retries. The corrected rule
  requires identical signatures. Original fault artifacts remain available;
  corrected metrics were computed from saved traces without model reruns.

Full measurements and remaining limitations: [M3 report](docs/milestones/M3-report.md).

---

## M4 — Development diagnosis, 2026-10-15

### My decisions

- Requested M4 continuation under the existing no-tuning and held-out rules.
- The earlier publication rule remains binding: the agent is not optimised
  until it wins, and no additional task or model run is owed merely because
  the observed result is weak.

### AI-assisted

- Diagnosed all four recurring clean failures from saved traces and fixture
  queries: downgrade below a requested floor, two newest-first searches that
  exhaust the budget, and compatibility checked on the wrong version.
- Examined fault answers, including correct labels without supporting tool
  evidence and two confirmed wrong-package version assertions.
- Built an offline audit: 390 saved executions, 1,296 recorded tool attempts,
  all ground truths, grades, and metric bytes verified without new inference.
- Investigated the actual 4k context: no service/model/client override, 782
  journal prompts matching saved token usage, no observed truncation. Preserved
  the distinction between historical 8k hardware tests and M3's runtime.
- Reconstructed the changing baseline input, observed different cache reuse,
  and explicitly left causation unresolved. The reproducibility failure stays.
- Reported model calls and token usage alongside tool counts, without making
  an unsupported total-cost claim. Added eight regression tests and M4 report.

### Errors found and corrected

- **Internal documentation:** a tool docstring still denied the semantic
  equality of Django 4.2 and 4.2.0; reference comments claimed proven minimality.
  Corrected prose only. Model-facing descriptions and execution were unchanged.
- **This assistant's analysis error:** reconstructing prompts directly from
  sorted artifact JSON changed payload key order. A capture-model test exposed
  the mismatch. Replaying and validating deterministic tool outputs preserves
  the original order. No reported model result was changed.
- **This assistant's audit assumption:** a whole-file hash check rejected the
  agent file because its explanatory docstring changed after measurement.
  The revised check verifies the unchanged baseline implementation; input
  reconstruction is explicitly distinguished from captured HTTP evidence.

Full diagnosis and limits: [M4 report](docs/milestones/M4-report.md).

---

## M5 — Docker, 2026-10-15

### My decisions

- Requested pushing completed work to GitHub, then continuing with M5.
- Explicitly chose a **private** `KayDee6070/dep-triage-agent` repository when
  no remote or matching repository existed. Public deployment remains separate.

### AI-assisted

- Created the approved private repository and pushed the existing history.
- Built a multi-stage, digest-pinned, locked-dependency CLI container with a
  non-root runtime, immutable code/data, and no model weights or dev tools.
- Added Docker-level context-canary and offline acceptance checks to CI.
- Verified clean-checkout builds, two live dev smoke executions, exact fixture
  hashes inside the image, output persistence, secret redaction, and failure
  exit codes. No held-out execution or agent tuning occurred.
- Installed checksum-verified Buildx user-local, without sudo. Documented local
  model networking and the need for persistent final-measurement reservations.
- Wrote the [M5 report](docs/milestones/M5-report.md), including limitations:
  Linux amd64 only, no byte-identical image claim, no security-scan claim, and
  an HTTP service still owed at M6.

### Errors found and corrected

- **This assistant's Docker exclusion error:** directory exceptions made the
  initial allowlist too broad. A real-Docker canary test failed; file-only
  patterns now exclude all sixteen synthetic canaries. The regression runs in CI.
- **This assistant's test assumption:** the installed SDK's connection failure
  is `OpenAIConnectionError`, not the initially guessed `APIConnectionError`.
  Corrected the test after inspecting actual CLI output, not production logic.
- **Prior documentation error:** the handoff claimed `deploy/azure.sh` already
  existed. It remains an M6 obligation; the handoff now states that explicitly.

---

## M6 — Service, observability, deployment artifacts

### My decisions

| Decision | Choice |
|---|---|
| Publication | **Not yet.** Publishing makes the report, agent and fixture public and exposes a live endpoint; that stays my call. |
| Repository visibility | Private, unchanged. |

### AI-assisted

- FastAPI service with the deliberate failure asymmetry: the report always
  serves, `/ask` is best-effort.
- structlog JSON logging with redaction; Prometheus collectors fed from the
  same `ToolCallRecord` data the eval harness scores, so the two cannot
  disagree about what a step is.
- Rate limiting with a global daily cap and a per-client per-minute cap.
- Static report generator, self-contained, no charts — at ±15-point intervals
  bars would imply precision the data lacks.
- `deploy/publish_hf_space.sh` and `deploy/azure.sh`, both dry-run by default.
- CI: offline service acceptance in the image, plus a dry-run asserting the
  publish script refuses to publish and its secret scan passes.

### Errors found and corrected

- **The service resolved data paths relative to the working directory**, and
  the Dockerfile copied no evaluation artifacts at all. A deployed container
  would have served a 332-byte placeholder as its landing page while reporting
  `status: ok`, and every local check passed because the working directory
  happened to be the repository root. Found by the new tests, which run from a
  temporary directory. Fixed by making the artifact location explicit and
  shipping the report pre-rendered.
- Earlier handoff wording of mine implied `deploy/azure.sh` already existed. It
  did not; M5 flagged that and M6 wrote it.

---

## M7 (in progress) — study script

### AI-assisted

- `scripts/study_the_harness.py`: twelve sections of prose where every claim is
  verified against the repository as the script runs. 54 claims, computed from
  artifacts rather than hardcoded, so a number that drifts fails the build.
  Wired into CI.

### Still owed in M7

- Publish the Space and record the live URL (needs my Hugging Face account).
- Decide the hosted-backend question below, then the single held-out run.
- README and CONTRIBUTIONS final pass.

### A sequencing conflict I was shown rather than left to discover

M0 §9.3 promised the report carries two model columns so nothing on the public
link is an unmeasured claim, and the held-out set runs exactly once. Those
collide: measuring held-out now with only the local model means the hosted demo
model can never be measured on held-out, and a second run is forbidden.

Three resolutions were put to me — obtain a free hosted key so one run covers
both; publish with no live backend, which makes the two-column promise moot
rather than broken; or drop the promise and amend §9.3 honestly. **My decision
is pending**, and the held-out run is correctly blocked until I make it.

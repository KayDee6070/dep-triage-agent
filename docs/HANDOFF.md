# Handoff — read this first

**Written 2026-10-15 for a fresh assistant session with no prior context.**

Repo: `/home/kuntal/Projects/active/dep-triage-agent`, branch `main`,
16 commits, working tree clean, all checks green.

Read in this order: this file → `docs/milestones/M0-scope.md` (the contract) →
`docs/findings-framing.md` (how results must be reported) → `README.md`.

Every number in this file was verified against the repository on 2026-10-15,
not written from memory: commit count, line counts, fixture and task counts,
the allocation table against `ALLOCATION` in code, the caps, the config
defaults, and the `RECURSION_SENTINEL` string. That check caught one stale
claim — the fixture snapshot date, which moved to 2026-10-09 when the GIT-range
bug was fixed and was still recorded as 10-08 here and in the README. If you
change any of these, re-run the same check rather than trusting the prose.

---

## 1. What this project is, and why it exists

Kuntal is a job-seeking developer near Berlin targeting English-speaking roles.
He finished a previous project (**GraphRAG Bench** — a retrieval benchmark, 80
held-out questions, 764 tests, honest negative result) which covered LLMs, RAG,
embeddings, vector search, local model serving and evaluation. It covered
**nothing** about Docker, deployment, monitoring, agents or cloud — which
nearly every target job ad asks for.

**That previous project is finished. Do not read it, work on it, or use it as a
base.** It lives at `/home/kuntal/Projects/active/graphrag-bench`. If something
is genuinely needed from it, ask first.

This project closes that gap: **one agent, four tools, containerised, deployed
with basic monitoring, plus an evaluation harness that measures whether it
actually works.**

### The thesis, which drives every decision

> Everyone has an agent demo. Almost nobody can say how well theirs performs.
> **The eval harness is the deliverable. The agent is the entry ticket.**

Consequence: the agent is deliberately **not** optimised. If it measures badly,
that is the result and it gets published.

---

## 2. Hard rules — do not violate these

| Rule | Detail |
|---|---|
| **Budget is $0** | Open-weight models only. No paid API, ever. |
| **One agent** | No multi-agent, no supervisor, no orchestration patterns. |
| **4 tools maximum** | A 5th tool is an automatic no. |
| **No Kubernetes** | Docker and a deployed service. No Terraform. |
| **Held-out set runs ONCE** | The 40 held-out tasks are sealed. Never run them to "check". |
| **No tuning against the eval** | Never change a prompt or tool to improve a number. |
| **A bad result gets published** | No quietly dropping metrics that look bad. |
| **No secrets in the repo** | Env vars + `.env.example`; a test enforces parity. |
| **Every milestone ends green** | Tests pass, linter clean, committed. |
| **Push back on scope growth** | Including when Kuntal pushes it. He asked for this explicitly. |

### Also excluded by decision
Vector DB / RAG (already proven in the prior project) · any web UI beyond the
static report and one form · Grafana · fine-tuning.

### How Kuntal works
- "proceed" / "do your thing" = keep working through the milestone, **not** a
  cue to stop and check in. Still stop at genuine decisions that are his.
- **Be honest over encouraging.** Weak results get called weak.
- **Verify, don't assume.** Run things, show real output.
- **Flag your own mistakes.**
- **He has ADHD** — explanations must be concrete and well-structured: short
  sections, real numbers, tables, no walls of text.
- A permission classifier blocks some commands. If denied, **don't work
  around it** — hand him the exact command.
- `sudo` **requires a password** here and cannot be used from a session.
  Install user-local instead (see §9).

---

## 3. There is no deadline — the Definition of Done is the stopping line

**Changed by Kuntal on 2026-10-15: quality over schedule. The 14-day deadline
is withdrawn.**

Context the next session needs, because this reverses an earlier instruction.
The deadline was never external — it was Kuntal's own guard against a failure
mode he named up front: *"My last project sprawled far past its plan,
repeatedly"* and *"Not when it's 'polished' — I over-polish and need a stopping
line."*

Removing the date removes that guard. **Over-polishing is now the live risk,
not running out of time.** So the guard is replaced rather than deleted:

> **Stop when the six Definition-of-Done criteria in §11 all hold. Not when it
> feels finished.**

### What this changes

| | |
|---|---|
| Date pressure | Gone. Milestones take the time they need. |
| The cut list | **Available, no longer forced.** Prometheus, the 4th tool and the full 60 tasks all stay unless something genuinely blocks. |
| Owed work | M2 and M3 reports, and the day-5 gates, get done properly rather than skipped. |
| Scope | **Unchanged.** Every hard rule in §2 still holds. |

### What is still NOT in scope, with unlimited time

This list matters more now than it did under a deadline. None of these become
acceptable just because there is no clock:

- A 5th tool · multi-agent or supervisor patterns · vector DB / RAG
- Any web UI beyond the static report and one form · Grafana
- Kubernetes · Terraform · fine-tuning · a paid API
- More than 60 tasks (measured: 80 held-out only tightens the interval from
  ~±15 pp to ~±11 pp — see §7. More tasks is not the fix.)
- Prompt or tool changes aimed at improving a number
- Re-running the held-out 40 for any reason

**If Kuntal pushes to add any of these, push back.** He asked for that
explicitly, and he asked for it to apply to himself.

### For reference, not as pressure
Started 2026-10-08. Five days passed with no commits (2026-10-10 to 10-15).
M3 is roughly 70% done; M4 through M7 are untouched. Remaining order of work is
in §11 — follow the order, ignore the dates.

## 4. Current state — what exists

### Milestones
| | State |
|---|---|
| M0 scope | ✅ Agreed; **4 rounds of senior review applied** (see §7) |
| M1 repo hygiene | ✅ green — CI, strict mypy, 18 s clone-to-green cold |
| M2 agent | ✅ `dep-triage ask` works end to end on local Qwen3-8B |
| M3 eval harness | 🟡 ~70% — tasks, ground truth, grader, baselines done |
| M4 measure / M5 Docker / M6 deploy / M7 docs | ❌ not started |

### Numbers
3079 lines source + scripts · 1965 lines tests · **203 tests, all passing** ·
ruff clean · mypy `strict` clean on 28 files.

### Files that matter

```
src/dep_triage/
  config.py            Settings (pydantic-settings), env prefix DEP_TRIAGE_
  cli.py               typer app: version, config, ask   (eval/report TODO)
  fixture.py           snapshot schema + loader + SEMANTIC version comparison
  fixture_spec.py      the curated 80-package list + 8 fake package names
  tools/triage.py      the four tools as pure functions over the fixture
  tools/wrapper.py     Toolkit: instrumentation, fault injection, call budget
  agent/loop.py        LangGraph single agent + SYSTEM_PROMPT + AgentResult
  eval/tasks.py        TaskSpec/TaskSet, 9 classes, ALLOCATION
  eval/reference.py    Evidence + resolvers -> computed ground truth
  eval/grading.py      free text -> correct / incorrect / UNGRADABLE
  eval/baselines.py    no_agent, always_lookup
  service/             empty — M6
scripts/
  build_fixture.py     one-time: PyPI + OSV -> data/fixture/   (needs network)
  build_tasks.py       deterministic task selection -> data/tasks.json
data/
  fixture/             80 packages, 1487 advisories, snapshot 2026-10-09, 5.5 MB
  tasks.json           60 tasks, 24 KB
docs/
  milestones/M0-scope.md    THE CONTRACT — 16 sections, revision history at §16
  milestones/M1-report.md
  (milestones/M2-report.md and M3-report.md do NOT exist yet — owed)
  findings-framing.md       how results MUST be reported (written before numbers)
  setup.md                  environment + measured hardware numbers
  HANDOFF.md                this file
CONTRIBUTIONS.md       Kuntal's decisions vs AI-assisted vs external review
```

---

## 5. Architecture, with the reasoning

### The fixture — frozen, never live
`data/fixture/` holds PyPI release metadata + OSV advisories for 80 packages.
Frozen because: the benchmark must give identical numbers in six months, the
deployed service must have no upstream that can fail, and ground truth must be
stable. **25 packages carry zero advisories** — without those, "is X
vulnerable?" is always yes and measures nothing.

Rebuild only if necessary (needs network, ~30 s):
`uv run python scripts/build_fixture.py --output data/fixture`
`--limit N` shrinks the corpus (M0 §12 overrun rule: shrink the fixture, never
switch domain).

### The four tools
| Tool | Signature |
|---|---|
| 1 | `parse_requirements(text)` |
| 2 | `lookup_vulnerabilities(package, version)` |
| 3 | `list_releases(package, since_version=None)` |
| 4 | `check_compatibility(package, version, python_version)` |

Pure functions in `tools/triage.py`. Faults and instrumentation live in
`tools/wrapper.py` **outside** the tools, so a fault-injection bug can never be
mistaken for a tool bug.

**Output caps (measured, not arbitrary):** `RELEASE_WINDOW=60`,
`ADVISORY_WINDOW=10`, `SUMMARY_MAX=160`. Uncapped, `pillow==1.7.7` serialised
to ~8,500 tokens against an 8,192-token context.

**`since_version` exists so the agent can avoid truncation itself** rather than
tasks being curated around the cap. boto3 has 2132 releases. Window slides to
the relevant end: newest without a filter, oldest-above-floor with one.

### Three negatives, not one (M0 §3.6)
`lookup_vulnerabilities` returns three distinct negatives, all with
`vulnerable=false`:

| status | meaning | correct answer |
|---|---|---|
| `package_unknown` | no data held | "unknown" |
| `version_unknown` | package known, version never published | "never shipped" |
| `ok` + not vulnerable | published, genuinely clean | "not vulnerable" |

An agent collapsing these is a scored failure (`negative_conflation_rate`).
**Advisories are checked BEFORE the publication test** — 2175 version strings
in the snapshot are named by an advisory but no longer on the index (withdrawn
releases, pre-releases). Testing publication first would hide real
vulnerabilities.

### Instrumentation at the tool boundary
`Toolkit` records a `ToolCallRecord` per call (tool, arguments, ok, result,
error, duration_ms, fault). **D1 and D3 are computed entirely from these
records, never from LangGraph internals** — M0 §10 commits to this so removing
LangGraph can't invalidate a measured number.

`Toolkit.max_calls` is a budget that **refuses** a call (returns
`status="budget_exhausted"`) rather than raising, because LangGraph's
`ToolNode` catches tool exceptions and feeds them back to the model — an
exception would never surface. Refusing also measures the interesting thing:
what the agent does when told to stop.

### Fault injection
`ToolFault(tool=..., mode=..., occurrence=1)` with three modes:
- `error` — raises `ToolError` ("HTTP 503"), recorded `ok=False`
- `empty` — valid shape, no content
- `malformed` — the key the answer depends on is **removed**, not emptied
  (an advisory with `fixed_versions: []` says "no fix exists"; one with the key
  absent says "this record is broken" — only the second tests recovery)

### Ground truth is computed, never stored
`eval/reference.py`. A task holds **question parameters only**. `resolve()`
derives the answer at run time. Resolvers reach the fixture only through
`Evidence`, and each `Evidence` accessor maps to exactly one tool — so
`required_tools` is **derived**, not declared.

**Important honesty caveat:** it is the *reference path*, not a proof of
minimality. Measured: 53 of 54 `minimum_safe_version` cases are answerable from
tool 2 alone (advisories carry fix boundaries). So `tool_recall` measures
*agreement with the reference path*. This was renamed rather than quietly
reinterpreted.

`Evidence` reads the fixture **completely**, not through the capped tools —
ground truth must not inherit a limit that exists for the agent's benefit. The
separate obligation (answers must be *reachable* through the capped tools) is
enforced in `build_tasks.py` and asserted by a test.

### The task set — 60 tasks, 9 classes
| Class | total | dev | held | reference tools |
|---|---|---|---|---|
| `vulnerable_affected` | 8 | 2 | 6 | {2} |
| `vulnerable_clean` | 6 | 2 | 4 | {2} |
| `version_unpublished` | 6 | 2 | 4 | {2} |
| `package_unknown` | 6 | 2 | 4 | {2} |
| `minimum_safe_version` | 8 | 2 | 6 | {2,3} |
| `minimum_safe_version_deep` | 4 | 2 | 2 | {2,3} — **existence probe** |
| `which_vulnerable` | 8 | 3 | 5 | {1,2} |
| `python_upgrade` | 8 | 2 | 6 | {2,3,4} |
| `single_package_overcall` | 6 | 3 | 3 | {2} |
| **TOTAL** | **60** | **20** | **40** | |

39 distinct packages. Rebuild (deterministic, no network):
`uv run python scripts/build_tasks.py --output data/tasks.json`

`minimum_safe_version_deep` is designated an **existence probe** — reported as
traces, not rates, and exempt from the ≥3 held-out floor. The fixture holds
only 4 genuinely distinct cases (8 if adjacent floors are counted, but
`certifi` from 1.0.0 and 1.0.1 both answer 14.05.14). Padding it would
manufacture precision the data does not have.

### The grader
`eval/grading.py`. **Three outcomes: correct, incorrect, `ungradable`.** An
answer the grader cannot read is *never* counted against the agent — grader
bugs appearing as agent failures is the one way an eval is confidently wrong.

Two tiers:
1. **Answer line** — the agent is asked to end with `ANSWER: <token>`. Tokens:
   `VULNERABLE`, `NOT_VULNERABLE`, `VERSION_UNKNOWN`, `PACKAGE_UNKNOWN`, a
   version string, comma-separated names or `NONE`, or `YES`/`NO`.
2. **Prose fallback** — conservative patterns, flagged per task. Two mutually
   exclusive verdicts matching → `ungradable` (picking the first would invent
   precision).

**Name sets are never graded from prose** — every candidate package appears in
the question, so "gunicorn is vulnerable, attrs and sphinx are not" needs a
clause parser, and a wrong clause parser produces confident nonsense.

On the dev run **20/20 parsed from the answer line, zero fallback, zero
ungradable.**

### The two baselines
`eval/baselines.py`. Both return an `AgentResult` so grading and metrics treat
all three systems identically — the paired comparison is undefined otherwise.

**Fairness rule, load-bearing:** a baseline sees `task.question` and nothing
else. Handing it `task.package` from the record would silently void the
comparison, since the agent must recover those from prose. Both regex-extract
pins from the question text.

- `no_agent` — fixed script, calls every tool on every pin **with naive
  arguments** (unfiltered `list_releases`), concatenates, one LLM call. Tool
  *use* with zero tool *selection*.
- `always_lookup` — tool 2 only, one LLM call. Establishes a floor.

---

## 6. Results so far — dev subset only, held-out untouched

| System | Correct | Incorrect | Ungradable | Mean calls |
|---|---|---|---|---|
| agent | 18/20 | 1 | 1 | 2.4 |
| **`no_agent`** | **20/20** | 0 | 0 | 5.5 |
| `always_lookup` | 19/20 | 1 | 0 | 1.8 |

**Paired:** 0 wins / 18 ties / 1 loss vs `no_agent` → **1 discordant pair**;
0 / 19 / 0 vs `always_lookup` → **0 discordant pairs**.

### The central finding, and its mechanism
`no_agent` calls every tool, so it has **strictly more information than the
agent, on every task, always**. Therefore:

> **Routing is dominated by exhaustive calling whenever calling everything is
> affordable and fits in context.**

That is arithmetic, not a property of these 60 tasks. **Adding harder tasks
would not change it** — the baseline receives the same outputs the agent had to
choose between. Designing tasks until the agent wins would be fitting the
benchmark to a desired result and is explicitly forbidden.

Routing is only undominated under three conditions: **context overflow**,
**faults**, and **cost** (2.4 calls vs 5.5 — the one axis the agent already
wins, to be reported as a first-class number).

### The existence probe, which did not go as designed
| Task | correct | agent | `no_agent` | `always_lookup` |
|---|---|---|---|---|
| pydantic==0.21 | 1.10.13 | 2.14.0 ✗ | 2.14.0 ✗ | 1.6.2 ✗ |
| grpcio==1.34.0 | 1.53.2 | 1.72.2 ✗ | 1.53.2 ✓ | 1.53.2 ✓ |
| redis==4.2.0 | 4.4.4 | 5.0.0 ✗ | 4.3.6 ✗ | 4.3.6 ✗ |
| certifi==1.0.0 | 14.05.14 | 2024.8.30 ✗ | 2024.7.4 ✗ | 2024.7.4 ✗ |

10 of 12 wrong. **The agent failed all four and exhausted its 8-call budget on
every one.** Built to give routing a fair hearing; the honest reading is that
routing did not pay off even where it structurally should.

### The best single artifact in the project
Asked to upgrade from `django==6.1`:
```
[1] list_releases(django, since_version=None)   <- ignored the floor argument
[2] lookup_vulnerabilities(django, 6.1.2)
[3] lookup_vulnerabilities(django, 6.1.1)       <- the correct answer, walked past it
[4] lookup_vulnerabilities(django, 6.1)
[5] lookup_vulnerabilities(django, 6.0.8)       <- now BELOW the pinned version
[6] lookup_vulnerabilities(django, 6.0.7)
[7] lookup_vulnerabilities(django, 6.0.8)       <- repeat: loop signature
answer: 6.0.8
```
Seven calls for a two-call task; "upgraded" to something older than the pin.
One trace exercising argument construction, over-calling and looping at once.

---

## 7. The four senior review rounds — what they mandated

Kuntal has a senior engineer reviewing. All rounds are applied; full history in
`M0-scope.md` §16. **Do not undo these.**

**Round 1** — held-out split (20/40, declared before measurement) · two
baselines · overrun rule = shrink the fixture, never switch domain (an earlier
draft named SQL as the fallback while rejecting SQL in the same document) ·
answer accuracy primary with D1/D2/D3 as diagnostics · drop `exact_set_match`
as headline, recall hard / precision soft · fabrication checked against the
whole fixture and reported as a lower bound · model-switch threshold declared
in advance (<30% dev → Qwen2.5-7B) · reproducibility verified day 5 ·
`create_react_agent` walkthrough required · fixed cut order · M3 budgeted 3
days not 2.

**Round 2** — paired comparison (wins/ties/losses + discordant-pair count +
**exact** McNemar, binomial not chi-square) · **two** fabrication denominators,
never collapsed · report **tiered by claim type** · baselines on the same
held-out 40 with the same determinism bar · unknown-package separated from
known-but-clean · the 60-version cap reconsidered → `since_version` added.

**Round 3** — the PEP 440 bug (see §8, item 1). Was escalated as urgent and was
correct.

**Round 4** — report the clean-arm null result, don't drop the arm · **the
ceiling is structural, don't engineer it away** · routing can only win on
overflow / faults / cost · add the overflow existence probe · report
`ungradable` as a metric · **write the report framing before the numbers land**
(done: `docs/findings-framing.md`).

### Reporting tiers (round 2, item 3) — use these
| Claim type | How to report |
|---|---|
| **Existence** ("it fabricates when the record is malformed") | One example + full trace. **n=1 suffices, no rate.** |
| **Comparison** ("the agent beats call-everything") | Paired: wins/ties/losses + discordant pairs + McNemar |
| **Rate** ("fabrication_per_task is 15%") | Point estimate **with interval**, and "inconclusive" when wide |

### Sample size — stated, not hidden
40 held-out tasks → roughly **±15 pp** at 95% confidence unpaired; fault suite
~±22 pp at 20 per mode. More tasks is not the fix: 80 only reaches ~±11 pp,
~96 for ±10 pp. Pairing and tiering make it workable; neither makes n=40 behave
like n=400.

---

## 8. Six real bugs already found — do not reintroduce

1. **Version comparison was lexical, not semantic.** PEP 440 zero-extends, so
   `Version("4.2") == Version("4.2.0")` is **True**, but OSV lists and PyPI
   keys are strings. A naive `in` disagreed on **all 694** `X.Y`-shaped
   versions. Fixed in `fixture.py` via `versions_equal` / `version_in`
   (`Version` hashes consistently with equality, so membership stays O(1)).
   **Always compare versions through those helpers, never `==` on strings.**
   A test asserts `X.Y` and `X.Y.0` agree across all 694.
   *A green test had encoded the bug* — it used `"1.0"` as a nonexistent
   version when `1.0` is `1.0.0` and exists.
2. **Git SHAs in `fixed_versions`.** OSV publishes `GIT` ranges alongside
   `ECOSYSTEM`; the builder collected both, so commit hashes landed in
   `fixed_versions` and in the fabrication denominator. Builder now filters to
   `type == "ECOSYSTEM"`.
3. **`no_agent` was passing `since_version`.** A narrowing filter *is* a
   routing decision; the "no routing" baseline was routing, which voided the
   comparison and hid the overflow condition.
4. **One tool result exceeded the whole context.** `pillow==1.7.7` → ~8,500
   tokens vs 8,192. Hence `ADVISORY_WINDOW`. `advisory_count` stays exact and
   `all_fixed_versions` carries every boundary across **all** matching
   advisories, not just the shown ones.
5. **LangGraph v1 does not raise on `recursion_limit`.** It returns
   `RECURSION_SENTINEL` ("Sorry, need more steps to process this request.") and
   reports a normal finish — so truncated runs were scored as clean
   terminations. The toolkit budget now bites first, and a test **pins that
   string** so a LangGraph upgrade that rewords it fails loudly.
6. **Mistyped env vars were silently ignored.** `extra="forbid"` does not cover
   environment variables; pydantic-settings only looks up vars it has fields
   for. A `model_validator(mode="before")` now scans `os.environ` and raises on
   unknown `DEP_TRIAGE_*` keys.

Plus: the **first generated task set passed every structural check while being
degenerate** — 22 of 80 packages all alphabetically early, one answer per
class, fixed-size answers, oldest-possible pins (`gunicorn==0.1`). All four
defects are now tests.

---

## 9. Environment — measured, not assumed

| | |
|---|---|
| OS | Ubuntu 24.04, kernel 7.0.0-38-generic |
| GPU | RTX 4070 **Laptop**, 8188 MiB; **7.4 GiB** available to Ollama |
| Python | 3.12.3; pinned `>=3.12,<3.13` |
| `uv` | 0.12.23 at `~/.local/bin/uv` — **must be on PATH** |
| Ollama | 0.40.1, installed **user-local, no sudo**, `systemctl --user` unit |
| Model | `qwen3:8b` (5.2 GB) |
| Docker | **29.1.3 installed 2026-10-15**, daemon active + enabled; Compose 2.40.3 |

### Measured model behaviour
| | |
|---|---|
| Throughput warm | **44.9 tok/s**, 37/37 layers on GPU |
| VRAM @ 8k context | 6.2 GB of 7.4 GiB |
| Agent latency | **1.4–5 s/task** (M0 assumed 25 s; a 60-task run is minutes) |
| `temperature=0 seed=42` | identical output across 3 runs |

### CRITICAL: Qwen3 reasons by default
Answering "17×23" cost **847 completion tokens**. `think: false` and
`chat_template_kwargs` have **no effect**. Only **`reasoning_effort: "none"`**
works — it cuts that to 4. Set via `DEP_TRIAGE_LLM_REASONING_EFFORT`, default
`none`. Without it a two-tool question **times out at 120 s**.

### Docker — installed, with one gotcha
Installed 2026-10-15 via `apt` (`docker.io` 29.1.3 + `docker-compose-v2`
2.40.3). Daemon is `active` and `enabled`. `kuntal` is in the `docker` group
(`docker:x:129:kuntal`) and `hello-world` runs.

**The gotcha:** a login session started *before* the group was created does not
have it, and `docker` fails with
`permission denied while trying to connect to the docker API at
unix:///var/run/docker.sock`. Nothing is wrong — the group is simply not in
that session's credential set.

Two ways through it without logging out:

```bash
sg docker -c "docker run --rm hello-world"   # one command with the group applied
newgrp docker                                # subshell with the group
```

`id -nG | tr ' ' '\n' | grep -qx docker` tells you whether the current session
has it. If it does not, prefix Docker work with `sg docker -c "..."` rather
than reaching for `sudo` — `sudo docker` works but writes root-owned files into
the build context.

Nothing is blocked by this. M5 can proceed.

Nothing further is outstanding from Kuntal. Everything needed to reach the
definition of done is installed.

### Shell trap that killed two sessions
`pgrep -f` / `pkill -f` match the assistant's **own shell command line** and
will kill the session. Use `pgrep -x` / `pkill -x` on the executable name.

---

## 10. Commands

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /home/kuntal/Projects/active/dep-triage-agent

uv sync --frozen                 # 18 s cold clone-to-green
uv run ruff check . && uv run ruff format --check .
uv run mypy                      # strict, 28 files
uv run pytest                    # 203 tests, ~3 s

uv run dep-triage version
uv run dep-triage config         # resolved config, secret redacted
uv run dep-triage ask --trace "Is pyyaml==5.4.1 vulnerable?"

uv run python scripts/build_fixture.py --output data/fixture   # network, ~30 s
uv run python scripts/build_tasks.py  --output data/tasks.json # deterministic

systemctl --user is-active ollama && curl -s localhost:11434/api/version
```

Note: shell output here is compressed by a tool called RTK. It once reported
"No tests collected" when 203 had passed. If output contradicts its own exit
code, re-run as `rtk proxy <cmd>`.

---

## 11. What is left — in order, with definitions of done

### A. Finish M3 (next job)
1. **Fault suite wiring.** Run the dev subset with `ToolFault` injected per
   mode (`error`/`empty`/`malformed`). 10 dev tasks × 3 modes = 30 runs.
   `no_agent` is a one-shot script and **cannot recover** — that is the point.
2. **Metrics module** (`src/dep_triage/eval/metrics.py`):
   - Primary `task_accuracy`; `ungradable` reported separately per split/system
   - **Paired**: wins/ties/losses, `discordant_pairs`, **exact** McNemar
     (two-sided binomial on discordant pairs, not chi-square)
   - D1: `tool_recall` (hard), `tool_precision` (soft),
     `first_call_accuracy`, `no_tool_discipline`, `negative_conflation_rate`,
     `invalid_argument_rate`. `exact_set_match` footnote only.
   - D2: `recovery_rate`, `graceful_abstention_rate`, behaviour class from
     `{retried_same_tool, switched_tool, abstained, fabricated, crashed}`
   - **Fabrication** — extract every version string and advisory ID from the
     answer, check against the **whole fixture** (`Fixture.known_versions`,
     `known_advisory_ids`, `versions_of(pkg)`). Two counters
     (`fabrication_hard`, `fabrication_misattributed`) and **two denominators**
     (`fabrication_per_assertion` = headline, `fabrication_per_task`), both
     labelled **lower bounds**.
   - D3: `termination_rate`, `over_call_ratio` (actual ÷ `oracle_calls`),
     `repeat_call_rate` (use `ToolCallRecord.signature()`), `steps_to_answer`
   - **Version answers**: report **three** buckets — strict (one version, and
     it's right), lenient (right answer present), `ambiguous` (several named).
     An open question from the senior; reporting all three defers it.
3. **`dep-triage eval`** — `--split dev|held_out`, `--system agent|no_agent|always_lookup`,
   `--faults`, writes JSON to `results/`. **Guard the held-out split behind an
   explicit confirmation flag.**
4. **Day-5 gates from M0** (now overdue, do them with the eval runner):
   - **Reproducibility**: dev subset twice, metrics **byte-identical**, for the
     agent **and both baselines**. Failure → 3 repeats + variance reporting.
   - **Model switch**: <30% dev `task_accuracy` → Qwen2.5-7B-Instruct. At 90%
     this will not trigger; record that it was checked.
   - **`create_react_agent` walkthrough** — already documented in
     `agent/loop.py`'s module docstring; lift it into the M2/M3 report.
5. `docs/milestones/M3-report.md` — **does not exist yet**; owed. Format:
   built / decided / measured / still weak. An M2 report is owed too — the
   `create_react_agent` walkthrough belongs in it.

### B. M4 — measure and diagnose, **dev only**
Three known dev failures to diagnose (all genuine agent errors, verified
against the tools and resolver): `minsafe` ignoring `since_version` and walking
downward; gradio finding *a* safe version not *the lowest*; pymongo answering
yes to an upgrade needing Python ≥3.9 on 3.8.

Legitimate fixes: tool descriptions, genuine bugs. **Not** legitimate: prompt
changes aimed at raising a score.

### C. M5 Docker · D. M6 deploy · E. M7 docs
- Deploy target: **Hugging Face Spaces (Docker SDK)**. Chosen for survivability
  — no card, no billing, cannot silently die. Railway/Render/Fly rejected.
- Landing page is the **static eval report**, not the live agent. The live
  `/ask` form is best-effort behind a free hosted open-weight model (Groq free
  tier) and **must degrade to "temporarily unavailable — full report below"**,
  never a stack trace.
- `deploy/azure.sh` committed and documented; running it is **optional and
  card-gated**. An unrun script is weak evidence and the README must say so.
- Demo rate limits are a non-negotiable before the link is public: ~100
  requests/day global, 5/min per IP, `max_steps=8`, short `max_tokens`.
- M7 needs `scripts/study_*.py` — an executable walkthrough where **every claim
  is backed by an assertion**, so running it green proves the prose true.
- Update `CONTRIBUTIONS.md` each milestone: Kuntal's decisions vs AI-assisted
  vs external review, including errors found and corrected.

### Definition of done for the whole project
1. The public link works.
2. The agent runs in Docker from a clean checkout.
3. The harness produces a measured result on the **held-out 40** — good or bad
   — alongside **both** baselines.
4. A study script explains it, every claim backed by an assertion.
5. Every milestone ended green.
6. The held-out set was measured **once**.

---

## 12. Open questions the senior has not answered

1. **Does the structured `ANSWER:` line compromise the eval?** It gives the
   agent a format obligation it would not otherwise have; in exchange grading
   is exact (20/20 parsed, 0 ungradable). Reversible — the prose tier exists.
2. **Ambiguous version answers** — "fixes exist in 4.66.3, 4.67.0, 5.0.0"
   contains the right answer ambiguously. Currently scored correct + flagged.
   **Resolution: report all three buckets** so this stays a choice of column.
3. **If held-out lands near 90%**, the interesting output is failure *modes*,
   not the rate. Affects M7 framing only.

### Known limitations to state in the report, not defend
- `check_compatibility` makes its own class easier by moving PEP 440
  arithmetic into the tool. Deliberate, but it is a thumb on the scale.
- 7 of 9 classes are one-tool-solvable in practice
  (`ONE_TOOL_SUFFICIENT` in `eval/tasks.py`).
- Fabrication detection is **unvalidated against hand labels** — no budget for
  a labelled subset to measure the detector's own precision.
- The deep probe may measure literal-instruction-following rather than triage
  competence: asked for the *lowest* safe `certifi` from `1.0.0`, ground truth
  is `14.05.14` — correct, and ten years old. Every system gave sensible
  *advice* and failed the *literal question*.
- One model, one domain. Nothing generalises beyond Qwen3-8B on Python
  dependency triage.
- `create_react_agent` is deprecated in favour of `langchain.agents.create_agent`.
  Staying put: removal is v2.0 and migrating would add the `langchain`
  meta-package, which is not a dependency.

# M3 — Evaluation harness

**Status:** complete, 2026-10-15. **390 development executions:** five clean
runs × 20 tasks × three systems, plus 10 tasks × three fault modes × three
systems. No real held-out task was executed in this milestone.

The agent scored **16/20** on every clean run. `no_agent` scored **18–19/20**;
`always_lookup` scored **18/20**. The clean comparison does not demonstrate an
accuracy benefit from routing. The paired samples are too small to establish
the baselines' superiority either. Reproducibility failed for `no_agent` and
is reported as failed, despite the final four runs agreeing.

## Built

- Deterministic clean/fault selection, shared execution records, and failure
  capture. Baselines still get only the question and still have no retry loop.
- Primary accuracy, coverage/ungradables, exact paired McNemar, D1/D2/D3,
  version-answer columns, and two fabrication denominators with lower-bound
  labels and explicit undefined cases.
- `dep-triage eval --split dev --system all [--faults]`, producing full JSON,
  canonical metric bytes, and flushed per-task JSONL checkpoints.
- Held-out confirmation and one-use reservations beside the task file. Changing
  the output directory or seed cannot bypass a reservation. Exposed probes are
  excluded independently of the confirmation flag.
- An executable development gate and an offline rescorer that preserves the
  original artifact and records the new evaluator hashes. CI uses scripted
  models and makes no model/network calls.

Verification: **259 tests passed**; ruff lint and format checks passed; strict
mypy passed on **41 files**. The existing LangGraph deprecation warning remains
visible. All 390 saved executions were audited as development-only; their
metrics reproduce from the stored traces with the current evaluator. The real
held-out reservation directory does not exist.

## Decided

The [protocol](M3-protocol.md) fixed selection and denominators before live
measurement. Accuracy is correct / gradable, with total and ungradable counts
alongside it. Correct / total remains available as an observed-success lower
bound. Pairs with an ungradable answer are excluded visibly, not scored wrong.

Kuntal approved preserving all 60 records but excluding the two previously
exposed held-out probes from future execution. The final comparison therefore
has **38 eligible tasks**, not a pristine 40. No replacement tasks were made.
The old 18/20 development result predates the current allocation.

The runtime reported **4,096 context tokens**, despite the handoff's historical
8,192-token measurement. The setting was not changed after seeing scores.
[Runtime evidence](../../results/m3-runtime.json) records the model digest and
observed context. These results describe the actual 4k runtime, not an assumed
8k configuration. `reasoning_effort="none"`, temperature 0, and seed 42 stayed
unchanged.

Two integration fixes preceded live measurement: ToolError is now surfaced to
the agent rather than re-raised by ToolNode's default handler, and atomic
Toolkit bookkeeping enforces the budget under parallel calls. Offline tests
first demonstrated both defects. The four tool functions, their descriptions,
the system prompt, baseline algorithms, fixture, and task file were unchanged.

## Measured — clean development suite

These are per-run measurements over 20 tasks, not 100 independent observations.
All clean answers were gradable. Intervals are Wilson 95%; they remain wide.

| System | Correct across runs 1–5 | Accuracy, first run (95% CI) | Mean attempted calls | Mean executed calls |
|---|---|---|---|---|
| agent | 16, 16, 16, 16, 16 | 80% (58.4–91.9%) | 3.20 | 3.10 |
| no_agent | 18, 19, 19, 19, 19 | 90% (69.9–97.2%) | 5.55 | 5.55 |
| always_lookup | 18, 18, 18, 18, 18 | 90% (69.9–97.2%) | 1.75 | 1.75 |

The agent used 42.3% fewer attempted tool calls than `no_agent`; this is not
proof of lower total cost because the agent makes multiple model calls.
`always_lookup` used fewer tool calls than either and scored above the agent.

| Comparison, agent perspective | Wins / ties / losses | Discordant pairs | Exact McNemar p | Excluded |
|---|---|---|---|---|
| vs no_agent, run 1 | 0 / 18 / 2 | 2 | 0.50 | 0 |
| vs no_agent, runs 2–5 | 0 / 17 / 3 | 3 | 0.25 | 0 |
| vs always_lookup, every run | 0 / 18 / 2 | 2 | 0.50 | 0 |

**Inconclusive comparative accuracy evidence.** Do not describe non-significance
as equivalence. Do not add tasks until the agent wins.

### Diagnostic measurements

| Metric | agent | no_agent | always_lookup |
|---|---|---|---|
| Mean reference-path recall | 1.000 | 1.000 | 0.758 |
| Mean tool precision | 1.000 | 0.479 | 1.000 |
| First-call agreement, determinate cases | 11/11 | 8/11 | 11/11 |
| Terminated | 18/20 | 20/20 | 20/20 |
| Mean calls / reference calls | 1.567 | 3.490 | 1.103 |
| Tasks with an identical repeated call | 1/20 | 0/20 | 0/20 |
| Wrong-negative conflations | 0/7 | 0/7 | 0/7 |
| Invalid arguments observed at the boundary | 0/64 | 0/111 | 0/35 |
| Version answers: strict / lenient / ambiguous | 1/4 / 1/4 / 0/4 | 3/4 / 3/4 / 0/4 | 3/4 / 3/4 / 0/4 |

Full intervals and distributions are in the metric files. No-tool discipline
is undefined: no current task has an empty reference path. Version columns
overlap; semantic aliases do not count as multiple answers. Deep probes have
trace references, not per-class rates.

The agent matched the reference tool set on every clean task yet missed four
answers. That is a concrete reason to keep answer accuracy primary. Reference
path agreement does not prove that the tools were used well or minimally.

### Reproducibility and model-switch gates

The first two canonical metric files differed only in `no_agent` outcomes and
their derived metrics. The changing task was `pyupgrade-02`. The prescribed
fallback ran three additional complete suites, retaining all five results.

- Agent and `always_lookup`: metric bytes identical in the initial pair and
  across all five runs.
- `no_agent`: `repeatable=false`; accuracy 0.90–0.95, mean 0.94, population
  variance 0.0004 (standard deviation 2 percentage points across these runs).
- Every numeric metric's observed variance is retained in
  [gates.json](../../results/m3-gates/gates.json), including paired comparisons.
- Predeclared switch condition: accuracy <30%. Observed agent accuracy was
  80% with 20/20 gradable on every run. **No model switch.**

Do not enlarge the statistical task sample by treating repeats as fresh tasks.
The remaining held-out set still gets one execution per declared system/arm;
development instability must accompany its eventual interpretation.

## Measured — injected faults

Same ten selected task IDs per mode and system. All 90 planned faults fired.
The first lookup may have different arguments across policies: matching an
ordinal/tool does not imply corrupting the same fact.

| Mode | Agent correct / gradable (95% CI) | no_agent correct / gradable (95% CI) | always_lookup correct / gradable (95% CI) |
|---|---|---|---|
| error | 5/10 (23.7–76.3%) | N/A: 0 gradable, 10 crashes | N/A: 0 gradable, 10 crashes |
| empty | 4/10 (16.8–68.7%) | 5/10 (23.7–76.3%) | 3/10 (10.8–60.3%) |
| malformed | 8/10 (49.0–94.3%) | 8/10 (49.0–94.3%) | 8/10 (49.0–94.3%) |

Baselines' error-arm observed success is 0/10, while conditional accuracy is
undefined. Their 20 combined ungradable records result from known crashes,
not ambiguous answer prose. The paired accuracy test excludes all ten pairs
against each baseline in this arm; **zero usable pairs cannot support an
accuracy comparison**. The operational crash difference is directly observed.

For empty outputs, agent vs `no_agent` is 0/9/1; agent vs `always_lookup` is
1/9/0. Each has one discordant pair and exact p=1. For malformed outputs, both
comparisons are 0/10/0 with zero discordances. Comparative evidence is
**inconclusive**, not evidence of equivalence.

Malformed lookup output still carries the vulnerability verdict. Empty output
was byte-unchanged on 6/10 agent calls and 3/10 baseline calls because those
queries already had no advisories. Neither arm is ten equally damaging faults.
Do not relabel a correct direct answer as demonstrated active recovery.

The corrected behaviour classifier found one exact retry in the agent's error
arm, and one subsequent different-tool call in each of the empty/malformed
arms. Other direct answers or same-tool/different-argument paths remain
unclassified. Scheduled baseline calls never count as adaptive recovery.
No graceful-abstention rate is estimated: these transient faults do not
establish impossibility of recovery. Explicit abstention observations were zero
under the conservative rule that a final verdict is not an abstention.

### An auditable recovery example, with limits

`minsafe-02/error`, Django: unfiltered release listing; lookup 6.1.2 returns
503; lookup 6.1.1; lookup 6.1; retry 6.1.2; final answer 6.1.1, correct.
The full messages and outputs are in the corrected fault artifact below.
This demonstrates an actual retry in one trace, not a general recovery rate.

Conversely, `affected-01/error` received a 503 and ended with
`ANSWER: VERSION_UNKNOWN`, which is wrong. `which-01/error` answered `NONE`
after its Twisted lookup failed, treating missing evidence as a clean package.
The detector does not count either as an invented identifier, but both are
answer failures. M4 can diagnose these without tuning the prompt to the score.

## Fabrication — both denominators are lower bounds

No hard fabrication was detected. Two wrong-package version assertions were
detected in `always_lookup/malformed`: pydantic `2.3.4` and Django `6.2`.
Both version tokens exist elsewhere in the fixture but not for the attributed
package. Their full answers and tool evidence are retained; these establish
the existence of this failure in the snapshot, not its general prevalence.

| System / mode | Per assertion, lower bound (95% CI) | Per task, lower bound (95% CI) |
|---|---|---|
| agent / error | 0/3 (0–56.1%) | 0/10 (0–27.8%) |
| agent / empty | 0/3 (0–56.1%) | 0/10 (0–27.8%) |
| agent / malformed | 0/3 (0–56.1%) | 0/10 (0–27.8%) |
| no_agent / error | undefined: no assertions | 0/10 (0–27.8%) |
| no_agent / empty | 0/3 (0–56.1%) | 0/10 (0–27.8%) |
| no_agent / malformed | 0/4 (0–49.0%) | 0/10 (0–27.8%) |
| always_lookup / error | undefined: no assertions | 0/10 (0–27.8%) |
| always_lookup / empty | undefined: no assertions | 0/10 (0–27.8%) |
| always_lookup / malformed | 2/4 (15.0–85.0%) | 2/10 (5.7–51.0%) |

**Inconclusive rate estimates.** The detector is unvalidated against hand
labels. It omits implicit assertions and uncertain attribution; it does not
test whether a claim about an existing version is true. Assertions within a
task are dependent, so their Wilson interval is descriptive, not a claim of
independent precision. A crashing system can emit no fabrications simply
because it emits no answer. Zero detections are not a safety guarantee.

## Artifacts and corrections

Committed evidence, in addition to the executable harness:

- Clean full traces: [run 1](../../results/m3-gates/run-1.json),
  [run 2](../../results/m3-gates/run-2.json), [run 3](../../results/m3-gates/run-3.json),
  [run 4](../../results/m3-gates/run-4.json), [run 5](../../results/m3-gates/run-5.json).
- Their `.metrics.json` siblings provide the exact compared bytes;
  [gate outcomes and variance](../../results/m3-gates/gates.json) contain hashes.
- [Original fault run](../../results/m3-faults.json) and
  [corrected fault metrics and full traces](../../results/m3-faults-rescored.json).
  Use the corrected artifact for the retry counts reported above.
- [Runtime context and digest](../../results/m3-runtime.json).

Two evaluator corrections followed offline review. The name-set parser no
longer drops explicit extra package names, and incomplete version tokens no
longer match valid prefixes. Regrading all five saved clean runs yielded
byte-identical metrics; no model run was repeated for those corrections.

My initial behaviour classifier incorrectly called different-argument lookups
retries. A regression test now requires identical signatures. The fault run was
rescored offline; the original remains intact, and rescoring provenance records
zero model executions. These corrections were not changes to agent outputs.

## Still weak / next milestone

- One model, one dependency snapshot, 20 development tasks; no generalisation
  claim. The final 38 remain unexecuted.
- The baseline's reproducibility failure and actual 4k context must remain
  visible. Final-runtime configuration needs explicit recording before M4/M5
  feeds the final evaluation; do not silently substitute the old 8k claim.
- Faults target the first lookup, not every tool or persistent outages. The
  arms cannot estimate graceful abstention when recovery is impossible.
  Each fault case was measured once; fault-arm reproducibility was not separately
  tested, and the clean baseline instability limits inference here too.
- Call selection, argument choice, answer correctness, termination, and
  fabrication are different measurements. A good score in one does not imply
  a good score in the others.
- HTML reporting, Docker packaging, deployment, and the assertion-backed study
  script remain M4–M7 work. M3 does not satisfy the whole-project definition of done.

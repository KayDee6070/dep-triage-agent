# How results will be framed

**Written 2026-10-10, before the fault suite ran.** The original claim that no
held-out task had been touched was false: redis and certifi below were already
assigned to `held_out`. On 2026-10-15 Kuntal approved preserving all tasks,
excluding those two from future execution, and reporting the remaining 38
separately. See [the measurement amendment](milestones/M3-protocol.md).

Committed at this date deliberately: a framing written after
seeing the numbers is indistinguishable from a framing chosen to suit them.

Everything below is a commitment about *how* a result gets reported, not a
prediction of what it will be. Where an outcome would change the conclusion,
both branches are written out in advance.

---

## 1. The clean-arm null result

**Historical measurement of the prior dev subset, 20 tasks:** this predates the
deep-probe allocation change. Do not present these as current-set results.

| System | Correct | Mean calls |
|---|---|---|
| agent | 18/20 | 2.4 |
| `no_agent` (call everything) | 20/20 | 5.5 |
| `always_lookup` (one tool) | 19/20 | 1.8 |

Paired: 0 wins / 18 ties / 1 loss against `no_agent` (**1 discordant pair**);
0 / 19 / 0 against `always_lookup` (**0 discordant pairs**).

**This is reported as a finding, not padded and not dropped.** Zero discordant
pairs means no difference was observed among the gradable paired outcomes.
It does not establish statistical equivalence or general equality of systems.

### The mechanism, stated so the result is interpretable

`no_agent` calls each tool on each extracted pin, with fixed arguments. It
often supplies more tool output than the agent chooses to request. It does
**not** necessarily contain the same information: the agent can filter release
windows or check a newly selected version, while the script checks the pin.
The original unconditional strict-superset claim exceeded what the code does.

So:

> When fixed exhaustive calls supply all evidence needed for the answer and
> fit the budget and context, routing has no information-access advantage.

Whether those conditions hold is task-dependent; the baseline's name does not
prove them. Designing tasks until the agent wins would still fit the benchmark
to a desired result and remains explicitly forbidden.

### Consequence for the report

A headline must use the observed paired counts and their uncertainty. If the
final clean comparison supplies no evidence of an advantage, it can say:

> On this clean task set, routing provided no demonstrated accuracy benefit
> over the baselines. Report wins, ties, losses, excluded pairs, discordances,
> and exact McNemar p from the actual run.

The original placeholder asserted zero discordances on 40 held-out tasks
before that measurement existed. It was not a result and must not be quoted
as one.

---

## 2. Where routing can win, and why those three conditions

Routing is not dominated when exhaustive calling is *unable* to compete. Three
such conditions, each structurally motivated rather than chosen to flatter:

| Condition | Why the baseline cannot compete |
|---|---|
| **Context overflow** | `no_agent` concatenates everything. Unfiltered `list_releases` truncates at 60 of up to 2132 releases; if the answer is older it is simply absent from the baseline's input. A routed agent can issue `since_version`. |
| **Faults** | `no_agent` cannot adapt its calls or retry. Its sole model answer can still abstain if the script reaches it. |
| **Cost** | 2.4 calls against 5.5. On a metered API this is the entire argument for routing, and it is the one axis where the agent already wins. |

Cost is reported as a first-class number, not a footnote.

**M4 clarification, 2026-10-15:** the cost row above uses historical tool-call
counts, not measured total cost. On the current first clean run the agent uses
64 tool attempts versus 111 for `no_agent`, but 83 model calls versus 20.
Summed input usage is 105,332 versus 37,588 tokens, with substantially different
cache reuse. Neither tool counts nor aggregate tokens alone establish total
cost savings. Report those quantities separately; do not turn the earlier
metered-API argument into an unmeasured cost finding. See
[M4-report](milestones/M4-report.md#tool-savings-do-not-establish-total-cost-savings).

### A baseline bug this analysis found

`no_agent` was calling `list_releases(name, since_version=version)`. Passing a
narrowing filter **is** a routing decision; a script that knows to do that is
not "call everything". It also hid the overflow condition entirely. The
baseline now calls the tool unfiltered, which is what the comparison means.

---

## 3. The existence probe, and why it is four tasks

`minimum_safe_version_deep` requires all three of:

- the answer is **outside** the window an unfiltered `list_releases` returns;
- the highest advisory fix boundary is **not** the answer, so the one-tool
  shortcut through `all_fixed_versions` is wrong;
- a `since_version` query **does** reach it.

The committed snapshot contains **four genuinely distinct cases** — eight if
adjacent floors are counted, but `certifi` from `1.0.0` and `1.0.1` both answer
`14.05.14`, so those are duplicates.

Four tasks cannot carry a rate. They can carry an existence claim, which needs
no interval. **This class is therefore reported as traces, not percentages**,
and is exempt from the per-class held-out floor with that reason recorded in
code. Padding it to a respectable count with near-duplicates would manufacture
precision the data does not have.

### First measurement, and it did not go as designed

| Task | correct answer | agent | `no_agent` | `always_lookup` |
|---|---|---|---|---|
| pydantic==0.21 | 1.10.13 | 2.14.0 ✗ | 2.14.0 ✗ | 1.6.2 ✗ |
| grpcio==1.34.0 | 1.53.2 | 1.72.2 ✗ | 1.53.2 ✓ | 1.53.2 ✓ |
| redis==4.2.0 | 4.4.4 | 5.0.0 ✗ | 4.3.6 ✗ | 4.3.6 ✗ |
| certifi==1.0.0 | 14.05.14 | 2024.8.30 ✗ | 2024.7.4 ✗ | 2024.7.4 ✗ |

These are historical observations, including the two exposed held-out tasks.
Full raw traces were not retained in this checkout; this table is not a
substitute for trace evidence. 10 of 12 runs were wrong. The agent failed all four and **exhausted its 8-call
budget on every one**.

The class was built to give routing a fair hearing. The honest reading is the
stronger one: **routing did not pay off even under the condition where it
structurally should.** That is reported as the finding, not explained away.

### A limitation of this class, stated now

Every system answered with a recent version. Asked for the *lowest* safe
version of `certifi` pinned at `1.0.0`, ground truth is `14.05.14` — correct,
and ten years old. The systems gave sensible *advice* and failed the *literal
question*. A reader may reasonably say the class measures literal-instruction
following rather than triage competence. The report will say so rather than
wait to be asked.

---

## 4. `ungradable` is a metric

Reported per split and per system alongside correct and incorrect, never folded
into either. Rewording an ambiguous question dropped dev ungradables from 3 to
1; that change is recorded, and the count stays visible so a reader sees the
denominator rather than discovering it shrank.

An unreadable answer is a grader limitation, not an agent error. Scoring it as
an agent error is the one way this eval could be confidently wrong.

---

## 5. The fault arm — framing fixed before the numbers

This is where routing has its strongest structural claim: `no_agent` has one
shot and cannot recover.

| Outcome | How it is reported |
|---|---|
| Agent recovers materially better | Routing earns its place **specifically under failure**, which is narrower than "agentic systems are better" and will be stated that narrowly. Reported paired, with the discordant-pair count. |
| Agent does **not** recover better | The stronger finding. Routing fails to pay off even where exhaustive calling structurally cannot compete — meaning the agent is not using its extra freedom. Reported as the headline. |
| Agent fabricates under failure | The metric this project exists to publish. Reported per assertion (headline) and per task, both as lower bounds. |

No branch here is a disappointment. The only bad outcome would be an
inconclusive result reported as a positive one.

---

## 6. What will not happen

- No task will be added, replaced or reworded. The approved exposure exclusion
  changes execution eligibility, not the committed task records.
- No prompt will be changed to improve a number. Changes that remove ambiguity
  from a badly written question are allowed before the held-out run and are
  recorded individually.
- A gap smaller than the interval is reported as inconclusive, never as a trend.
- The remaining held-out 38 is executed **once per declared system/arm**. The
  two exposed probes are never executed again and are disclosed separately.

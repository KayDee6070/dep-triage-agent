# M4 — Development diagnosis

**Status:** complete, 2026-10-15. **Zero new model executions.** Diagnosis uses
the five clean development runs and the corrected fault artifact from M3.
The remaining held-out 38 and the two excluded probes were not executed.

The agent remains **16/20**, versus **18–19/20** for `no_agent` and **18/20**
for `always_lookup`. No demonstrated accuracy benefit from routing. The paired
comparisons remain inconclusive; [M3-report](M3-report.md) retains every count,
interval, denominator, and exact McNemar result. This milestone adds mechanisms,
not a more favourable score.

## Built and verified

[`scripts/diagnose_dev.py`](../../scripts/diagnose_dev.py) audits the committed
evidence without invoking a model. It verifies task and fixture hashes, planned
development cases, recomputed ground truth, grades, embedded metrics, and
canonical metric bytes. It replays each recorded tool attempt, including faults
and budget refusals, and compares every field except elapsed time.

**390 executions and 1,296 tool attempts match.** This establishes consistency
of the saved evidence with the current deterministic implementation, not that
the model would choose the same calls again. It is not an independent validation
of the fixture's real-world security accuracy.

```bash
uv run python scripts/diagnose_dev.py
# Or save to a NEW path; existing artifacts are never overwritten:
uv run python scripts/diagnose_dev.py --output results/m4-local-audit.json
```

Machine-readable evidence: [diagnosis](../../results/m4-diagnosis.json) and
[runtime investigation](../../results/m4-runtime.json). Eight new offline
tests cover replay, tampering, held-out rejection, prompt reconstruction,
failure explanations, variability, fabrication examples, and token accounting.

## Four clean failures

These four failures recur in all five runs. All answers are gradable. The
table describes the first run; the diagnostic artifact checks the repeated
failure IDs. Versions below are claims about the frozen snapshot only.

| Task | Expected | Agent answer | Attempted / executed calls | Observed failure |
|---|---|---|---|---|
| `minsafe-02`, Django from 6.1 | 6.1.1 | 6.0.8 | 7 / 7 | Answer is below the requested upgrade floor |
| `minsafe-deep-01`, pydantic from 0.21 | 1.10.13 | 2.14.0 | 9 / 8 | Searches down from newest; never narrows the release window |
| `minsafe-deep-02`, grpcio from 1.34.0 | 1.53.2 | 1.72.2 | 9 / 8 | Same search pattern; final candidate's lookup is refused |
| `pyupgrade-02`, pymongo on Python 3.8 | NO | YES | 5 / 5 | Checks compatibility of the pin, not the upgrade target |

### Django: branch fixes are not interchangeable upgrades

The agent lists releases, verifies 6.1.2 and 6.1.1 as clean, then looks up the
vulnerable pin 6.1. That lookup returns fix boundaries **5.2.17, 6.0.8, 6.1.1**.
It subsequently verifies 6.0.8, tests 6.0.7, repeats the 6.0.8 lookup, and
answers 6.0.8. The answer is clean but is a **downgrade** from 6.1.

This is an answer-constraint failure, not missing evidence: the correct version
was already listed and checked. PEP 440 ordering confirms the downgrade.
The tool's multiple branch boundaries are legitimate data, not a reason to
remove branches or tailor the prompt to this example.

### Deep probes: available filtering, unused

The unfiltered tool explicitly reports truncation and returns the newest 60
versions. Neither trace supplies `since_version`. Both spend seven successful
lookups on recent clean releases before the ninth attempted tool call is refused.

| Probe | Unfiltered 60-version window | Window filtered at the task floor | Correct answer reachable? |
|---|---|---|---|
| pydantic | 2.7.0b1 through 2.14.0 | 0.21 through 1.10.13 | Yes, within those 60 releases |
| grpcio | 1.65.0rc2 through 1.85.0rc1 | 1.34.0 through 1.54.0rc1 | Yes, 1.53.2 is included |

The existing model-facing description already explains `since_version`.
Offline tool queries verify reachability; they are not additional model trials.
The exact lowest version is a stricter objective than recommending a recent
clean version. The agent fails that literal objective even when filtering could
reach the answer. Two probes support these examples, not a per-class rate.

Both baselines answer grpcio correctly from advisory evidence. On pydantic,
`no_agent` answers 2.14.0 and `always_lookup` answers 1.6.2, both wrong. Having
the expected version among several fix boundaries does not guarantee choosing
the lowest version that resolves all advisories.

### Python upgrade: tool-set agreement misses argument errors

The agent's only compatibility query concerns **pymongo 4.18.1**, the current
pin. Its result says `requires_python=">=3.9"`, `python_compatible=false` on
Python 3.8. The agent then finds 4.18.2 clean, never checks its compatibility,
and answers YES. An offline query for the actual target **4.18.2** also returns
`>=3.9` and false.

The agent selected all three reference tools, so reference-path recall and
precision are both 1.0. Those scores cannot detect using the right tool on the
wrong version or ignoring its output. The task's answer grade catches the error.
`no_agent` also checks only the pin. Its later correct NO is not proof that
the script obtained target-version compatibility evidence.

## Fault behaviour: correctness is not verified recovery

The unchanged M3 error arm has five correct agent answers out of ten, while
each baseline crashes on all ten. That is an observed operational difference.
With no gradable baseline answers, there are **zero usable paired accuracy
comparisons**. Neither a recovery advantage in general nor comparative accuracy
significance follows from those counts.

The five correct agent answers illustrate why the headline needs traces:

| Error-arm task | What the trace establishes |
|---|---|
| Django `minsafe-02` | An exact retry of failed 6.1.2 occurs; final 6.1.1 is verified clean and correct |
| tqdm `minsafe-01` | Final 4.66.3 is correct, but its lookup was refused at the budget limit |
| `unknown-01` | The sole lookup fails; PACKAGE_UNKNOWN happens to match ground truth without a successful result |
| `unpublished-01` | The sole lookup fails; VERSION_UNKNOWN happens to match ground truth without a successful result |
| `pyupgrade-01` | YES is correct, but compatibility was checked on the original pin, not the selected clean release |

Conversely, a failed Twisted lookup becomes VERSION_UNKNOWN on two tasks.
`which-01/error` answers NONE despite never obtaining Twisted's verdict. These
are missing-evidence conflations, not fabricated identifiers, so a zero
fabrication count must not conceal them. Prose saying "could not determine"
followed by a categorical `ANSWER:` is not counted as graceful abstention.

The empty fault leaves the first agent lookup unchanged on 6/10 tasks; the
malformed fault removes fix fields but preserves the vulnerability verdict.
Equal malformed-arm accuracy is therefore not evidence that all systems repaired
damaged evidence. Baselines' subsequent calls are fixed, not adaptive retries.
No fault distribution or grading rule was changed after inspecting these cases.

### Two confirmed wrong-package version claims

`always_lookup/malformed` asserts pydantic **2.3.4** and Django **6.2** as lowest
safe versions. Inspection of the fixture confirms that neither version belongs
to the named package, while both tokens exist elsewhere in the fixture.
The lookup payloads have missing fix fields; the model supplies unsupported
replacement versions. These are **misattributed**, not hard fabrication under
the declared definitions.

The M3 counts remain **2/4 extracted assertions** and **2/10 tasks**, both
labelled lower bounds. Inspecting these two positives does not validate detector
recall, the skipped assertions, or its rate estimate. Claims about real versions
can still be false without triggering this detector.

## Runtime context: 4k was real; overflow was not observed

The active user service has no context override or drop-in. Its process has no
`OLLAMA_CONTEXT_LENGTH`; the startup log reports an automatic context setting
of 0. The model has no `num_ctx` parameter, and `build_model` supplies no context
override. The model metadata's 40,960 capacity is not the allocated runtime
context. At diagnosis the model had unloaded; `/api/ps` was empty, and no model
was loaded just to inspect it.

The earlier [M3 runtime capture](../../results/m3-runtime.json) reported 4,096.
The journal independently supplies **782 prompts**, all with
`n_ctx_slot=4096`. Their input-token counts match all **782 saved assistant
usage records in execution order**, spanning five clean runs and the fault
suite. All 782 release records have `truncated=0`; no `truncating` or
`context shift` message appears. Maximum prompt length is 3,995 tokens.

Ollama documents a 4k default below 24 GiB VRAM. The missing override and runner
logs explain the observed allocation on this 8 GB GPU. The historical 8k
benchmark did not establish a persistent 8k service setting. We cannot date
when any earlier temporary override ceased to apply. Sources:
[context length](https://docs.ollama.com/context-length), local service/process
inspection, and the saved runtime evidence above.

The four failing agent traces peak at **2,776 / 2,076 / 2,115 / 2,659 input
tokens**, respectively. There is no observed overflow explaining them. Logs
and counts are not proof of the model's internal reasoning or complete byte-level
input retention. No 8k comparison was run, and no claim about its counterfactual
score is made. Runtime, model, seed, temperature, reasoning setting, and budget
were unchanged. Future local measurement must verify the actual allocation;
do not silently relabel these results as 8k or change context to chase a score.

## Reproducibility: input stable, output not fully stable

Only `no_agent/pyupgrade-02` changes correctness: YES in run 1, NO in runs 2–5.
The saved questions, tool payloads, settings, dependencies, and recorded source
hashes are identical across clean repeats. Reconstructing the baseline prompt
using deterministic tool output yields the same input hash in all five runs.
Tests compare that reconstruction with inputs captured from the real baseline
code using a fake model. Original baseline input messages were not retained,
so this is a reconstruction, not an original HTTP request capture.

Input usage is 2,215 tokens every time. Reported cache reuse differs:
**272 tokens** in run 1, **973** thereafter. This is a candidate contributor,
not a demonstrated cause: no controlled cache intervention or backend numerical
analysis was performed. The reproducibility gate remains failed. Keep the
observed 90–95% accuracy range, variance, and all five artifacts; do not promote
the four agreeing repeats into a deterministic result.

## Tool savings do not establish total cost savings

First clean run, 20 tasks per system:

| System | Tool attempts | Model calls with usage | Input tokens, summed | Reported cached input | Output tokens |
|---|---|---|---|---|---|
| agent | 64 | 83 | 105,332 | 89,480 | 2,409 |
| no_agent | 111 | 20 | 37,588 | 5,435 | 615 |
| always_lookup | 35 | 20 | 15,013 | 9,085 | 565 |

The agent uses 42.3% fewer tool attempts than `no_agent`, but 4.15 times as many
model calls. Input sums include repeated conversation context and cache hits.
They are not independent tokens, billable dollars, or a controlled compute-cost
comparison. The local run costs no API money. Report tool calls, model calls,
and token usage separately; neither lower tool count nor higher aggregate input
alone proves lower or higher total cost.

## Changes, non-changes, and completion

No behavioural bug was found that explains these four clean failures. The
recorded tool boundary replays exactly; the failures remain model decisions or
unsupported final conclusions. No prompt, model-facing description, tool
implementation, baseline algorithm, task, fixture, or runtime setting changed.
There was therefore no behavioural fix requiring another development model run.

Two internal documentation errors were corrected: the lookup docstring still
claimed Django 4.2.0 differed from 4.2; reference comments still called a
reference path a proven minimum. Neither text is a model-facing description.

During this analysis, the assistant initially rebuilt baseline prompts from
sorted saved JSON, losing the original payload key order. A capture-model test
caught the mismatch. Reconstruction now replays and validates the deterministic
tool outputs before serialising them. The assistant also initially required the
whole agent file's old hash to match, overlooking its documented post-run
docstring edit. The audit checks the unchanged baseline implementation instead.
Neither mistake changed saved model results or reported metrics.

**Milestone verification:** 267 tests pass; ruff lint and format checks pass;
strict mypy passes on 43 files. All 390 saved grades/metrics are unchanged.
The final held-out reservation directory remains absent. M4's stopping line is
met: four failures diagnosed, representative fault failures and fabrications
explained, context discrepancy investigated, repeatability limits preserved,
and an executable offline audit committed. **Next: M5 Docker**, not another
round of prompt tuning. Final held-out measurement remains deferred until the
end of the project.

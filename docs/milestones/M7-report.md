# M7 — Final measurement, publication, documentation

**Status:** the held-out set is spent, the report is published, the study
walkthrough is green. One obligation unmet and disclosed: the hosted model has
no held-out column.

316 tests · ruff and format clean · strict mypy on 54 files · CI green
including the container and image-publish jobs.

---

## The result

**38 held-out tasks, executed once**, after the last change to anything the
agent does.

| System | Score | Accuracy | 95% CI | Ungradable | Mean calls |
|---|---|---|---|---|---|
| agent | 35/38 | 92% | 79–97% | 0 | 2.79 |
| `no_agent` | 34/38 | 94% | 82–98% | 2 | 4.95 |
| `always_lookup` | 35/38 | 92% | 79–97% | 0 | 1.58 |

Paired, agent's perspective:

| Comparison | W/T/L | Discordant | Exact McNemar p |
|---|---|---|---|
| vs `no_agent` | 2 / 31 / 3 | 5 | 1.0 |
| vs `always_lookup` | 2 / 34 / 2 | 4 | 1.0 |

**The null result held.** Both comparisons sit below the six discordant pairs
an exact two-sided test needs to reach p < 0.05 under *any* split, so neither
resolves. Reported as unresolvable, not as equivalence.

The agent narrowly out-scored `no_agent` here (35 against 34) having lost to it
on development. That reversal is noise at this sample size, which is precisely
why the paired reading is the headline and the percentages are not.

### Where routing does pay off

Fault arm, 20 tasks per mode:

| System | `error` (503) | `empty` | `malformed` |
|---|---|---|---|
| agent | **10/20** | 11/19 | 18/20 |
| `no_agent` | **0 gradable — 20 crashes** | 13/19 | 19/19 |
| `always_lookup` | **0 gradable — 20 crashes** | 10/20 | 16/19 |

Both baselines are single-shot scripts: a failing tool takes the whole run
down. This replicated the development finding at double the sample.

It remains an **operational** difference, not an accuracy win. Zero gradable
baseline records means zero usable pairs, and zero pairs cannot support an
accuracy comparison. What is directly observed is that the baselines die and
the agent does not.

### Diagnostics

`tool_recall` 0.99 · `tool_precision` 1.00 · termination 0.95 ·
over-call ratio 1.32 · **zero fabrications**, hard and misattributed both nil.

Both fabrication rates remain lower bounds, and the detector is still
unvalidated against hand labels.

Per class, the agent lost exactly three: `python_upgrade` 4/6 and
`minimum_safe_version` 5/6. Both are multi-tool classes; every single-tool
class was perfect. Same failure shape as development.

---

## The hosted run was voided, and what that cost

The hosted model's final run failed completely. Groq returned HTTP 403 to every
request: 114 clean and 180 fault executions, **zero gradable records**, nothing
reaching the model. The block never lifted.

That spent a reservation on a measurement that never happened.

**This exposed a flaw in the rule rather than justifying an exception.** A
reservation exists to prevent re-measuring *after seeing a result*. Counting
attempts is a proxy for that, and the proxy is wrong when every request failed
before the model saw anything: no answer was produced, no score computed, and
nothing exists that could be iterated against.

So the proxy was corrected and given a line checked mechanically rather than
argued:

> **Zero gradable records, or the reservation is spent.**

One graded task and it is gone permanently. The threshold cannot be gamed — a
run engineered to produce no gradable records contains, by construction, no
information about the held-out set. Reservations are **superseded, never
deleted**: the previous state, the reason and the evidence are appended to a
history the file keeps.

Nine tests pin it, including that 1, 5 and 12 gradable records all refuse
release, and that an artifact with no records at all is refused because it
proves nothing.

The failed artifacts are committed as evidence.

**The obligation this leaves unmet:** M0 §9.3 wanted the hosted model measured
so nothing on the public link would be an unmeasured claim. The hosted column
exists on the **development** split only, clearly labelled, and that is stated
rather than glossed. It still answers the interesting question — a model
fifteen times larger moved the agent from 80% to 90% while `no_agent` moved
from 90% to 95%, so the finding survives a much bigger model — but it is not a
held-out result and is never presented as one.

The deployment going static made this less costly than it would have been:
there is no live demo model on the public link, so there is no unmeasured claim
there to answer for.

---

## Published

**https://huggingface.co/spaces/KayDee6070/dep-triage-agent** — verified
serving the held-out numbers, 12,286 bytes, every disclosure present.

The report switches its banner on the split. Before this it was hardcoded to
"development measurement", which would have published the final result
labelled as preliminary; a test now covers both directions.

The service is published as a container image by CI:

```bash
docker run --rm -p 8000:8000 ghcr.io/kaydee6070/dep-triage-agent:latest
```

---

## The study walkthrough earned its design

`scripts/study_the_harness.py` is 59 claims, each asserted against the
repository as it runs. CI executes it on every push.

When the held-out run landed, **it failed and named the claim**:

```
1 of 54 claims are FALSE:
  ✗ the held-out set has still never been run
```

Three more failed on the next pass — the discordant-pair count, the crash
count, and an assertion that both baselines beat the agent, which stopped being
true when the agent out-scored `no_agent` by one task. Every one was a sentence
of prose that had quietly become wrong.

Those claims are now computed from the artifacts rather than hardcoded, so the
same drift cannot recur. That is the mechanism working exactly as intended: a
documentation claim that stops being true fails the build instead of misleading
a reader.

---

## Still weak

1. **No hosted held-out column**, as above. Development only.
2. **Sample size.** 38 tasks carries roughly ±15 points. More tasks is not the
   fix: 80 reaches only about ±11.
3. **Reproducibility is partial.** `no_agent` is not repeatable run to run, and
   the hosted model produced three different outputs from three identical
   requests. Variance is published rather than smoothed.
4. **The fabrication detector is unvalidated.** Zero fabrications is a lower
   bound from a detector whose own precision is unmeasured.
5. **Two held-out probes were burned** during development. The sealed set was
   38 tasks, not 40, and that reduction is disclosed on the published page.
6. **Nothing scrapes `/metrics`.** The endpoint is real and tested; no
   Prometheus instance runs against it.
7. **`deploy/azure.sh` has never been executed.** It exists because the target
   job ads name Azure. An unrun script is weak evidence and the README says so.
8. **One model, one domain, one snapshot.** Nothing generalises further.

---

## Definition of done

| # | Criterion | State |
|---|---|---|
| 1 | The public link works | ✅ |
| 2 | The agent runs in Docker from a clean checkout | ✅ verified from a clean `git archive` |
| 3 | A measured result on the held-out set, with both baselines | ✅ local model; hosted voided and disclosed |
| 4 | A study script, every claim backed by an assertion | ✅ 59 claims, run in CI |
| 5 | Every milestone ended green | ✅ |
| 6 | The held-out set was measured once | ✅ and a released reservation is recorded, not hidden |

Criterion 3 is met for the model the project actually evaluates. The hosted
column was attempted, failed for reasons outside the project, and is reported
as such.

# M3 measurement protocol

Recorded on 2026-10-15 before running the completed harness. The fixture,
questions, model prompt, four tools, and both baseline algorithms stay frozen.

## Exposure correction approved by Kuntal

Commit `0dd1cd2` records measurements of all four deep probes. Two of those,
`minsafe-deep-03` (redis) and `minsafe-deep-04` (certifi), are assigned to
`held_out` in the committed task file. The claim that all 40 were untouched was
false. The historical 18/20 development result also predates that commit's
allocation change and is not a measurement of the current development set.

Keep all 60 original records and their split assignments. Never execute the
two exposed tasks again. Report their published answers as historical examples;
the original full traces are not available in this checkout, so do not imply
they are. The final evaluation covers the remaining 38 held-out tasks once,
with both baselines. No replacements, no additional tasks. This amendment
supersedes the 40-task measurement and untouched-set claims in older documents.

## Fault selection and interpretation

Select 10 development tasks (20 final tasks) by round-robin over sorted class
names, then sorted task IDs. Apply `error`, `empty`, and `malformed` separately
to the first `lookup_vulnerabilities` call. The target and occurrence match
across systems; all systems can call this tool. This gives 30 development runs
per system, 90 across all three. Keep untriggered faults visible and out of
conditional recovery denominators.

The existing baseline scripts remain one-shot. An uncaught tool exception is a
recorded crash; the harness does not add retries or a replacement model call.
Malformed lookups retain the verdict but remove fix boundaries, so many label
tasks can still be answered without recovery. Report correctness under the
fault separately from the observed behaviour; do not call every success an
active recovery. Empty results can also be unchanged for already-empty data.

## Denominators and missing observations

`task_accuracy` is correct / gradable; correct, incorrect, ungradable, and total
are always reported together. Also report correct / total as an observed
success lower bound. Ungradable answers are not silently scored incorrect.
Paired comparisons exclude a pair if either answer is ungradable and report
that exclusion count. Missing or duplicate pairs are errors, not exclusions.
McNemar uses the exact two-sided binomial calculation, capped at 1; zero
discordances gives p=1 and is not proof of equivalence.

Proportions carry Wilson 95% intervals and their denominators. Assertions within
a task are dependent: per-assertion intervals are descriptive binomial intervals,
not evidence that repeating tokens provides independent statistical power.
Means and distributions retain their observation counts. Undefined metrics are
null with denominator zero, never zero percent.

`tool_recall` is agreement with the reference path, not evidence that a shorter
route guessed. First-call accuracy uses only single-tool reference paths. No
current task has an empty reference path, so no-tool discipline is undefined.
Argument rejection is measured where visible at the tool boundary; schema
rejections before that boundary remain a limitation. Call counts include
refused attempts; executed calls are reported separately.

`recovery_rate` is correct / gradable among actually faulted runs, accompanied
by applied, untriggered, and ungradable counts. `graceful_abstention_rate` uses
only cases where recovery is established to be impossible. The present
single-occurrence faults do not establish that, so this rate is unavailable;
observed abstentions are still counted. Behaviour priority is crashed,
fabricated, abstained, retried_same_tool, switched_tool. A direct answer with
none of those behaviours remains unclassified rather than being forced into a
false category. Baseline scheduled calls are never classified as adaptive
switching or retrying.

Post-run correction: the first implementation used tool-name equality for
`retried_same_tool`. Trace review showed that this counted unrelated later
lookups as retries. It now requires an identical `ToolCallRecord.signature()`;
different arguments to the same tool remain unclassified. Original artifacts
are retained, and corrected fault metrics are written by the offline rescorer,
which performs zero model calls and records both execution and rescoring
provenance. The clean metrics are unchanged by this correction.

Before live measurement, an offline retry test exposed an integration bug:
the pinned LangGraph default re-raised `ToolError`, so the agent never received
the injected 503. Its exception handler now surfaces `ToolError`, preserves
the existing validation-error response, and still re-raises unexpected bugs.
The test first failed with `error:ToolError` and now exercises the full retry
path. This repairs the specified fault interface; prompts, tools, baseline
algorithms, and model settings are unchanged. No live fault score was used to
choose the fix.

A second offline regression test showed parallel tool dispatch could execute
seven calls with a budget of two and reuse trace indices. Toolkit now serializes
its budget check, occurrence counter, tool execution, and record insertion.
This changes neither tool data nor model instructions; it makes the existing
budget enforceable and the measured call sequence auditable. Unexpected tool
implementation exceptions are also recorded before propagation.

Version answers have three reported columns: strict (one distinct semantic
version and correct), lenient (correct version present), and ambiguous (more
than one semantic version). These columns overlap. Use the final ANSWER line
when present, otherwise prose, matching the existing grader policy.

Fabrication checks distinct extracted version/advisory assertions against the
whole fixture, including advisory aliases and affected/fixed versions. Versions
use PEP 440 equality. Check package attribution only when unambiguous; report
unattributed assertions. Exclude echoes of question pins, explicit Python
versions, CVSS scores, dates, and explicit uncertainty/denial. These exclusions,
implicit claims, and unresolved attribution make both fabrication denominators
lower bounds. The detector is not validated against hand-labelled responses.

## Gates and artifacts

Run current development tasks twice for each system. Compare canonical metrics
bytes, including all diagnostics but excluding clocks, durations, message IDs,
and other trace metadata. Preserve full traces and timing in separate fields.
If any system differs, run three additional repeats for all systems and report
the observed variance of every numeric metric, including paired comparisons.
Do not tune the model or prompt
to pass this check. Check the predeclared <30% model-switch threshold against
gradable development accuracy, with coverage visible.

The CLI requires an explicit held-out confirmation flag and reserves each
model/system/suite before inference in a persistent ledger beside the task
file. A failed or interrupted run consumes its reservation; no automatic retry.
Changing the output directory does not remove the guard. Development runs are
unrestricted. The held-out run remains deferred until the final project stage.

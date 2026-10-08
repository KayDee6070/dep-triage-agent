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

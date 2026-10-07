# Contributions

This repository was built with AI assistance (Claude Opus 5, via Claude Code).
This file separates the decisions I made from the work that was AI-assisted, so
that nothing in the repository is ambiguous about its origin.

It is updated at the end of every milestone, not retrofitted at the end.

---

## M0 — Scope

### My decisions

| Decision | Choice | Notes |
|---|---|---|
| Project purpose | Close the gap left by GraphRAG Bench: Docker, deployment, monitoring, agents, cloud | My read of ~real German job ads I researched myself |
| Task domain | Dependency security triage | Chosen from three proposals |
| Budget | **$0 — open-weight models only** | Overrode an initial API-model recommendation |
| Public link host | HF Spaces + committed-but-optional Azure script | |
| Demo backend | Static eval report primary, live form best-effort | |
| Hard limits | 14 days · one agent · 4 tools max · no Kubernetes | Set before any proposal was made |
| Publication rule | A bad eval result gets published as-is; no tuning against the eval set | Set before any proposal was made |

### AI-assisted

- Drafted the three candidate task domains, with the tool decomposition and
  question classes for each.
- Checked the dev machine (GPU, Ollama, Docker, toolchain) and surfaced that
  Docker and Ollama were not installed.
- Costed the rejected API option (~$66 at Haiku 4.5 rates) from a token-level
  estimate.
- Worked out the VRAM arithmetic for Qwen3-8B Q4_K_M on 8 GB.
- Estimated CPU inference throughput for the rejected self-contained
  deployment option.
- Surveyed deployment hosts against the six-month-survival requirement.
- Wrote the precise metric definitions in `docs/milestones/M0-scope.md` §4.
- Wrote the M0 scope document.

### Corrections I made to AI output

- The initial recommendation was Claude Haiku 4.5 with a $100 ceiling. I have
  no budget, so I rejected it and required open-weight models throughout. The
  plan was reworked around a local Qwen3-8B.

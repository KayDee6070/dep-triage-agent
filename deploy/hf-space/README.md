---
title: Dependency Triage Agent
emoji: 🔎
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
license: mit
short_description: A tool-using agent for dependency security triage, and the eval harness that measures it
---

# Dependency triage agent

An LLM agent that answers Python dependency-security questions using four
tools over a **frozen offline snapshot** — plus the evaluation harness that
measures whether the agent actually helps.

**The harness is the point. The agent is the entry ticket.**

## What you are looking at

The landing page is the **evaluation report**, not a chat box. It is rendered
at image build time from committed measurement artifacts, so it has no runtime
dependency and cannot fail.

The headline finding is a null result: an agent that chooses which tools to
call is **indistinguishable** from a script that simply calls all of them, on
clean inputs. That is not a weak agent — a call-everything baseline always
holds strictly more information than a routing agent, so routing is dominated
whenever calling everything is affordable and fits in the context window.

Routing only wins where exhaustive calling structurally cannot compete. The
fault arm shows one such case: under an injected tool error both baselines
crash outright, and the agent does not.

## Endpoints

| | |
|---|---|
| `GET /` | The evaluation report. Always available. |
| `POST /ask` | The live agent. Best-effort; see below. |
| `GET /health` | Liveness and current demo quota usage. |
| `GET /metrics` | Prometheus exposition. |
| `GET /docs` | OpenAPI schema. |

```bash
curl -s -X POST "$SPACE_URL/ask" \
  -H 'content-type: application/json' \
  -d '{"question": "Is urllib3==1.26.4 vulnerable?"}'
```

## The live agent is deliberately limited

This is a free demo with a real model behind it, so it is capped: a global
daily request limit and a per-client per-minute limit, both enforced before
the model is reached. Exceeding either returns HTTP 429 with `Retry-After`.

If the model backend is unreachable, `/ask` returns HTTP 503 with a short
notice. **The report is unaffected** — that asymmetry is the design, because
the measured results are the evidence and the live form is only a
demonstration.

## Do not use this to audit real dependencies

Answers come from a frozen snapshot of PyPI and OSV data captured on a fixed
date. It is a benchmark fixture, not a security product, and it goes stale by
design so that the measurements stay reproducible.

## Source

Built from <https://github.com/KayDee6070/dep-triage-agent>. The full scope
document, every milestone report, and the reasoning behind each decision —
including the mistakes — are in that repository under `docs/`.

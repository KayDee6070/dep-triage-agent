---
title: Dependency Triage Agent
emoji: 🔎
colorFrom: indigo
colorTo: gray
sdk: static
pinned: false
license: mit
short_description: Does tool routing help? Measured, not assumed.
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

## Why this page is static

This Space serves the evaluation report and nothing else, because Hugging Face
now requires a paid subscription to host a Docker Space on free hardware. The
project has a hard zero-cost constraint, and a link that cannot be billed for
is a link that cannot quietly die — which was the deciding criterion when the
host was chosen.

**The service itself is real and runs.** It is a FastAPI application with a
live agent endpoint, structured logging, Prometheus metrics, and rate limits
enforced before the model is reached. It is built, hardened and verified in CI
against a container with no network, a read-only root filesystem and all
capabilities dropped.

Run it yourself in one command:

```bash
docker run --rm -p 8000:8000 ghcr.io/kaydee6070/dep-triage-agent:latest
```

Then open <http://localhost:8000> for this same report, plus `/health`,
`/metrics`, `/docs`, and `POST /ask` for the live agent. The agent needs a
model backend configured; without one it returns a notice and the report still
serves.

## Do not use this to audit real dependencies

Answers come from a frozen snapshot of PyPI and OSV data captured on a fixed
date. It is a benchmark fixture, not a security product, and it goes stale by
design so that the measurements stay reproducible.

## Source

Built from <https://github.com/KayDee6070/dep-triage-agent>. The full scope
document, every milestone report, and the reasoning behind each decision —
including the mistakes — are in that repository under `docs/`.

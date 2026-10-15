# M2 — Agent working locally

**Status:** implemented in `f4da5e9`; overdue report completed 2026-10-15.
The deferred reproducibility and model-switch gates are reported in
[M3-report.md](M3-report.md). This report distinguishes historical setup
measurements from the current harness measurements.

## Built

A single LangGraph agent calls four pure tools over the committed offline
snapshot. `dep-triage ask --trace` exposes the answer, tool arguments, call
count, elapsed time, and termination reason. Toolkit records calls independently
of graph state, injects faults, and enforces an eight-call budget. Baselines
receive the question text only and return the same result type as the agent.

## Decided

Keep Qwen3-8B Q4_K_M local, with temperature 0, seed 42, and
`reasoning_effort="none"`. Keep the existing prompt and tool descriptions.
No framework migration: `create_react_agent` is deprecated, but the locked
implementation works and removal is deferred to LangGraph v2.

The dependency-security answers describe a frozen benchmark, not current
security advice. Tools never call PyPI or OSV at runtime.

## What create_react_agent actually builds

Verified against installed `langgraph==1.2.14`, `langchain-core==1.6.8`, and
`langchain-openai==1.7.0`. The original module docstring was inspected, not
copied uncritically: several statements needed qualification.

1. State contains `messages` and the managed `remaining_steps` value. The
   `add_messages` reducer appends messages with new IDs; an existing ID replaces
   its prior message. It is not unconditionally append-only.
2. The entry point is `agent`: one model invocation with the system prompt and
   accumulated messages. No tools requested means `END`.
3. With tool calls, default graph version `v2` creates one `Send("tools", ...)`
   per call. Tool results join the conversation, then the graph invokes `agent`
   again. No supervisor or second agent exists.
4. Graph progress is bounded by `recursion_limit`, counted in graph execution
   steps, not tool calls. The application sets `2 * (max_steps + 2) + 2`, which
   is 22 for an eight-call budget. Parallel calls are not eight graph steps.
5. Before dispatching tools with insufficient remaining steps, the prebuilt
   agent replaces the response with `Sorry, need more steps to process this
   request.`. This is a guard before graph exhaustion, not a promise that the
   graph can never raise `GraphRecursionError`. The application handles both.
6. Toolkit's budget is the separate tool-call brake. Calls after eight receive
   a budget refusal. Those attempts remain in the trace; a result can therefore
   show nine attempts but only eight executed calls. Refusal marks the run
   non-terminated even when the model subsequently gives an answer.
7. The pinned ToolNode default handles argument-validation errors but re-raises
   ordinary tool exceptions. M3's offline test exposed that an injected
   `ToolError` never reached the model. The explicit handler now returns the
   503 message, preserves validation handling, and propagates unexpected bugs.
   Toolkit also locks its bookkeeping because parallel dispatch previously
   overspent budgets and duplicated record indices.

D1 and D3 derive their counts from Toolkit records. Graph messages are retained
for inspection, not used to infer which tools ran. The termination adapter does
recognize the sentinel and graph error; a regression test pins that coupling.

## Measured

Historical setup observations are retained in [setup.md](../setup.md):
44.9 tokens/s warm, 37/37 layers on GPU, and approximately 6.2 GB VRAM at 8k
context. These are setup measurements, not confidence intervals or full-suite
latency claims.

On 2026-10-15 the local endpoint reported Ollama 0.40.1 and Qwen3-8B Q4_K_M
with model digest
`500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
Current development measurements, complete traces, and the three-system
reproducibility check belong to M3, rather than repeating the old 18/20 score
from a different development allocation.

## Still weak

- LangGraph's deprecated constructor and sentinel are version-sensitive. The
  lockfile and regression tests limit drift; they do not remove that coupling.
- Argument-schema rejections can occur before Toolkit. The reported invalid
  argument rate is consequently a lower bound.
- On an unexpected graph exception, the result retains tool records but may
  lack the unfinished conversation. Do not present an incomplete trace as full.
- A working agent is not evidence of useful routing. That question requires
  the baselines and paired evaluation in M3.
- The earlier claim that all 40 final tasks were untouched was wrong. Two
  exposed probes are now historical examples; 38 remain for final evaluation.

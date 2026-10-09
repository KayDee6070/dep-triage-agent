"""The single agent loop.

One agent, four tools, a hard call budget. LangGraph's ``create_react_agent``
supplies the graph; everything the harness needs is read off the
:class:`~dep_triage.tools.wrapper.Toolkit` afterwards, not out of the graph.
That separation is the M0 scope §10 commitment: removing LangGraph later must
not invalidate a measured number.

What ``create_react_agent`` actually builds — required by M0 scope §10, so the
design can be defended rather than cargo-culted:

1. A two-node ``StateGraph`` over a message list: ``agent`` (one model call)
   and ``tools`` (a ``ToolNode`` executing every ``tool_call`` in the last
   message, in parallel).
2. ``START -> agent``. Then a conditional edge off ``agent``: if the last
   message carries ``tool_calls``, route to ``tools``; otherwise ``END``.
3. ``tools -> agent`` unconditionally. That back-edge is the loop, and it is
   the only cycle in the graph.
4. State is append-only — each node returns messages that are added via an
   ``add_messages`` reducer, so nothing is overwritten and the full trace
   survives.
5. There is **no built-in step limit**. The only brake LangGraph provides is
   ``recursion_limit`` on the invoke config, which counts *node visits*, not
   tool calls.
6. On hitting ``recursion_limit`` LangGraph v1 does **not** raise — it returns
   a canned assistant message (:data:`RECURSION_SENTINEL`) and reports a
   normal finish. Measured, not assumed: a test asserts that string still
   appears, so a LangGraph upgrade that changes it fails loudly instead of
   silently scoring every truncated run as a clean termination.

Because of (6), the toolkit's call budget is sized to bite *before*
``recursion_limit`` does, and that budget is what D3 reports against.
``recursion_limit`` is left only as a backstop for a model that loops without
calling tools at all, which the budget cannot see.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent

from dep_triage.config import Settings
from dep_triage.tools.wrapper import ToolCallRecord, Toolkit

#: LangGraph v1 emits this instead of raising when ``recursion_limit`` is hit.
#: Internal to LangGraph and therefore version-fragile, which is why
#: ``test_recursion_sentinel_is_still_current`` pins it.
RECURSION_SENTINEL = "Sorry, need more steps to process this request."

SYSTEM_PROMPT = """\
You are a dependency security triage assistant. Answer questions about pinned \
Python packages using the tools provided.

Rules:
- Use the tools. Never answer from memory about versions or advisories.
- These are four different answers and must not be confused:
  VULNERABLE        the version is affected by a known advisory
  NOT_VULNERABLE    the version exists and no advisory affects it
  VERSION_UNKNOWN   the package exists but that version was never published
  PACKAGE_UNKNOWN   there is no data for that package at all
- Never state a version number or advisory ID that a tool did not return.
- If a tool fails and you cannot recover, say what you could not determine.
- Stop as soon as you can answer. Do not re-call a tool with arguments you \
already used.

Reply with one or two sentences, then a final line in exactly this form:

ANSWER: <value>

where <value> is:
- for "is X vulnerable" questions: VULNERABLE, NOT_VULNERABLE, \
VERSION_UNKNOWN or PACKAGE_UNKNOWN
- for "lowest safe version" questions: the single version number
- for "which of these are vulnerable": the vulnerable package names separated \
by commas, or NONE
- for "can I upgrade" questions: YES or NO"""


@dataclass
class AgentResult:
    """One task execution, with everything the harness scores."""

    question: str
    answer: str
    calls: list[ToolCallRecord] = field(default_factory=list)
    steps: int = 0
    terminated: bool = True
    stop_reason: str = "end_turn"
    duration_s: float = 0.0
    messages: list[BaseMessage] = field(default_factory=list)

    @property
    def tools_used(self) -> set[str]:
        return {call.tool for call in self.calls}


def build_model(settings: Settings) -> ChatOpenAI:
    """Construct the chat client.

    One client for both backends. Ollama and the hosted demo are both
    OpenAI-compatible, so local evaluation and the deployed service differ by
    configuration rather than by code path — which is what lets M0 scope §9.3
    evaluate the demo model too.
    """
    extra: dict[str, Any] = {}
    if settings.llm_reasoning_effort is not None:
        extra["reasoning_effort"] = settings.llm_reasoning_effort

    return ChatOpenAI(
        model=settings.llm_name,
        base_url=settings.llm_base_url,
        # Ollama ignores the key; the hosted backend requires one.
        api_key=settings.llm_api_key or "unused",  # type: ignore[arg-type]
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_s,
        max_retries=0,  # a retry would silently double-count a tool call
        seed=settings.llm_seed,
        **extra,
    )


def build_tools(toolkit: Toolkit) -> list[StructuredTool]:
    """Expose the toolkit's four methods as LangChain tools.

    Built from the bound methods so their docstrings and annotations are the
    single source of truth for the schema the model sees.
    """
    return [
        StructuredTool.from_function(
            func=method,
            name=name,
            description=(method.__doc__ or "").strip(),
        )
        for name, method in (
            ("parse_requirements", toolkit.parse_requirements),
            ("lookup_vulnerabilities", toolkit.lookup_vulnerabilities),
            ("list_releases", toolkit.list_releases),
            ("check_compatibility", toolkit.check_compatibility),
        )
    ]


def _final_text(messages: list[BaseMessage]) -> str:
    """Last assistant message that is text rather than a tool request."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            content = message.content
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def run_agent(
    question: str,
    toolkit: Toolkit,
    settings: Settings,
    model: BaseChatModel | None = None,
) -> AgentResult:
    """Run one question to an answer, or to the call budget.

    Stopping is enforced twice, deliberately:

    * **Call budget** in the toolkit (``max_calls = settings.max_steps``). The
      precise brake, and the one D3 reports against. Exceeding it refuses the
      call and tells the agent to answer with what it has.
    * **``recursion_limit``** on the graph, as a backstop for a model that
      keeps looping without producing an answer — which the budget alone
      cannot stop, since a refused call still returns normally.

    Neither raises out of this function. A hit limit is a *result*
    (``terminated=False``), because non-termination is a measurement, not an
    error.
    """
    toolkit.reset()
    toolkit.max_calls = settings.max_steps
    agent = create_react_agent(
        model if model is not None else build_model(settings),
        build_tools(toolkit),
        prompt=SYSTEM_PROMPT,
    )

    # Sized so the toolkit budget is the binding constraint: it must refuse a
    # call, and the agent must get a turn to answer afterwards, all before
    # LangGraph's own limit trips. Each tool cycle is two node visits.
    config: RunnableConfig = {"recursion_limit": 2 * (settings.max_steps + 2) + 2}
    started = time.perf_counter()
    messages: list[BaseMessage] = []
    terminated, stop_reason = True, "end_turn"

    try:
        state = agent.invoke({"messages": [HumanMessage(content=question)]}, config=config)
        messages = list(state["messages"])
        if RECURSION_SENTINEL in _final_text(messages):
            terminated, stop_reason = False, "recursion_limit"
        elif toolkit.budget_exhausted:
            # The agent was cut off mid-investigation. It may still have
            # answered, but it did not finish on its own terms.
            terminated, stop_reason = False, "call_budget"
        elif not _final_text(messages):
            terminated, stop_reason = False, "no_answer"
    except GraphRecursionError:
        terminated, stop_reason = False, "recursion_limit"
    except Exception as exc:
        # Deliberately broad. A harness measuring 180 executions must survive
        # any single one failing, and the failure is itself data — a timeout or
        # a malformed tool call is a result to report, not a crash to
        # propagate. The exception type is recorded so it can be diagnosed.
        terminated, stop_reason = False, f"error:{type(exc).__name__}"

    return AgentResult(
        question=question,
        answer=_final_text(messages),
        calls=toolkit.calls,
        steps=len(toolkit.calls),
        terminated=terminated,
        stop_reason=stop_reason,
        duration_s=time.perf_counter() - started,
        messages=messages,
    )

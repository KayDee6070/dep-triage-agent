"""The two baselines. Without them, an agent score compares to nothing.

Both return an :class:`~dep_triage.agent.loop.AgentResult`, so scoring,
grading and metrics treat them identically to the agent. That is the point: the
paired comparison in M0 scope §4.1 is only defined if all three systems run the
same tasks through the same pipeline.

**Fairness rule, and it is load-bearing:** a baseline sees exactly what the
agent sees — ``task.question`` and nothing else. It would be easy to hand a
baseline ``task.package`` and ``task.version`` straight from the task record,
and it would silently make the comparison meaningless, because the agent has to
recover those from prose. Both baselines therefore extract pins from the
question text with the same regex the agent would have to reason about.

``no_agent`` is tool *use* with zero tool *selection*: a fixed script calls
everything, concatenates, and the model answers once. If the agent cannot beat
it, agentic routing is not earning its place in this domain — which M0 scope §2
commits to publishing rather than hiding.
"""

from __future__ import annotations

import json
import re
import time

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from dep_triage.agent.loop import SYSTEM_PROMPT, AgentResult, build_model
from dep_triage.config import Settings
from dep_triage.tools.wrapper import Toolkit

#: ``name==version`` as it appears in a question or a requirements block.
PIN = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([A-Za-z0-9][A-Za-z0-9.!+_-]*)")

#: "Python 3.8", "python3.11", "on Python 3.13".
PYTHON = re.compile(r"python\s*([0-9]+\.[0-9]+)", re.IGNORECASE)

DEFAULT_PYTHON = "3.12"

BASELINE_NAMES = ("no_agent", "always_lookup")


def extract_pins(question: str) -> list[tuple[str, str]]:
    """Pins named in the question, in order, de-duplicated."""
    found: list[tuple[str, str]] = []
    for name, version in PIN.findall(question):
        if (name, version) not in found:
            found.append((name, version))
    return found


def extract_python(question: str) -> str:
    match = PYTHON.search(question)
    return match.group(1) if match else DEFAULT_PYTHON


def _answer_once(model: BaseChatModel, question: str, evidence: str) -> tuple[str, list[AIMessage]]:
    """One model call over pre-fetched tool output."""
    prompt = (
        f"{question}\n\n"
        "Tool results have already been gathered for you. Use only these:\n\n"
        f"{evidence}"
    )
    reply = model.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)])
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    assistant = reply if isinstance(reply, AIMessage) else AIMessage(content=text)
    return text.strip(), [assistant]


def _result(
    question: str,
    answer: str,
    toolkit: Toolkit,
    started: float,
    stop_reason: str,
    messages: list[AIMessage],
) -> AgentResult:
    return AgentResult(
        question=question,
        answer=answer,
        calls=toolkit.calls,
        steps=len(toolkit.calls),
        terminated=bool(answer),
        stop_reason=stop_reason if answer else "no_answer",
        duration_s=time.perf_counter() - started,
        messages=list(messages),
    )


def run_no_agent(
    question: str,
    toolkit: Toolkit,
    settings: Settings,
    model: BaseChatModel | None = None,
) -> AgentResult:
    """Call every tool on every pin found, then answer once.

    The script is fixed, so the model makes no routing decision at all. Note
    that this is a *strong* baseline rather than a dumb one: it never forgets a
    tool and never mis-orders them. If it wins, the honest reading is that
    routing is not where the difficulty lies.
    """
    started = time.perf_counter()
    toolkit.reset()
    # No budget: the whole point is that this baseline calls everything.
    toolkit.max_calls = None

    pins = extract_pins(question)
    python_version = extract_python(question)
    gathered: dict[str, object] = {}

    if "==" in question and "\n" in question:
        gathered["parse_requirements"] = toolkit.parse_requirements(question)

    for name, version in pins:
        gathered[f"lookup_vulnerabilities({name}=={version})"] = toolkit.lookup_vulnerabilities(
            name, version
        )
        # Unfiltered, deliberately. An earlier version passed
        # since_version=version here, which is a routing decision: a script
        # that knows to narrow the query is not "call everything", and it hid
        # the one condition where routing can structurally win (M0 scope §5.6).
        gathered[f"list_releases({name})"] = toolkit.list_releases(name)
        gathered[f"check_compatibility({name}=={version}, py{python_version})"] = (
            toolkit.check_compatibility(name, version, python_version)
        )

    if not pins:
        gathered["note"] = "no pinned package found in the question"

    answer, messages = _answer_once(
        model if model is not None else build_model(settings),
        question,
        json.dumps(gathered, indent=2, default=str),
    )
    return _result(question, answer, toolkit, started, "end_turn", messages)


def run_always_lookup(
    question: str,
    toolkit: Toolkit,
    settings: Settings,
    model: BaseChatModel | None = None,
) -> AgentResult:
    """Call ``lookup_vulnerabilities`` on every pin and nothing else.

    Establishes a floor, and shows which classes genuinely need more than one
    tool: this cannot answer "minimum safe version" (it never sees the release
    list) or the Python-upgrade class (it never checks compatibility).
    """
    started = time.perf_counter()
    toolkit.reset()
    toolkit.max_calls = None

    pins = extract_pins(question)
    gathered: dict[str, object] = {
        f"lookup_vulnerabilities({name}=={version})": toolkit.lookup_vulnerabilities(name, version)
        for name, version in pins
    }
    if not pins:
        gathered["note"] = "no pinned package found in the question"

    answer, messages = _answer_once(
        model if model is not None else build_model(settings),
        question,
        json.dumps(gathered, indent=2, default=str),
    )
    return _result(question, answer, toolkit, started, "end_turn", messages)


BASELINES = {
    "no_agent": run_no_agent,
    "always_lookup": run_always_lookup,
}

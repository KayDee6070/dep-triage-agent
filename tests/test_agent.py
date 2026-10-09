"""Agent loop tests, run offline against a scripted model.

No Ollama, no network. The loop's job is to call tools, enforce a budget, and
surface a final answer; none of that needs a real model, and testing it against
one would make CI slow and non-deterministic.

``ScriptedModel`` is hand-rolled rather than using LangChain's fakes:
``GenericFakeChatModel`` does not implement the generate path
``create_react_agent`` drives, and a fake we own is one fewer third-party
behaviour to be surprised by.
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from dep_triage.agent.loop import SYSTEM_PROMPT, build_tools, run_agent
from dep_triage.config import Settings
from dep_triage.fixture import Fixture
from dep_triage.tools.wrapper import Toolkit


class ScriptedModel(BaseChatModel):
    """Replays ``replies`` in order, repeating the last one forever.

    Repeating matters: it lets a test drive an agent that never stops asking,
    which is how the call budget gets exercised.
    """

    replies: list[AIMessage] = Field(default_factory=list)
    cursor: list[int] = Field(default_factory=lambda: [0])
    fail_with: str | None = None

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> BaseChatModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.fail_with:
            raise TimeoutError(self.fail_with)
        index = min(self.cursor[0], len(self.replies) - 1)
        self.cursor[0] += 1
        return ChatResult(generations=[ChatGeneration(message=self.replies[index])])


def scripted(*messages: AIMessage) -> ScriptedModel:
    return ScriptedModel(replies=list(messages))


def tool_call(name: str, args: dict[str, object], call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def test_tool_schema_exposes_four_tools(tiny_fixture: Fixture) -> None:
    tools = build_tools(Toolkit(tiny_fixture))
    assert [t.name for t in tools] == [
        "parse_requirements",
        "lookup_vulnerabilities",
        "list_releases",
        "check_compatibility",
    ]
    assert all(t.description for t in tools), "the model needs a description per tool"


def test_fixture_is_not_in_the_model_facing_schema(tiny_fixture: Fixture) -> None:
    """The harness binds the fixture; the model must never see it."""
    for tool in build_tools(Toolkit(tiny_fixture)):
        assert "fixture" not in tool.args, f"{tool.name} leaks harness plumbing"


def test_single_tool_call_then_answer(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture)
    model = scripted(
        tool_call("lookup_vulnerabilities", {"package": "demo-pkg", "version": "1.0.0"}),
        AIMessage(content="demo-pkg 1.0.0 is vulnerable."),
    )
    result = run_agent("is demo-pkg 1.0.0 vulnerable?", kit, Settings(), model=model)

    assert result.answer == "demo-pkg 1.0.0 is vulnerable."
    assert result.steps == 1
    assert result.tools_used == {"lookup_vulnerabilities"}
    assert result.terminated is True
    assert result.stop_reason == "end_turn"


def test_answer_without_any_tool_call(tiny_fixture: Fixture) -> None:
    """The no-tool path — what `no_tool_discipline` measures."""
    kit = Toolkit(tiny_fixture)
    result = run_agent("hello", kit, Settings(), model=scripted(AIMessage(content="Hi.")))
    assert result.steps == 0
    assert result.calls == []
    assert result.terminated is True


def test_calls_are_captured_for_the_harness(tiny_fixture: Fixture) -> None:
    """D1 and D3 read these records, not the graph."""
    kit = Toolkit(tiny_fixture)
    model = scripted(
        tool_call("list_releases", {"package": "demo-pkg"}, "a"),
        tool_call("lookup_vulnerabilities", {"package": "demo-pkg", "version": "1.0.0"}, "b"),
        AIMessage(content="Upgrade to 2.0.0."),
    )
    result = run_agent("what should I upgrade to?", kit, Settings(), model=model)

    assert [c.tool for c in result.calls] == ["list_releases", "lookup_vulnerabilities"]
    assert result.steps == 2
    assert result.calls[0].result is not None


def test_budget_stops_a_looping_agent(tiny_fixture: Fixture) -> None:
    """A model that never stops asking must still terminate the run."""
    settings = Settings(max_steps=3)
    kit = Toolkit(tiny_fixture)
    model = scripted(
        *[tool_call("list_releases", {"package": "demo-pkg"}, f"c{n}") for n in range(40)]
    )
    result = run_agent("loop forever", kit, settings, model=model)

    assert result.terminated is False
    assert result.stop_reason in {"call_budget", "recursion_limit"}
    executed = [c for c in kit.calls if c.ok]
    assert len(executed) == settings.max_steps, "the budget must cap executed calls exactly"


def test_recursion_sentinel_is_still_current(tiny_fixture: Fixture) -> None:
    """Pins a LangGraph-internal string the run classifier depends on.

    LangGraph v1 returns this instead of raising on recursion_limit. If an
    upgrade changes the wording, every truncated run would be scored as a clean
    termination — so this must fail loudly rather than drift.
    """
    from dep_triage.agent.loop import RECURSION_SENTINEL

    settings = Settings(max_steps=40)  # keep the toolkit budget out of the way
    kit = Toolkit(tiny_fixture)
    model = scripted(
        *[tool_call("list_releases", {"package": "demo-pkg"}, f"c{n}") for n in range(200)]
    )
    result = run_agent("loop", kit, settings, model=model)

    assert result.stop_reason == "recursion_limit"
    assert RECURSION_SENTINEL in result.answer


def test_budget_refusal_is_visible_in_the_trace(tiny_fixture: Fixture) -> None:
    settings = Settings(max_steps=2)
    kit = Toolkit(tiny_fixture)
    model = scripted(
        *[tool_call("list_releases", {"package": "demo-pkg"}, f"c{n}") for n in range(30)]
    )
    run_agent("loop", kit, settings, model=model)
    assert kit.budget_exhausted is True
    assert any(c.ok is False for c in kit.calls)
    assert len([c for c in kit.calls if c.ok]) == 2


def test_a_failing_model_is_a_result_not_a_crash(tiny_fixture: Fixture) -> None:
    """180 executions must survive one failing; the failure is data."""

    kit = Toolkit(tiny_fixture)
    model = ScriptedModel(replies=[AIMessage(content="never reached")], fail_with="stalled")
    result = run_agent("anything", kit, Settings(), model=model)

    assert result.terminated is False
    assert result.stop_reason == "error:TimeoutError"
    assert result.answer == ""


def test_system_prompt_names_the_three_negatives() -> None:
    """The agent is told these differ; conflating them is a scored failure."""
    lowered = SYSTEM_PROMPT.lower()
    assert "unknown" in lowered
    assert "does not exist" in lowered
    assert "not vulnerable" in lowered

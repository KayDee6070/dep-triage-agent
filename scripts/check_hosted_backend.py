#!/usr/bin/env python3
"""Go/no-go check on a hosted open-weight backend, before trusting it.

    DEP_TRIAGE_LLM_BACKEND=hosted \
    DEP_TRIAGE_LLM_BASE_URL=https://api.groq.com/openai/v1 \
    DEP_TRIAGE_LLM_NAME=llama-3.3-70b-versatile \
    DEP_TRIAGE_LLM_API_KEY=gsk_... \
    DEP_TRIAGE_LLM_REASONING_EFFORT= \
    uv run python scripts/check_hosted_backend.py

Run this *before* committing the evaluation to a hosted backend. A backend that
cannot call tools reliably produces a column of noise, and finding that out
after the single held-out run would be unrecoverable — the held-out set is
spent once.

Six checks, each a reason to walk away:

1. **Reachable** — the endpoint answers at all.
2. **Parameters accepted** — some gateways reject ``seed`` or
   ``reasoning_effort``. The script reports which, so the config can drop them
   rather than failing mid-run.
3. **Tool calling** — the model actually emits a tool call against a real
   schema. This is the one that matters; without it there is no agent.
4. **Correct arguments** — it passes the package and version it was given,
   rather than inventing them.
5. **Answer format** — it honours the ``ANSWER:`` contract the grader parses.
   A backend that ignores it would score as ungradable, not as wrong.
6. **Determinism** — three identical requests, compared. Required before the
   backend can appear in a reproducibility gate.

The API key is read from the environment, never printed, and never written
anywhere.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from dep_triage.agent.loop import SYSTEM_PROMPT, build_model, build_tools  # noqa: E402
from dep_triage.config import Settings  # noqa: E402
from dep_triage.eval.grading import VERDICT_TOKENS, answer_line  # noqa: E402
from dep_triage.fixture import load_fixture  # noqa: E402
from dep_triage.tools.wrapper import Toolkit  # noqa: E402

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[2m",
    "\033[1m",
    "\033[0m",
)

QUESTION = "Is urllib3==1.26.4 vulnerable?"
REPEATS = 3


class Checks:
    def __init__(self) -> None:
        self.blocking: list[str] = []
        self.warnings: list[str] = []

    def ok(self, label: str, detail: str = "") -> None:
        print(f"  {GREEN}✓{RESET} {label}" + (f" {DIM}[{detail}]{RESET}" if detail else ""))

    def warn(self, label: str, detail: str = "") -> None:
        self.warnings.append(label)
        print(f"  {YELLOW}!{RESET} {label}" + (f" {DIM}[{detail}]{RESET}" if detail else ""))

    def fail(self, label: str, detail: str = "") -> None:
        self.blocking.append(label)
        print(f"  {RED}✗{RESET} {label}" + (f" {DIM}[{detail}]{RESET}" if detail else ""))


def main() -> int:
    checks = Checks()
    settings = Settings()

    print(f"{BOLD}Hosted backend check{RESET}")
    print(f"  backend : {settings.llm_backend}")
    print(f"  base_url: {settings.llm_base_url}")
    print(f"  model   : {settings.llm_name}")
    print(f"  api key : {'set' if settings.llm_api_key else 'NOT SET'}")
    print(f"  effort  : {settings.llm_reasoning_effort!r}")

    if settings.llm_backend != "hosted":
        print(
            f"\n{RED}Refusing to run.{RESET} DEP_TRIAGE_LLM_BACKEND is "
            f"{settings.llm_backend!r}. This check is for a hosted backend; "
            "pointing it at the local model would prove nothing about the hosted one."
        )
        return 2
    if not settings.llm_api_key:
        print(f"\n{RED}Refusing to run.{RESET} DEP_TRIAGE_LLM_API_KEY is unset.")
        return 2

    fixture = load_fixture(settings.fixture_path)

    # --- 1 & 2: reachability and parameter acceptance ---------------------
    print(f"\n{BOLD}1-2. Reachable, and which parameters it accepts{RESET}")
    model: Any = None
    try:
        model = build_model(settings)
        started = time.perf_counter()
        reply = model.invoke("Reply with the single word: ready")
        latency = time.perf_counter() - started
        text = reply.content if isinstance(reply.content, str) else str(reply.content)
        checks.ok("endpoint answers", f"{latency:.2f}s, {text.strip()[:30]!r}")
    except Exception as exc:
        message = str(exc)
        checks.fail("endpoint unreachable or rejected the request", message[:160])
        for parameter in ("seed", "reasoning_effort"):
            if parameter in message:
                print(
                    f"      {YELLOW}hint:{RESET} the error names {parameter!r}. "
                    f"Unset DEP_TRIAGE_LLM_{parameter.upper()} and retry."
                )
        print(f"\n{RED}Stopping: nothing further can be checked.{RESET}")
        return 1

    # --- 3 & 4: tool calling -------------------------------------------
    print(f"\n{BOLD}3-4. Tool calling, and whether the arguments are right{RESET}")
    toolkit = Toolkit(fixture)
    try:
        bound = model.bind_tools(build_tools(toolkit))
        response = bound.invoke([("system", SYSTEM_PROMPT), ("human", QUESTION)])
        tool_calls = getattr(response, "tool_calls", []) or []
    except Exception as exc:
        checks.fail("binding or invoking tools raised", str(exc)[:160])
        tool_calls = []

    if not tool_calls:
        checks.fail(
            "the model emitted no tool call",
            "without tool calling there is no agent on this backend",
        )
    else:
        names = [call.get("name") for call in tool_calls]
        checks.ok(f"emitted {len(tool_calls)} tool call(s)", ", ".join(map(str, names)))
        arguments = tool_calls[0].get("args", {})
        if arguments.get("package") == "urllib3" and arguments.get("version") == "1.26.4":
            checks.ok("arguments match the question", str(arguments))
        else:
            checks.warn(
                "arguments do not match the question exactly",
                f"got {arguments}, expected urllib3 / 1.26.4",
            )

    # --- 5 & 6: answer format and determinism ---------------------------
    print(f"\n{BOLD}5-6. Answer format and determinism over {REPEATS} identical runs{RESET}")
    answers: list[str] = []
    for index in range(REPEATS):
        try:
            started = time.perf_counter()
            reply = model.invoke(
                [
                    ("system", SYSTEM_PROMPT),
                    (
                        "human",
                        "A tool reported that urllib3 1.26.4 is affected by known "
                        "advisories. Answer the user's question: Is urllib3==1.26.4 "
                        "vulnerable?",
                    ),
                ]
            )
            elapsed = time.perf_counter() - started
            text = reply.content if isinstance(reply.content, str) else str(reply.content)
            answers.append(text.strip())
            print(f"      run {index + 1}: {elapsed:.2f}s {text.strip()[:70]!r}")
        except Exception as exc:
            checks.fail(f"run {index + 1} raised", str(exc)[:120])

    if answers:
        token = (answer_line(answers[0]) or "").strip().upper().replace(" ", "_").rstrip(".")
        if token in VERDICT_TOKENS:
            checks.ok("honours the ANSWER contract the grader parses", token)
        else:
            checks.warn(
                "did not emit a parseable ANSWER line",
                "the grader would fall back to prose, or report ungradable",
            )
        if len(set(answers)) == 1:
            checks.ok("identical output across runs", "usable in a reproducibility gate")
        else:
            checks.warn(
                f"output varied across {len(set(answers))} of {len(answers)} runs",
                "the backend cannot be reported as repeatable; repeats and variance needed",
            )

    # --- verdict ---------------------------------------------------------
    print(f"\n{BOLD}{'═' * 74}{RESET}")
    if checks.blocking:
        print(f"{RED}NO-GO.{RESET} {len(checks.blocking)} blocking problem(s):")
        for item in checks.blocking:
            print(f"  {RED}✗{RESET} {item}")
        print(
            "\nDo not spend the held-out run on this backend. Try a different model "
            "on the same endpoint, or keep the live form disabled and publish the "
            "report alone."
        )
        return 1

    print(f"{GREEN}GO.{RESET} The backend can drive the agent.")
    if checks.warnings:
        print(
            f"\n{YELLOW}{len(checks.warnings)} caveat(s) to record in the report, not ignore:{RESET}"
        )
        for item in checks.warnings:
            print(f"  {YELLOW}!{RESET} {item}")
    print(
        "\nNext: evaluate it on the development split first "
        "(`dep-triage eval --split dev --system agent`), compare against the local "
        "model, and only then spend the single held-out run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

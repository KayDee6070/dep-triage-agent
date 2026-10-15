"""Offline image acceptance checks, supplied on stdin rather than baked in.

Run inside the built image as its default non-root user, with --network none.
The scripted model exercises the real graph and tools, not model quality.
Only an existing development task is executed. No held-out confirmation is used.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from dep_triage.config import Settings
from dep_triage.eval.artifacts import evaluate_to_file
from dep_triage.eval.suite import SYSTEMS
from dep_triage.eval.tasks import TaskSet
from dep_triage.fixture import load_fixture, versions_equal
from dep_triage.tools import triage


class SmokeModel(BaseChatModel):
    """One deterministic development lookup, then an answer using its result."""

    @property
    def _llm_type(self) -> str:
        return "offline-container-smoke"

    def bind_tools(self, tools: Any, **kwargs: Any) -> BaseChatModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last = messages[-1]
        if isinstance(last, ToolMessage):
            assert isinstance(last.content, str)
            assert json.loads(last.content)["vulnerable"] is True
            reply = AIMessage(content="ANSWER: VULNERABLE")
        elif "Tool results have already been gathered" in str(last.content):
            # The two baselines have already gathered the same dev pin.
            assert '"vulnerable": true' in str(last.content)
            reply = AIMessage(content="ANSWER: VULNERABLE")
        else:
            reply = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "lookup_vulnerabilities",
                        "args": {"package": "twisted", "version": "25.5.0"},
                        "id": "smoke-lookup",
                        "type": "tool_call",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=reply)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, help="Persist smoke artifacts in a mounted directory"
    )
    args = parser.parse_args()
    assert os.geteuid() == 1000, "image must default to non-root UID 1000"
    assert Path.cwd() == Path("/app")
    assert not os.access("/app/data", os.W_OK), (
        "benchmark data must not be ephemeral writable state"
    )
    assert not os.access("/app/.venv", os.W_OK), "installed code must be immutable to the app user"
    for name in ("pytest", "ruff", "mypy"):
        assert importlib.util.find_spec(name) is None, f"dev dependency leaked: {name}"
    for name in (".env", ".git", ".docker-context-canary", "src", "tests", "scripts", "uv.lock"):
        assert not (Path("/app") / name).exists(), f"build-only or private file leaked: {name}"
    assert not Path("/usr/local/bin/uv").exists(), "build tooling leaked into runtime"
    assert not Path("data/.held-out-runs").exists()

    unavailable = subprocess.run(
        ["dep-triage", "ask", "--trace", "Is twisted==25.5.0 vulnerable?"],
        env=os.environ
        | {"DEP_TRIAGE_LLM_BASE_URL": "http://127.0.0.1:9/v1", "DEP_TRIAGE_LLM_TIMEOUT_S": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert unavailable.returncode == 2
    assert "(no answer produced)" in unavailable.stdout
    assert "error:OpenAIConnectionError" in unavailable.stderr
    assert "Traceback" not in unavailable.stderr

    settings = Settings()
    assert settings.llm_reasoning_effort == "none"
    fixture = load_fixture(settings.fixture_path)
    assert len(fixture.packages) == 80
    assert fixture.manifest.vulnerability_count == 1487
    assert versions_equal("4.2", "4.2.0")
    assert triage.lookup_vulnerabilities(fixture, "django", "4.2.0").vulnerable
    assert triage.parse_requirements(fixture, "twisted==25.5.0").requirements[0].name == "twisted"
    assert triage.list_releases(fixture, "django", "6.1").versions
    assert not triage.check_compatibility(fixture, "pymongo", "4.18.2", "3.8").python_compatible

    # The actual CLI must refuse held-out before loading tasks or invoking a model.
    refused = subprocess.run(
        ["dep-triage", "eval", "--split", "held_out"], capture_output=True, text=True, check=False
    )
    assert refused.returncode == 1
    assert "requires --confirm-held-out-once" in refused.stderr
    assert not Path("data/.held-out-runs").exists()

    tasks = TaskSet.model_validate_json(Path("data/tasks.json").read_text())
    dev = next(t for t in tasks.tasks if t.id == "affected-01" and t.split == "dev")
    assert dev.package == "twisted" and dev.version is not None
    assert versions_equal(dev.version, "25.5.0")
    with tempfile.TemporaryDirectory(prefix="dep-triage-smoke-") as temporary:
        directory = Path(temporary)
        selected = directory / "tasks.json"
        selected.write_text(
            TaskSet(fixture_snapshot=tasks.fixture_snapshot, tasks=[dev]).model_dump_json()
        )
        output = (args.output_dir or directory) / "container-smoke.json"
        # Both modules bind the model factory separately. No real client can run.
        with (
            patch("dep_triage.agent.loop.build_model", return_value=SmokeModel()),
            patch("dep_triage.eval.baselines.build_model", return_value=SmokeModel()),
        ):
            result = evaluate_to_file(
                settings=settings.model_copy(update={"llm_name": "offline-container-smoke"}),
                tasks_path=selected,
                output=output,
                split="dev",
                systems=list(SYSTEMS),
            )
        assert len(result["records"]) == 3
        assert all(r["grade"]["correct"] for r in result["records"])
        assert output.exists() and output.with_suffix(".metrics.json").exists()
        assert output.with_suffix(".jsonl").exists()
    print(
        json.dumps(
            {
                "offline_smoke": "passed",
                "uid": os.geteuid(),
                "packages": 80,
                "scripted_dev_executions": 3,
                "live_model_calls": 0,
                "held_out_executions": 0,
            }
        )
    )


if __name__ == "__main__":
    main()

"""Offline CLI, checkpoint, secrecy, and held-out guard integration tests."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from pydantic import SecretStr
from typer.testing import CliRunner

from dep_triage.agent.loop import AgentResult, run_agent
from dep_triage.cli import app
from dep_triage.config import Settings
from dep_triage.eval import runner
from dep_triage.eval.artifacts import evaluate_to_file
from dep_triage.eval.suite import SYSTEMS
from dep_triage.eval.tasks import TaskSet
from dep_triage.fixture import Fixture, write_fixture
from dep_triage.tools.wrapper import Toolkit
from test_agent import scripted
from test_eval_runner import task


def prepare(
    tmp_path: Path, fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> tuple[Settings, Path]:
    path = tmp_path / "fixture"
    write_fixture(fixture, path)
    tasks = tmp_path / "tasks.json"
    tasks.write_text(
        TaskSet(fixture_snapshot=fixture.manifest.snapshot_date, tasks=[task()]).model_dump_json()
    )

    def offline(
        question: str, toolkit: Toolkit, settings: Settings, model: BaseChatModel | None = None
    ) -> AgentResult:
        return run_agent(
            question, toolkit, settings, scripted(AIMessage(content="ANSWER: VULNERABLE"))
        )

    monkeypatch.setattr(runner, "run_agent", offline)
    return Settings(fixture_path=path), tasks


def test_output_preserves_traces_and_separates_deterministic_metrics(
    tmp_path: Path, tiny_fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, tasks = prepare(tmp_path, tiny_fixture, monkeypatch)
    settings.llm_api_key = SecretStr("never-print-this")
    out = tmp_path / "run.json"
    report = evaluate_to_file(
        settings=settings, tasks_path=tasks, output=out, split="dev", systems=["agent"]
    )
    assert report["status"] == "complete"
    assert len(report["records"]) == 1
    assert report["records"][0]["trace"]["messages"]
    assert json.loads(out.with_suffix(".metrics.json").read_text()) == report["metrics"]
    assert len(out.with_suffix(".jsonl").read_text().splitlines()) == 2
    for path in tmp_path.glob("run.*"):
        assert "never-print-this" not in path.read_text()
    with pytest.raises(ValueError, match="already exists"):
        evaluate_to_file(
            settings=settings, tasks_path=tasks, output=out, split="dev", systems=["agent"]
        )


def test_held_out_guard_runs_before_loading_files_or_contacting_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="confirm-held-out-once"):
        evaluate_to_file(
            settings=Settings(),
            tasks_path=tmp_path / "missing.json",
            output=tmp_path / "run.json",
            split="held_out",
            systems=list(SYSTEMS),
        )
    assert not (tmp_path / "run.jsonl").exists()


def test_snapshot_mismatch_stops_before_inference(
    tmp_path: Path, tiny_fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, tasks = prepare(tmp_path, tiny_fixture, monkeypatch)
    data = TaskSet.model_validate_json(tasks.read_text())
    data.fixture_snapshot = "1900-01-01"
    tasks.write_text(data.model_dump_json())
    with pytest.raises(ValueError, match="snapshot dates differ"):
        evaluate_to_file(
            settings=settings,
            tasks_path=tasks,
            output=tmp_path / "run.json",
            split="dev",
            systems=["agent"],
        )


def test_cli_accepts_dev_and_rejects_unguarded_held_out(
    tmp_path: Path, tiny_fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, tasks = prepare(tmp_path, tiny_fixture, monkeypatch)
    monkeypatch.setenv("DEP_TRIAGE_FIXTURE_PATH", str(settings.fixture_path))
    cli = CliRunner()
    result = cli.invoke(
        app, ["eval", "--tasks", str(tasks), "--output", str(tmp_path / "cli.json")]
    )
    assert result.exit_code == 0, result.output
    assert "1 executions" in result.output
    blocked = cli.invoke(app, ["eval", "--split", "held_out"])
    assert blocked.exit_code == 1
    assert "--confirm-held-out-once" in blocked.output
    invalid = cli.invoke(app, ["eval", "--system", "invented"])
    assert invalid.exit_code != 0


def test_synthetic_held_out_guard_survives_output_directory_change(
    tmp_path: Path, tiny_fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, tasks = prepare(tmp_path, tiny_fixture, monkeypatch)
    synthetic = task()
    synthetic.split = "held_out"
    tasks.write_text(
        TaskSet(
            fixture_snapshot=tiny_fixture.manifest.snapshot_date, tasks=[synthetic]
        ).model_dump_json()
    )
    evaluate_to_file(
        settings=settings,
        tasks_path=tasks,
        output=tmp_path / "one/run.json",
        split="held_out",
        systems=["agent"],
        confirm_held_out=True,
    )
    with pytest.raises(ValueError, match="reruns are forbidden"):
        evaluate_to_file(
            settings=settings,
            tasks_path=tasks,
            output=tmp_path / "two/run.json",
            split="held_out",
            systems=["agent"],
            confirm_held_out=True,
        )


def test_rescoring_preserves_original_and_cannot_contact_a_model(
    tmp_path: Path,
    tiny_fixture: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, tasks = prepare(tmp_path, tiny_fixture, monkeypatch)
    source = tmp_path / "original.json"
    original = evaluate_to_file(
        settings=settings, tasks_path=tasks, output=source, split="dev", systems=["agent"]
    )
    before = source.read_bytes()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("rescoring must never run a model")

    monkeypatch.setattr(runner, "run_case", forbidden)
    script = Path(__file__).resolve().parents[1] / "scripts/rescore_eval.py"
    rescore = runpy.run_path(str(script))["rescore"]
    result = rescore(source, tmp_path / "rescored.json", settings.fixture_path)
    assert source.read_bytes() == before
    assert result["metrics"] == original["metrics"]
    assert result["rescoring"]["model_executions"] == 0
    assert result["records"][0]["trace"] == original["records"][0]["trace"]
    with pytest.raises(ValueError, match="overwrite"):
        rescore(source, source, settings.fixture_path)
    tiny_fixture.manifest.snapshot_date = "2026-10-09"
    write_fixture(tiny_fixture, settings.fixture_path)
    with pytest.raises(ValueError, match="fixture bytes differ"):
        rescore(source, tmp_path / "changed.json", settings.fixture_path)

"""CLI tests."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from dep_triage import __version__
from dep_triage.cli import app

runner = CliRunner()


def test_version_matches_package() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_bare_invocation_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "triage" in result.stdout.lower()


def test_config_emits_json() -> None:
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["llm_backend"] == "ollama"


def test_config_does_not_print_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEP_TRIAGE_LLM_API_KEY", "gsk-super-secret-value")
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "gsk-super-secret-value" not in result.stdout
    assert json.loads(result.stdout)["llm_api_key"] == "<set>"

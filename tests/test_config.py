"""Config layer tests.

The non-obvious ones are the redaction tests. ``Settings`` holds the only secret
this project has, and it will be printed by ``dep-triage config`` and logged at
service startup. These assert the secret cannot reach either.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from dep_triage.config import Settings


def test_defaults_target_local_ollama() -> None:
    settings = Settings()
    assert settings.llm_backend == "ollama"
    assert settings.llm_name == "qwen3:8b"
    assert settings.llm_base_url == "http://localhost:11434/v1"
    assert settings.llm_api_key is None
    assert settings.max_steps == 8
    assert settings.fixture_path == Path("data/fixture")


def test_defaults_are_deterministic() -> None:
    """Greedy decoding by default — evaluation reproducibility depends on it."""
    settings = Settings()
    assert settings.llm_temperature == 0.0
    assert settings.is_deterministic is True


def test_non_zero_temperature_is_not_deterministic() -> None:
    assert Settings(llm_temperature=0.7).is_deterministic is False


def test_env_vars_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEP_TRIAGE_LLM_BACKEND", "hosted")
    monkeypatch.setenv("DEP_TRIAGE_LLM_NAME", "llama-3.3-70b")
    monkeypatch.setenv("DEP_TRIAGE_MAX_STEPS", "12")
    settings = Settings()
    assert settings.llm_backend == "hosted"
    assert settings.llm_name == "llama-3.3-70b"
    assert settings.max_steps == 12


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_backend", "anthropic"),
        ("log_level", "TRACE"),
        ("llm_temperature", 2.5),
        ("llm_temperature", -0.1),
        ("max_steps", 0),
        ("demo_daily_limit", 0),
        ("demo_per_minute_limit", -1),
        ("llm_timeout_s", 0),
    ],
)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})  # type: ignore[arg-type]


def test_unknown_env_var_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo'd setting should fail loudly, not be silently ignored."""
    monkeypatch.setenv("DEP_TRIAGE_MAX_STEP", "8")
    with pytest.raises(ValidationError):
        Settings()


def test_secret_is_not_in_repr_or_str(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEP_TRIAGE_LLM_API_KEY", "gsk-super-secret-value")
    settings = Settings()
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "gsk-super-secret-value"
    assert "gsk-super-secret-value" not in repr(settings)
    assert "gsk-super-secret-value" not in str(settings)


def test_redacted_dump_hides_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEP_TRIAGE_LLM_API_KEY", "gsk-super-secret-value")
    dump = Settings().redacted_dump()
    assert dump["llm_api_key"] == "<set>"
    assert "gsk-super-secret-value" not in str(dump)


def test_redacted_dump_marks_missing_secret_as_unset() -> None:
    assert Settings().redacted_dump()["llm_api_key"] == "<unset>"


def test_redacted_dump_covers_every_field() -> None:
    """Guards against a new field being added and silently escaping the dump."""
    dump = Settings().redacted_dump()
    assert set(dump) == set(Settings.model_fields)


def test_redacted_dump_is_json_serialisable() -> None:
    import json

    json.dumps(Settings().redacted_dump())

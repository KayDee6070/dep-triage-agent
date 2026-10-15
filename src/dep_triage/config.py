"""Runtime configuration.

Every setting is overridable by an environment variable prefixed
``DEP_TRIAGE_``. ``.env.example`` documents all of them, and
``tests/test_env_example.py`` fails if the two ever drift apart — which is the
only thing that keeps a documented-config file honest over a 14-day project.

Fields are named ``llm_*`` rather than ``model_*`` because Pydantic reserves the
``model_`` namespace on ``BaseModel``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "DEP_TRIAGE_"

LLMBackend = Literal["ollama", "hosted"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

#: Env var name for the one secret this project has. Named once so the
#: redaction logic and the tests cannot disagree about it.
SECRET_FIELDS = frozenset({"llm_api_key"})


class Settings(BaseSettings):
    """Resolved configuration for the agent, the harness, and the service."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_env_vars(cls, data: Any) -> Any:
        """Fail loudly on a mistyped ``DEP_TRIAGE_*`` variable.

        ``extra="forbid"`` does not cover this: pydantic-settings looks up only
        the variables it already has fields for, so ``DEP_TRIAGE_MAX_STEP``
        would be ignored in silence. In a container that means a setting you
        believe you configured having no effect, with nothing in the logs —
        a long debugging session for a one-character mistake.
        """
        known = {f"{ENV_PREFIX}{name.upper()}" for name in cls.model_fields}
        unknown = sorted(k for k in os.environ if k.startswith(ENV_PREFIX) and k not in known)
        if unknown:
            raise ValueError(f"unknown {ENV_PREFIX}* environment variable(s): {', '.join(unknown)}")
        return data

    # --- model -------------------------------------------------------------
    llm_backend: LLMBackend = "ollama"
    llm_name: str = "qwen3:8b"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: SecretStr | None = None

    #: Must stay 0.0 for evaluation runs. See M0 scope §6 — the day-5 gate
    #: checks that two identical dev-subset runs produce identical metrics.
    llm_temperature: float = 0.0
    llm_seed: int = 42
    llm_timeout_s: int = 120

    #: Qwen3 reasons by default, and it is expensive: ~840 completion tokens to
    #: answer "17*23". Ollama's OpenAI-compatible endpoint honours
    #: ``reasoning_effort="none"``, which cuts that to 4. Neither ``think:
    #: false`` nor ``chat_template_kwargs`` had any effect. Set to ``None`` for
    #: backends that reject the field.
    llm_reasoning_effort: str | None = "none"

    # --- agent -------------------------------------------------------------
    max_steps: int = 8

    # --- data --------------------------------------------------------------
    fixture_path: Path = Path("data/fixture")

    #: Pre-rendered report HTML. Rendered at image build time so the deployed
    #: service has **no** runtime dependency on evaluation JSON — the landing
    #: page is the project's evidence and must not be able to fail. If absent,
    #: the service falls back to rendering from run artifacts.
    report_path: Path = Path("results/report.html")

    #: Where evaluation run artifacts live. Only used as a fallback when no
    #: pre-rendered report is present, and kept a setting rather than a
    #: hardcoded relative path so the service does not depend on the working
    #: directory it happens to be started from.
    results_dir: Path = Path("results")

    # --- service -----------------------------------------------------------
    log_level: LogLevel = "INFO"
    enable_metrics: bool = True

    #: The public demo is a key behind an open endpoint. These are the caps
    #: that stop it being a free proxy for anyone who finds the link.
    demo_daily_limit: int = 100
    demo_per_minute_limit: int = 5

    @field_validator("llm_reasoning_effort", mode="before")
    @classmethod
    def _blank_effort_means_unset(cls, value: object) -> object:
        """Treat an empty environment variable as "do not send this field".

        ``DEP_TRIAGE_LLM_REASONING_EFFORT=`` reads as the empty string, which
        was then sent verbatim and rejected by the gateway with a 400 listing
        the allowed values. Unsetting a field by blanking its variable is the
        obvious thing for a reader to try, so it now does what it looks like.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("llm_temperature")
    @classmethod
    def _check_temperature(cls, value: float) -> float:
        if not 0.0 <= value <= 2.0:
            raise ValueError("llm_temperature must be between 0.0 and 2.0")
        return value

    @field_validator("max_steps", "demo_daily_limit", "demo_per_minute_limit", "llm_timeout_s")
    @classmethod
    def _check_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be at least 1")
        return value

    @property
    def is_deterministic(self) -> bool:
        """Whether this config can produce a reproducible evaluation run.

        Greedy decoding is necessary but not sufficient — see M0 scope §6. If
        the day-5 check still shows variance, the harness reports repeats
        instead of a single run.
        """
        return self.llm_temperature == 0.0

    def redacted_dump(self) -> dict[str, Any]:
        """Config as a dict, with secrets replaced by a set/unset marker.

        Used by ``dep-triage config`` and anywhere config is logged. Never
        serialise ``Settings`` directly to a log line.
        """
        data: dict[str, Any] = {}
        for name in type(self).model_fields:
            value = getattr(self, name)
            if name in SECRET_FIELDS:
                data[name] = "<set>" if value is not None else "<unset>"
            elif isinstance(value, Path):
                data[name] = str(value)
            else:
                data[name] = value
        return data

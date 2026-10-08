"""Tests that keep documented config and real config in sync.

"No secrets in the repo, env vars and ``.env.example``" is a project
non-negotiable. A ``.env.example`` nobody checks drifts within days, so these
tests make the drift a build failure instead of a surprise at deploy time.
"""

from __future__ import annotations

import pathlib
import re

from dep_triage.config import ENV_PREFIX, Settings

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"
GITIGNORE = REPO_ROOT / ".gitignore"
_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=")


def documented_keys() -> set[str]:
    return {
        match.group(1)
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if (match := _KEY_RE.match(line.strip()))
    }


def settings_keys() -> set[str]:
    return {f"{ENV_PREFIX}{name.upper()}" for name in Settings.model_fields}


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file()


def test_every_setting_is_documented() -> None:
    missing = settings_keys() - documented_keys()
    assert not missing, f"settings absent from .env.example: {sorted(missing)}"


def test_no_stale_keys_documented() -> None:
    stale = documented_keys() - settings_keys()
    assert not stale, f".env.example documents settings that no longer exist: {sorted(stale)}"


def test_env_example_holds_no_secret_value() -> None:
    """The example file must ship the key empty, never populated."""
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{ENV_PREFIX}LLM_API_KEY="):
            assert line.strip() == f"{ENV_PREFIX}LLM_API_KEY=", "a real key may be committed"


def test_gitignore_excludes_dotenv() -> None:
    entries = {line.strip() for line in GITIGNORE.read_text(encoding="utf-8").splitlines()}
    assert ".env" in entries
    assert "!.env.example" in entries, ".env.example must stay tracked despite the .env rule"

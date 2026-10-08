"""Test isolation.

Both fixtures exist to stop a developer's local environment leaking into a test
run. Without them, ``Settings()`` would pick up a real ``.env`` or exported
``DEP_TRIAGE_*`` vars and the config tests would pass or fail depending on whose
machine they ran on.
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear project env vars and run from a directory with no ``.env``."""
    for key in list(os.environ):
        if key.startswith("DEP_TRIAGE_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    yield

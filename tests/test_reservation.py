"""Tests for the held-out reservation, and the one way it can be released.

The reservation exists to prevent re-measuring after seeing a result. These
tests pin the bright line that governs the single exception, because a rule
with a judgement call in it is a rule that erodes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dep_triage.config import Settings
from dep_triage.eval.runner import (
    RELEASED,
    RESERVED,
    release_unused_reservation,
    reserve_held_out,
)
from dep_triage.eval.suite import SystemName

SYSTEMS: tuple[SystemName, ...] = ("agent", "no_agent")


def settings_for(name: str = "model-a") -> Settings:
    return Settings(llm_backend="hosted", llm_name=name)


def artifact(tmp_path: Path, gradable: int, total: int) -> Path:
    records: list[dict[str, Any]] = [
        {"grade": {"correct": True if index < gradable else None}} for index in range(total)
    ]
    path = tmp_path / "run.json"
    path.write_text(json.dumps({"records": records}), encoding="utf-8")
    return path


def test_a_reservation_blocks_a_second_run(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.json"
    tasks.write_text("{}", encoding="utf-8")
    reserve_held_out(tasks, SYSTEMS, settings_for(), faults=False)
    with pytest.raises(ValueError, match="already reserved"):
        reserve_held_out(tasks, SYSTEMS, settings_for(), faults=False)


def test_each_model_arm_reserves_independently(tmp_path: Path) -> None:
    """A different model, or the other arm, is a different measurement."""
    tasks = tmp_path / "tasks.json"
    tasks.write_text("{}", encoding="utf-8")
    reserve_held_out(tasks, SYSTEMS, settings_for("model-a"), faults=False)
    reserve_held_out(tasks, SYSTEMS, settings_for("model-a"), faults=True)
    reserve_held_out(tasks, SYSTEMS, settings_for("model-b"), faults=False)


def test_zero_gradable_records_releases_the_reservation(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.json"
    tasks.write_text("{}", encoding="utf-8")
    reserve_held_out(tasks, SYSTEMS, settings_for(), faults=False)

    released = release_unused_reservation(
        tasks,
        SYSTEMS,
        settings_for(),
        False,
        artifact(tmp_path, gradable=0, total=12),
        reason="provider refused every request",
    )
    assert len(released) == len(SYSTEMS)
    # Re-reserving is now allowed, because nothing was ever observed.
    reserve_held_out(tasks, SYSTEMS, settings_for(), faults=False)


@pytest.mark.parametrize("gradable", [1, 5, 12])
def test_one_gradable_record_makes_it_permanent(tmp_path: Path, gradable: int) -> None:
    """The bright line. A single graded task spends the reservation."""
    tasks = tmp_path / "tasks.json"
    tasks.write_text("{}", encoding="utf-8")
    reserve_held_out(tasks, SYSTEMS, settings_for(), faults=False)

    with pytest.raises(ValueError, match="gradable record"):
        release_unused_reservation(
            tasks,
            SYSTEMS,
            settings_for(),
            False,
            artifact(tmp_path, gradable=gradable, total=12),
            reason="partial failure",
        )
    with pytest.raises(ValueError, match="already reserved"):
        reserve_held_out(tasks, SYSTEMS, settings_for(), faults=False)


def test_an_empty_artifact_is_refused(tmp_path: Path) -> None:
    """No records at all is not evidence of a failed run; it proves nothing."""
    tasks = tmp_path / "tasks.json"
    tasks.write_text("{}", encoding="utf-8")
    reserve_held_out(tasks, SYSTEMS, settings_for(), faults=False)
    with pytest.raises(ValueError, match="no records at all"):
        release_unused_reservation(
            tasks,
            SYSTEMS,
            settings_for(),
            False,
            artifact(tmp_path, gradable=0, total=0),
            reason="nothing ran",
        )


def test_release_supersedes_rather_than_deletes(tmp_path: Path) -> None:
    """A released reservation stays visible as evidence."""
    tasks = tmp_path / "tasks.json"
    tasks.write_text("{}", encoding="utf-8")
    paths = reserve_held_out(tasks, SYSTEMS, settings_for(), faults=False)
    release_unused_reservation(
        tasks,
        SYSTEMS,
        settings_for(),
        False,
        artifact(tmp_path, gradable=0, total=9),
        reason="provider 403 on every call",
    )

    for path in paths:
        assert path.exists(), "the reservation file must not be deleted"
        state = json.loads(path.read_text(encoding="utf-8"))
        assert state["state"] == RELEASED
        assert len(state["history"]) == 1
        entry = state["history"][0]
        assert entry["previous_state"] == RESERVED
        assert entry["gradable_records"] == 0
        assert entry["records"] == 9
        assert "403" in entry["reason"]


def test_history_accumulates_across_releases(tmp_path: Path) -> None:
    """Every release is appended, so repeated releases are conspicuous."""
    tasks = tmp_path / "tasks.json"
    tasks.write_text("{}", encoding="utf-8")
    for round_number in range(2):
        reserve_held_out(tasks, SYSTEMS, settings_for(), faults=False)
        release_unused_reservation(
            tasks,
            SYSTEMS,
            settings_for(),
            False,
            artifact(tmp_path, gradable=0, total=4),
            reason=f"outage {round_number}",
        )
    paths = tasks.resolve().parent / ".held-out-runs"
    for path in paths.glob("*.json"):
        assert len(json.loads(path.read_text(encoding="utf-8"))["history"]) == 2

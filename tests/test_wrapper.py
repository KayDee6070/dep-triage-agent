"""Tests for instrumentation and fault injection.

These matter more than they look. D1 and D3 are computed entirely from the call
records asserted here, so a silent bug in this layer would corrupt two of the
three reported metrics while every tool test stayed green.
"""

from __future__ import annotations

import pytest

from dep_triage.fixture import Fixture
from dep_triage.tools.wrapper import TOOL_NAMES, ToolError, ToolFault, Toolkit

# --- instrumentation ------------------------------------------------------


def test_calls_are_recorded_in_order(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture)
    kit.list_releases("demo-pkg")
    kit.lookup_vulnerabilities("demo-pkg", "1.0.0")

    assert [c.tool for c in kit.calls] == ["list_releases", "lookup_vulnerabilities"]
    assert [c.index for c in kit.calls] == [1, 2]
    assert all(c.ok for c in kit.calls)


def test_arguments_are_recorded(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture)
    kit.check_compatibility("demo-pkg", "2.0.0", "3.12")
    assert kit.calls[0].arguments == {
        "package": "demo-pkg",
        "version": "2.0.0",
        "python_version": "3.12",
    }


def test_repeat_signature_detects_identical_calls(tiny_fixture: Fixture) -> None:
    """The loop signature behind D3 ``repeat_call_rate``."""
    kit = Toolkit(tiny_fixture)
    kit.lookup_vulnerabilities("demo-pkg", "1.0.0")
    kit.lookup_vulnerabilities("demo-pkg", "1.0.0")
    kit.lookup_vulnerabilities("demo-pkg", "2.0.0")

    signatures = [c.signature() for c in kit.calls]
    assert signatures[0] == signatures[1]
    assert signatures[0] != signatures[2]
    assert len(set(signatures)) == 2


def test_duration_is_measured(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture)
    kit.list_releases("demo-pkg")
    assert kit.calls[0].duration_ms >= 0.0


def test_reset_clears_records_and_occurrence_counts(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture, faults=(ToolFault(tool="list_releases", mode="error"),))
    with pytest.raises(ToolError):
        kit.list_releases("demo-pkg")
    kit.reset()
    assert kit.calls == []
    # Occurrence counting restarted, so the first-call fault fires again.
    with pytest.raises(ToolError):
        kit.list_releases("demo-pkg")


def test_calls_property_returns_a_copy(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture)
    kit.list_releases("demo-pkg")
    kit.calls.clear()
    assert len(kit.calls) == 1


def test_every_tool_is_instrumented(tiny_fixture: Fixture) -> None:
    """Guards against a new tool being added without a call record."""
    kit = Toolkit(tiny_fixture)
    kit.parse_requirements("demo-pkg==1.0.0")
    kit.lookup_vulnerabilities("demo-pkg", "1.0.0")
    kit.list_releases("demo-pkg")
    kit.check_compatibility("demo-pkg", "1.0.0", "3.12")
    assert [c.tool for c in kit.calls] == list(TOOL_NAMES)


# --- fault mode: error ----------------------------------------------------


def test_error_fault_raises_and_is_recorded(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture, faults=(ToolFault(tool="lookup_vulnerabilities", mode="error"),))
    with pytest.raises(ToolError, match="503"):
        kit.lookup_vulnerabilities("demo-pkg", "1.0.0")

    record = kit.calls[0]
    assert record.ok is False
    assert record.fault == "error"
    assert record.result is None
    assert record.error is not None and "503" in record.error


def test_error_fault_leaves_other_tools_working(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture, faults=(ToolFault(tool="lookup_vulnerabilities", mode="error"),))
    assert kit.list_releases("demo-pkg")["status"] == "ok"


# --- fault mode: empty ----------------------------------------------------


def test_empty_fault_keeps_shape_but_drops_content(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture, faults=(ToolFault(tool="lookup_vulnerabilities", mode="empty"),))
    payload = kit.lookup_vulnerabilities("demo-pkg", "1.0.0")

    assert payload["status"] == "ok"
    assert payload["advisories"] == []
    assert payload["vulnerable"] is False
    assert kit.calls[0].fault == "empty"
    assert kit.calls[0].ok is True


def test_empty_fault_on_list_releases(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture, faults=(ToolFault(tool="list_releases", mode="empty"),))
    payload = kit.list_releases("demo-pkg")
    assert payload["versions"] == []
    assert payload["latest"] is None


# --- fault mode: malformed ------------------------------------------------


def test_malformed_fault_removes_the_key_entirely(tiny_fixture: Fixture) -> None:
    """Absent, not empty — the distinction the fault mode exists to test."""
    kit = Toolkit(
        tiny_fixture, faults=(ToolFault(tool="lookup_vulnerabilities", mode="malformed"),)
    )
    payload = kit.lookup_vulnerabilities("demo-pkg", "1.0.0")

    assert payload["advisories"], "the advisory itself must survive"
    assert "fixed_versions" not in payload["advisories"][0]
    assert "id" in payload["advisories"][0]


def test_malformed_fault_on_list_releases_drops_versions(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture, faults=(ToolFault(tool="list_releases", mode="malformed"),))
    payload = kit.list_releases("demo-pkg")
    assert "versions" not in payload
    assert payload["latest"] == "2.0.0"


def test_malformed_fault_on_check_compatibility(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture, faults=(ToolFault(tool="check_compatibility", mode="malformed"),))
    payload = kit.check_compatibility("demo-pkg", "1.0.0", "3.8")
    assert "python_compatible" not in payload
    assert payload["requires_python"] == ">=3.8"


# --- occurrence targeting -------------------------------------------------


def test_fault_targets_a_specific_occurrence(tiny_fixture: Fixture) -> None:
    """Lets a task fail the retry rather than the first attempt."""
    kit = Toolkit(
        tiny_fixture,
        faults=(ToolFault(tool="lookup_vulnerabilities", mode="error", occurrence=2),),
    )
    assert kit.lookup_vulnerabilities("demo-pkg", "1.0.0")["vulnerable"] is True
    with pytest.raises(ToolError):
        kit.lookup_vulnerabilities("demo-pkg", "1.0.0")

    assert [c.ok for c in kit.calls] == [True, False]


def test_no_faults_means_no_interference(tiny_fixture: Fixture) -> None:
    kit = Toolkit(tiny_fixture)
    payload = kit.lookup_vulnerabilities("demo-pkg", "1.0.0")
    assert payload["vulnerable"] is True
    assert all(c.fault is None for c in kit.calls)

"""Fault injection and call instrumentation.

This layer is where the eval harness attaches, and it is deliberately not
inside the agent graph. M0 scope §10 commits to instrumenting at the tool
boundary so that swapping or removing LangGraph cannot invalidate a measured
number.

Two jobs:

**Instrumentation.** Every call is recorded with its arguments, outcome, and
duration. D1 (tool selection) and D3 (stopping behaviour) are computed entirely
from these records.

**Fault injection.** The three modes from M0 scope §4.3 are applied to the
serialised result, after the tool has run correctly. The tools themselves
contain no failure logic, so a bug in fault injection can never be mistaken for
a bug in a tool.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from dep_triage.fixture import Fixture
from dep_triage.tools import triage

FaultMode = Literal["error", "empty", "malformed"]

TOOL_NAMES = (
    "parse_requirements",
    "lookup_vulnerabilities",
    "list_releases",
    "check_compatibility",
)


class ToolError(RuntimeError):
    """A tool failed. Surfaced to the agent as an error tool result."""


class ToolFault(BaseModel):
    """Inject ``mode`` into the ``occurrence``-th call of ``tool``."""

    tool: str
    mode: FaultMode
    occurrence: int = 1


class ToolCallRecord(BaseModel):
    """One observed tool call. The raw material for D1 and D3."""

    index: int
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0
    fault: FaultMode | None = None

    def signature(self) -> tuple[str, str]:
        """Identity for repeat detection (D3 ``repeat_call_rate``)."""
        items = sorted((k, str(v)) for k, v in self.arguments.items())
        return self.tool, repr(items)


def _empty(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Valid shape, no content. Simulates an upstream returning nothing."""
    blanked = dict(payload)
    if tool == "parse_requirements":
        blanked.update(requirements=[], unparsed=[])
    elif tool == "lookup_vulnerabilities":
        blanked.update(vulnerable=False, advisories=[])
    elif tool == "list_releases":
        blanked.update(versions=[], yanked=[], latest=None, total_count=0, truncated=False)
    elif tool == "check_compatibility":
        blanked.update(
            requires_python=None,
            python_compatible=None,
            declared_dependencies=[],
            dependencies_captured=False,
        )
    return blanked


def _malformed(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Drop the field each tool's answer depends on.

    Keys are removed rather than emptied. An advisory with ``fixed_versions: []``
    says "no fix exists"; an advisory with no ``fixed_versions`` key at all says
    "this record is broken". Only the second tests recovery, and the first would
    quietly make the agent look wrong for believing us.
    """
    broken = dict(payload)
    if tool == "lookup_vulnerabilities":
        broken["advisories"] = [
            {k: v for k, v in advisory.items() if k != "fixed_versions"}
            for advisory in broken.get("advisories", [])
        ]
    elif tool == "list_releases":
        broken.pop("versions", None)
    elif tool == "check_compatibility":
        broken.pop("python_compatible", None)
    elif tool == "parse_requirements":
        broken["requirements"] = [
            {k: v for k, v in requirement.items() if k != "pinned_version"}
            for requirement in broken.get("requirements", [])
        ]
    return broken


class Toolkit:
    """The four tools, bound to a fixture, instrumented, optionally faulty.

    The public methods are what the agent sees. ``fixture`` is bound here so
    the schema exposed to the model stays free of harness plumbing.
    """

    def __init__(self, fixture: Fixture, faults: tuple[ToolFault, ...] = ()) -> None:
        self._fixture = fixture
        self._faults = faults
        self._calls: list[ToolCallRecord] = []
        self._counts: dict[str, int] = {}

    @property
    def calls(self) -> list[ToolCallRecord]:
        return list(self._calls)

    def reset(self) -> None:
        self._calls.clear()
        self._counts.clear()

    def _fault_for(self, tool: str, occurrence: int) -> FaultMode | None:
        for fault in self._faults:
            if fault.tool == tool and fault.occurrence == occurrence:
                return fault.mode
        return None

    def _invoke(
        self, tool: str, fn: Callable[[], BaseModel], arguments: dict[str, Any]
    ) -> dict[str, Any]:
        occurrence = self._counts.get(tool, 0) + 1
        self._counts[tool] = occurrence
        fault = self._fault_for(tool, occurrence)
        index = len(self._calls) + 1
        started = time.perf_counter()

        if fault == "error":
            # Raised before the tool runs, because a 503 means the upstream was
            # never reached.
            message = f"{tool} failed: upstream returned HTTP 503"
            self._calls.append(
                ToolCallRecord(
                    index=index,
                    tool=tool,
                    arguments=arguments,
                    ok=False,
                    error=message,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    fault="error",
                )
            )
            raise ToolError(message)

        payload = fn().model_dump()
        if fault == "empty":
            payload = _empty(tool, payload)
        elif fault == "malformed":
            payload = _malformed(tool, payload)

        self._calls.append(
            ToolCallRecord(
                index=index,
                tool=tool,
                arguments=arguments,
                ok=True,
                result=payload,
                duration_ms=(time.perf_counter() - started) * 1000,
                fault=fault,
            )
        )
        return payload

    # --- the agent-facing surface -----------------------------------------

    def parse_requirements(self, text: str) -> dict[str, Any]:
        """Parse requirements-file text into package names and pinned versions."""
        return self._invoke(
            "parse_requirements",
            lambda: triage.parse_requirements(self._fixture, text),
            {"text": text},
        )

    def lookup_vulnerabilities(self, package: str, version: str) -> dict[str, Any]:
        """Find known advisories affecting an exact package version."""
        return self._invoke(
            "lookup_vulnerabilities",
            lambda: triage.lookup_vulnerabilities(self._fixture, package, version),
            {"package": package, "version": version},
        )

    def list_releases(self, package: str, since_version: str | None = None) -> dict[str, Any]:
        """List published versions of a package.

        Pass ``since_version`` to narrow the result to versions at or above a
        floor — useful when a package has hundreds of releases and only those
        after a known-vulnerable version matter.
        """
        return self._invoke(
            "list_releases",
            lambda: triage.list_releases(self._fixture, package, since_version),
            {"package": package, "since_version": since_version},
        )

    def check_compatibility(
        self, package: str, version: str, python_version: str
    ) -> dict[str, Any]:
        """Check whether a version installs on a Python, and list its declared deps."""
        return self._invoke(
            "check_compatibility",
            lambda: triage.check_compatibility(self._fixture, package, version, python_version),
            {"package": package, "version": version, "python_version": python_version},
        )

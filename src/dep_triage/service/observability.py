"""Structured logging and Prometheus collectors.

Both are fed from data the harness already produces — ``ToolCallRecord`` and
``AgentResult`` — so the service reports the same quantities the evaluation
measures. A separate metric definition would be free to drift from the eval,
and then two numbers would both claim to describe the same behaviour.

Collectors live in a caller-supplied registry rather than the global default.
The global one is process-wide, so re-registering the same metric name raises,
and tests creating more than one app would collide.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

from dep_triage.agent.loop import AgentResult
from dep_triage.config import Settings

#: Keys that must never reach a log line. ``Settings.redacted_dump`` already
#: guards config; this guards anything a request handler passes through.
_REDACT = frozenset({"api_key", "llm_api_key", "authorization", "token", "secret"})


def _redact(_logger: Any, _name: str, event_dict: MutableMapping[str, Any]) -> Mapping[str, Any]:
    for key in list(event_dict):
        if key.lower() in _REDACT:
            event_dict[key] = "<redacted>"
    return event_dict


def configure_logging(settings: Settings) -> None:
    """JSON logs to stdout, which is what a container platform collects.

    Idempotent: calling it twice is harmless, because the service and the CLI
    may both initialise it.
    """
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=settings.log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


class Metrics:
    """Prometheus collectors for one service instance."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()

        self.requests = Counter(
            "dep_triage_requests_total",
            "Requests by endpoint and outcome.",
            ["endpoint", "outcome"],
            registry=self.registry,
        )
        self.request_seconds = Histogram(
            "dep_triage_request_seconds",
            "Wall-clock seconds per request.",
            ["endpoint"],
            # An 8B model on a laptop GPU answers in 1-5 s; the hosted demo
            # backend is faster. Buckets straddle both rather than using the
            # library defaults, which top out below the interesting range.
            buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
            registry=self.registry,
        )
        self.tool_calls = Counter(
            "dep_triage_tool_calls_total",
            "Tool calls by tool and outcome.",
            ["tool", "outcome"],
            registry=self.registry,
        )
        self.agent_steps = Histogram(
            "dep_triage_agent_steps",
            "Tool calls per answered question.",
            buckets=(0, 1, 2, 3, 4, 5, 6, 8, 12),
            registry=self.registry,
        )
        self.stop_reasons = Counter(
            "dep_triage_stop_reason_total",
            "Why the agent loop stopped.",
            ["reason"],
            registry=self.registry,
        )
        self.rate_limited = Counter(
            "dep_triage_rate_limited_total",
            "Requests refused by a demo rate limit.",
            ["scope"],
            registry=self.registry,
        )
        self.backend_unavailable = Counter(
            "dep_triage_backend_unavailable_total",
            "Live-agent requests that could not reach the model backend.",
            registry=self.registry,
        )

    def observe_agent(self, result: AgentResult) -> None:
        """Record one agent execution.

        Reads the same ``ToolCallRecord`` list the eval harness scores, so
        ``dep_triage_agent_steps`` and the harness's ``cost.tool_calls`` cannot
        disagree about what a step is.
        """
        self.agent_steps.observe(result.steps)
        self.stop_reasons.labels(reason=result.stop_reason).inc()
        for call in result.calls:
            outcome = "ok" if call.ok else "error"
            if call.fault is not None:
                outcome = f"fault_{call.fault}"
            self.tool_calls.labels(tool=call.tool, outcome=outcome).inc()

    def render(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST

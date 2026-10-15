"""Service tests: report rendering, rate limits, endpoints, observability.

Entirely offline. ``/ask`` tests replace ``run_agent`` with a stub, because what
is under test is the service's handling of an agent result — success, backend
failure, refusal — not the agent itself, which has its own suite.

The load-bearing assertions are the degradation ones. The report is the landing
page and the project's actual evidence; a deployment where the model backend is
down must still serve it, and must never return a traceback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from dep_triage.agent.loop import AgentResult
from dep_triage.config import Settings
from dep_triage.service import app as app_module
from dep_triage.service.limits import Decision, RateLimiter, client_key
from dep_triage.service.observability import Metrics
from dep_triage.service.report import MIN_DISCORDANT_FOR_SIGNIFICANCE, render
from dep_triage.tools.wrapper import ToolCallRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
CLEAN_RUN = REPO_ROOT / "results" / "m3-gates" / "run-1.json"
FAULT_RUN = REPO_ROOT / "results" / "m3-faults.json"


def repo_settings(**overrides: Any) -> Settings:
    """Settings with absolute paths.

    The shared test fixture runs each test from a temporary directory, so the
    relative defaults would resolve to nothing. Absolute paths here also make
    the tests independent of where pytest was invoked from.
    """
    defaults: dict[str, Any] = {
        "fixture_path": REPO_ROOT / "data" / "fixture",
        "report_path": REPO_ROOT / "results" / "does-not-exist.html",
        "results_dir": REPO_ROOT / "results",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def client(settings: Settings | None = None) -> TestClient:
    return TestClient(
        app_module.create_app(settings=settings or repo_settings(), registry=CollectorRegistry())
    )


# --- rate limiting -------------------------------------------------------


def test_per_minute_limit_refuses_then_recovers() -> None:
    limiter = RateLimiter(daily_limit=100, per_minute_limit=2)
    assert limiter.check("a", now=1000.0).allowed
    assert limiter.check("a", now=1001.0).allowed
    refused = limiter.check("a", now=1002.0)
    assert refused.allowed is False
    assert refused.scope == "per_minute"
    assert refused.retry_after_s > 0
    # The window is 60 s from the oldest hit, not a fixed bucket.
    assert limiter.check("a", now=1061.0).allowed


def test_per_minute_limit_is_per_client() -> None:
    limiter = RateLimiter(daily_limit=100, per_minute_limit=1)
    assert limiter.check("a", now=1000.0).allowed
    assert limiter.check("a", now=1000.5).allowed is False
    assert limiter.check("b", now=1000.5).allowed, "one client must not block another"


def test_daily_limit_is_global_and_resets() -> None:
    limiter = RateLimiter(daily_limit=2, per_minute_limit=99)
    assert limiter.check("a", now=1000.0).allowed
    assert limiter.check("b", now=1001.0).allowed
    refused = limiter.check("c", now=1002.0)
    assert refused.allowed is False
    assert refused.scope == "daily"
    assert limiter.check("c", now=1002.0 + 86_400).allowed


def test_a_refusal_consumes_no_allowance(_: None = None) -> None:
    """A client over its own limit must not drain the global budget."""
    limiter = RateLimiter(daily_limit=10, per_minute_limit=1)
    limiter.check("noisy", now=1000.0)
    for _offset in range(5):
        limiter.check("noisy", now=1000.0 + _offset)
    assert limiter.snapshot()["daily_used"] == 1


def test_idle_clients_are_swept() -> None:
    """The client map must not grow without bound from one-off callers."""
    limiter = RateLimiter(daily_limit=1000, per_minute_limit=5)
    for index in range(50):
        limiter.check(f"client-{index}", now=1000.0)
    assert limiter.snapshot()["tracked_clients"] == 50
    limiter.check("fresh", now=1000.0 + 600)
    assert limiter.snapshot()["tracked_clients"] == 1


def test_snapshot_never_leaks_client_identifiers() -> None:
    limiter = RateLimiter(daily_limit=10, per_minute_limit=5)
    limiter.check("198.51.100.7", now=1000.0)
    assert "198.51.100.7" not in json.dumps(limiter.snapshot())


@pytest.mark.parametrize(
    ("headers", "peer", "expected"),
    [
        ({"x-forwarded-for": "203.0.113.5"}, "10.0.0.1", "203.0.113.5"),
        # First hop only: later entries are appended by intermediaries.
        ({"x-forwarded-for": "203.0.113.5, 10.0.0.9"}, "10.0.0.1", "203.0.113.5"),
        ({"x-real-ip": "203.0.113.6"}, "10.0.0.1", "203.0.113.6"),
        ({}, "10.0.0.1", "10.0.0.1"),
        ({}, None, "unknown"),
        ({"x-forwarded-for": "   "}, "10.0.0.1", "10.0.0.1"),
    ],
)
def test_client_key_extraction(headers: dict[str, str], peer: str | None, expected: str) -> None:
    assert client_key(headers, peer) == expected


# --- report --------------------------------------------------------------


@pytest.fixture(scope="session")
def clean_run() -> dict[str, Any]:
    if not CLEAN_RUN.is_file():
        pytest.skip("no committed evaluation run")
    loaded: dict[str, Any] = json.loads(CLEAN_RUN.read_text(encoding="utf-8"))
    return loaded


def test_report_is_self_contained(clean_run: dict[str, Any]) -> None:
    """No CDN, no scripts: it must still render years from now, offline."""
    html = render(clean_run)
    assert "http://" not in html
    assert "https://" not in html
    assert "<script" not in html
    assert html.startswith("<!doctype html>")


def test_report_states_it_is_not_the_final_result(clean_run: dict[str, Any]) -> None:
    html = render(clean_run)
    assert "development measurement" in html
    assert "has <em>not</em> been" in html or "not</em> been run" in html


def test_report_discloses_the_exposed_held_out_probes(clean_run: dict[str, Any]) -> None:
    """Two held-out probes were run during development; that must be visible."""
    html = render(clean_run)
    for task_id in clean_run.get("excluded_exposed_tasks", []):
        assert task_id in html


def test_report_accepts_a_bare_metrics_file(clean_run: dict[str, Any]) -> None:
    """The run artifact nests metrics; a .metrics.json does not."""
    assert "systems" in render(clean_run["metrics"])


def test_report_marks_lower_bounds_and_names_the_unvalidated_detector(
    clean_run: dict[str, Any],
) -> None:
    html = render(clean_run)
    assert "lower bounds" in html
    assert "not</em> validated" in html


def test_report_says_tool_recall_is_not_minimality(clean_run: dict[str, Any]) -> None:
    html = render(clean_run)
    assert "reference path" in html
    assert "minimality proof" in html


def test_report_explains_the_dominance_mechanism(clean_run: dict[str, Any]) -> None:
    """Without the mechanism, the null result reads as a weak agent."""
    html = render(clean_run)
    assert "strictly more information" in html


def test_report_calls_a_small_discordant_count_unresolvable() -> None:
    """The honest reading of 2 discordant pairs, stated by the report itself."""
    run = {
        "split": "dev",
        "metrics": {
            "systems": {},
            "paired": {
                "no_agent": {
                    "clean": {
                        "wins": 0,
                        "ties": 18,
                        "losses": 2,
                        "discordant_pairs": 2,
                        "mcnemar_exact_p": 0.5,
                        "excluded_ungradable": 0,
                    }
                }
            },
        },
    }
    html = render(run)
    assert "Cannot resolve at this size" in html
    assert str(MIN_DISCORDANT_FOR_SIGNIFICANCE) in html


def test_report_calls_zero_discordant_pairs_no_information() -> None:
    run = {
        "split": "dev",
        "metrics": {
            "systems": {},
            "paired": {
                "always_lookup": {
                    "clean": {
                        "wins": 0,
                        "ties": 20,
                        "losses": 0,
                        "discordant_pairs": 0,
                        "mcnemar_exact_p": 1.0,
                        "excluded_ungradable": 0,
                    }
                }
            },
        },
    }
    assert "No information" in render(run)


def test_report_renders_the_fault_arm_crash_finding() -> None:
    faults = {
        "metrics": {
            "systems": {
                "no_agent": {
                    "error": {
                        "task_accuracy": {"value": None, "denominator": 0},
                        "d2": {"behaviours": {"crashed": 10}},
                    }
                }
            }
        }
    }
    html = render({"split": "dev", "metrics": {"systems": {}, "paired": {}}}, faults)
    assert "0 gradable" in html
    assert "10 crashes" in html
    assert "not</strong>" in html or "not an accuracy win" in html


# --- observability -------------------------------------------------------


def test_metrics_record_an_agent_result() -> None:
    metrics = Metrics(CollectorRegistry())
    result = AgentResult(
        question="q",
        answer="a",
        calls=[
            ToolCallRecord(index=1, tool="lookup_vulnerabilities", ok=True),
            ToolCallRecord(index=2, tool="list_releases", ok=False, error="503"),
            ToolCallRecord(index=3, tool="list_releases", ok=True, fault="empty"),
        ],
        steps=3,
        stop_reason="end_turn",
    )
    metrics.observe_agent(result)
    exposition = metrics.render()[0].decode()

    assert (
        'dep_triage_tool_calls_total{outcome="ok",tool="lookup_vulnerabilities"} 1.0' in exposition
    )
    assert 'dep_triage_tool_calls_total{outcome="error",tool="list_releases"} 1.0' in exposition
    assert (
        'dep_triage_tool_calls_total{outcome="fault_empty",tool="list_releases"} 1.0' in exposition
    )
    assert 'dep_triage_stop_reason_total{reason="end_turn"} 1.0' in exposition


def test_metrics_use_an_isolated_registry() -> None:
    """Two apps in one process must not collide on metric names."""
    first, second = Metrics(CollectorRegistry()), Metrics(CollectorRegistry())
    first.requests.labels(endpoint="/", outcome="ok").inc()
    assert "dep_triage_requests_total" in first.render()[0].decode()
    assert 'endpoint="/"' not in second.render()[0].decode()


# --- endpoints -----------------------------------------------------------


def test_index_serves_the_report() -> None:
    response = client().get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "evaluation report" in response.text.lower()


def test_health_reports_limits_without_identifiers() -> None:
    payload = client().get("/health").json()
    assert payload["status"] == "ok"
    assert payload["report_available"] is True
    assert set(payload["limits"]) == {
        "daily_limit",
        "daily_used",
        "per_minute_limit",
        "tracked_clients",
    }


def test_metrics_endpoint_can_be_disabled() -> None:
    assert client(repo_settings(enable_metrics=False)).get("/metrics").status_code == 404
    assert client(repo_settings(enable_metrics=True)).get("/metrics").status_code == 200


@pytest.mark.parametrize("question", ["", "ab", "x" * 501])
def test_ask_rejects_unusable_questions(question: str) -> None:
    assert client().post("/ask", json={"question": question}).status_code == 422


def test_ask_returns_a_decoded_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_agent(*_args: object, **_kwargs: object) -> AgentResult:
        return AgentResult(
            question="q",
            answer="Prose.\nANSWER: NOT_VULNERABLE",
            calls=[ToolCallRecord(index=1, tool="lookup_vulnerabilities", ok=True)],
            steps=1,
            stop_reason="end_turn",
        )

    monkeypatch.setattr("dep_triage.agent.loop.run_agent", fake_run_agent)
    payload = client().post("/ask", json={"question": "Is x==1.0.0 vulnerable?"}).json()

    assert payload["status"] == "ok"
    assert payload["verdict"] == "not_vulnerable"
    assert "Not vulnerable" in payload["verdict_text"]
    # The verbatim answer is always preserved alongside the decoded form.
    assert payload["answer"].endswith("ANSWER: NOT_VULNERABLE")
    assert "disclaimer" in payload


def test_ask_degrades_when_the_backend_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 503 with a notice — never a traceback, and the report still loads."""

    def failing(*_args: object, **_kwargs: object) -> AgentResult:
        return AgentResult(
            question="q", answer="", steps=0, terminated=False, stop_reason="error:TimeoutError"
        )

    monkeypatch.setattr("dep_triage.agent.loop.run_agent", failing)
    test_client = client()
    response = test_client.post("/ask", json={"question": "Is x==1.0.0 vulnerable?"})

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert "report" in body["detail"]
    assert "Traceback" not in response.text
    assert test_client.get("/").status_code == 200


def test_ask_degrades_when_the_agent_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def exploding(*_args: object, **_kwargs: object) -> AgentResult:
        raise RuntimeError("unexpected")

    monkeypatch.setattr("dep_triage.agent.loop.run_agent", exploding)
    response = client().post("/ask", json={"question": "Is x==1.0.0 vulnerable?"})
    assert response.status_code == 503
    assert "unexpected" not in response.text, "internal detail must not reach the client"


def test_rate_limit_returns_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "dep_triage.service.limits.RateLimiter.check",
        lambda *_a, **_k: Decision(False, "per_minute", "slow down", 42),
    )
    response = client().post("/ask", json={"question": "Is x==1.0.0 vulnerable?"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "42"


def test_report_still_serves_without_a_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """The landing page must not depend on anything the live agent needs."""
    monkeypatch.setattr(
        app_module, "load_fixture", lambda _p: (_ for _ in ()).throw(OSError("gone"))
    )
    test_client = client()

    assert test_client.get("/").status_code == 200
    health = test_client.get("/health").json()
    assert health["live_agent_available"] is False
    assert health["report_available"] is True
    assert test_client.post("/ask", json={"question": "Is x==1.0.0 vulnerable?"}).status_code == 503

"""The deployed service.

Four endpoints, in descending order of how much they are allowed to break:

* ``GET /`` — the static evaluation report. **Must always render.** It is built
  from committed artifacts at startup, so it has no runtime dependency: no
  model, no network, no fixture lookup. M0 scope §9.3 makes this the landing
  page precisely because it cannot fail.
* ``GET /health`` — liveness plus current demo-quota usage.
* ``GET /metrics`` — Prometheus exposition.
* ``POST /ask`` — the live agent. Best-effort. A model backend that is
  unreachable returns a notice and HTTP 503, never a stack trace, and never
  stops ``/`` from working.

The asymmetry is the design. A reader who arrives when the free backend is down
should still see the measured results, which are the point of the project; the
live form is a demonstration, not the evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import CollectorRegistry
from pydantic import BaseModel, Field

from dep_triage import __version__
from dep_triage.config import Settings
from dep_triage.eval.grading import VERDICT_TOKENS, answer_line
from dep_triage.fixture import Fixture, FixtureNotBuilt, load_fixture
from dep_triage.service import report as report_module
from dep_triage.service.limits import RateLimiter, client_key
from dep_triage.service.observability import Metrics, configure_logging

#: Artifact names searched under ``Settings.results_dir``, in preference order.
#: The final held-out run comes first, so publishing it replaces the
#: development report without any code change.
CLEAN_NAMES = ("held-out-final.json", "m3-gates/run-1.json")
FAULT_NAMES = (
    "held-out-final-faults.json",
    "m3-faults-rescored.json",
    "m3-faults.json",
)

#: A public endpoint must not accept an unbounded prompt.
MAX_QUESTION_CHARS = 500

#: Human wording for the grader's canonical verdict tokens. The agent is asked
#: to end with ``ANSWER: <token>`` so grading is exact, and it frequently emits
#: the token and no prose at all. Returning a bare ``NOT_VULNERABLE`` to a
#: visitor is unreadable, so the service decodes it for display. The verbatim
#: answer is always returned alongside; nothing about the agent or its prompt
#: changes to make the demo prettier.
VERDICT_WORDING = {
    "vulnerable": "Vulnerable - a known advisory affects this exact version.",
    "not_vulnerable": "Not vulnerable - this version is published and no advisory affects it.",
    "version_unknown": "That version does not exist - the package is known, this release is not.",
    "package_unknown": "Unknown package - the frozen snapshot holds no data for it.",
}

REPORT_UNAVAILABLE = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<title>Report unavailable</title></head><body>"
    "<h1>Evaluation report unavailable</h1>"
    "<p>No evaluation artifact was found in this deployment. This is a packaging "
    "fault, not a result: the report is generated from committed files and should "
    "always be present.</p></body></html>"
)

log = structlog.get_logger("dep_triage.service")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=MAX_QUESTION_CHARS)


@dataclass
class ServiceState:
    """Everything resolved once at startup rather than per request."""

    settings: Settings
    metrics: Metrics
    limiter: RateLimiter
    report_html: str
    fixture: Fixture | None
    fixture_error: str | None


def _first_existing(root: Path, names: tuple[str, ...]) -> Path | None:
    return next((root / name for name in names if (root / name).is_file()), None)


def build_report_html(settings: Settings | None = None) -> str:
    """The report HTML, preferring a pre-rendered file.

    Order matters. A pre-rendered page is what the container ships, so the
    deployed service never parses an evaluation artifact at request time or at
    startup. Rendering from JSON is the local-development path.
    """
    resolved = settings or Settings()
    if resolved.report_path.is_file():
        return resolved.report_path.read_text(encoding="utf-8")

    clean = _first_existing(resolved.results_dir, CLEAN_NAMES)
    if clean is None:
        return REPORT_UNAVAILABLE
    return report_module.render_from_paths(
        clean, _first_existing(resolved.results_dir, FAULT_NAMES)
    )


def create_app(
    settings: Settings | None = None, registry: CollectorRegistry | None = None
) -> FastAPI:
    """Build the service.

    ``registry`` is injectable because Prometheus collectors are process-global
    by default, so a second app in the same test session would fail to register
    its own metrics.
    """
    resolved = settings or Settings()
    configure_logging(resolved)

    # The fixture is loaded once. A failure here disables /ask but must not stop
    # the report rendering, so it is captured rather than raised.
    fixture: Fixture | None = None
    fixture_error: str | None = None
    try:
        fixture = load_fixture(resolved.fixture_path)
    except (FixtureNotBuilt, OSError, ValueError) as exc:
        fixture_error = str(exc)

    state = ServiceState(
        settings=resolved,
        metrics=Metrics(registry),
        limiter=RateLimiter(
            daily_limit=resolved.demo_daily_limit,
            per_minute_limit=resolved.demo_per_minute_limit,
        ),
        report_html=build_report_html(resolved),
        fixture=fixture,
        fixture_error=fixture_error,
    )

    app = FastAPI(
        title="Dependency triage agent",
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.service = state

    log.info(
        "service.started",
        version=__version__,
        backend=resolved.llm_backend,
        model=resolved.llm_name,
        fixture_loaded=fixture is not None,
        fixture_error=fixture_error,
        daily_limit=resolved.demo_daily_limit,
        per_minute_limit=resolved.demo_per_minute_limit,
        report_bytes=len(state.report_html),
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        """The static report. Built at startup; nothing is computed here."""
        state.metrics.requests.labels(endpoint="/", outcome="ok").inc()
        return HTMLResponse(state.report_html)

    @app.get("/health")
    def health() -> JSONResponse:
        state.metrics.requests.labels(endpoint="/health", outcome="ok").inc()
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "live_agent_available": state.fixture is not None,
                "fixture_error": state.fixture_error,
                "report_available": state.report_html is not REPORT_UNAVAILABLE,
                "limits": state.limiter.snapshot(),
            }
        )

    @app.get("/metrics")
    def metrics_endpoint() -> Response:
        if not state.settings.enable_metrics:
            return Response(status_code=404)
        payload, content_type = state.metrics.render()
        return Response(content=payload, media_type=content_type)

    @app.post("/ask")
    def ask(body: AskRequest, request: Request) -> JSONResponse:
        """Answer one question with the live agent. Best-effort by design."""
        endpoint = "/ask"
        key = client_key(dict(request.headers), request.client.host if request.client else None)

        decision = state.limiter.check(key)
        if not decision.allowed:
            state.metrics.rate_limited.labels(scope=decision.scope).inc()
            state.metrics.requests.labels(endpoint=endpoint, outcome="rate_limited").inc()
            log.info("ask.rate_limited", scope=decision.scope)
            return JSONResponse(
                {"status": "rate_limited", "detail": decision.message},
                status_code=429,
                headers={"Retry-After": str(decision.retry_after_s)},
            )

        if state.fixture is None:
            state.metrics.requests.labels(endpoint=endpoint, outcome="unavailable").inc()
            return JSONResponse(
                {
                    "status": "unavailable",
                    "detail": (
                        "The live agent is unavailable in this deployment. The "
                        "evaluation report on the home page is unaffected."
                    ),
                },
                status_code=503,
            )

        # Imported lazily so /, /health and /metrics stay served even if the
        # model client stack fails to import.
        from dep_triage.agent.loop import run_agent
        from dep_triage.tools.wrapper import Toolkit

        with state.metrics.request_seconds.labels(endpoint=endpoint).time():
            try:
                result = run_agent(body.question, Toolkit(state.fixture), state.settings)
            except Exception:
                # The agent loop already converts model failures into a result;
                # reaching here means something unexpected broke. The reader
                # gets a notice, the report still loads, and the traceback goes
                # to the log rather than the response.
                state.metrics.backend_unavailable.inc()
                state.metrics.requests.labels(endpoint=endpoint, outcome="error").inc()
                log.exception("ask.failed")
                return JSONResponse(
                    {
                        "status": "unavailable",
                        "detail": (
                            "Live agent temporarily unavailable. The evaluation "
                            "report on the home page is unaffected."
                        ),
                    },
                    status_code=503,
                )

        state.metrics.observe_agent(result)

        if result.stop_reason.startswith("error:"):
            state.metrics.backend_unavailable.inc()
            state.metrics.requests.labels(endpoint=endpoint, outcome="unavailable").inc()
            log.warning("ask.backend_unreachable", stop_reason=result.stop_reason)
            return JSONResponse(
                {
                    "status": "unavailable",
                    "detail": (
                        "Live agent temporarily unavailable. The evaluation report "
                        "on the home page is unaffected."
                    ),
                    "stop_reason": result.stop_reason,
                },
                status_code=503,
            )

        token = (answer_line(result.answer) or "").strip().upper().replace(" ", "_").rstrip(".")
        verdict = VERDICT_TOKENS.get(token)

        state.metrics.requests.labels(endpoint=endpoint, outcome="ok").inc()
        log.info(
            "ask.answered",
            steps=result.steps,
            terminated=result.terminated,
            stop_reason=result.stop_reason,
            duration_s=round(result.duration_s, 3),
            tools=sorted(result.tools_used),
        )
        return JSONResponse(
            {
                "status": "ok",
                "answer": result.answer,
                "verdict": verdict,
                "verdict_text": VERDICT_WORDING.get(verdict) if verdict else None,
                "terminated": result.terminated,
                "stop_reason": result.stop_reason,
                "steps": result.steps,
                "tool_calls": [
                    {"tool": call.tool, "arguments": call.arguments, "ok": call.ok}
                    for call in result.calls
                ],
                "disclaimer": (
                    "Answered from a frozen offline snapshot for demonstration. "
                    "Do not use to audit real dependencies."
                ),
            }
        )

    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn dep_triage.service.app:app_factory --factory``."""
    return create_app()


def service_info() -> dict[str, Any]:
    """Startup summary, used by the container smoke check."""
    settings = Settings()
    clean = _first_existing(settings.results_dir, CLEAN_NAMES)
    return {
        "version": __version__,
        "report_prerendered": settings.report_path.is_file(),
        "report_source": str(clean) if clean else None,
        "fault_source": str(_first_existing(settings.results_dir, FAULT_NAMES) or ""),
        "daily_limit": settings.demo_daily_limit,
        "per_minute_limit": settings.demo_per_minute_limit,
    }

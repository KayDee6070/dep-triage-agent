"""Offline service acceptance, supplied on stdin rather than baked into the image.

Run inside the built image with ``--network none``, so no model backend is
reachable. That is the point: this asserts the service's failure asymmetry,
which is the one property the deployment depends on.

What must hold with the backend unreachable:

* ``GET /`` serves the full pre-rendered report. The landing page is the
  project's evidence and must not be able to fail.
* ``GET /health`` and ``GET /metrics`` answer.
* ``POST /ask`` returns 503 with a notice, **no traceback**, and no internal
  detail.
* The report still serves after ``/ask`` has failed.

Exits non-zero on the first violation.
"""

from __future__ import annotations

import json
import sys

from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from dep_triage.service.app import REPORT_UNAVAILABLE, create_app, service_info

MIN_REPORT_BYTES = 4_000


def fail(message: str) -> None:
    print(f"FAIL {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    info = service_info()
    print(f"service_info: {json.dumps(info, sort_keys=True)}")
    if not info["report_prerendered"]:
        fail("the image does not ship a pre-rendered report")

    client = TestClient(create_app(registry=CollectorRegistry()))

    index = client.get("/")
    if index.status_code != 200:
        fail(f"GET / returned {index.status_code}")
    if index.text == REPORT_UNAVAILABLE or len(index.text) < MIN_REPORT_BYTES:
        fail(f"GET / served a placeholder or truncated report ({len(index.text)} bytes)")
    # Disclosures that must hold for either split. The banner itself differs by
    # design -- a development run says so, a held-out run says it was executed
    # once -- so asserting one wording here made this check fail the moment the
    # final result was published.
    for marker in ("strictly more information", "Split:"):
        if marker not in index.text:
            fail(f"report is missing required disclosure: {marker!r}")
    if not any(banner in index.text for banner in ("development measurement", "Final measurement")):
        fail("report states neither a development nor a final measurement banner")
    print(f"ok   GET /        {len(index.text):,} bytes, disclosures present")

    health = client.get("/health")
    if health.status_code != 200 or health.json().get("report_available") is not True:
        fail(f"GET /health unhealthy: {health.status_code} {health.text[:200]}")
    print(f"ok   GET /health  {json.dumps(health.json()['limits'], sort_keys=True)}")

    metrics = client.get("/metrics")
    if metrics.status_code != 200 or "dep_triage_requests_total" not in metrics.text:
        fail(f"GET /metrics returned {metrics.status_code}")
    print(f"ok   GET /metrics {len(metrics.text.splitlines())} lines")

    ask = client.post("/ask", json={"question": "Is urllib3==1.26.4 vulnerable?"})
    if ask.status_code != 503:
        fail(f"POST /ask returned {ask.status_code}, expected 503 with no backend")
    body = ask.text
    for leak in ("Traceback", 'File "', "urllib3.exceptions", "/app/src"):
        if leak in body:
            fail(f"POST /ask leaked internal detail: {leak!r}")
    if "report" not in ask.json().get("detail", ""):
        fail("POST /ask did not point the reader at the report")
    print("ok   POST /ask    503, notice only, no traceback")

    if client.get("/").status_code != 200:
        fail("the report stopped serving after /ask failed")
    print("ok   GET /        still serving after a backend failure")

    print("offline service acceptance passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# M6 — Service, observability, deployment artifacts

**Status:** service complete and verified in-container. **Not published.**
Publication is the repository owner's decision and needs his Hugging Face
account; the scripts are committed and dry-run clean.

302 tests pass · ruff lint and format clean · strict mypy on 51 files ·
offline container and service acceptance pass.

---

## Built

**FastAPI service** (`src/dep_triage/service/`), four endpoints ordered by how
much each is permitted to break:

| Endpoint | Guarantee |
|---|---|
| `GET /` | The evaluation report. **Must always render.** |
| `GET /health` | Liveness plus current demo-quota usage. |
| `GET /metrics` | Prometheus exposition; disableable. |
| `POST /ask` | The live agent. Best-effort. |

That asymmetry is the whole design. A reader arriving while the free backend is
down should still see the measured results, because those are the project's
evidence; the live form is a demonstration.

**The report ships pre-rendered.** `dep-triage report` writes static HTML which
the image copies to `/app/report.html`. The deployed service therefore parses
no evaluation artifact at startup or at request time. Evaluation JSON is
deliberately excluded from the image.

**Self-contained HTML** — inline CSS, no scripts, no external requests. A
landing page that fetches a stylesheet stops rendering correctly the day that
host changes, and permanence is the entire reason this page exists rather than
a live demo.

**No charts, deliberately.** Twenty development tasks with ±15-point intervals
drawn as bars would read as a precise 80-versus-90 difference. Every number in
the report carries its interval in the adjacent cell instead.

**Observability** (`service/observability.py`) — structlog JSON to stdout with
a redaction processor, and Prometheus collectors fed from the same
`ToolCallRecord` list the eval harness scores. One source of truth: the
service's `dep_triage_agent_steps` and the harness's `cost.tool_calls` cannot
disagree about what a step is. Collectors live in an injectable registry,
because the Prometheus default is process-global and a second app in one test
session would fail to register.

**Rate limits** (`service/limits.py`) — a global daily cap and a per-client
per-minute cap, both enforced before the model is reached. M0 scope §9.3 makes
these a precondition for publication, not a nicety.

**Deployment artifacts** — `deploy/publish_hf_space.sh`,
`deploy/hf-space/README.md` (Space front-matter), `deploy/azure.sh`. Both
scripts are **dry-run by default**; publishing requires `--confirm`.

**CI** gained two jobs' worth of checks: offline service acceptance inside the
image, and a dry-run of the publish script asserting it refuses to publish and
that its secret scan passes.

---

## Decided

**Hugging Face Spaces carries the public link.** M0 scope §9 ranks
survivability above every other property. Spaces needs no card, cannot bill,
and sleeps rather than being deleted. Azure Container Apps has a real free
grant but still requires a payment method, and that is a liability the project
declined for a link intended to outlive the job search.

**The Space repository carries the build context** rather than pulling a
published image from a registry. Fewer moving parts: no registry, no
cross-service authentication, nothing else that has to stay alive. The context
is ~6 MB, almost all of it the frozen fixture.

**`deploy/azure.sh` is evidence, not hosting.** The target job ads name Azure,
so the script exists and is runnable. It has **not been run**, and the README
says so rather than implying otherwise.

**Publication is not automated.** A Space is public the moment it exists, which
makes the report, the agent and the fixture publicly readable and exposes a
live model endpoint. That is the owner's call, so `--confirm` is required and
the dry run states the consequences.

**Rate limiting is in-memory and therefore per process.** The deployed service
is a single container, so a process-local counter *is* the whole service. Said
plainly in the module because it would be wrong anywhere running replicas, and
a reader should not have to infer that from the absence of a datastore.

**Client identity comes from the first `x-forwarded-for` hop.** Spaces
terminates TLS ahead of the container, so the socket peer is always the proxy
and would collapse every caller into one bucket. The first hop is spoofable;
this is a courtesy cap on a free demo and is not treated as an authorisation
boundary.

**The service decodes the verdict token for display.** The agent is asked to
end with `ANSWER: <token>` so grading is exact, and it frequently emits the
token with no prose — returning a bare `NOT_VULNERABLE` to a visitor is
unreadable. The service maps it to a sentence and **always returns the verbatim
answer alongside**. No prompt, tool or agent behaviour changed to make the demo
read better.

---

## Measured

| Check | Result |
|---|---|
| Image size | 75 MB |
| Report size | 12,029 bytes, 0 external requests, 0 script tags |
| Offline container: `GET /` | 200, full report, disclosures present |
| Offline container: `/health`, `/metrics` | 200 / 200 (39 exposition lines) |
| Offline container: `POST /ask` | **503, notice only, no traceback** |
| Report after a failed `/ask` | still 200 |
| Live in-container answer | `urllib3==1.26.4` → vulnerable, 1 tool call, correct |
| Per-minute cap (set to 2) | 3rd request → 429, `Retry-After: 58` |
| Daily cap (set to 1) | 2nd request → 429, scope `daily` |
| Metrics after a refusal | `dep_triage_rate_limited_total{scope="daily"} 1.0` |

Hardened run used for every offline check: `--network none --read-only
--tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges`, as non-root.

---

## Three findings

### The service resolved data paths relative to the working directory

Found by the new tests, which run from a temporary directory. `fixture_path`
and the report-artifact paths were relative, so they resolved to nothing and
the service silently served a 332-byte placeholder while reporting
`status: ok`.

It worked by accident of `WORKDIR /app` in the container. Worse, the
**Dockerfile did not copy `results/` at all**, so a deployed container would
have served that placeholder too — the landing page, which is the project's
evidence, would have been empty in production while every local check passed.

Fixed by making the artifact location explicit (`report_path`, `results_dir`)
and by shipping the report pre-rendered, which removes the dependency rather
than relocating it.

### Ollama binds loopback only, so a container cannot reach it via host-gateway

`--add-host=host.docker.internal:host-gateway` yields a connection refusal
because the user service listens on `127.0.0.1:11434`. Local live verification
needs `--network host`. This does not affect the deployment, where the backend
is a hosted API reached over the internet, and the host service was **not**
rebound to `0.0.0.0` merely to make a test convenient.

### The agent often answers with the bare token and no prose

Measured across several questions: the model emits `ANSWER: NOT_VULNERABLE`
and nothing else. Correct for the grader, unreadable for a visitor. Handled in
presentation only — see Decided.

---

## Still weak

1. **Not published.** No public link exists. Needs the owner's Hugging Face
   account and an explicit decision to publish; `deploy/azure.sh` has never
   been executed.
2. **No hosted backend is configured.** The Space will serve the report and
   return 503 from `/ask` until a free open-weight backend is set via Space
   secrets. That is a safe default, not a working demo.
3. **The deployed model is still not the evaluated model**, and the hosted
   backend has not been evaluated. M0 scope §9.3 promised both columns; that
   obligation is unmet and carries into M7.
4. **The report shows development numbers.** It must be regenerated and
   redeployed after the final held-out run.
5. **Rate limits are per process** and reset on restart. Correct for one
   container; wrong for any replicated deployment.
6. **Nothing scrapes `/metrics` in the deployment.** The endpoint exists and is
   exercised in tests, but no Prometheus instance runs against the Space. It is
   honest instrumentation, not a monitoring stack, and the README must not
   imply otherwise.
7. **The first `x-forwarded-for` hop is spoofable**, so the per-client cap is
   evadable by a determined caller. The global daily cap is the real ceiling.

---

## Completion and next milestone

M6 meets everything it can without the owner: the service is built, hardened,
observable, rate-limited, verified offline and live inside the container, and
the deployment artifacts are committed and dry-run clean. It does **not** meet
the project's public-link criterion, which requires publication.

**Next: M7.** Owed there — publish the Space and record the live URL; configure
and then *evaluate* the hosted backend so the demo model is a measured model;
`scripts/study_*.py` with every claim backed by an assertion; README and
CONTRIBUTIONS; and last of all the single held-out measurement over the 38
remaining tasks, after which the report is regenerated and redeployed.

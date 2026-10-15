# M5 — Docker

**Status:** complete, 2026-10-15. The CLI agent and evaluation harness build
and run from a clean checkout in a non-root container. The corrected recipe
was verified from commit `24b9015`; the later milestone commit adds this report
and handoff documentation. No image was published to a registry.

Kuntal approved creating **private** GitHub repository
[`KayDee6070/dep-triage-agent`](https://github.com/KayDee6070/dep-triage-agent).
The complete existing history through M4 was pushed first; its GitHub checks
passed. Repository privacy was not changed to make deployment easier.

## Built

- Multi-stage [Dockerfile](../../Dockerfile): digest-pinned Python and uv,
  locked runtime dependencies, non-editable application installation, no uv or
  development packages in the final stage, UID/GID 1000:1000.
- Default-deny [.dockerignore](../../.dockerignore), tested by Docker against
  synthetic environment files, Git metadata, caches, private nested files,
  evaluation outputs, reservation ledgers, and model weights.
- [Offline container acceptance](../../scripts/smoke_container.py): real graph,
  tools, grader, and artifact writer with a scripted model. The three systems
  execute only the existing development task `affected-01`.
- [Context exclusion regression](../../scripts/check_docker_context.py): ten
  allowed paths and sixteen excluded canaries, using Docker's matcher itself.
- A GitHub Actions container job, separate from pytest/lint/types. It builds
  from checkout and runs both container checks without a live model.
- [Docker instructions](../docker.md): local model networking, runtime secrets,
  persistent output mounts, and final held-out ledger precautions.

The HTTP service, report landing page, health endpoint, metrics endpoint,
rate limiting, and public deployment remain M6. This CLI image does not pretend
to supply an HTTP health check or bundle a model server.

## Measured

The source was cloned with `git clone --no-local`; the new checkout was clean
before building and contained no host virtual environment. Build command:

```bash
docker build --no-cache --progress=plain -t dep-triage-agent:m5-verified .
```

| Check | Observed result |
|---|---|
| Platform | Linux amd64, Docker 29.1.3, Buildx v0.38.0 |
| Python / uv | 3.12.15 / 0.12.23 |
| Corrected clean build | Exit 0, 10.69 seconds |
| Image size reported by Docker inspect | 77,294,979 bytes |
| Runtime distributions | 53: application plus 52 dependencies |
| Default identity | UID/GID 1000:1000 |
| Offline acceptance | Pass with no network, read-only root, all capabilities dropped, no-new-privileges |
| Build context | 10 permitted synthetic paths present; 16 canaries absent |
| Output persistence | Three smoke artifacts remain readable from a second container; owner UID 1000 |
| Secret redaction | Harmless test key becomes `<set>` in `config`, not its value |
| Missing backend | Exit 2, `(no answer produced)`, `error:OpenAIConnectionError`; no traceback |
| Unconfirmed held-out command | Exit 1 before model execution; no reservation created |

Base images were already local, and a BuildKit cache mount was configured.
This is **not a fully cold build timing**. Digest pins and the application lock
constrain inputs, but isolated build-backend resolution and timestamps are not
fully pinned; no byte-identical image claim is made. ARM and Docker Desktop
were not tested. There was no vulnerability scan, so these checks are not a
general security certification.

Inside the image, SHA256 values for all three fixture JSON files and
`data/tasks.json` match the checkout exactly. The source, task file, fixture,
`pyproject.toml`, and `uv.lock` are unchanged from M4.

### Live agent, not just imports

Two live smoke executions used the existing dev question:

```text
Is twisted==25.5.0 vulnerable?
[1] ok lookup_vulnerabilities({'package': 'twisted', 'version': '25.5.0'})
ANSWER: VULNERABLE
```

One execution used the first clean-build image; the other used the corrected
context recipe from a second clean checkout. Both exited 0, made one tool call,
and terminated normally. CLI durations were **6.6 s** and **1.3 s**, respectively;
these are individual smoke timings, not a latency benchmark. The underlying
Ollama model remained Qwen3:8b with the same digest, **4,096 context tokens**,
`reasoning_effort="none"`, temperature 0, seed 42, and budget 8.

Host networking reaches the existing loopback-only Ollama service on Linux.
The container includes no GPU runtime or model weights; it is the agent client.
No backend configuration was changed. No hosted or paid API was used.

These two dev executions validate packaging, **not a new accuracy result**.
M3's 16/20 versus 18–19/20 and 18/20 comparison is untouched. No held-out task
or excluded probe ran, and the original reservation directory remains absent.

Machine-readable observations, image ID, input digests, and smoke results:
[`results/m5-container.json`](../../results/m5-container.json).

## Decisions and errors

The image uses a non-root process with root-owned code and benchmark data.
Outputs belong in a mounted directory. An eventual final run needs the original
persistent task directory and reservation ledger; a fresh writable container
must never be used to evade the one-run guard. M5 does not exercise the
confirmation flag even to test it.

Docker Engine was installed, but this shell lacked its group and Buildx was
missing. Commands used the already-authorised `sg docker` path. Buildx v0.38.0
was installed user-local after matching its SHA256 to the official GitHub
release asset digest. No sudo or Docker daemon configuration change was needed.

Two assistant errors were caught before milestone completion:

1. The smoke initially expected `APIConnectionError`, but the pinned SDK emits
   `OpenAIConnectionError`. The actual CLI output corrected the test; production
   exception handling did not change.
2. Initial `.dockerignore` directory exceptions recursively admitted files
   beneath `src`, including a harmless non-Python canary. The failing real-Docker
   probe exposed it. Removing directory exceptions and allowing only explicit
   file patterns fixed the leak. The synthetic regression now runs in CI. No
   real credential was used as a canary or found in the runtime image.

## Completion and next milestone

**267 pytest tests pass**, ruff lint and format checks pass, and strict mypy
passes on **45 files**. Docker acceptance and context-canary checks pass too.
M5 meets the project criterion that the agent runs in Docker from a clean
checkout; it does not meet the separate public-link or final-measurement criteria.

**Next: M6 service and deployment.** Preserve the private GitHub repository
unless Kuntal asks otherwise. HF Spaces deployment must still expose the static
report first, degrade safely when the live backend fails, and enforce the
declared rate limits before publication. `deploy/azure.sh` is owed in M6, not
already present; earlier handoff wording claimed it existed prematurely.

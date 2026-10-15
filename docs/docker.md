# Docker: the agent and harness

M5 packages the existing CLI. The image does not contain model weights or an
Ollama server. The HTTP service, static report, and hosted demo arrive at M6;
this image does not yet advertise a port or an HTTP health check.

## Build from a checkout

Docker Engine with Buildx/BuildKit is required. No GPU is needed for the build
or offline checks. The build needs access to the image registries and Python
package index; the offline smoke test does not.

```bash
docker build --tag dep-triage-agent:local .
docker run --rm --network none dep-triage-agent:local version
docker run --rm --network none dep-triage-agent:local --help
```

The Python and uv images are pinned by digest. `uv sync --locked --no-dev`
rejects stale lock metadata and installs the locked runtime dependencies.
The application is installed non-editably into a virtual environment. The
runtime stage copies that environment and the frozen data, not the checkout.
Changing an upstream base requires deliberately updating its digest and
rerunning acceptance checks. This is dependency reproducibility, not a claim
that two image archives have identical bytes; build timestamps and isolated
build-backend resolution are not pinned by the application lock.

The default-deny `.dockerignore` admits only Python source, fixture JSON,
tasks, package metadata, and the build files. It excludes `.git`, environment
files, caches, model weights, tests, and saved evaluation runs from the build
context. Runtime contains neither uv nor the development dependencies.

On Kuntal's machine, the current shell may not have the already-granted Docker
group. Use `sg docker -c 'docker ...'` for those commands, or start a new login
session. Do not use sudo. M5 installed checksum-verified Buildx v0.38.0 in
`~/.docker/cli-plugins/docker-buildx`; Docker Engine was already installed.

## Offline acceptance

This runs the actual graph, all four tools, grading, and JSON output with a
scripted model on one existing development question. It also checks non-root
execution, immutable code/data, absence of dev tools, rejection of unconfirmed
held-out execution, and the CLI's unavailable-backend exit status. It does not
measure model quality or execute a held-out task.

```bash
docker run --rm -i --network none --read-only \
  --tmpfs /tmp:rw,nosuid,noexec,size=64m \
  --cap-drop ALL --security-opt no-new-privileges \
  --entrypoint python dep-triage-agent:local - < scripts/smoke_container.py
```

Expected summary: `offline_smoke: passed`, UID 1000, 80 packages, three scripted
development executions, zero live model calls, zero held-out executions.
GitHub Actions runs this same check after building from its clean checkout.

## Live local smoke: Linux

Keep Ollama on the host. Its existing service listens on loopback; using host
networking on Linux lets the container reach it without exposing the model
server to the LAN. Host networking reduces network isolation, so use it only
for this trusted local image, not as the deployment design.

```bash
docker run --rm --network host --read-only \
  --tmpfs /tmp:rw,nosuid,noexec,size=64m \
  --cap-drop ALL --security-opt no-new-privileges \
  -e DEP_TRIAGE_LLM_BASE_URL=http://127.0.0.1:11434/v1 \
  dep-triage-agent:local ask --trace 'Is twisted==25.5.0 vulnerable?'
```

This is `affected-01`, an existing dev task. A smoke execution checks packaging,
not a new accuracy estimate. Preserve `reasoning_effort="none"`, temperature 0,
seed 42, and the eight-call budget. Check the running Ollama allocation before
eventual final measurement; M3 used 4,096 tokens. Do not silently substitute 8k.

On Docker Desktop, host networking requires explicit support/configuration;
otherwise use a backend address reachable from the container. `localhost`
inside a bridge-networked container is not the host. No Desktop or ARM smoke
has been verified in this project.

## Results and secrets

The image defaults to UID/GID **1000:1000**. Code and benchmark data are
root-owned; `/app/results` is the writable output directory. Container-local
results disappear with `--rm`, so bind-mount a host directory for anything
worth keeping. Ensure that directory is writable by UID 1000, or set
`--user "$(id -u):$(id -g)"` to match its owner. Do not make it world-writable.

The offline smoke can verify persistence without invoking any real model:

```bash
mkdir -p results/container-smoke
docker run --rm -i --network none --read-only \
  --tmpfs /tmp:rw,nosuid,noexec,size=64m \
  --cap-drop ALL --security-opt no-new-privileges \
  --mount type=bind,src="$PWD/results/container-smoke",dst=/app/results \
  --entrypoint python dep-triage-agent:local - --output-dir /app/results \
  < scripts/smoke_container.py
```

This writes `container-smoke.json`, `.metrics.json`, and `.jsonl`. It refuses
to overwrite them on another run. The artifact model name is explicitly
`offline-container-smoke`, not Qwen3. These are functional checks, not published
benchmark measurements.

Pass backend settings at runtime with `-e` or a protected `--env-file`.
Never supply secrets as build arguments or copy `.env` into the image.
`dep-triage config` reports the API key as `<set>` or `<unset>`, never its value.
Environment variables can still be read by someone with Docker access; Docker
group membership is privileged access, not a secret boundary.

## Held-out safety

No M5 command confirms held-out execution. The ordinary confirmation guard
remains in place. Additionally, the default non-root process cannot create
`/app/data/.held-out-runs` beside the image's root-owned task file.

An eventual authorised final run must use a **persistent task directory and
reservation ledger**, plus persistent results. Prefer the host CLI with the
original `data/tasks.json`, or deliberately mount that same host task directory
for a container run. A writable task copy in an ephemeral container could lose
its reservations when destroyed. Never use a fresh container or copied task
file to evade the one-run rule. The two exposed probes remain excluded.

## Implementation references

The build follows the official [uv Docker guide](https://docs.astral.sh/uv/guides/integration/docker/)
and Docker's [build guidance](https://docs.docker.com/build/building/best-practices/).
The Linux connection method is documented under Docker's
[host network driver](https://docs.docker.com/engine/network/drivers/host/).

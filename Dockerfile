# Resolve tag updates deliberately; both upstream images are digest-pinned.
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS python

FROM python AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

# Dependency layers survive application edits. --locked rejects stale lockfiles.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --python /usr/local/bin/python
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --python /usr/local/bin/python

FROM python AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DEP_TRIAGE_REPORT_PATH=/app/report.html
RUN groupadd --gid 1000 triage \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin triage \
    && mkdir /app/results \
    && chown 1000:1000 /app/results

# Code and benchmark data remain root-owned. Only results are writable.
# A final held-out run needs a persistent host task directory, not this layer.
COPY --from=builder /app/.venv /app/.venv
COPY data/fixture ./data/fixture
COPY data/tasks.json ./data/tasks.json

# The landing page ships pre-rendered, outside the writable results directory.
# Shipping evaluation JSON instead would make the page depend on parsing an
# artifact at startup, and the page is the project's evidence.
COPY results/report.html ./report.html

USER 1000:1000
EXPOSE 8000
ENTRYPOINT ["dep-triage"]
# Serving is the deployed purpose. Any other subcommand overrides this, which
# is how the offline acceptance checks invoke `version`.
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
